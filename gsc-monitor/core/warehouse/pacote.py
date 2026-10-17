"""
pacote.py — Monta o pacote de análise do acervo (P7.2).

O acervo extrai; a ANÁLISE acontece depois, numa sessão separada, com o projeto
do site em mãos. Este módulo produz o que atravessa essa fronteira:

    relatorios/{dominio}/acervo/pacote/
        acervo.sqlite3   snapshot consistente (Connection.backup())
        DADOS.md         o entregável de primeira classe
        eventos.csv      a timeline, para uso de máquina
        evento_urls.csv  uma linha por (evento, URL informada, casou ou não)
        consultas.sql    ~9 consultas prontas — boilerplate de SQL, NÃO análise
        extras/LEIA.md   onde largar exports manuais da UI do GSC

`DADOS.md` existe para impedir conclusão errada, e isso é mais específico do que
"documentar o banco". Três leituras erradas que o dado real de fato produziu, e
que o documento tem de barrar:

  1. Cobertura de 1,29 lida como banco corrompido. Não é: o grão `pagina` vem
     com `responseAggregationType = byPage`, e aí uma impressão de SERP é
     contada uma vez POR URL do site que apareceu nela, enquanto o grão `total`
     (`byProperty`) conta uma só. Passar de 1,0 é o esperado.
  2. Cobertura de 0,61 lida como coleta falha. Não é: num grão `byProperty` o
     que falta é a cauda que o GSC anonimiza — e é justamente o que a cobertura
     serve para MEDIR.
  3. As duas pontas das coortes de URL lidas como onda real de publicação e de
     mortandade. Não são: toda URL que já existia quando a janela abriu cai no
     primeiro mês, e toda URL ainda viva cai no último. São artefato da janela,
     e aqui vêm rotuladas como artefato.

Não analisa, não pontua, não dá veredito: tudo aqui é contagem, data, rótulo de
proveniência e SQL de boilerplate.
"""

import os
import sqlite3
from datetime import date

from core.warehouse import plan, store

# Nome fixo dentro do pacote: `consultas.sql` e qualquer caminho que a sessão de
# análise anote continuam valendo entre gerações do pacote.
NOME_SNAPSHOT = "acervo.sqlite3"

# O que o snapshot `--reduzido` deixa de fora. `fato_query_pagina` é mais da
# metade do volume (no site-piloto: 161 MB inteiros contra ~70 MB sem ela) e é
# também o grão mais caro de perder — por isso o default é o pacote COMPLETO, e
# o reduzido é opt-in, declarado no DADOS.md.
TABELAS_FORA_DO_REDUZIDO = ("fato_query_pagina",)

MAX_DIAS_LISTADOS = 40
MAX_URLS_LISTADAS = 15


# ---------------------------------------------------------------------------
# Consultas prontas (boilerplate de SQL, não análise)
# ---------------------------------------------------------------------------
#
# Cada entrada é (slug, título, para que serve, SQL). Toda consulta é UM SELECT
# que roda como está contra o snapshot — inclusive em banco vazio — e tem os
# valores a trocar marcados com `TROQUE`. Ficam em Python, e não num .sql solto,
# porque assim o teste executa exatamente o que o arquivo contém.

_POSICAO_PONDERADA = """SUM(CASE WHEN position IS NOT NULL THEN position * impressions END)
             / NULLIF(SUM(CASE WHEN position IS NOT NULL THEN impressions END), 0)"""

