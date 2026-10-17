"""
acervo_fetcher.py — Ingestão do acervo histórico via Search Analytics API (P7).

É a única camada do acervo que fala com a rede. Consome o plano puro de
core/warehouse/plan.py, normaliza com core/warehouse/rows.py e persiste com
core/warehouse/store.py.

Por que um fetcher NOVO em vez de estender position_fetcher.py: os testes de
tests/test_date_trends.py afirmam os corpos daquele módulo posicional e
literalmente (len(bodies) == 2, bodies[0]["dimensions"] == ["date"]), e quatro
superfícies dependem das suas funções. O acervo precisa enviar `type`,
`startRow` e `dimensionFilterGroups` — que o fetcher antigo nunca deve começar a
enviar. Retrofit fica para depois do acervo provado.

O que este módulo faz e o antigo não:
  - PAGINA com startRow até a resposta de ZERO linhas (o pseudocódigo oficial);
    rowLimit=25000 é tamanho de página, não teto de dados.
  - RETENTA 429/5xx com backoff (fetchers/gsc_retry.py).
  - RETOMA de onde parou, consultando a escrituração antes de pedir qualquer dia.
"""

import time

from config import (
    ACERVO_MAX_PAGINAS,
    ACERVO_PAUSA_REQUISICAO,
    ACERVO_TETO_DIA_TIPO,
    ROW_LIMIT,
)
from core.warehouse import plan, rows, store
from googleapiclient.errors import HttpError

from fetchers.gsc_retry import executar_com_retentativa


class AcervoFetchError(RuntimeError):
    """Falha fatal de ingestão (propriedade inexistente, dimensão recusada...)."""


# ---------------------------------------------------------------------------
# Paginação
# ---------------------------------------------------------------------------


def consultar_paginado(
    service,
    site_url: str,
    corpo_base: dict,
    *,
    max_paginas: int = ACERVO_MAX_PAGINAS,
    pausa: float = ACERVO_PAUSA_REQUISICAO,
    dormir=time.sleep,
    contador: "dict | None" = None,
) -> tuple:
    """Pagina com startRow até o terminador de ZERO linhas.

    Retorna (linhas_brutas, requisicoes, agregacao_resposta, capado).

    O terminador é a resposta VAZIA, não `len(rows) < rowLimit`: quando o total
    é múltiplo exato do rowLimit, a última página cheia é ambígua e só a
    resposta vazia seguinte prova que acabou. A API devolve 200 com zero linhas
    quando startRow passa do fim — é a saída limpa que a doc documenta.

    `capado` indica que o freio de max_paginas foi atingido: pode haver cauda
    não lida, e isso tem de ficar VISÍVEL na escrituração, nunca silencioso.
    """
    limite = corpo_base.get("rowLimit", ROW_LIMIT)
    etiqueta = (
        f"{corpo_base.get('dimensions')} {corpo_base.get('startDate')}..{corpo_base.get('endDate')}"
    )

    linhas: list = []
    requisicoes = 0
    agregacao = None
    capado = False

    for pagina in range(max_paginas):
        corpo = dict(corpo_base)
        if pagina:
            corpo["startRow"] = pagina * limite

        if requisicoes and pausa:
            dormir(pausa)

        resposta = executar_com_retentativa(
            lambda c=corpo: service.searchanalytics().query(siteUrl=site_url, body=c).execute(),
            etiqueta=etiqueta,
            dormir=dormir,
            contador=contador,
        )
        requisicoes += 1

        lote = resposta.get("rows") or []
        agregacao = agregacao or resposta.get("responseAggregationType")

        if not lote:
            break
        linhas.extend(lote)
        if len(lote) < limite:
            break
    else:
        capado = True
        print(
            f"[acervo] AVISO: freio de {max_paginas} paginas atingido em {etiqueta} "
            "— pode haver cauda nao lida (marcado 'pagina_capada')."
        )

    return linhas, requisicoes, agregacao, capado


# ---------------------------------------------------------------------------
# Execução de um passo
# ---------------------------------------------------------------------------


