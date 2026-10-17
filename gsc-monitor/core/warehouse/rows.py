"""
rows.py — Normalização das linhas da Search Analytics API (lógica PURA).

Converte a resposta da API em "linhas lógicas" prontas para o upsert, sem tocar
em sqlite nem em rede. A resolução das dimensões internadas (URL -> dim_pagina.id,
termo -> dim_query.id) é feita depois, em store.py: aqui a chave carrega o valor
de texto cru.

Duas decisões que importam para a análise futura:

  - `ctr` é guardado CRU (fração 0..1) e `position` sem arredondar. Diverge de
    propósito de fetchers/position_fetcher.py, que faz round(ctr*100, 2) e
    round(position, 1) para apresentação. Um arquivo não deve embutir decisão de
    apresentação: arredondar a posição para 1 decimal destrói exatamente os
    deltas pequenos que uma análise de 2 anos procura.

  - `clicks` e `impressions` são inteiros (a API devolve float), `position` pode
    ser None. Nada é inventado: linha sem o valor de alguma dimensão da chave é
    DESCARTADA, não completada com vazio.
"""

# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------


def _metricas(linha: dict) -> dict:
    """Extrai e coage as 4 métricas de uma linha da API."""
    posicao = linha.get("position")
    return {
        "clicks": int(linha.get("clicks") or 0),
        "impressions": int(linha.get("impressions") or 0),
        "ctr": float(linha.get("ctr") or 0.0),
        "position": float(posicao) if posicao is not None else None,
    }


def normalizar_linhas(
    linhas: list,
    *,
    colunas: tuple,
    fixo: "dict | None" = None,
) -> list:
    """Resposta da API -> linhas lógicas.

    `colunas` são as colunas de chave além de (propriedade, tipo, data), na
    MESMA ordem das dimensões pedidas depois de `date` (mapeamento posicional
    com `keys`, que é como a API devolve).

    `fixo` injeta chaves cujo valor NÃO vem de `keys` mas do filtro da
    requisição — o caso da aparência, que a API não deixa agrupar com outra
    dimensão (ver plan.filtro_aparencia).

    Retorna:
        [{"data": "YYYY-MM-DD", "chaves": {coluna: valor},
          "clicks": int, "impressions": int, "ctr": float, "position": float|None}]
    """
    fixo = fixo or {}
    saida = []

    for linha in linhas or []:
        keys = linha.get("keys") or []
        if not keys:
            continue  # sem a dimensão `date` não há como datar a linha

        data = keys[0]
        if not data:
            continue

        chaves = dict(fixo)
        faltou = False
        for pos, coluna in enumerate(colunas):
            if coluna in chaves:
                continue  # veio do filtro, não de keys
            idx = pos + 1  # keys[0] é sempre a data
            valor = keys[idx] if idx < len(keys) else None
            if valor is None or valor == "":
                faltou = True
                break
            chaves[coluna] = valor

        if faltou or len(chaves) != len(colunas):
            continue

        saida.append({"data": data, "chaves": chaves, **_metricas(linha)})

    return saida


def valores_aparencia(linhas: list) -> list:
    """Etapa 1 da aparência: extrai os tipos presentes de ["searchAppearance"].

    Ordenado para o plano ser determinístico (e os testes, estáveis).
    """
    vistos = []
    for linha in linhas or []:
        keys = linha.get("keys") or []
        if keys and keys[0]:
            vistos.append(keys[0])
    return sorted(set(vistos))


# ---------------------------------------------------------------------------
# Agregados por dia — alimentam a escrituração (`ingestao`)
# ---------------------------------------------------------------------------


def contar_por_dia(linhas: list) -> dict:
    """{data: nº de linhas}. É o que detecta dia no teto de 50k."""
    contagem: dict = {}
    for linha in linhas:
        contagem[linha["data"]] = contagem.get(linha["data"], 0) + 1
    return contagem


def impressoes_por_dia(linhas: list) -> dict:
    """{data: soma de impressões} do grão."""
    soma: dict = {}
    for linha in linhas:
        soma[linha["data"]] = soma.get(linha["data"], 0) + linha["impressions"]
    return soma


def cobertura_por_dia(impressoes_grao: dict, impressoes_total: dict) -> dict:
    """{data: impressões do grão / impressões do site no mesmo dia}.

    O grão `total` nunca trunca (1 linha/dia), então serve de régua para todos
    os outros. O número resultante mede DUAS coisas de uma vez, e por isso vale
    mais que um detector dedicado:

      - em `pagina`, bem abaixo de 1,0 indica TRUNCAMENTO (a API cortou a cauda);
      - em `query`/`query_pagina`, mede a CAUDA ANONIMIZADA — o quanto o GSC
        esconde por limiar de privacidade. É o número que o pacote de análise
        tem de reportar para ninguém tratar a soma das queries como o total.

    None quando não há total conhecido para o dia (nunca 0 ou 1: inventar valor
    aqui seria exatamente o tipo de falsa confiança que o acervo evita).
    """
    cobertura: dict = {}
    for dia, impressoes in impressoes_grao.items():
        total = impressoes_total.get(dia)
        cobertura[dia] = (impressoes / total) if total else None
    return cobertura