CONSULTAS = (
    (
        "serie_diaria_de_uma_url",
        "Série diária de UMA URL",
        "O gráfico de uma página ao longo de toda a janela.",
        """
SELECT data, clicks, impressions, ctr, position, data_state
FROM v_pagina_dia
WHERE tipo = 'web'
  AND pagina LIKE '%'          -- TROQUE: AND pagina = 'https://.../sua-url'
ORDER BY data
""",
    ),
    (
        "serie_mensal_de_uma_query",
        "Série mensal de UMA query",
        "ctr e posição JÁ re-derivados pela view (não some as colunas cruas).",
        """
SELECT ano_mes, clicks, impressions, ctr_recalculado, posicao_ponderada, dias_com_dado
FROM v_query_mes
WHERE tipo = 'web'
  AND query LIKE '%'           -- TROQUE: AND query = 'sua query'
ORDER BY ano_mes
""",
    ),
    (
        "antes_depois_do_site",
        "Antes/depois de uma data, no site inteiro",
        "A régua: o grão `total` nunca trunca e nunca é afetado pela anonimização.",
        f"""
WITH j AS (
    SELECT '2026-01-01' AS antes_de,  '2026-01-31' AS antes_ate,   -- TROQUE
           '2026-03-01' AS depois_de, '2026-03-31' AS depois_ate   -- TROQUE
)
SELECT CASE WHEN data BETWEEN (SELECT antes_de FROM j) AND (SELECT antes_ate FROM j)
            THEN 'antes' ELSE 'depois' END AS fase,
       COUNT(*) AS dias, SUM(clicks) AS clicks, SUM(impressions) AS impressions,
       1.0 * SUM(clicks) / NULLIF(SUM(impressions), 0) AS ctr,
       {_POSICAO_PONDERADA} AS posicao
FROM fato_total
WHERE tipo = 'web'
  AND (data BETWEEN (SELECT antes_de FROM j)  AND (SELECT antes_ate FROM j)
    OR data BETWEEN (SELECT depois_de FROM j) AND (SELECT depois_ate FROM j))
GROUP BY fase
""",
    ),
    (
        "antes_depois_evento_tratadas_x_demais",
        "Antes/depois das URLs de UM evento contra as demais URLs do site",
        (
            "A consulta que carrega o argumento: o grupo tratado (as URLs que o "
            "evento registrou) contra o resto do site, nas mesmas duas janelas. "
            "Se as duas coortes caem igual, a causa não é o que foi feito nessas "
            "URLs. A coorte vem de `evento_pagina`, já casada com dim_pagina."
        ),
        f"""
WITH evt AS (
    SELECT data AS inicio, COALESCE(data_fim, data) AS fim
    FROM evento WHERE id = 1                         -- TROQUE pelo id do evento
),
j AS (
    SELECT date(inicio, '-28 days') AS antes_de,  date(inicio, '-1 days') AS antes_ate,
           date(fim,    '+1 days')  AS depois_de, date(fim,   '+28 days') AS depois_ate
    FROM evt
),
base AS (
    SELECT f.pagina_id,
           CASE WHEN ep.pagina_id IS NOT NULL THEN 'tratada' ELSE 'nao_tratada' END AS coorte,
           CASE WHEN f.data BETWEEN (SELECT antes_de FROM j)  AND (SELECT antes_ate FROM j)
                     THEN 'antes'
                WHEN f.data BETWEEN (SELECT depois_de FROM j) AND (SELECT depois_ate FROM j)
                     THEN 'depois' END AS fase,
           f.clicks, f.impressions, f.position
    FROM fato_pagina f
    LEFT JOIN evento_pagina ep
           ON ep.pagina_id = f.pagina_id AND ep.evento_id = 1   -- TROQUE (o mesmo id)
    WHERE f.tipo = 'web'
      AND f.data BETWEEN (SELECT antes_de FROM j) AND (SELECT depois_ate FROM j)
)
SELECT coorte, fase, COUNT(DISTINCT pagina_id) AS urls,
       SUM(clicks) AS clicks, SUM(impressions) AS impressions,
       1.0 * SUM(clicks) / NULLIF(SUM(impressions), 0) AS ctr,
       {_POSICAO_PONDERADA} AS posicao
FROM base
WHERE fase IS NOT NULL
GROUP BY coorte, fase
ORDER BY coorte, fase
""",
    ),
    (
        "urls_que_cairam",
        "URLs que caíram mais entre duas janelas",
        "Delta por URL. Ordenado pela maior queda de cliques.",
        f"""
WITH j AS (
    SELECT '2026-01-01' AS antes_de,  '2026-01-31' AS antes_ate,   -- TROQUE
           '2026-03-01' AS depois_de, '2026-03-31' AS depois_ate   -- TROQUE
),
antes AS (
    SELECT pagina_id, SUM(clicks) AS clicks, SUM(impressions) AS impressions, {_POSICAO_PONDERADA} AS posicao
    FROM fato_pagina, j
    WHERE tipo = 'web' AND data BETWEEN j.antes_de AND j.antes_ate
    GROUP BY pagina_id
),
depois AS (
    SELECT pagina_id, SUM(clicks) AS clicks, SUM(impressions) AS impressions, {_POSICAO_PONDERADA} AS posicao
    FROM fato_pagina, j
    WHERE tipo = 'web' AND data BETWEEN j.depois_de AND j.depois_ate
    GROUP BY pagina_id
)
SELECT p.url,
       COALESCE(a.clicks, 0) AS clicks_antes, COALESCE(d.clicks, 0) AS clicks_depois,
       COALESCE(d.clicks, 0) - COALESCE(a.clicks, 0) AS delta_clicks,
       COALESCE(a.impressions, 0) AS impressions_antes,
       COALESCE(d.impressions, 0) AS impressions_depois,
       a.posicao AS posicao_antes, d.posicao AS posicao_depois
FROM dim_pagina p
LEFT JOIN antes  a ON a.pagina_id = p.id
LEFT JOIN depois d ON d.pagina_id = p.id
WHERE a.pagina_id IS NOT NULL OR d.pagina_id IS NOT NULL
ORDER BY delta_clicks
LIMIT 200
""",
    ),
    (
        "queries_que_trocaram_de_url",
        "Queries que trocaram de URL entre duas janelas",
        (
            "A URL dominante (mais impressões) de cada query em cada janela. "
            "Exige o grão `query_pagina` — vazio no snapshot reduzido."
        ),
        """
WITH j AS (
    SELECT '2026-01-01' AS antes_de,  '2026-01-31' AS antes_ate,   -- TROQUE
           '2026-03-01' AS depois_de, '2026-03-31' AS depois_ate   -- TROQUE
),
fases AS (
    SELECT f.query_id, f.pagina_id,
           CASE WHEN f.data BETWEEN j.antes_de AND j.antes_ate THEN 'antes'
                ELSE 'depois' END AS fase,
           SUM(f.impressions) AS impressions
    FROM fato_query_pagina f, j
    WHERE f.tipo = 'web'
      AND (f.data BETWEEN j.antes_de  AND j.antes_ate
        OR f.data BETWEEN j.depois_de AND j.depois_ate)
    GROUP BY f.query_id, f.pagina_id, fase
),
dominante AS (
    SELECT query_id, pagina_id, fase, impressions,
           ROW_NUMBER() OVER (PARTITION BY query_id, fase ORDER BY impressions DESC) AS posto
    FROM fases
)
SELECT q.termo AS query, pa.url AS url_antes, pd.url AS url_depois,
       a.impressions AS impressions_antes, d.impressions AS impressions_depois
FROM dominante a
JOIN dominante d ON d.query_id = a.query_id AND d.fase = 'depois' AND d.posto = 1
JOIN dim_query  q  ON q.id  = a.query_id
JOIN dim_pagina pa ON pa.id = a.pagina_id
JOIN dim_pagina pd ON pd.id = d.pagina_id
WHERE a.fase = 'antes' AND a.posto = 1 AND a.pagina_id <> d.pagina_id
ORDER BY d.impressions DESC
LIMIT 200
""",
    ),
    (
        "coorte_de_urls",
        "Primeiro e último dia de cada URL (coortes)",
        (
            "As ondas de publicação e de mortandade. ATENÇÃO: as duas pontas são "
            "ARTEFATO — URL que já existia antes da janela aparece surgindo no "
            "primeiro mês, e URL ainda viva aparece morrendo no último. Compare "
            "`surgiu`/`visto_por_ultimo` com o primeiro e o último dia do acervo "
            "antes de chamar qualquer uma das duas pontas de evento."
        ),
        """
WITH borda AS (
    SELECT MIN(data) AS primeiro_dia, MAX(data) AS ultimo_dia
    FROM fato_pagina WHERE tipo = 'web'
),
url AS (
    SELECT pagina_id, MIN(data) AS surgiu, MAX(data) AS visto_por_ultimo,
           COUNT(*) AS dias_com_dado, SUM(clicks) AS clicks
    FROM fato_pagina WHERE tipo = 'web' GROUP BY pagina_id
)
SELECT p.url, u.surgiu, u.visto_por_ultimo, u.dias_com_dado, u.clicks,
       CASE WHEN u.surgiu = (SELECT primeiro_dia FROM borda) THEN 1 ELSE 0 END
            AS surgiu_na_borda_artefato,
       CASE WHEN u.visto_por_ultimo = (SELECT ultimo_dia FROM borda) THEN 1 ELSE 0 END
            AS viva_no_fim_artefato
FROM url u JOIN dim_pagina p ON p.id = u.pagina_id
ORDER BY u.surgiu, p.url
""",
    ),
    (
        "cobertura_e_agregacao",
        "Cobertura medida AO LADO da agregação declarada pela API",
        (
            "Leia as duas colunas juntas, sempre. `byPage` conta uma impressão de "
            "SERP uma vez por URL do site que apareceu nela, então cobertura > 1 é "
            "esperada; `byProperty` conta uma só, então cobertura < 1 é a cauda "
            "anonimizada. Ver a seção 6 do DADOS.md."
        ),
        """
SELECT grao, agregacao_resposta, substr(data, 1, 7) AS ano_mes,
       COUNT(*) AS dias, AVG(cobertura_impressoes) AS cobertura_media,
       MIN(cobertura_impressoes) AS cobertura_min, MAX(cobertura_impressoes) AS cobertura_max
FROM ingestao
WHERE tipo = 'web' AND cobertura_impressoes IS NOT NULL
GROUP BY grao, agregacao_resposta, ano_mes
ORDER BY grao, ano_mes
""",
    ),
    (
        "eventos_e_suas_coortes",
        "Eventos anotados e o tamanho da coorte de cada um",
        (
            "`urls_casadas` menor que o que você anotou significa que a URL não "
            "existe em dim_pagina — ou nunca teve impressão, ou a forma informada "
            "não casou. Confira em evento_urls.csv antes de concluir."
        ),
        """
SELECT e.id, e.data, COALESCE(e.data_fim, e.data) AS data_fim, e.tipo, e.descricao,
       e.fonte, COUNT(ep.pagina_id) AS urls_casadas
FROM evento e
LEFT JOIN evento_pagina ep ON ep.evento_id = e.id
GROUP BY e.id
ORDER BY e.data, e.id
""",
    ),
)


# ---------------------------------------------------------------------------
# Helpers de formatação
# ---------------------------------------------------------------------------


def _comprimir_intervalos(dias: list) -> list:
    """['2026-01-01','2026-01-02','2026-01-05'] -> ['2026-01-01 a 2026-01-02', '2026-01-05'].

    Um buraco de 60 dias consecutivos tem de caber numa linha, senão a seção de
    buracos vira um paredão que ninguém lê — e buraco não lido é buraco não
    considerado.
    """
    if not dias:
        return []
    from datetime import timedelta

    ordenados = sorted(dias)
    blocos = []
    inicio = anterior = date.fromisoformat(ordenados[0])
    for texto in ordenados[1:]:
        atual = date.fromisoformat(texto)
        if atual - anterior == timedelta(days=1):
            anterior = atual
            continue
        blocos.append((inicio, anterior))
        inicio = anterior = atual
    blocos.append((inicio, anterior))
    return [a.isoformat() if a == b else f"{a.isoformat()} a {b.isoformat()}" for a, b in blocos]