def _executar_passo(
    service,
    conn,
    site_url: str,
    passo: plan.Passo,
    *,
    propriedade: str,
    pausa: float = ACERVO_PAUSA_REQUISICAO,
    dormir=time.sleep,
    contador: "dict | None" = None,
    teto: int = ACERVO_TETO_DIA_TIPO,
) -> dict:
    """Pede, normaliza e grava um lote. Retorna estatísticas do lote.

    Se algum dia do lote chegar perto do teto de 50k linhas, o resultado do lote
    é DESCARTADO e o lote é refeito dia a dia (único nível de fallback): só com o
    dia isolado dá para saber se o corte foi do dia ou da consulta. Nesta escala
    (~340 linhas/dia) isso nunca dispara.
    """
    spec = plan.GRAOS[passo.grao]
    corpo = plan.montar_corpo(
        passo.inicio,
        passo.fim,
        passo.dimensoes,
        tipo=passo.tipo,
        # O passo carrega o rotulo de PROVENIENCIA ('final_provisorio' inclusive);
        # a API so aceita 'final'/'all'. A traducao mora aqui, na fronteira.
        data_state=plan.data_state_api(passo.data_state),
        filtros=passo.filtros,
    )

    try:
        brutas, requisicoes, agregacao, capado = consultar_paginado(
            service,
            site_url,
            corpo,
            pausa=pausa,
            dormir=dormir,
            contador=contador,
        )
    except HttpError as exc:
        store.marcar_erro(
            conn,
            grao=passo.grao,
            propriedade=propriedade,
            tipo=passo.tipo,
            dias=passo.dias,
            data_state=passo.data_state,
            erro=f"{getattr(exc, 'status_code', '?')} {getattr(exc, 'reason', exc)}",
        )
        raise

    fixo = {"aparencia": passo.aparencia} if passo.aparencia else None
    linhas = rows.normalizar_linhas(brutas, colunas=spec["colunas"], fixo=fixo)
    contagem = rows.contar_por_dia(linhas)

    if len(passo.dias) > 1 and plan.precisa_dia_a_dia(contagem, teto=teto):
        print(
            f"[acervo] Lote {passo.grao} {passo.inicio}..{passo.fim} chegou perto do teto "
            "de 50k linhas/dia — refazendo dia a dia para nao perder a cauda."
        )
        resultado = {"linhas": 0, "requisicoes": requisicoes, "dias": 0, "dividido": True}
        for dia in passo.dias:
            parcial = _executar_passo(
                service,
                conn,
                site_url,
                plan.Passo(
                    grao=passo.grao,
                    tipo=passo.tipo,
                    dimensoes=passo.dimensoes,
                    inicio=dia,
                    fim=dia,
                    dias=(dia,),
                    data_state=passo.data_state,
                    filtros=passo.filtros,
                    aparencia=passo.aparencia,
                ),
                propriedade=propriedade,
                pausa=pausa,
                dormir=dormir,
                contador=contador,
                teto=teto,
            )
            resultado["linhas"] += parcial["linhas"]
            resultado["requisicoes"] += parcial["requisicoes"]
            resultado["dias"] += parcial["dias"]
        return resultado

    # Cobertura: impressões do grão / impressões do site no mesmo dia. Para o
    # próprio `total` não faz sentido (seria 1,0 por construção).
    cobertura: dict = {}
    if passo.grao != "total":
        totais = store.impressoes_total_por_dia(
            conn, propriedade=propriedade, tipo=passo.tipo, dias=list(passo.dias)
        )
        cobertura = rows.cobertura_por_dia(rows.impressoes_por_dia(linhas), totais)

    status_por_dia = {}
    for dia in plan.dias_no_teto(contagem, teto=teto):
        status_por_dia[dia] = store.STATUS_TETO
    if capado:
        for dia in passo.dias:
            status_por_dia.setdefault(dia, store.STATUS_CAPADO)

    gravado = store.gravar_lote(
        conn,
        grao=passo.grao,
        propriedade=propriedade,
        tipo=passo.tipo,
        linhas=linhas,
        dias_do_lote=passo.dias,
        data_state=passo.data_state,
        lote_inicio=passo.inicio,
        lote_fim=passo.fim,
        paginas=requisicoes,
        agregacao=agregacao,
        cobertura=cobertura,
        status_por_dia=status_por_dia,
    )

    return {
        "linhas": gravado["linhas"],
        "dias": gravado["dias"],
        "requisicoes": requisicoes,
        "dividido": False,
    }


