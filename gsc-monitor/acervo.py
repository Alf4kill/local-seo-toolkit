"""
acervo.py — Armazém histórico do Google Search Console (P7).

Puxa e ACUMULA o grão diário que a Search Analytics API entrega, para análise
posterior. Não analisa, não pontua, não dá veredito: a análise acontece depois,
fora desta ferramenta, sobre o pacote que o acervo entrega.

Por que existe: a retenção do GSC é uma JANELA MÓVEL de ~16 meses. Cada dia que
passa apaga para sempre o dia mais antigo. O backfill pega o que ainda existe; o
`diario` acumula para frente e nunca apaga — é assim que a série passa de 2 anos.

Uso básico:
    py acervo.py aferir   --site www.exemplo.com.br     # rode UMA vez por site
    py acervo.py backfill --site www.exemplo.com.br --dry-run
    py acervo.py backfill --site www.exemplo.com.br
    py acervo.py diario   --site www.exemplo.com.br     # agende este (semanal)
    py acervo.py status   --site www.exemplo.com.br
    py acervo.py anotar   --site www.exemplo.com.br --data 2026-03-10 \
                          --tipo conteudo-editado --desc "reescrevi o texto" \
                          --urls-de urls_reescritas.txt
    py acervo.py pacote   --site www.exemplo.com.br     # o que vai para a análise

Subcomandos:
    aferir     Mede empiricamente como o teto de linhas da API se comporta neste
               site (a doc não resolve se os 50k valem por dia ou por consulta).
               Nunca grava fato; grava só o diagnóstico em `meta`.
    backfill   Traz a janela retroativa inteira (padrão 480 dias, o máximo do
               GSC). Retoma de onde parou se for interrompido.
    diario     Re-busca a ponta que ainda assenta e incorpora os dias novos.
               É o comando para agendar.
    reingerir  Força a re-ingestão de um intervalo (--de/--ate).
    anotar     Registra o que mudou no site e QUANDO — com as URLs afetadas.
               É o que transforma a análise em comparação de URLs tratadas
               contra não tratadas.
    eventos    Lista (ou remove) os eventos anotados.
    pacote     Gera relatorios/{dominio}/acervo/pacote/: snapshot do banco,
               DADOS.md, eventos.csv, consultas.sql e extras/.
    status     O que existe no acervo, o que falta e o que não é confiável.

Agendamento (Windows), depois de `aferir` e do primeiro `backfill`:
    schtasks /Create /TN "GSC Acervo Semanal" /SC WEEKLY /D MON /ST 07:00 ^
      /TR "py E:\\projetos\\projetoprst.com.br\\gsc-monitor\\acervo.py diario --batch sites.txt"

    Exige token.json já gerado E o app OAuth PUBLICADO em producao: client em
    "Testing" emite refresh token que expira em 7 dias, e a tarefa agendada
    morreria em uma semana sem avisar.
"""

import sys

# Força UTF-8 no stdout/stderr para caracteres Unicode funcionarem em qualquer
# terminal Windows (que usa cp1252 por padrão no Python 3.13).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import json
import os
from datetime import date

from config import (
    ACERVO_ASSENTAMENTO_DIAS,
    ACERVO_DIAS_BACKFILL,
    ACERVO_PAUSA_REQUISICAO,
    GSC_DELAY_DAYS,
)
from core.urls import build_site_url, normalize_domain
from core.warehouse import pacote, plan, store

# Vocabulário sugerido para `acervo.py anotar` (P7.2). Documentado aqui porque a
# coluna `evento.tipo` é texto livre de propósito: evento é o que aconteceu, não
# o que o esquema previu.
TIPOS_EVENTO_SUGERIDOS = (
    "migracao",
    "redesign",
    "conteudo-novo",
    "conteudo-editado",
    "titulo",
    "hospedagem",
    "301",
    "poda",
    "robots",
    "sitemap",
    "tecnico",
    "outro",
)