def _lista_curta(itens: list, maximo: int) -> str:
    """Itens separados por vírgula, truncados com a contagem do que sobrou."""
    if not itens:
        return "—"
    if len(itens) <= maximo:
        return ", ".join(str(i) for i in itens)
    resto = len(itens) - maximo
    return ", ".join(str(i) for i in itens[:maximo]) + f" … (+{resto})"


def _pct(valor) -> str:
    """Cobertura com 3 decimais e vírgula decimal (pt-BR).

    A vírgula não é cosmética: o documento usa ponto como separador de MILHAR
    ('94.720 linhas'), então imprimir a cobertura como '1.060' deixaria o número
    ambíguo entre 'um e pouco' e 'mil e sessenta' — e é justamente este número
    que a seção 6 existe para o analista ler certo.
    """
    return "—" if valor is None else f"{valor:.3f}".replace(".", ",")


def _milhar(n: int) -> str:
    """700000 -> '700.000'. Só o número: aplicar o replace na linha inteira da
    tabela trocaria também a vírgula do texto ao lado."""
    return f"{n:,}".replace(",", ".")


def _tamanho_mb(caminho: str) -> float:
    return os.path.getsize(caminho) / 1_048_576 if os.path.exists(caminho) else 0.0


# ---------------------------------------------------------------------------
# Coleta: tudo que o DADOS.md declara, lido do banco
# ---------------------------------------------------------------------------


def coletar(conn: sqlite3.Connection, *, propriedade: str, tipo: str) -> dict:
    """Lê do banco tudo que o DADOS.md precisa. Só leitura e contagem."""
    # Contagem DO TIPO deste pacote, não da tabela inteira: um acervo pode ter
    # `web` e `image`, e somar os dois num pacote de `web` inflaria todo número
    # da seção 1 com linhas de outra superfície de busca.
    por_tipo = {
        grao: store.contar_linhas_por_tipo(conn, spec["tabela"])
        for grao, spec in plan.GRAOS.items()
    }
    contagens = {grao: contagens_grao.get(tipo, 0) for grao, contagens_grao in por_tipo.items()}
    outros_tipos = sorted(
        {t for contagens_grao in por_tipo.values() for t in contagens_grao} - {tipo}
    )
    return {
        "propriedade": propriedade,
        "tipo": tipo,
        "outros_tipos": outros_tipos,
        "gerado_em": store.agora(),
        "versao_esquema": conn.execute("PRAGMA user_version").fetchone()[0],
        "meta": {
            chave: store.ler_meta(conn, chave)
            for chave in ("criado_em", "fuso_dados", "propriedades", "afericao_em")
        },
        "contagens": contagens,
        "dimensoes": {
            "paginas": store.contar_linhas(conn, "dim_pagina"),
            "queries": store.contar_linhas(conn, "dim_query"),
        },
        "graos": store.dias_por_grao(conn, propriedade=propriedade, tipo=tipo),
        "provisorios": store.dias_provisorios(conn, propriedade=propriedade),
        "agregacao": store.agregacao_e_cobertura(conn, propriedade=propriedade, tipo=tipo),
        "cobertura_mes": store.cobertura_por_mes(conn, propriedade=propriedade, tipo=tipo),
        "coortes": store.coortes_url(conn, propriedade=propriedade, tipo=tipo),
        "eventos": store.listar_eventos(conn, propriedade=propriedade),
        "aparencias": [
            dict(linha)
            for linha in conn.execute(
                "SELECT valor, primeira_vez, ultima_vez FROM dim_aparencia_vista ORDER BY valor"
            )
        ],
        "execucoes": store.ultimas_execucoes(conn, 5),
    }


# ---------------------------------------------------------------------------
# DADOS.md
# ---------------------------------------------------------------------------


def _secao_identificacao(dados: dict) -> list:
    meta = dados["meta"]
    propriedade = dados["propriedade"]
    forma = (
        "propriedade de DOMÍNIO (sc-domain:) — agrega todos os subdomínios e protocolos"
        if propriedade.startswith("sc-domain:")
        else "propriedade de PREFIXO de URL — só o que casa com este prefixo exato"
    )
    return (
        [
            "## 1. Identificação",
            "",
            f"- **Propriedade**: `{propriedade}`",
            f"- **Forma**: {forma}",
            f"- **`type` da Search Analytics**: `{dados['tipo']}`",
            f"- **Pacote gerado em**: {dados['gerado_em']} (UTC)",
            f"- **Banco criado em**: {meta.get('criado_em') or '—'}",
            f"- **Esquema**: `user_version = {dados['versao_esquema']}`",
            f"- **Fuso dos dados**: {meta.get('fuso_dados') or '—'}",
            f"- **Propriedades no mesmo banco**: {meta.get('propriedades') or '—'}",
            f"- **Aferição do teto rodada em**: {meta.get('afericao_em') or 'NÃO RODADA'}",
            "",
            "Linhas por tabela:",
            "",
            "| grão | tabela | linhas | |",
            "|---|---|---|---|",
        ]
        + [
            f"| `{grao}` | `{plan.GRAOS[grao]['tabela']}` | {_milhar(n)} | "
            f"{_nota_grao(dados, grao)} |"
            for grao, n in dados["contagens"].items()
        ]
        + [
            f"| (dimensão) | `dim_pagina` | {_milhar(dados['dimensoes']['paginas'])} | |",
            f"| (dimensão) | `dim_query` | {_milhar(dados['dimensoes']['queries'])} | |",
            "",
            "**0 linhas num grão NÃO INGERIDO não significa ausência de tráfego** — "
            "significa que ninguém pediu aquele grão à API. Zero em `fato_dispositivo` "
            'não é "o site não tem acesso mobile": é "não coletamos por dispositivo". '
            "Para coletar, rode `acervo.py backfill --graos dispositivo,pais`.",
            "",
        ]
    )


def _nota_grao(dados: dict, grao: str) -> str:
    """Rótulo que distingue grão sem dado de grão nunca pedido à API."""
    ingeridos = {info["grao"] for info in dados["graos"]}
    if grao in ingeridos:
        return ""
    if plan.GRAOS[grao].get("fixo"):
        return "**NÃO INGERIDO** (grão de 2 etapas, fase P7.4)"
    return "**NÃO INGERIDO** — ausência de coleta, não ausência de tráfego"


def _secao_arquivos(dados: dict, arquivos: dict, extras: list) -> list:
    reduzido = arquivos.get("reduzido")
    linhas = [
        "## 2. Arquivos deste pacote",
        "",
        "| arquivo | o que é |",
        "|---|---|",
        f"| `{NOME_SNAPSHOT}` | snapshot do acervo "
        f"({arquivos.get('snapshot_mb', 0):.1f} MB) — consulte com SQL direto |",
        "| `DADOS.md` | este documento |",
        "| `eventos.csv` | a timeline da seção 10, para uso de máquina |",
        "| `evento_urls.csv` | uma linha por (evento, URL informada), com o casamento |",
        "| `consultas.sql` | consultas prontas; boilerplate de SQL, **não** análise |",
        "| `extras/` | onde largar exports manuais da UI do GSC |",
        "",
    ]
    if reduzido:
        fora = ", ".join(f"`{t}`" for t in TABELAS_FORA_DO_REDUZIDO)
        linhas += [
            "### ⚠ Este snapshot é REDUZIDO",
            "",
            f"Foi gerado com `--reduzido`: as tabelas {fora} estão **vazias** (a tabela "
            "existe, as linhas foram apagadas e o arquivo foi compactado com VACUUM). "
            "O grão `query_pagina` é mais da metade do volume do banco, e também o mais "
            "caro de perder: é o único que responde *qual URL ganhou ou perdeu esta "
            "query*. Sem ele, a consulta `queries_que_trocaram_de_url` volta vazia — "
            "não porque nada trocou de URL, mas porque o dado não veio no pacote.",
            "",
            f"O banco completo continua em `{arquivos.get('origem', '—')}` "
            f"({arquivos.get('origem_mb', 0):.1f} MB). Para analisar `query_pagina`, "
            "use aquele arquivo ou gere o pacote sem `--reduzido`.",
            "",
        ]
    else:
        linhas += [
            f"O snapshot é COMPLETO ({arquivos.get('snapshot_mb', 0):.1f} MB): é o banco "
            "inteiro, com todas as tabelas que a ingestão preencheu (quais são, e quais "
            "ficaram em zero, está na tabela da seção 1). "
            "`py acervo.py pacote --site X --reduzido` gera uma versão sem "
            f"{', '.join('`' + t + '`' for t in TABELAS_FORA_DO_REDUZIDO)} "
            "(mais da metade do volume), e o DADOS.md dela diz isso em letras garrafais. "
            "Nenhuma das duas esconde o que não tem.",
            "",
        ]
    linhas += ["### `extras/` — o que foi encontrado", ""]
    if extras:
        linhas += [f"- `{nome}` ({tam:.0f} KB)" for nome, tam in extras]
    else:
        linhas += [
            "- (vazio) Nenhum export manual foi largado em `extras/`. Relatórios que a "
            "API **não** entrega (desempenho de IA generativa, por exemplo) só chegam "
            "aqui por esse caminho.",
        ]
    return linhas + [""]


