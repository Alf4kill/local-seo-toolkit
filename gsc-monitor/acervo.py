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

Subcomandos:
    aferir     Mede empiricamente como o teto de linhas da API se comporta neste
               site (a doc não resolve se os 50k valem por dia ou por consulta).
               Nunca grava fato; grava só o diagnóstico em `meta`.
    backfill   Traz a janela retroativa inteira (padrão 480 dias, o máximo do
               GSC). Retoma de onde parou se for interrompido.
    diario     Re-busca a ponta que ainda assenta e incorpora os dias novos.
               É o comando para agendar.
    reingerir  Força a re-ingestão de um intervalo (--de/--ate).
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
from core.warehouse import plan, store

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
    return f"[OK]   {site:<28} {s.get('linhas', 0)} linhas  {s.get('requisicoes', 0)} requisicoes"


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def _imprimir_plano(site: str, graos: tuple, inicio: str, fim: str, args) -> dict:
    """Monta e imprime o plano SEM tocar na API (nem constrói o `service`)."""
    conn, propriedade = _abrir(site)
    try:
        dias_janela = plan.listar_dias(inicio, fim)
        medias = store.media_linhas_por_dia(conn, propriedade=propriedade, tipo=args.tipo)
        passos = []
        pendentes_por_grao = {}
        for grao in plan.graos_aplicaveis(graos, args.tipo):
            pendentes = store.dias_pendentes(
                conn,
                propriedade=propriedade,
                tipo=args.tipo,
                grao=grao,
                dias=dias_janela,
                forcar=getattr(args, "forcar", False),
            )
            pendentes_por_grao[grao] = pendentes
            passos.extend(plan.montar_passos(grao, args.tipo, pendentes))

        estimativa = plan.estimar_requisicoes(passos, medias)
    finally:
        conn.close()

    print("\n[acervo] PLANO (nenhuma chamada a API sera feita)")
    print(f"  propriedade: {propriedade}")
    print(f"  janela     : {inicio} a {fim} ({len(dias_janela)} dias)")
    print(f"  tipo       : {args.tipo}")
    print("")
    print(f"  {'grao':<14}{'pend.':>7}{'lote':>7}{'lotes':>7}{'req.est.':>10}{'linhas est.':>14}")
    print("  " + "-" * 59)
    vazio = {"lotes": 0, "requisicoes": 0, "linhas": 0}
    for grao, pendentes in pendentes_por_grao.items():
        info = estimativa["por_grao"].get(grao, vazio)
        print(
            f"  {grao:<14}{len(pendentes):>7}"
            f"{plan.ACERVO_DIAS_LOTE.get(grao, 30):>7}{info['lotes']:>7}"
            f"{info['requisicoes']:>10}{info['linhas'] or '?':>14}"
        )
    print("  " + "-" * 59)
    total = estimativa["total"]
    print(f"  TOTAL: {total['requisicoes']} requisicoes, ~{total['linhas'] or '?'} linhas")
    origem = (
        "medido na escrituracao"
        if total["medido"]
        else "SEM medicao ainda (rode um backfill curto primeiro)"
    )
    print(f"  estimativa de linhas: {origem}")
    segundos = total["requisicoes"] * (args.pausa + 1.5)
    print(f"  tempo estimado: ~{segundos / 60:.1f} min (pausa {args.pausa}s + latencia ~1.5s)\n")
    return estimativa


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
    """Corpo comum de backfill e diario."""
    from core.auth import build_service
    from fetchers.acervo_fetcher import ingerir_janela

    _checar_token()
    conn, propriedade = _abrir(args.site)
    execucao_id = store.iniciar_execucao(conn, comando=args.comando, propriedade=propriedade)
    contador: dict = {}
    try:
        service = build_service()
        resumo = ingerir_janela(
            service,
            conn,
            site_url=propriedade,
            propriedade=propriedade,
            inicio=inicio,
            fim=fim,
            graos=graos,
            tipo=args.tipo,
            data_state=data_state,
            forcar=forcar,
            pausa=args.pausa,
            contador=contador,
        )
        store.finalizar_execucao(
            conn,
            execucao_id,
            requisicoes=resumo["requisicoes"],
            linhas=resumo["linhas"],
            retentativas=contador.get("retentativas", 0),
            esperas_carga=contador.get("esperas_carga", 0),
        )
        print(
            f"\n[acervo] {propriedade}: {resumo['linhas']} linhas gravadas em "
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
    conn, propriedade = _abrir(args.site)
    try:
        apagado = store.apagar_intervalo(
            conn,
            propriedade=propriedade,
            tipo=args.tipo,
            graos=plan.graos_aplicaveis(graos, args.tipo),
            de=args.de,
            ate=args.ate,
            apagar_fatos=args.apagar,
        )
    finally:
        conn.close()
    print(
        f"[acervo] Escrituracao limpa: {apagado['ingestao']} dias, "
        f"{apagado['fatos']} linhas de fato apagadas."
    )
    return _ingerir(args, inicio=args.de, fim=args.ate, graos=graos)


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
            grao: store.contar_linhas(conn, spec["tabela"]) for grao, spec in plan.GRAOS.items()
        }
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
    print("  Cobertura (dias por grao e status)")
    if not cobertura:
        print("    (vazio — nenhuma ingestao ainda)")
    for linha in cobertura:
        media = linha.get("cobertura_media")
        extra = f"  cobertura {media:.0%}" if media is not None else ""
        print(
            f"    {linha['grao']:<14}{linha['status']:<14}{linha['dias']:>5} dias  "
            f"{linha['primeiro']} a {linha['ultimo']}{extra}"
        )

    print("-" * 70)
    print("  Linhas por tabela de fato")
    for grao, n in contagens.items():
        print(f"    {grao:<14}{n:>12}")

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
        p.add_argument(
            "--tipo",
            default="web",
            choices=plan.TIPOS_VALIDOS,
            help="`type` da Search Analytics (padrao: web)",
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

    p_st = sub.add_parser("status", help="o que existe, o que falta, o que nao e confiavel")
    p_st.add_argument("--site", required=True)
    p_st.add_argument("--tipo", default="web", choices=plan.TIPOS_VALIDOS)

    return parser.parse_args(argv)


def _validar_datas(args) -> None:
    for campo in ("de", "ate"):
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


COMANDOS = {
    "aferir": cmd_aferir,
    "backfill": cmd_backfill,
    "diario": cmd_diario,
    "reingerir": cmd_reingerir,
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