class AcervoError(RuntimeError):
    """Falha fatal de um comando do acervo (espelha posicao.PipelineError)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_graos(texto: "str | None") -> tuple:
    """'pagina,query' -> ('pagina','query'). Valida contra os grãos disponíveis."""
    if not texto:
        return plan.GRAOS_PADRAO
    pedidos = tuple(g.strip() for g in texto.split(",") if g.strip())
    invalidos = [g for g in pedidos if g not in plan.GRAOS]
    if invalidos:
        raise AcervoError(
            f"grao(s) desconhecido(s): {', '.join(invalidos)}. "
            f"Disponiveis: {', '.join(plan.GRAOS_PADRAO)}"
        )
    futuros = [g for g in pedidos if plan.GRAOS[g].get("fixo")]
    if futuros:
        raise AcervoError(
            f"o grao '{futuros[0]}' usa as 2 etapas com dimensionFilterGroups e entra na fase P7.4."
        )
    return pedidos


def _parse_tipos(args) -> tuple:
    """Os `type` da Search Analytics a ingerir nesta execução.

    `--tipos web,image` para vários; `--tipo image` (singular) continua valendo
    para um só — é o que a GUI monta e o que scripts antigos passam. Os dois são
    mutuamente exclusivos no argparse, então não há como pedir coisas diferentes.

    Vale lembrar por que mais de um tipo importa: `image` pode ter MAIS
    impressões que `web` e cair de forma diferente dele. Coletar só `web` não é
    um recorte menor do mesmo fato, é outro fato.
    """
    texto = getattr(args, "tipos", None)
    if not texto:
        return (getattr(args, "tipo", None) or "web",)
    pedidos = tuple(dict.fromkeys(t.strip() for t in texto.split(",") if t.strip()))
    invalidos = [t for t in pedidos if t not in plan.TIPOS_VALIDOS]
    if invalidos:
        raise AcervoError(
            f"tipo(s) desconhecido(s): {', '.join(invalidos)}. "
            f"Disponiveis: {', '.join(plan.TIPOS_VALIDOS)}. "
            "Nao existe valor de IA: o relatorio de IA generativa do GSC e so da interface."
        )
    return pedidos or ("web",)


def _checar_token() -> None:
    """Falha RÁPIDO se não há token.json utilizável.

    Sem isso, uma execução agendada chamaria flow.run_local_server(), que tenta
    abrir um navegador e ficaria pendurada até o timeout da tarefa.
    """
    from core.auth import CLIENT_SECRETS_FILE, TOKEN_FILE

    if not os.path.exists(CLIENT_SECRETS_FILE):
        raise AcervoError(
            f"client_secrets.json nao encontrado em {CLIENT_SECRETS_FILE}. "
            "Veja o README (secao de credenciais)."
        )
    if not os.path.exists(TOKEN_FILE):
        raise AcervoError(
            f"token.json nao encontrado em {TOKEN_FILE}. Rode primeiro um comando "
            "interativo (ex.: py posicao.py --site SEU.SITE) para autorizar; o "
            "acervo nao abre navegador, para nao pendurar tarefa agendada."
        )


def _info_token() -> dict:
    """Validade do token, sem jamais imprimir o segredo em si."""
    from core.auth import TOKEN_FILE

    if not os.path.exists(TOKEN_FILE):
        return {"existe": False}
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return {"existe": True, "erro": str(exc)}
    return {
        "existe": True,
        "expiry": dados.get("expiry"),
        "tem_refresh": bool(dados.get("refresh_token")),
    }


def _abrir(site: str):
    """(conn, propriedade). `propriedade` é o siteUrl literal enviado à API.

    Guardar a propriedade (e não só o domínio) é essencial: normalize_domain()
    colapsa 'https://x/' e 'sc-domain:x' na mesma pasta de propósito, mas são
    propriedades DIFERENTES do GSC, com dados diferentes. Sem isso na chave,
    rodar as duas formas sobrescreveria uma com a outra.
    """
    propriedade = build_site_url(site)
    conn = store.abrir(normalize_domain(site))
    store.semear_meta(conn, propriedade=propriedade)
    return conn, propriedade


def _resumo_lote(resultado: dict) -> str:
    """Linha-resumo do --batch (substitui a do core/batch, que fala de health)."""
    site = resultado.get("site", "?")
    if not resultado.get("ok"):
        return f"[ERRO] {site:<28} {resultado.get('error', 'erro desconhecido')}"
    s = resultado.get("summary") or {}
    # `pacote` nao faz requisicao nenhuma: imprimir "0 linhas 0 requisicoes"
    # para ele seria verdade enganosa.
    if "pasta" in s:
        return f"[OK]   {site:<28} pacote em {s['pasta']} ({s.get('snapshot_mb', 0):.1f} MB)"
    return f"[OK]   {site:<28} {s.get('linhas', 0)} linhas  {s.get('requisicoes', 0)} requisicoes"


def _coletar_urls(args) -> list:
    """URLs do evento: de --urls (repetível, aceita vírgula) e de --urls-de arquivo.

    As duas formas existem porque o caso real são DEZENAS ou CENTENAS de URLs
    ("estas 243 URLs são o lote regionalizado"), e isso não cabe numa linha de
    comando. O arquivo é uma URL por linha, `#` comenta, BOM tolerado.

    Deduplica preservando a ordem informada — e NÃO normaliza: o que o analista
    digitou é guardado como digitou, para auditoria. A normalização acontece só
    no casamento com dim_pagina (store.chave_pagina).
    """
    brutas = []
    for item in getattr(args, "urls", None) or []:
        brutas.extend(parte for parte in item.split(","))

    arquivo = getattr(args, "urls_de", None)
    if arquivo:
        if not os.path.exists(arquivo):
            raise AcervoError(f"--urls-de: arquivo nao encontrado: {arquivo}")
        with open(arquivo, encoding="utf-8-sig") as f:
            for linha in f:
                linha = linha.strip()
                if linha and not linha.startswith("#"):
                    brutas.append(linha)

    vistas, urls = set(), []
    for url in (u.strip() for u in brutas):
        if url and url not in vistas:
            vistas.add(url)
            urls.append(url)
    return urls


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def _plano_de_um_tipo(conn, *, propriedade: str, tipo: str, graos: tuple, dias_janela: list, args):
    """(pendentes_por_grao, estimativa) de UM `type`. Pura quanto a rede."""
    medias = store.media_linhas_por_dia(conn, propriedade=propriedade, tipo=tipo)
    passos = []
    pendentes_por_grao = {}
    for grao in plan.graos_aplicaveis(graos, tipo):
        pendentes = store.dias_pendentes(
            conn,
            propriedade=propriedade,
            tipo=tipo,
            grao=grao,
            dias=dias_janela,
            forcar=getattr(args, "forcar", False),
        )
        pendentes_por_grao[grao] = pendentes
        passos.extend(plan.montar_passos(grao, tipo, pendentes))
    return pendentes_por_grao, plan.estimar_requisicoes(passos, medias)


def _imprimir_plano(site: str, graos: tuple, inicio: str, fim: str, args) -> dict:
    """Monta e imprime o plano SEM tocar na API (nem constrói o `service`).

    Com vários `type`, o custo sai discriminado por tipo E somado: é a diferença
    entre decidir coletar `image` sabendo o que custa e descobrir depois.
    """
    tipos = _parse_tipos(args)
    conn, propriedade = _abrir(site)
    try:
        dias_janela = plan.listar_dias(inicio, fim)
        por_tipo = {
            tipo: _plano_de_um_tipo(
                conn,
                propriedade=propriedade,
                tipo=tipo,
                graos=graos,
                dias_janela=dias_janela,
                args=args,
            )
            for tipo in tipos
        }
    finally:
        conn.close()

    print("\n[acervo] PLANO (nenhuma chamada a API sera feita)")
    print(f"  propriedade: {propriedade}")
    print(f"  janela     : {inicio} a {fim} ({len(dias_janela)} dias)")
    print(f"  tipo(s)    : {', '.join(tipos)}")

    vazio = {"lotes": 0, "requisicoes": 0, "linhas": 0}
    geral = {"requisicoes": 0, "linhas": 0, "medido": True}
    for tipo, (pendentes_por_grao, estimativa) in por_tipo.items():
        print("")
        if len(tipos) > 1:
            print(f"  type={tipo}")
        print(
            f"  {'grao':<14}{'pend.':>7}{'lote':>7}{'lotes':>7}{'req.est.':>10}{'linhas est.':>14}"
        )
        print("  " + "-" * 59)
        for grao, pendentes in pendentes_por_grao.items():
            info = estimativa["por_grao"].get(grao, vazio)
            print(
                f"  {grao:<14}{len(pendentes):>7}"
                f"{plan.ACERVO_DIAS_LOTE.get(grao, 30):>7}{info['lotes']:>7}"
                f"{info['requisicoes']:>10}{info['linhas'] or '?':>14}"
            )
        print("  " + "-" * 59)
        total = estimativa["total"]
        geral["requisicoes"] += total["requisicoes"]
        geral["linhas"] += total["linhas"]
        geral["medido"] = geral["medido"] and total["medido"]
        rotulo = f"  SUBTOTAL {tipo}" if len(tipos) > 1 else "  TOTAL"
        print(f"{rotulo}: {total['requisicoes']} requisicoes, ~{total['linhas'] or '?'} linhas")

    if len(tipos) > 1:
        print("")
        print(
            f"  TOTAL ({len(tipos)} tipos): {geral['requisicoes']} requisicoes, "
            f"~{geral['linhas'] or '?'} linhas"
        )
    origem = (
        "medido na escrituracao"
        if geral["medido"]
        else "SEM medicao ainda (rode um backfill curto primeiro)"
    )
    print(f"  estimativa de linhas: {origem}")
    segundos = geral["requisicoes"] * (args.pausa + 1.5)
    print(f"  tempo estimado: ~{segundos / 60:.1f} min (pausa {args.pausa}s + latencia ~1.5s)\n")

    unico = next(iter(por_tipo.values()))[1]
    return unico if len(tipos) == 1 else {"por_tipo": por_tipo, "total": geral}


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


def cmd_aferir(args) -> dict:
    """Mede o comportamento do teto de linhas antes de fixar tamanho de lote."""
    from core.auth import build_service
    from fetchers.acervo_fetcher import aferir

    _checar_token()
    conn, propriedade = _abrir(args.site)
    try:
        service = build_service()
        print(f"[acervo] Aferindo {propriedade} (~5 a 8 requisicoes, nada e gravado)...")
        resultado = aferir(service, propriedade, pausa=args.pausa)

        store.definir_meta(conn, "afericao", resultado)
        store.definir_meta(conn, "afericao_em", store.agora())
    finally:
        conn.close()

    print("\n" + "=" * 62)
    print("  Afericao do teto de linhas da Search Analytics")
    print("=" * 62)
    print(f"  janela          : {resultado['janela'][0]} a {resultado['janela'][1]}")
    if "dia_pico" not in resultado:
        print(f"  {resultado.get('conclusao')}")
        print("=" * 62 + "\n")
        return resultado

    print(
        f"  dia de pico     : {resultado['dia_pico']} ({resultado['impressoes_no_dia']} impressoes)"
    )
    iso = resultado["isolado"]
    lote = resultado["no_lote"]
    print(f"  dia isolado     : {iso['linhas']} linhas, {iso['impressoes']} impressoes")
    print(
        f"  dentro do lote  : {lote['linhas']} linhas, {lote['impressoes']} impressoes "
        f"(lote de {lote['dias_no_lote']} dias, {lote['linhas_lote_inteiro']} linhas)"
    )
    print(f"  teto vale por   : {resultado['teto_por'].upper()}")
    print(f"  aparencias      : {', '.join(resultado.get('aparencias') or []) or '(nenhuma)'}")
    print(f"  aparencia+date  : {resultado.get('aparencia_combinada', '?')}")
    print("-" * 62)
    print(f"  {resultado['conclusao']}")
    print("=" * 62 + "\n")
    return resultado


def _ingerir(args, *, inicio: str, fim: str, graos: tuple, data_state=None, forcar=False) -> dict:
    """Corpo comum de backfill, diario e reingerir — um ou vários `type`.

    Um `type` por vez, em sequência, e cada um com sua própria escrituração:
    `tipo` está na chave primária de toda tabela de fato e da `ingestao`, logo o
    mesmo dia e a mesma URL em `web` e em `image` são DUAS linhas, e ter `web`
    ingerido não marca `image` como resolvido.

    Uma `execucao` só cobre a passada inteira — ela registra o comando, não o
    tipo —, e o resumo é a soma, com a quebra por tipo em `por_tipo`.
    """
    from core.auth import build_service
    from fetchers.acervo_fetcher import ingerir_janela

    tipos = _parse_tipos(args)
    _checar_token()
    conn, propriedade = _abrir(args.site)
    execucao_id = store.iniciar_execucao(conn, comando=args.comando, propriedade=propriedade)
    contador: dict = {}
    resumo: dict = {"linhas": 0, "requisicoes": 0, "por_tipo": {}}
    try:
        service = build_service()
        for tipo in tipos:
            if len(tipos) > 1:
                print(f"\n[acervo] ── type={tipo} ──")
            parcial = ingerir_janela(
                service,
                conn,
                site_url=propriedade,
                propriedade=propriedade,
                inicio=inicio,
                fim=fim,
                graos=graos,
                tipo=tipo,
                data_state=data_state,
                forcar=forcar,
                pausa=args.pausa,
                contador=contador,
            )
            resumo["por_tipo"][tipo] = parcial
            resumo["linhas"] += parcial["linhas"]
            resumo["requisicoes"] += parcial["requisicoes"]

        store.finalizar_execucao(
            conn,
            execucao_id,
            requisicoes=resumo["requisicoes"],
            linhas=resumo["linhas"],
            retentativas=contador.get("retentativas", 0),
            esperas_carga=contador.get("esperas_carga", 0),
        )
        print("")
        if len(tipos) > 1:
            for tipo, parcial in resumo["por_tipo"].items():
                print(
                    f"[acervo] {tipo:11s} {parcial['linhas']} linhas, "
                    f"{parcial['requisicoes']} requisicoes."
                )
        print(
            f"[acervo] {propriedade}: {resumo['linhas']} linhas gravadas em "
            f"{resumo['requisicoes']} requisicoes."
        )
        return resumo
    except Exception as exc:
        store.finalizar_execucao(conn, execucao_id, erro=str(exc))
        raise
    finally:
        conn.close()


def cmd_backfill(args) -> dict:
    graos = _parse_graos(args.graos)
    inicio, fim = plan.intervalo_datas(args.dias)
    if args.dry_run:
        _imprimir_plano(args.site, graos, inicio, fim, args)
        return {"linhas": 0, "requisicoes": 0, "dry_run": True}
    return _ingerir(args, inicio=inicio, fim=fim, graos=graos, forcar=args.forcar)


def cmd_diario(args) -> dict:
    """Re-busca a ponta que ainda assenta e incorpora os dias novos.

    A janela é (atraso + assentamento) dias: o GSC revisa o dado por ~10 dias
    depois dos 2-3 de atraso, e um dia dentro dessa janela é re-pedido mesmo se
    já estiver gravado. `revisoes`/`alterado_em` mostram o que de fato mudou.
    """
    graos = _parse_graos(args.graos)
    inicio, fim = plan.janela_assentamento()
    if args.dry_run:
        _imprimir_plano(args.site, graos, inicio, fim, args)
        return {"linhas": 0, "requisicoes": 0, "dry_run": True}

    resumo = _ingerir(args, inicio=inicio, fim=fim, graos=graos)

    if args.ponta_fresca:
        # Os últimos `atraso` dias, que nenhuma passada `final` alcança ainda
        # (atraso=0 faz a janela terminar HOJE em vez de hoje - 3).
        inicio_f, fim_f = plan.intervalo_datas(GSC_DELAY_DAYS, atraso=0)
        print(f"[acervo] Ponta fresca (dataState=all): {inicio_f} a {fim_f}")
        fresco = _ingerir(
            args,
            inicio=inicio_f,
            fim=fim_f,
            graos=graos,
            data_state=plan.ESTADO_FRESCO,
            forcar=True,
        )
        resumo["linhas"] += fresco["linhas"]
        resumo["requisicoes"] += fresco["requisicoes"]
    return resumo


def cmd_reingerir(args) -> dict:
    graos = _parse_graos(args.graos)
    tipos = _parse_tipos(args)
    conn, propriedade = _abrir(args.site)
    # A limpeza é por tipo, como a escrituração: reingerir `image` não pode
    # apagar o que já foi coletado de `web` no mesmo intervalo.
    apagado = {"ingestao": 0, "fatos": 0}
    try:
        for tipo in tipos:
            parcial = store.apagar_intervalo(
                conn,
                propriedade=propriedade,
                tipo=tipo,
                graos=plan.graos_aplicaveis(graos, tipo),
                de=args.de,
                ate=args.ate,
                apagar_fatos=args.apagar,
            )
            apagado["ingestao"] += parcial["ingestao"]
            apagado["fatos"] += parcial["fatos"]
    finally:
        conn.close()
    print(
        f"[acervo] Escrituracao limpa ({', '.join(tipos)}): {apagado['ingestao']} dias, "
        f"{apagado['fatos']} linhas de fato apagadas."
    )
    return _ingerir(args, inicio=args.de, fim=args.ate, graos=graos)


def cmd_anotar(args) -> dict:
    """Registra uma mudança no site, com as URLs afetadas. Dado, não análise."""
    urls = _coletar_urls(args)
    if args.tipo_evento not in TIPOS_EVENTO_SUGERIDOS:
        print(
            f"[acervo] Aviso: tipo '{args.tipo_evento}' esta fora do vocabulario sugerido "
            f"({', '.join(TIPOS_EVENTO_SUGERIDOS)}). Nao e erro — `evento.tipo` e texto "
            "livre de proposito — mas tipo consistente e o que deixa a timeline legivel."
        )

    conn, propriedade = _abrir(args.site)
    try:
        ident = store.adicionar_evento(
            conn,
            propriedade=propriedade,
            data=args.data,
            data_fim=args.ate,
            tipo=args.tipo_evento,
            descricao=args.desc,
            urls=urls or None,
            fonte=args.fonte,
        )
        casamento = store.casar_urls_evento(conn, evento_id=ident)[ident] if urls else None
    finally:
        conn.close()

    periodo = f"{args.data} a {args.ate}" if args.ate else args.data
    print(f"\n[acervo] Evento #{ident} registrado: {periodo}  [{args.tipo_evento}]")
    print(f"  {args.desc}")
    if casamento is None:
        print(
            "  SEM URLs. O evento entra na timeline, mas NAO vira coorte: sem URLs nao da "
            "para comparar as paginas tratadas contra as demais. Se voce sabe quais paginas "
            "o evento tocou, informe-as (--urls ou --urls-de) — e a peca que carrega o "
            "argumento da analise."
        )
        return {"evento_id": ident, "urls": 0}

    print(f"  URLs informadas: {casamento['informadas']}")
    print(f"  casadas em dim_pagina: {casamento['casadas']}")
    if casamento["sem_casamento"]:
        print(
            f"  NAO casaram ({len(casamento['sem_casamento'])}): ou a URL nunca teve "
            "impressao (e por isso nao esta em dim_pagina), ou a forma informada nao "
            "corresponde a que o GSC devolve. A comparacao do GSC ignora protocolo, www, "
            "barra final, query e percent-encoding — se mesmo assim nao casou, confira o "
            "caminho:"
        )
        for url in casamento["sem_casamento"][:10]:
            print(f"    - {url}")
        if len(casamento["sem_casamento"]) > 10:
            print(f"    ... (+{len(casamento['sem_casamento']) - 10})")
        print(
            "  O evento foi gravado de todo jeito, e o casamento e refeito a cada "
            "`pacote` — uma URL publicada agora entra em dim_pagina na proxima ingestao."
        )
    return {"evento_id": ident, "urls": casamento["informadas"], "casadas": casamento["casadas"]}


def cmd_eventos(args) -> dict:
    """Lista (ou remove) os eventos anotados do site."""
    conn, propriedade = _abrir(args.site)
    try:
        if args.remover:
            removido = store.remover_evento(conn, args.remover)
            print(
                f"[acervo] Evento #{args.remover} "
                + ("removido (com a coorte de URLs)." if removido else "NAO encontrado.")
            )
            if not removido:
                raise AcervoError(f"evento #{args.remover} nao existe neste banco")
        store.casar_urls_evento(conn)
        eventos = store.listar_eventos(conn, propriedade=propriedade)
        urls_por_evento = (
            {ev["id"]: store.paginas_do_evento(conn, ev["id"]) for ev in eventos}
            if args.urls
            else {}
        )
    finally:
        conn.close()

    print("\n" + "=" * 78)
    print(f"  Eventos anotados — {propriedade}")
    print("=" * 78)
    if not eventos:
        print("  (nenhum) — sem evento anotado, qualquer inflexao da serie fica sem causa")
        print("  candidata. Anote o que voce sabe ter feito: `acervo.py anotar --help`")
    for ev in eventos:
        periodo = ev["data"] if ev["data_fim"] == ev["data"] else f"{ev['data']}..{ev['data_fim']}"
        print(f"  #{ev['id']:<4} {periodo:<24} {ev['tipo']:<18} {ev['descricao']}")
        if ev["urls_informadas"]:
            print(
                f"         URLs: {ev['urls_casadas']} casadas de {ev['urls_informadas']} "
                f"informadas   (fonte: {ev['fonte'] or '—'})"
            )
        for url in urls_por_evento.get(ev["id"], []):
            print(f"           - {url}")
    print("=" * 78 + "\n")
    return {"eventos": eventos}


def cmd_pacote(args) -> dict:
    """Gera o pacote de análise: snapshot + DADOS.md + CSVs + consultas + extras/."""
    dominio = normalize_domain(args.site)
    conn, propriedade = _abrir(args.site)
    try:
        resultado = pacote.gerar(
            conn,
            propriedade=propriedade,
            site=dominio,
            tipo=args.tipo,
            reduzido=args.reduzido,
            com_snapshot=not args.sem_snapshot,
        )
    finally:
        conn.close()

    print("\n" + "=" * 78)
    print(f"  Pacote de analise — {propriedade}")
    print("=" * 78)
    print(pacote.resumo_texto(resultado))
    print("-" * 78)
    print("  Leia o DADOS.md ANTES de concluir qualquer coisa: as secoes 4 a 7 existem")
    print("  porque cada uma corresponde a uma leitura errada que este dado ja produziu.")
    print("=" * 78 + "\n")
    return {
        "pasta": resultado["pasta"],
        "snapshot_mb": resultado["snapshot_mb"],
        "eventos": resultado["eventos"],
    }


def cmd_status(args) -> dict:
    conn, propriedade = _abrir(args.site)
    try:
        caminho = store.caminho_banco(normalize_domain(args.site))
        tamanho = os.path.getsize(caminho) if os.path.exists(caminho) else 0
        versao = conn.execute("PRAGMA user_version").fetchone()[0]
        cobertura = store.cobertura(conn, propriedade=propriedade)
        provisorios = store.dias_provisorios(conn, propriedade=propriedade)
        execucoes = store.ultimas_execucoes(conn, 3)
        afericao = store.ler_meta(conn, "afericao_em")
        contagens = {
            grao: store.contar_linhas_por_tipo(conn, spec["tabela"])
            for grao, spec in plan.GRAOS.items()
        }
        tipos_vistos = sorted({t for por_tipo in contagens.values() for t in por_tipo})
    finally:
        conn.close()

    print("\n" + "=" * 70)
    print(f"  Acervo — {propriedade}")
    print("=" * 70)
    print(f"  banco      : {caminho}")
    print(f"  tamanho    : {tamanho / 1_048_576:.1f} MB   esquema v{versao}")
    print(f"  afericao   : {afericao or 'NAO RODADA — rode `acervo.py aferir` primeiro'}")

    token = _info_token()
    if not token.get("existe"):
        print("  token      : AUSENTE — rode um comando interativo para autorizar")
    elif token.get("tem_refresh"):
        # O `expiry` do token.json e do ACCESS token (1 hora): estar vencido
        # entre execucoes e NORMAL, o refresh renova sozinho. O risco real nao
        # aparece aqui — e o app OAuth ficar em "Testing", porque ai o REFRESH
        # token expira em 7 dias e a tarefa agendada morre sem avisar.
        print("  token      : refresh_token presente (renovacao silenciosa)")
        print("               app OAuth tem de estar PUBLICADO em producao; em")
        print('               "Testing" o refresh token expira em 7 dias')
    else:
        print("  token      : SEM refresh_token — vai exigir re-autorizacao manual")

    print("-" * 70)
    print("  Cobertura (dias por tipo, grao e status)")
    if not cobertura:
        print("    (vazio — nenhuma ingestao ainda)")
    for linha in cobertura:
        media = linha.get("cobertura_media")
        extra = f"  cobertura {media:.0%}" if media is not None else ""
        print(
            f"    {linha['tipo']:<11}{linha['grao']:<14}{linha['status']:<9}{linha['dias']:>5} dias"
            f"  {linha['primeiro']} a {linha['ultimo']}{extra}"
        )

    print("-" * 70)
    # Por tipo, nunca somado: `web` e `image` sao superficies diferentes, e um
    # total unico esconderia que uma delas nao foi coletada.
    print("  Linhas por tabela de fato, por tipo")
    if len(tipos_vistos) > 1:
        print(f"    {'grao':<14}" + "".join(f"{t:>12}" for t in tipos_vistos))
        for grao, por_tipo in contagens.items():
            print(f"    {grao:<14}" + "".join(f"{por_tipo.get(t, 0):>12}" for t in tipos_vistos))
    else:
        rotulo = tipos_vistos[0] if tipos_vistos else "web"
        for grao, por_tipo in contagens.items():
            print(f"    {grao:<14}{por_tipo.get(rotulo, 0):>12}")
    nao_coletados = [t for t in plan.TIPOS_VALIDOS if t not in tipos_vistos]
    if nao_coletados:
        print(
            f"    NAO coletados: {', '.join(nao_coletados)} — zero linhas aqui nao e "
            "ausencia de trafego,"
        )
        sugestao = ",".join([*tipos_vistos, nao_coletados[0]])
        print(f"    e so ausencia de coleta. Para incluir: --tipos {sugestao}")

    print("-" * 70)
    janela = GSC_DELAY_DAYS + ACERVO_ASSENTAMENTO_DIAS
    print(
        f"  Dias provisorios ({len(provisorios)}): ainda assentando, nao tire "
        f"conclusao da ponta (janela de {janela} dias)."
    )
    if provisorios:
        print(f"    {provisorios[0]} a {provisorios[-1]}")

    print("-" * 70)
    print("  Ultimas execucoes")
    for ex in execucoes:
        estado = ex["erro"] or ("em andamento" if not ex["terminado_em"] else "ok")
        print(
            f"    #{ex['id']} {ex['comando']:<10} {ex['iniciado_em']}  "
            f"{ex['linhas']} linhas  {ex['requisicoes']} req  [{estado}]"
        )
    print("=" * 70 + "\n")
    return {"cobertura": cobertura, "provisorios": provisorios}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Acervo historico do Google Search Console (extracao, nao analise)"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    def comum(p, *, batch: bool = False):
        alvo = p.add_mutually_exclusive_group(required=True)
        alvo.add_argument("--site", help="dominio ou sc-domain: a ingerir")
        if batch:
            alvo.add_argument("--batch", help="arquivo com um dominio por linha")
        # Mutuamente exclusivos de propósito: `--tipo` (um só) é o que a GUI
        # monta e o que scripts antigos passam, e `--tipos` é a forma nova.
        # Permitir os dois na mesma linha deixaria expressável pedir coisas
        # diferentes e ter de inventar uma regra de precedência.
        quais = p.add_mutually_exclusive_group()
        quais.add_argument(
            "--tipo",
            default="web",
            choices=plan.TIPOS_VALIDOS,
            help="`type` da Search Analytics (padrao: web)",
        )
        quais.add_argument(
            "--tipos",
            help=(
                "varios `type` separados por virgula (ex. web,image). "
                "`image` costuma ter volume comparavel ao de `web` e cair diferente dele"
            ),
        )
        p.add_argument(
            "--graos",
            help=f"lista separada por virgula (padrao: {','.join(plan.GRAOS_PADRAO)})",
        )
        p.add_argument(
            "--pausa",
            type=float,
            default=ACERVO_PAUSA_REQUISICAO,
            help="segundos entre requisicoes (educado; nao e cota)",
        )

    p_aferir = sub.add_parser("aferir", help="mede o comportamento do teto de linhas")
    p_aferir.add_argument("--site", required=True)
    p_aferir.add_argument("--pausa", type=float, default=ACERVO_PAUSA_REQUISICAO)

    p_back = sub.add_parser("backfill", help="traz a janela retroativa inteira")
    comum(p_back, batch=True)
    p_back.add_argument("--dias", type=int, default=ACERVO_DIAS_BACKFILL)
    p_back.add_argument("--dry-run", action="store_true", help="imprime o plano e sai")
    p_back.add_argument("--forcar", action="store_true", help="re-pede dias ja resolvidos")

    p_dia = sub.add_parser("diario", help="re-busca a ponta e incorpora dias novos")
    comum(p_dia, batch=True)
    p_dia.add_argument("--dry-run", action="store_true")
    p_dia.add_argument(
        "--ponta-fresca",
        action="store_true",
        help="passada extra com dataState=all nos ultimos dias (dado volatil)",
    )

    p_re = sub.add_parser("reingerir", help="forca a re-ingestao de um intervalo")
    comum(p_re)
    p_re.add_argument("--de", required=True, help="data inicial ISO")
    p_re.add_argument("--ate", required=True, help="data final ISO")
    p_re.add_argument(
        "--apagar",
        action="store_true",
        help="apaga tambem as linhas de fato (para pagina/query que desapareceu)",
    )

    p_an = sub.add_parser(
        "anotar",
        help="registra o que mudou no site e quando (com as URLs afetadas)",
        description=(
            "Registra uma mudanca no site. As URLs sao o que transforma a analise em "
            "comparacao: com elas, 'reescrevi o texto destas 40 URLs' vira um grupo "
            "tratado contra o resto do site. Use --urls-de para lotes grandes."
        ),
    )
    p_an.add_argument("--site", required=True)
    p_an.add_argument("--data", required=True, help="data (ISO) do evento ou do inicio")
    p_an.add_argument("--ate", help="data final (ISO) para evento que levou dias")
    p_an.add_argument(
        "--tipo",
        dest="tipo_evento",
        required=True,
        help=f"vocabulario sugerido (texto livre): {', '.join(TIPOS_EVENTO_SUGERIDOS)}",
    )
    p_an.add_argument("--desc", required=True, help="o que mudou, em uma frase")
    p_an.add_argument(
        "--urls",
        action="append",
        help="URLs afetadas (repetivel; aceita lista separada por virgula)",
    )
    p_an.add_argument(
        "--urls-de",
        dest="urls_de",
        help="arquivo com uma URL por linha (# comenta) — para lotes grandes",
    )
    p_an.add_argument("--fonte", default="manual", help="quem/como registrou (padrao: manual)")

    p_ev = sub.add_parser("eventos", help="lista (ou remove) os eventos anotados")
    p_ev.add_argument("--site", required=True)
    p_ev.add_argument("--remover", type=int, help="id do evento a remover")
    p_ev.add_argument("--urls", action="store_true", help="lista tambem as URLs casadas")

    p_pac = sub.add_parser("pacote", help="gera o pacote de analise (snapshot + DADOS.md)")
    alvo_pac = p_pac.add_mutually_exclusive_group(required=True)
    alvo_pac.add_argument("--site", help="dominio ou sc-domain:")
    alvo_pac.add_argument("--batch", help="arquivo com um dominio por linha")
    p_pac.add_argument("--tipo", default="web", choices=plan.TIPOS_VALIDOS)
    p_pac.add_argument(
        "--reduzido",
        action="store_true",
        help=(
            "snapshot sem fato_query_pagina (mais da metade do volume). O DADOS.md "
            "declara o que ficou de fora"
        ),
    )
    p_pac.add_argument(
        "--sem-snapshot",
        dest="sem_snapshot",
        action="store_true",
        help="regenera so os documentos, sem recopiar o banco",
    )

    p_st = sub.add_parser("status", help="o que existe, o que falta, o que nao e confiavel")
    p_st.add_argument("--site", required=True)
    p_st.add_argument("--tipo", default="web", choices=plan.TIPOS_VALIDOS)

    return parser.parse_args(argv)


def _validar_datas(args) -> None:
    for campo in ("de", "ate", "data"):
        valor = getattr(args, campo, None)
        if valor is None:
            continue
        try:
            date.fromisoformat(valor)
        except ValueError as exc:
            raise AcervoError(f"--{campo} invalido: {valor} (use YYYY-MM-DD)") from exc
    de, ate = getattr(args, "de", None), getattr(args, "ate", None)
    if de and ate and de > ate:
        raise AcervoError(f"--de ({de}) e posterior a --ate ({ate})")
    # `anotar` usa --data/--ate como inicio/fim do mesmo evento.
    data = getattr(args, "data", None)
    if data and ate and data > ate:
        raise AcervoError(f"--data ({data}) e posterior a --ate ({ate})")


COMANDOS = {
    "aferir": cmd_aferir,
    "backfill": cmd_backfill,
    "diario": cmd_diario,
    "reingerir": cmd_reingerir,
    "anotar": cmd_anotar,
    "eventos": cmd_eventos,
    "pacote": cmd_pacote,
    "status": cmd_status,
}


def main(argv=None) -> None:
    args = parse_args(argv)
    funcao = COMANDOS[args.comando]

    try:
        _validar_datas(args)

        if getattr(args, "batch", None):
            from core.batch import parse_sites_file, run_batch

            sites = parse_sites_file(args.batch)
            if not sites:
                raise AcervoError(f"nenhum dominio valido em {args.batch}")

            def pipeline(site: str, _args=args, _fn=funcao):
                import copy

                por_site = copy.copy(_args)
                por_site.site = site
                por_site.batch = None
                return _fn(por_site)

            run_batch(sites, pipeline, format_fn=_resumo_lote)
            return

        funcao(args)
    # AcervoError e fetchers.acervo_fetcher.AcervoFetchError sao ambos
    # RuntimeError: um except cobre os dois sem importar googleapiclient aqui.
    # Qualquer outra excecao sobe com traceback — bug nao deve virar mensagem.
    except RuntimeError as exc:
        print(f"\n[ERRO] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