def _secao_periodo(dados: dict) -> list:
    linhas = [
        "## 3. Período coberto, por grão",
        "",
        "| grão | primeiro dia | último dia | dias registrados | ok | vazio | teto | erro |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for info in dados["graos"]:
        st = info["por_status"]
        linhas.append(
            f"| `{info['grao']}` | {info['primeiro']} | {info['ultimo']} | "
            f"{info['dias_registrados']} | {st.get('ok', 0)} | {st.get('vazio', 0)} | "
            f"{st.get('teto', 0) + st.get('pagina_capada', 0)} | {st.get('erro', 0)} |"
        )
    if not dados["graos"]:
        linhas.append("| (nenhuma ingestão registrada) | — | — | — | — | — | — | — |")
    linhas += [
        "",
        "`vazio` é dia SEM dado, registrado de propósito para não ser re-pedido para "
        "sempre — não é falha. Dia `vazio` em sequência longa, porém, costuma ser o "
        "site de fato sem tráfego naquele período; confira contra o grão `total`.",
        "",
    ]
    ingeridos = {info["grao"] for info in dados["graos"]}
    ausentes = [grao for grao in plan.GRAOS if grao not in ingeridos]
    if ausentes:
        linhas += [
            "**Grãos que não aparecem nesta tabela nunca foram ingeridos**: "
            + ", ".join(f"`{g}`" for g in ausentes)
            + ". Eles não têm NENHUM dia — não um dia zerado, nenhum dia. Qualquer "
            "pergunta que dependa deles não tem resposta neste pacote.",
            "",
        ]
    return linhas


def _secao_buracos(dados: dict) -> list:
    linhas = [
        "## 4. Buracos, explícitos",
        "",
        "Dias **sem registro nenhum** entre o primeiro e o último dia de cada grão, e "
        "dias que bateram no teto de linhas da API (dado incompleto NAQUELE dia).",
        "",
    ]
    algum = False
    for info in dados["graos"]:
        faltando = info["faltando"]
        teto = info["dias_teto"]
        if not faltando and not teto:
            continue
        algum = True
        linhas.append(f"- **`{info['grao']}`**")
        if faltando:
            linhas.append(
                f"  - faltando ({len(faltando)} dias): "
                f"{_lista_curta(_comprimir_intervalos(faltando), MAX_DIAS_LISTADOS)}"
            )
        if teto:
            linhas.append(
                f"  - no teto ({len(teto)} dias, dado TRUNCADO nesses dias): "
                f"{_lista_curta(_comprimir_intervalos(teto), MAX_DIAS_LISTADOS)}"
            )
    if not dados["graos"]:
        # Sem ingestão nenhuma, "nenhum buraco" seria verdade vazia lida como
        # tranquilização. O buraco, aqui, é o acervo inteiro.
        linhas.append(
            "**Não há ingestão nenhuma neste acervo** — não existe buraco porque não "
            "existe dado. Rode `acervo.py backfill` antes de gerar o pacote."
        )
    elif not algum:
        linhas.append(
            "**Nenhum buraco e nenhum dia no teto.** Todo dia entre o primeiro e o "
            "último de cada grão tem registro de ingestão."
        )
    return linhas + [""]


def _secao_provisorios(dados: dict) -> list:
    provisorios = dados["provisorios"]
    linhas = [
        "## 5. Dias provisórios",
        "",
        f"{len(provisorios)} dia(s) gravado(s) com `data_state` diferente de `final`: "
        "ainda dentro da janela de assentamento do GSC (ele revisa o dado por ~10 dias "
        "depois dos 2-3 de atraso).",
        "",
        "**Não tire conclusão da ponta.** Uma queda nos últimos dias da série é, por "
        "default, dado ainda assentando — não um evento.",
        "",
    ]
    if provisorios:
        blocos = _comprimir_intervalos(provisorios)
        linhas.append(f"- dias: {_lista_curta(blocos, MAX_DIAS_LISTADOS)}")
        if len(blocos) > 1:
            # Mais de um bloco significa ponta provisória + algum dia antigo
            # re-ingerido como provisório: vale dizer onde começa e onde acaba.
            linhas.append(f"- do mais antigo ao mais recente: {provisorios[0]} a {provisorios[-1]}")
        linhas.append("")
    return linhas


def _mecanismos_por_grao(dados: dict) -> list:
    """Uma linha por grão: onde a cobertura dele caiu e qual mecanismo explica.

    DERIVADO do que foi medido neste acervo, nunca escrito à mão. A versão
    anterior trazia a faixa medida no site-piloto dentro do documento de
    qualquer site — e um número de OUTRA propriedade no meio do relatório desta
    é exatamente o tipo de coisa que a análise toma por fato local. Agora o
    número é sempre o da propriedade do pacote.
    """
    if not dados["agregacao"]:
        return [
            "- Nenhuma cobertura medida ainda: o grão `total` precisa estar ingerido na "
            "mesma janela dos outros, porque é contra ele que a cobertura é calculada."
        ]
    saida = []
    for item in dados["agregacao"]:
        grao = item["grao"]
        agregacao = item["agregacao"] or "não declarada"
        minimo, maximo = item["minimo"], item["maximo"]
        tem_query = "query" in plan.GRAOS.get(grao, {}).get("dimensoes", ())
        por_pagina = agregacao == "byPage"

        if minimo is None or maximo is None:
            onde = "sem faixa medida"
        elif minimo == maximo:
            # Grão sem nenhum dos dois mecanismos (dispositivo, país) mede
            # exatamente 1,000 todo dia. Cair no galho "atravessa 1,0" diria ao
            # analista que o valor varia em volta de 1,0, quando ele é constante
            # — e este documento existe justamente para não induzir leitura.
            onde = f"**exatamente {_pct(minimo)} em todos os dias medidos**"
        elif minimo > 1.0:
            onde = "**acima de 1,0 em todos os dias medidos**"
        elif maximo < 1.0:
            onde = "**abaixo de 1,0 em todos os dias medidos**"
        else:
            onde = "**atravessa 1,0**"

        if por_pagina and tem_query:
            causa = (
                "os DOIS mecanismos agem, em sentidos opostos — a cobertura dele não "
                "mede nem a cauda nem a sobreposição"
            )
        elif por_pagina:
            causa = "só o mecanismo 2 (`byPage`) age: passar de 1,0 é o esperado"
        elif tem_query:
            causa = "só o mecanismo 1 age: é o grão a usar para medir a cauda anonimizada"
        else:
            causa = (
                "nenhum dos dois mecanismos age; cobertura longe de 1,0 aqui merece "
                "investigação, ao contrário dos outros grãos"
            )
        saida.append(
            f"- `{grao}` (`{agregacao}`): {_pct(minimo)} a {_pct(maximo)} "
            f"(média {_pct(item['media'])}, {item['dias']} dias) — {onde}; {causa}."
        )
    return saida


def _secao_cobertura(dados: dict) -> list:
    """A seção que impede 1,29 de ser lido como banco corrompido."""
    linhas = [
        "## 6. Cauda anonimizada e agregação da API, medidas",
        "",
        "`ingestao.cobertura_impressoes` = impressões somadas no grão naquele dia ÷ "
        "impressões do grão `total` no mesmo dia. **Esse número não significa a mesma "
        "coisa em todos os grãos**, porque a API agrega diferente conforme as dimensões "
        "pedidas — e ela mesma declara como agregou, em `responseAggregationType`, que o "
        "acervo grava em `ingestao.agregacao_resposta`.",
        "",
        "| grão | agregação declarada | dias | cobertura média | mín | máx |",
        "|---|---|---|---|---|---|",
    ]
    for item in dados["agregacao"]:
        linhas.append(
            f"| `{item['grao']}` | `{item['agregacao'] or '—'}` | {item['dias']} | "
            f"{_pct(item['media'])} | {_pct(item['minimo'])} | {_pct(item['maximo'])} |"
        )
    if not dados["agregacao"]:
        linhas.append("| (sem cobertura medida ainda) | — | — | — | — | — |")

    linhas += (
        [
            "",
            "### Dois mecanismos, em sentidos opostos",
            "",
            "**1. A cauda anonimizada puxa a cobertura para BAIXO.** O GSC omite as queries "
            "raras (limiar de privacidade). Todo grão que tem a dimensão `query` perde essas "
            "linhas, e a soma dele fica abaixo do total. Isso **não é bug e não deve ser "
            "reconciliado**: é o que a cobertura serve para MEDIR. Cobertura de 0,61 num grão "
            "`byProperty` significa *enxergamos 61% das impressões do site nesse grão*, não "
            "*a coleta falhou*.",
            "",
            "**2. A agregação `byPage` puxa a cobertura para CIMA.** Quando a resposta vem "
            "`responseAggregationType = byPage`, uma impressão de SERP é contada **uma vez "
            "por URL do site que apareceu nela**, enquanto o grão `total` (`byProperty`) "
            "conta uma só. Se duas páginas do site aparecem na mesma SERP, o grão soma 2 e o "
            "total soma 1. Por isso **cobertura acima de 1,0 é esperada** nos grãos `byPage` "
            "— não é truncamento, não é dupla gravação, não é banco corrompido.",
            "",
            "### O que foi medido NESTE acervo, grão por grão",
            "",
            "Lido da tabela acima — são os números desta propriedade, não de outra:",
            "",
        ]
        + _mecanismos_por_grao(dados)
        + [
            "",
            "Quando um grão `byPage` **também** tem a dimensão `query` (é o caso de "
            "`query_pagina`), os dois mecanismos agem nele ao mesmo tempo e em sentidos "
            "opostos. A cobertura dele atravessa 1,0 e não mede nem a cauda nem a "
            "sobreposição de URLs: não a use como se medisse nenhuma das duas. Para medir a "
            "cauda, use um grão `byProperty` com `query`.",
            "",
            "Consequências práticas, para não errar:",
            "",
            "1. Cobertura só é comparável entre grãos com a **mesma** agregação.",
            "2. A soma de um grão **nunca** fecha com `fato_total`, nos dois sentidos. "
            "Tentar reconciliar é perseguir um artefato de definição.",
            "3. O grão `total` é a régua: ele nunca trunca e nunca é afetado por nenhum dos "
            "dois mecanismos.",
            "",
        ]
    )

    por_grao: dict = {}
    for item in dados["cobertura_mes"]:
        por_grao.setdefault(item["grao"], []).append(item)
    alvos = [g for g in ("query", "query_pagina", "pagina") if g in por_grao]
    if alvos:
        linhas += [
            "### Cobertura mês a mês",
            "",
            "Importa porque a cauda anonimizada **muda de tamanho** ao longo do tempo: se "
            "ela mudasse junto com a queda que você está medindo, a queda poderia ser "
            "artefato de anonimização e não do site.",
            "",
            "| mês | "
            + " | ".join(f"`{g}` ({por_grao[g][0]['agregacao'] or '—'})" for g in alvos)
            + " |",
            "|---|" + "---|" * len(alvos),
        ]
        meses = sorted({item["ano_mes"] for g in alvos for item in por_grao[g]})
        for mes in meses:
            celulas = []
            for grao in alvos:
                achado = next((i for i in por_grao[grao] if i["ano_mes"] == mes), None)
                celulas.append(_pct(achado["media"]) if achado else "—")
            linhas.append(f"| {mes} | " + " | ".join(celulas) + " |")
        linhas.append("")
    return linhas


def _secao_coortes(dados: dict) -> list:
    """Coortes de URL — com as duas pontas rotuladas como artefato."""
    c = dados["coortes"]
    linhas = [
        "## 7. Coortes de URL — primeiro e último dia em que cada URL apareceu",
        "",
        "Derivado de `MIN(data)`/`MAX(data)` de `fato_pagina` por URL, agrupado por mês. "
        "Dá de graça as ondas de publicação e as de mortandade de URLs.",
        "",
    ]
    if not c["primeiro_dia"]:
        return linhas + ["(sem dado no grão `pagina` ainda.)", ""]

    linhas += [
        f"- URLs com ao menos um dia de dado: **{c['urls']}**",
        f"- Janela do grão `pagina`: {c['primeiro_dia']} a {c['ultimo_dia']}",
        "",
        "### ⚠ As duas pontas são ARTEFATO DA JANELA, não evento",
        "",
        f"O acervo começa em {c['primeiro_dia']}. Toda URL que **já existia** antes disso "
        f"aparece como se tivesse surgido em {c['mes_borda_inicial']} — porque é o "
        f"primeiro mês em que havia dado, não porque algo foi publicado ali. "
        f"**{c['censuradas_a_esquerda']} URL(s)** já apareciam no primeiro dia do acervo.",
        "",
        f"O acervo termina em {c['ultimo_dia']}. Toda URL **ainda viva** aparece como "
        f'"vista por último" em {c["mes_borda_final"]} — porque o dado termina ali, não '
        f"porque a URL morreu. **{c['censuradas_a_direita']} URL(s)** ainda apareciam no "
        "último dia do acervo.",
        "",
        "Nas duas tabelas abaixo, a linha de borda vem marcada **(borda — artefato)**. "
        "Ler essas duas linhas como onda real de publicação ou de mortandade foi o "
        "primeiro erro de leitura que este dado produziu. Só os meses do MEIO são "
        "interpretáveis como evento.",
        "",
        "### URLs que surgiram, por mês",
        "",
        "| mês | URLs | |",
        "|---|---|---|",
    ]
    for item in c["surgimentos"]:
        marca = "**(borda — artefato)**" if item["borda"] else ""
        linhas.append(f"| {item['ano_mes']} | {item['urls']} | {marca} |")
    linhas += [
        "",
        "### URLs vistas por último, por mês",
        "",
        "| mês | URLs | |",
        "|---|---|---|",
    ]
    for item in c["desaparecimentos"]:
        marca = "**(borda — artefato)**" if item["borda"] else ""
        linhas.append(f"| {item['ano_mes']} | {item['urls']} | {marca} |")
    linhas += [
        "",
        'Uma URL "vista por último" num mês do meio pode ter sido despublicada, '
        "redirecionada, desindexada — ou só ter deixado de receber impressão. O acervo "
        "não distingue: ele só sabe que o GSC parou de devolvê-la. Cruze com os eventos "
        "da seção 10 e com o projeto do site.",
        "",
        "Um terceiro artefato, menor: num dia que bateu no TETO (seção 4) a API devolveu "
        "só parte das URLs, então o `MIN`/`MAX` de uma URL de baixo volume pode ter sido "
        "recortado por truncamento, e não por publicação ou por morte. Se a data de "
        "surgimento ou de desaparecimento de uma URL cair na vizinhança de um dia no "
        "teto, confira a série diária dela antes de concluir.",
        "",
    ]
    return linhas


def _secao_dicionario(dados: dict) -> list:
    return [
        "## 8. Dicionário de tabelas e views",
        "",
        "| objeto | o que contém |",
        "|---|---|",
        "| `fato_total` | 1 linha por (propriedade, tipo, dia). Nunca trunca. A régua. |",
        "| `fato_pagina` | 1 linha por (…, dia, `pagina_id`). Agregação `byPage`. |",
        "| `fato_query` | 1 linha por (…, dia, `query_id`). Agregação `byProperty`. |",
        "| `fato_query_pagina` | 1 linha por (…, dia, query, página). O mais caro e o mais "
        "valioso: é o único que responde *qual URL ganhou esta query*. |",
        "| `fato_dispositivo`, `fato_pais` | 1 linha por (…, dia, valor), texto inline. |",
        "| `fato_aparencia` | reservado (grão de 2 etapas, fase P7.4). |",
        "| `dim_pagina`, `dim_query` | texto internado; junte por `id`. |",
        "| `ingestao` | 1 linha por (propriedade, tipo, grão, DIA): status, `data_state`, "
        "linhas, `cobertura_impressoes`, `agregacao_resposta`. É a escrituração. |",
        "| `execucao` | log de cada execução da CLI. |",
        "| `evento` | o que mudou no site e quando. Preenchido à mão. |",
        "| `evento_pagina` | as URLs do evento JÁ casadas com `dim_pagina` — a coorte. |",
        "| `dim_aparencia_vista` | todo valor de `searchAppearance` já visto, com a "
        "primeira vez. Um valor novo aqui é como uma superfície nova apareceria. |",
        "| `v_pagina_dia`, `v_query_dia`, `v_query_pagina_dia` | os fatos com o texto já "
        "resolvido (sem precisar do JOIN). |",
        "| `v_pagina_mes`, `v_query_mes`, `v_site_mes`, `v_site_semana` | roll-up mensal/"
        "semanal **com `ctr` e posição re-derivados corretamente**. Prefira-as. |",
        "| `v_cobertura` | dias por grão e status, com a cobertura média. |",
        "| `v_evento`, `v_evento_pagina` | eventos e a coorte de URLs de cada um. |",
        "",
        "Unidades: `clicks`/`impressions` inteiros; `ctr` fração **crua** (0..1, não %); "
        "`position` **sem arredondar** (1,0 é o topo) e pode ser `NULL`; `data` é `TEXT` "
        "ISO `YYYY-MM-DD`; todo timestamp (`fetched_at`, `criado_em`) é ISO em **UTC**.",
        "",
    ]


def _secao_ressalvas(dados: dict) -> list:
    coortes = dados["coortes"]
    # O primeiro dia de qualquer grão serve de piso da janela; cair no grão
    # `pagina` apenas seria errado num acervo que só ingeriu `total`.
    primeiros = [info["primeiro"] for info in dados["graos"] if info["primeiro"]]
    primeiro = coortes.get("primeiro_dia") or (min(primeiros) if primeiros else None)
    janela = (
        f"O dado mais antigo aqui é de **{primeiro}**"
        if primeiro
        else "**Este acervo ainda não tem dado nenhum**, então não há data mais antiga"
    )
    return [
        "## 9. Ressalvas obrigatórias",
        "",
        "**1. `ctr` e `position` NUNCA podem ser somados nem mediados entre linhas.**",
        "",
        "```sql",
        "ctr      = SUM(clicks) / SUM(impressions)",
        "posicao  = SUM(position * impressions) / SUM(impressions)   -- ignorando NULL",
        "```",
        "",
        "Média simples de `position` entre dias ou entre URLs dá um número que não "
        "significa nada. As views `v_*_mes` já fazem isso certo — prefira-as a somar à mão.",
        "",
        "**2. A soma de um grão nunca fecha com `fato_total`** — nos dois sentidos, e por "
        "dois motivos diferentes. Ver a seção 6 antes de tentar reconciliar.",
        "",
        "**3. `data` é o dia em horário da CALIFÓRNIA** (`meta.fuso_dados = "
        "America/Los_Angeles`). Juntar com GA4, com log de servidor ou com data de "
        'publicação exige considerar o offset de 4-5 h: o "mesmo dia" não é o mesmo dia.',
        "",
        "**4. Teto de ~50 mil linhas por dia e por `type`.** Dia que bateu no teto está "
        "listado na seção 4 e tem dado TRUNCADO — o que falta nele são as linhas de menor "
        "volume, não uma amostra aleatória.",
        "",
        "**5. `data_state`**: `final` é definitivo; `final_provisorio` é rótulo nosso "
        "(não existe na API) para dia ainda dentro da janela de assentamento; `all` é "
        "dado fresco e volátil. Ver a seção 5.",
        "",
        f"**6. Janela móvel de ~16 meses.** {janela}. "
        "O GSC apaga um dia a cada dia que passa: **tudo o que é anterior a essa data "
        "está perdido para sempre** e nenhuma re-execução traz de volta. Se a análise "
        "precisa comparar com antes disso, a resposta é que não existe dado — não que o "
        "valor seja zero.",
        "",
        "**7. `position` pode ser `NULL`.** Toda média ponderada precisa do guard "
        "(`CASE WHEN position IS NOT NULL`), senão o `NULL` enviesa o resultado para baixo.",
        "",
        "**8. Uma URL ausente de `fato_pagina` num dia não teve ZERO impressões** — ela "
        "não foi devolvida pela API naquele dia. Na prática costuma ser zero impressão, "
        "mas pode ser truncamento (ver a seção 4). Ausência não é zero.",
        "",
    ]


def _secao_timeline(dados: dict) -> list:
    eventos = dados["eventos"]
    linhas = [
        "## 10. Timeline de eventos",
        "",
        "Anotada à mão (`py acervo.py anotar`) por quem tem o projeto do site. É o "
        '"porquê" que a API não tem.',
        "",
    ]
    if not eventos:
        linhas += [
            "**(nenhum evento anotado)** — e isso limita a análise: sem data de mudança, "
            "qualquer inflexão da série fica sem causa candidata. Anote o que você sabe "
            "ter feito, com as URLs afetadas, antes da sessão de análise:",
            "",
            "```",
            "py acervo.py anotar --site SEU.SITE --data 2026-03-10 --tipo conteudo-editado \\",
            '    --desc "reescrevi o texto destas URLs" --urls-de urls_reescritas.txt',
            "```",
            "",
        ]
        return linhas

    linhas += [
        "| id | data | até | tipo | descrição | URLs informadas | casadas em `dim_pagina` |",
        "|---|---|---|---|---|---|---|",
    ]
    for ev in eventos:
        ate = ev["data_fim"] if ev["data_fim"] != ev["data"] else "—"
        linhas.append(
            f"| {ev['id']} | {ev['data']} | {ate} | `{ev['tipo']}` | {ev['descricao']} | "
            f"{ev['urls_informadas']} | {ev['urls_casadas']} |"
        )
    linhas += [
        "",
        "A coluna **casadas** é a coorte utilizável: está em `evento_pagina`, pronta para "
        "o JOIN da consulta `antes_depois_evento_tratadas_x_demais`. Quando ela é menor "
        "que as informadas, as URLs que não casaram estão em `evento_urls.csv` — ou nunca "
        "tiveram impressão, ou a forma informada não corresponde à que o GSC devolve.",
        "",
        "**Datas de core update do Google NÃO estão aqui**, de propósito: não são dado "
        "deste site. Pesquise-as na sessão de análise, na fonte oficial, e trate-as como "
        "hipótese externa — nunca como linha desta tabela.",
        "",
    ]
    return linhas


def _ausencia_de_tipos(dados: dict) -> list:
    """O que este pacote NÃO cobre em matéria de `type` da Search Analytics.

    Medido em site real: `image` pode ter MAIS impressões que `web` e cair de
    forma bem diferente dele. Um pacote de um tipo só é um recorte legítimo,
    mas a análise tem de saber que é recorte — e, se o acervo tem outro tipo
    coletado, que ele existe e está FORA deste snapshot.
    """
    tipo = dados["tipo"]
    outros = dados.get("outros_tipos") or []
    naos = [t for t in plan.TIPOS_VALIDOS if t != tipo and t not in outros]

    linhas = [
        f"- **Os outros `type` da Search Analytics.** Este pacote é só de `{tipo}`. "
        f"`image` costuma ter volume comparável ao de `web` e pode cair de forma "
        f'diferente dele, então ler este recorte como "o site" erra por construção.',
    ]
    if outros:
        linhas.append(
            f"  O acervo TEM `{'`, `'.join(outros)}` coletado, mas **fora deste "
            f"snapshot**: gere o pacote daquele tipo com `--tipo {outros[0]}`."
        )
    if naos:
        linhas.append(
            f"  Nunca coletados: `{'`, `'.join(naos)}`. Zero neles não é ausência de "
            f"tráfego, é ausência de coleta (`--tipos {tipo},{naos[0]}`)."
        )
    return linhas


def _secao_ausencias(dados: dict) -> list:
    return [
        "## 11. O que NÃO está aqui",
        "",
        "Esta seção é tão importante quanto as outras: impede que ausência de dado seja "
        "lida como zero.",
        "",
        "- **Dados de IA / SGE / AI Overviews.** A Search Analytics API **não** tem "
        'nenhuma dimensão ou `type` de IA. O relatório de "desempenho de IA generativa" '
        "existe só na interface do GSC. Se você precisa dele, exporte à mão e largue em "
        "`extras/` — não há como o acervo buscá-lo.",
        "- **A dimensão `searchAppearance`** (grão de 2 etapas, fase P7.4). "
        "`dim_aparencia_vista` registra os valores já VISTOS, mas `fato_aparencia` está "
        "vazia.",
        *_ausencia_de_tipos(dados),
        "- **GA4, sessões, conversões, receita.** Outra fonte, outro fuso (ver ressalva 3).",
        "- **Core Web Vitals / PageSpeed / CrUX.**",
        "- **Crawl de links internos, HTML das páginas, texto dos artigos.** O acervo não "
        "rastreia o site. O que foi publicado, editado ou removido só chega aqui pela "
        "seção 10, anotado à mão.",
        "- **Datas de core update do Google.** Externas, pesquisadas na análise.",
        "- **Log de servidor e comportamento do Googlebot.** Existe no toolkit "
        "(`logs.py`), mas é outro relatório e não entra neste banco.",
        '- **Qualquer veredito.** Não há score, nem classificação, nem "causa provável" '
        "em nenhum arquivo deste pacote. A análise é a próxima etapa, não esta.",
        "",
    ]


def montar_dados_md(dados: dict, *, arquivos: dict, extras: list) -> str:
    """Monta o DADOS.md inteiro. Função pura (recebe o que `coletar` leu)."""
    cabecalho = [
        f"# DADOS.md — acervo GSC de `{dados['propriedade']}`",
        "",
        "Este pacote é **extração**, não análise. Nada aqui tem veredito, score ou causa "
        "provável: são contagens, datas e rótulos de proveniência, mais SQL de "
        "boilerplate. A análise é a etapa seguinte, feita com o projeto do site em mãos.",
        "",
        "**Leia as seções 4, 5, 6 e 7 antes de concluir qualquer coisa.** Elas existem "
        "porque cada uma delas corresponde a uma leitura errada que este dado já "
        "produziu: buraco invisível, ponta ainda assentando, cobertura acima de 1,0 "
        "confundida com banco corrompido, e as duas pontas das coortes de URL lidas como "
        "onda real.",
        "",
        "---",
        "",
    ]
    secoes = (
        _secao_identificacao(dados)
        + ["---", ""]
        + _secao_arquivos(dados, arquivos, extras)
        + ["---", ""]
        + _secao_periodo(dados)
        + ["---", ""]
        + _secao_buracos(dados)
        + ["---", ""]
        + _secao_provisorios(dados)
        + ["---", ""]
        + _secao_cobertura(dados)
        + ["---", ""]
        + _secao_coortes(dados)
        + ["---", ""]
        + _secao_dicionario(dados)
        + ["---", ""]
        + _secao_ressalvas(dados)
        + ["---", ""]
        + _secao_timeline(dados)
        + ["---", ""]
        + _secao_ausencias(dados)
    )
    rodape = [
        "---",
        "",
        f"_Gerado por `acervo.py pacote` em {dados['gerado_em']} (UTC). "
        "Regenere depois de cada `diario` ou de cada `anotar`: o documento é derivado "
        "do banco, não editado à mão._",
        "",
    ]
    return "\n".join(cabecalho + secoes + rodape)


# ---------------------------------------------------------------------------
# consultas.sql
# ---------------------------------------------------------------------------


def montar_consultas_sql(propriedade: str) -> str:
    """O arquivo `consultas.sql`, gerado a partir de CONSULTAS."""
    partes = [
        "-- consultas.sql — boilerplate de SQL para o acervo do GSC.",
        "--",
        f"-- Propriedade: {propriedade}",
        "-- Nada aqui é análise: são as junções e as re-derivações que você ia escrever à",
        "-- mão de todo jeito, já com os guards certos (ctr e posição re-derivados, NULL",
        "-- de position tratado). Os valores a ajustar estão marcados com TROQUE.",
        "--",
        "-- Leia a seção 6 do DADOS.md antes de interpretar qualquer cobertura, e a seção",
        "-- 7 antes de interpretar as pontas das coortes de URL.",
        "",
    ]
    for slug, titulo, explicacao, sql in CONSULTAS:
        partes += [
            "-- " + "=" * 74,
            f"-- {slug}: {titulo}",
            "-- " + "=" * 74,
        ]
        partes += [f"-- {linha}" for linha in _quebrar(explicacao, 74)]
        partes += [sql.strip(), ";", ""]
    return "\n".join(partes) + "\n"


def _quebrar(texto: str, largura: int) -> list:
    """Quebra um parágrafo em linhas de até `largura` (sem depender de textwrap)."""
    linhas, atual = [], ""
    for palavra in texto.split():
        if atual and len(atual) + 1 + len(palavra) > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = f"{atual} {palavra}".strip()
    if atual:
        linhas.append(atual)
    return linhas


# ---------------------------------------------------------------------------
# Geração do pacote
# ---------------------------------------------------------------------------

LEIA_EXTRAS = """# extras/ — exports manuais da UI do Google Search Console

Largue aqui, com o nome que quiser, qualquer CSV/XLSX que a **API não entrega** e
que você exportou à mão da interface do GSC: o relatório de desempenho de IA
generativa, o relatório "Páginas" com os motivos de não indexação, o que for.

O `DADOS.md` lista o que encontrou nesta pasta. Nada é parseado nem validado: a
sessão de análise lê o arquivo direto. Ela só não pode ler o que não está aqui.
"""


def _extras(pasta: str) -> list:
    """[(nome, KB)] do que o usuário largou em extras/, exceto o LEIA.md."""
    achados = []
    for nome in sorted(os.listdir(pasta)):
        caminho = os.path.join(pasta, nome)
        if nome == "LEIA.md" or not os.path.isfile(caminho):
            continue
        achados.append((nome, os.path.getsize(caminho) / 1024))
    return achados


def _reduzir(caminho: str) -> None:
    """Esvazia as tabelas fora do snapshot reduzido e compacta o arquivo.

    As tabelas CONTINUAM existindo, vazias, de propósito: assim `consultas.sql`
    roda inteiro no pacote reduzido (a consulta de query_pagina volta vazia em
    vez de dar erro de tabela inexistente) e o DADOS.md consegue declarar o que
    ficou de fora em vez de deixar o buraco implícito.
    """
    conn = sqlite3.connect(caminho)
    try:
        with conn:
            for tabela in TABELAS_FORA_DO_REDUZIDO:
                conn.execute(f"DELETE FROM {tabela}")
        conn.execute("VACUUM")
    finally:
        conn.close()


def gerar(
    conn: sqlite3.Connection,
    *,
    propriedade: str,
    site: str,
    tipo: str = "web",
    destino: "str | None" = None,
    reduzido: bool = False,
    com_snapshot: bool = True,
) -> dict:
    """Gera o pacote de análise. Retorna o inventário do que foi escrito.

    `com_snapshot=False` existe para regenerar só os documentos (DADOS.md,
    CSVs, consultas) sem recopiar centenas de MB — e para os testes.
    """
    from core import storage

    pasta = destino or storage.acervo_pacote_dir(site)
    pasta_extras = os.path.join(pasta, "extras")
    os.makedirs(pasta_extras, exist_ok=True)

    # Re-casar antes de ler: uma URL do evento pode só ter entrado em dim_pagina
    # numa ingestão posterior ao `anotar`.
    casamento = store.casar_urls_evento(conn)

    dados = coletar(conn, propriedade=propriedade, tipo=tipo)
    caminho_snapshot = os.path.join(pasta, NOME_SNAPSHOT)
    origem = store.caminho_banco(site)

    arquivos = {
        "pasta": pasta,
        "reduzido": reduzido,
        "origem": origem,
        "origem_mb": _tamanho_mb(origem),
    }
    if com_snapshot:
        store.snapshot(conn, caminho_snapshot)
        if reduzido:
            _reduzir(caminho_snapshot)
    arquivos["snapshot"] = caminho_snapshot if com_snapshot else None
    arquivos["snapshot_mb"] = _tamanho_mb(caminho_snapshot) if com_snapshot else 0.0

    leia = os.path.join(pasta_extras, "LEIA.md")
    if not os.path.exists(leia):
        with open(leia, "w", encoding="utf-8") as f:
            f.write(LEIA_EXTRAS)

    escritos = {
        "eventos_csv": _escrever_eventos_csv(pasta, dados),
        "evento_urls_csv": _escrever_evento_urls_csv(pasta, conn, dados, casamento),
        "consultas": _escrever(
            os.path.join(pasta, "consultas.sql"), montar_consultas_sql(propriedade)
        ),
        "dados_md": _escrever(
            os.path.join(pasta, "DADOS.md"),
            montar_dados_md(dados, arquivos=arquivos, extras=_extras(pasta_extras)),
        ),
    }

    return {
        "pasta": pasta,
        "snapshot": arquivos["snapshot"],
        "snapshot_mb": arquivos["snapshot_mb"],
        "reduzido": reduzido,
        "arquivos": escritos,
        "extras": [nome for nome, _ in _extras(pasta_extras)],
        "eventos": len(dados["eventos"]),
        "casamento": casamento,
        "dados": dados,
    }


def _escrever(caminho: str, texto: str) -> str:
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)
    return caminho