# ---------------------------------------------------------------------------
# Ingestão de uma janela
# ---------------------------------------------------------------------------


def ingerir_janela(
    service,
    conn,
    *,
    site_url: str,
    propriedade: str,
    inicio: str,
    fim: str,
    graos=plan.GRAOS_PADRAO,
    tipo: str = "web",
    hoje=None,
    data_state: "str | None" = None,
    forcar: bool = False,
    pausa: float = ACERVO_PAUSA_REQUISICAO,
    dormir=time.sleep,
    tamanhos: "dict | None" = None,
    contador: "dict | None" = None,
) -> dict:
    """Ingere a janela [inicio, fim] nos grãos pedidos, retomando o que falta.

    O grão `total` vem SEMPRE primeiro (plan.graos_aplicaveis garante): ele nunca
    trunca e é a régua contra a qual a cobertura dos outros grãos é medida.
    """
    pedidos = plan.graos_aplicaveis(graos, tipo)
    for grao in pedidos:
        if plan.GRAOS[grao].get("fixo"):
            raise AcervoFetchError(
                f"O grao '{grao}' depende de dimensionFilterGroups (2 etapas) e entra "
                "na fase P7.4. Rode sem ele."
            )

    dias_janela = plan.listar_dias(inicio, fim)
    resumo: dict = {"grãos": {}, "requisicoes": 0, "linhas": 0}

    for grao in pedidos:
        pendentes = store.dias_pendentes(
            conn,
            propriedade=propriedade,
            tipo=tipo,
            grao=grao,
            dias=dias_janela,
            hoje=hoje,
            forcar=forcar,
        )
        if not pendentes:
            print(f"[acervo] {grao:13s} nada pendente ({len(dias_janela)} dias ja no acervo).")
            resumo["grãos"][grao] = {"dias": 0, "linhas": 0, "requisicoes": 0}
            continue

        passos = plan.montar_passos(
            grao,
            tipo,
            pendentes,
            hoje=hoje,
            tamanho_lote=(tamanhos or {}).get(grao),
            data_state=data_state,
        )
        print(f"[acervo] {grao:13s} {len(pendentes)} dias pendentes em {len(passos)} lote(s)...")

        info = {"dias": 0, "linhas": 0, "requisicoes": 0}
        for passo in passos:
            parcial = _executar_passo(
                service,
                conn,
                site_url,
                passo,
                propriedade=propriedade,
                pausa=pausa,
                dormir=dormir,
                contador=contador,
            )
            info["dias"] += parcial["dias"]
            info["linhas"] += parcial["linhas"]
            info["requisicoes"] += parcial["requisicoes"]

        print(
            f"[acervo] {grao:13s} OK — {info['linhas']} linhas, "
            f"{info['dias']} dias, {info['requisicoes']} requisicoes."
        )
        resumo["grãos"][grao] = info
        resumo["requisicoes"] += info["requisicoes"]
        resumo["linhas"] += info["linhas"]

    return resumo


# ---------------------------------------------------------------------------
# Aferição do teto (roda uma vez por site, antes de fixar tamanho de lote)
# ---------------------------------------------------------------------------