_RESSALVAS_CSV = (
    "Extracao do acervo GSC — nenhum veredito, nenhuma analise.",
    "Eventos anotados a mao; datas de core update do Google NAO estao aqui.",
    "urls_casadas = URLs que casaram com dim_pagina (ver evento_urls.csv).",
)


def _escrever_eventos_csv(pasta: str, dados: dict) -> str:
    from core import storage

    linhas = [
        [
            ev["id"],
            ev["data"],
            ev["data_fim"],
            ev["tipo"],
            ev["descricao"],
            ev["fonte"] or "",
            ev["urls_informadas"],
            ev["urls_casadas"],
        ]
        for ev in dados["eventos"]
    ]
    return storage.write_csv(
        os.path.join(pasta, "eventos.csv"),
        ["id", "data", "data_fim", "tipo", "descricao", "fonte", "urls_informadas", "urls_casadas"],
        linhas,
        comments=list(_RESSALVAS_CSV),
    )


def _escrever_evento_urls_csv(
    pasta: str, conn: sqlite3.Connection, dados: dict, casamento: dict
) -> str:
    """Uma linha por (evento, URL informada), dizendo se casou e com qual URL do GSC.

    É aqui que "anotei 243 URLs e só 198 casaram" deixa de ser um número solto e
    passa a ser uma lista auditável.
    """
    from core import storage
    from core.urls import normalize_domain

    # O host da propriedade é o que permite casar a URL informada sem protocolo
    # ('exemplo.com.br/a'); sem ele, a linha sairia como casou=0 enquanto a
    # coorte em `evento_pagina` a tem — o CSV contradiria o banco.
    host = normalize_domain(dados["propriedade"])
    linhas = []
    for ev in dados["eventos"]:
        informadas = store.urls_informadas(ev.get("urls"))
        sem_casamento = set((casamento.get(ev["id"]) or {}).get("sem_casamento") or [])
        casadas = store.paginas_do_evento(conn, ev["id"])
        por_chave: dict = {}
        for url in casadas:
            por_chave.setdefault(store.chave_pagina(url), []).append(url)
        for url in informadas:
            alvo = por_chave.get(store.chave_pagina(url, host=host)) or []
            if url in sem_casamento or not alvo:
                linhas.append([ev["id"], ev["data"], ev["tipo"], url, "", 0])
            else:
                for url_gsc in alvo:
                    linhas.append([ev["id"], ev["data"], ev["tipo"], url, url_gsc, 1])
    return storage.write_csv(
        os.path.join(pasta, "evento_urls.csv"),
        ["evento_id", "data", "tipo", "url_informada", "url_no_gsc", "casou"],
        linhas,
        comments=[
            "Uma linha por (evento, URL informada).",
            "casou=0: a URL nao existe em dim_pagina — nunca teve impressao, ou a forma",
            "informada nao corresponde a que o GSC devolve. Ausencia NAO e zero.",
        ],
    )


def resumo_texto(resultado: dict) -> str:
    """Resumo de uma linha por item, para o terminal."""
    dados = resultado["dados"]
    coortes = dados["coortes"]
    partes = [
        f"  pasta        : {resultado['pasta']}",
        "  snapshot     : "
        + (
            f"{os.path.basename(resultado['snapshot'])} "
            f"({resultado['snapshot_mb']:.1f} MB)"
            + (" — REDUZIDO, sem fato_query_pagina" if resultado["reduzido"] else "")
            if resultado["snapshot"]
            else "(nao gerado)"
        ),
        f"  eventos      : {resultado['eventos']} anotado(s)",
        f"  URLs         : {coortes.get('urls', 0)} com dado"
        + (
            f"; {coortes.get('censuradas_a_esquerda', 0)} ja existiam no 1o dia, "
            f"{coortes.get('censuradas_a_direita', 0)} ainda vivas no ultimo (ARTEFATO)"
            if coortes.get("urls")
            else ""
        ),
        f"  extras/      : {len(resultado['extras'])} arquivo(s) do usuario",
    ]
    nao_casaram = sum(len(v["sem_casamento"]) for v in resultado["casamento"].values())
    if nao_casaram:
        partes.append(
            f"  ATENCAO      : {nao_casaram} URL(s) de evento nao casaram com dim_pagina "
            "(ver evento_urls.csv)"
        )
    return "\n".join(partes)