def aferir(
    service,
    site_url: str,
    *,
    hoje=None,
    dias_lote: int = 30,
    pausa: float = ACERVO_PAUSA_REQUISICAO,
    dormir=time.sleep,
    teto: int = ACERVO_TETO_DIA_TIPO,
) -> dict:
    """Mede empiricamente como o teto de linhas da API se comporta neste site.

    A doc oficial diz que a Search Analytics "exposes a maximum of 50K rows of
    data per day per search type", mas NÃO diz se esse teto vale por dia dentro
    da consulta ou por consulta — e as fontes de terceiros se contradizem. A
    diferença decide se lotes grandes são seguros ou se perdem a cauda longa.

    O teste: escolhe o dia de maior volume da janela e compara as linhas DAQUELE
    DIA (a) numa consulta de um dia só e (b) dentro de uma consulta de 30 dias.

      iguais     -> o teto vale por dia; lotes grandes são seguros.
      (b) menor  -> o teto vale por consulta; lotes grandes perdem cauda.

    Também confirma a regra da aparência: ["searchAppearance"] sozinho deve
    funcionar e ["date","searchAppearance"] deve ser recusado com 400.

    Custo: ~5 a 8 requisições. Nunca grava nada — só devolve o diagnóstico.
    """
    inicio, fim = plan.intervalo_datas(dias_lote, hoje=hoje)
    resultado: dict = {"janela": [inicio, fim], "teto_documentado": teto}

    # (0) dia de maior volume — ["date"] nunca trunca (1 linha/dia).
    brutas, _, _, _ = consultar_paginado(
        service,
        site_url,
        plan.montar_corpo(inicio, fim, ("date",)),
        pausa=pausa,
        dormir=dormir,
    )
    dias = rows.normalizar_linhas(brutas, colunas=())
    if not dias:
        resultado["conclusao"] = "sem dados na janela — nao foi possivel aferir"
        return resultado

    pico = max(dias, key=lambda linha: linha["impressions"])
    dia = pico["data"]
    resultado["dia_pico"] = dia
    resultado["impressoes_no_dia"] = pico["impressions"]

    # (a) o dia isolado
    brutas_a, req_a, _, _ = consultar_paginado(
        service,
        site_url,
        plan.montar_corpo(dia, dia, ("date", "query")),
        pausa=pausa,
        dormir=dormir,
    )
    linhas_a = rows.normalizar_linhas(brutas_a, colunas=("query_id",))
    resultado["isolado"] = {
        "linhas": len(linhas_a),
        "impressoes": sum(linha["impressions"] for linha in linhas_a),
        "requisicoes": req_a,
    }

    # (b) o mesmo dia dentro de um lote de `dias_lote` dias
    brutas_b, req_b, _, _ = consultar_paginado(
        service,
        site_url,
        plan.montar_corpo(inicio, fim, ("date", "query")),
        pausa=pausa,
        dormir=dormir,
    )
    linhas_b = [
        linha
        for linha in rows.normalizar_linhas(brutas_b, colunas=("query_id",))
        if linha["data"] == dia
    ]
    resultado["no_lote"] = {
        "linhas": len(linhas_b),
        "impressoes": sum(linha["impressions"] for linha in linhas_b),
        "requisicoes": req_b,
        "linhas_lote_inteiro": len(brutas_b),
        "dias_no_lote": dias_lote,
    }

    iguais = (
        resultado["isolado"]["linhas"] == resultado["no_lote"]["linhas"]
        and resultado["isolado"]["impressoes"] == resultado["no_lote"]["impressoes"]
    )
    if iguais:
        resultado["teto_por"] = "dia"
        resultado["conclusao"] = (
            "o lote de 30 dias enxergou o mesmo que o dia isolado: o teto vale POR DIA "
            "dentro da consulta. Lotes grandes sao seguros — pode subir ACERVO_DIAS_LOTE."
        )
    else:
        resultado["teto_por"] = "consulta"
        resultado["conclusao"] = (
            "o lote de 30 dias enxergou MENOS que o dia isolado: o teto vale POR CONSULTA. "
            "Lotes grandes perdem a cauda longa — mantenha ou reduza ACERVO_DIAS_LOTE."
        )

    # (c) a regra da aparência, confirmada contra a API e não contra a doc.
    try:
        brutas_c, _, _, _ = consultar_paginado(
            service,
            site_url,
            plan.montar_corpo(inicio, fim, ("searchAppearance",)),
            pausa=pausa,
            dormir=dormir,
        )
        resultado["aparencias"] = rows.valores_aparencia(brutas_c)
    except HttpError as exc:
        resultado["aparencias"] = []
        resultado["aparencia_isolada_erro"] = f"{getattr(exc, 'status_code', '?')} {exc}"

    try:
        consultar_paginado(
            service,
            site_url,
            plan.montar_corpo(inicio, fim, ("date", "searchAppearance")),
            pausa=pausa,
            dormir=dormir,
        )
        resultado["aparencia_combinada"] = "aceita (divergente da doc — reavaliar o plano)"
    except HttpError as exc:
        resultado["aparencia_combinada"] = (
            f"recusada como esperado: {getattr(exc, 'status_code', '?')} "
            f"{getattr(exc, 'reason', '')}".strip()
        )

    return resultado
