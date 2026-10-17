"""
schema.py — Esquema SQLite do acervo histórico do GSC (P7).

O acervo é um ARMAZÉM, não um relatório: acumula o grão diário que a Search
Analytics API entrega e nunca apaga. Existe porque a retenção do GSC é uma
janela móvel de ~16 meses (cada dia que passa apaga o dia mais antigo) e porque
o histórico atual (`historico_posicao.json`, 30 agregados de janela por
domínio) não tem grão diário nem semântica de append.

REGRAS DE LEITURA DESTE BANCO (valem para qualquer análise futura):

  - `ctr` e `position` NUNCA podem ser somados nem mediados entre linhas.
        ctr correto      = SUM(clicks) / SUM(impressions)
        posicao correta  = SUM(position*impressions) / SUM(impressions)
    As views v_*_mes / v_site_* já fazem isso certo — prefira-as a somar à mão.

  - `ctr` é fração CRUA da API (0..1) e `position` não é arredondada. Diverge de
    propósito de fetchers/position_fetcher.py, que arredonda para apresentação:
    arredondar destrói exatamente os deltas pequenos que uma análise de 2 anos
    procura.

  - A soma de um grão NUNCA fecha com `fato_total`: o GSC anonimiza queries
    raras (limiar de privacidade). Não é bug e não deve ser "reconciliado".
    `ingestao.cobertura_impressoes` MEDE esse buraco, dia por dia.

  - `data` é o dia em horário da CALIFÓRNIA (ver meta.fuso_dados). Juntar com
    GA4 ou log de servidor exige considerar o offset de 4-5 h.

  - `data_state` diz a confiança da linha: 'final' = definitivo,
    'final_provisorio' = ainda assentando (o GSC revisa por ~10 dias depois dos
    2-3 dias de atraso), 'all' = dado fresco e volátil.
"""

import sqlite3

VERSAO_ESQUEMA = 2

# WAL: a análise (leitura) não bloqueia a ingestão (escrita) e vice-versa.
PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA foreign_keys=ON",
)

# Colunas comuns a toda tabela de fato. data_state/fetched_at/alterado_em/
# revisoes são de VALOR, não de chave: existe UMA linha por célula, sempre a
# melhor versão conhecida, com a proveniência estampada nela.
_METRICAS = """
    clicks      INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    ctr         REAL    NOT NULL,
    position    REAL,
    data_state  TEXT    NOT NULL,
    fetched_at  TEXT    NOT NULL,
    alterado_em TEXT    NOT NULL,
    revisoes    INTEGER NOT NULL DEFAULT 0
"""

DDL = (
    # ── Metadados ───────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS meta (
        chave TEXT PRIMARY KEY,
        valor TEXT NOT NULL
    )
    """,
    # ── Dimensões internadas ────────────────────────────────────────────────
    # Só as duas de alta cardinalidade e string longa. Uma URL de 70 chars
    # repetida em 480 dias custa 480x70 bytes inline contra 480x~3 como inteiro.
    # pais/dispositivo/aparencia/tipo ficam inline: são curtos, e manter texto
    # deixa o SQL ad-hoc legível — o que importa quando a análise consulta
    # o banco direto.
    """
    CREATE TABLE IF NOT EXISTS dim_pagina (
        id  INTEGER PRIMARY KEY,
        url TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_query (
        id    INTEGER PRIMARY KEY,
        termo TEXT NOT NULL UNIQUE
    )
    """,
    # ── Grão 1/7: total do site por dia ─────────────────────────────────────
    # Nunca trunca (1 linha/dia) e por isso é SEMPRE ingerido primeiro: é a
    # régua contra a qual a cobertura_impressoes dos outros grãos é medida.
    f"""
    CREATE TABLE IF NOT EXISTS fato_total (
        propriedade TEXT NOT NULL,
        tipo        TEXT NOT NULL,
        data        TEXT NOT NULL,
        {_METRICAS},
        PRIMARY KEY (propriedade, tipo, data)
    ) WITHOUT ROWID
    """,
    # ── Grão 2/7: página x dia ──────────────────────────────────────────────
    f"""
    CREATE TABLE IF NOT EXISTS fato_pagina (
        propriedade TEXT NOT NULL,
        tipo        TEXT NOT NULL,
        data        TEXT NOT NULL,
        pagina_id   INTEGER NOT NULL REFERENCES dim_pagina(id),
        {_METRICAS},
        PRIMARY KEY (propriedade, tipo, data, pagina_id)
    ) WITHOUT ROWID
    """,
    # Progressão/regressão de UMA URL ao longo de 2 anos.
    "CREATE INDEX IF NOT EXISTS ix_fato_pagina_serie ON fato_pagina (pagina_id, data)",
    # ── Grão 3/7: query x dia ───────────────────────────────────────────────
    f"""
    CREATE TABLE IF NOT EXISTS fato_query (
        propriedade TEXT NOT NULL,
        tipo        TEXT NOT NULL,
        data        TEXT NOT NULL,
        query_id    INTEGER NOT NULL REFERENCES dim_query(id),
        {_METRICAS},
        PRIMARY KEY (propriedade, tipo, data, query_id)
    ) WITHOUT ROWID
    """,
    # Progressão/regressão de UMA keyword ao longo de 2 anos.
    "CREATE INDEX IF NOT EXISTS ix_fato_query_serie ON fato_query (query_id, data)",
    # ── Grão 4/7: query x página x dia (o mais caro e o mais valioso) ───────
    f"""
    CREATE TABLE IF NOT EXISTS fato_query_pagina (
        propriedade TEXT NOT NULL,
        tipo        TEXT NOT NULL,
        data        TEXT NOT NULL,
        query_id    INTEGER NOT NULL REFERENCES dim_query(id),
        pagina_id   INTEGER NOT NULL REFERENCES dim_pagina(id),
        {_METRICAS},
        PRIMARY KEY (propriedade, tipo, data, query_id, pagina_id)
    ) WITHOUT ROWID
    """,
    # "qual URL ganhou/perdeu esta query" e "quais queries esta URL ganhou".
    "CREATE INDEX IF NOT EXISTS ix_fqp_query ON fato_query_pagina (query_id, data)",
    "CREATE INDEX IF NOT EXISTS ix_fqp_pagina ON fato_query_pagina (pagina_id, data)",
    # ── Grãos 5-7: dispositivo / país / aparência ───────────────────────────
    f"""
    CREATE TABLE IF NOT EXISTS fato_dispositivo (
        propriedade TEXT NOT NULL,
        tipo        TEXT NOT NULL,
        data        TEXT NOT NULL,
        dispositivo TEXT NOT NULL,
        {_METRICAS},
        PRIMARY KEY (propriedade, tipo, data, dispositivo)
    ) WITHOUT ROWID
    """,
    f"""
    CREATE TABLE IF NOT EXISTS fato_pais (
        propriedade TEXT NOT NULL,
        tipo        TEXT NOT NULL,
        data        TEXT NOT NULL,
        pais        TEXT NOT NULL,
        {_METRICAS},
        PRIMARY KEY (propriedade, tipo, data, pais)
    ) WITHOUT ROWID
    """,
    f"""
    CREATE TABLE IF NOT EXISTS fato_aparencia (
        propriedade TEXT NOT NULL,
        tipo        TEXT NOT NULL,
        data        TEXT NOT NULL,
        aparencia   TEXT NOT NULL,
        {_METRICAS},
        PRIMARY KEY (propriedade, tipo, data, aparencia)
    ) WITHOUT ROWID
    """,
    # ── Escrituração: é isto que faz resume e re-ingestão funcionarem ───────
    # UMA linha por DIA, mesmo quando um lote de 30 dias a produziu
    # (lote_inicio/lote_fim registram qual lote). Sem isso, dias vazios seriam
    # re-buscados em toda execução, para sempre.
    """
    CREATE TABLE IF NOT EXISTS ingestao (
        propriedade TEXT NOT NULL,
        tipo        TEXT NOT NULL,
        grao        TEXT NOT NULL,
        data        TEXT NOT NULL,
        status      TEXT NOT NULL,
        data_state  TEXT NOT NULL,
        linhas      INTEGER NOT NULL DEFAULT 0,
        paginas     INTEGER NOT NULL DEFAULT 0,
        lote_inicio TEXT,
        lote_fim    TEXT,
        cobertura_impressoes REAL,
        agregacao_resposta   TEXT,
        fetched_at  TEXT NOT NULL,
        erro        TEXT,
        PRIMARY KEY (propriedade, tipo, grao, data)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS ix_ingestao_pendente ON ingestao (grao, tipo, status, data)",
    """
    CREATE TABLE IF NOT EXISTS execucao (
        id            INTEGER PRIMARY KEY,
        iniciado_em   TEXT NOT NULL,
        terminado_em  TEXT,
        comando       TEXT NOT NULL,
        propriedade   TEXT,
        requisicoes   INTEGER NOT NULL DEFAULT 0,
        linhas        INTEGER NOT NULL DEFAULT 0,
        retentativas  INTEGER NOT NULL DEFAULT 0,
        esperas_carga INTEGER NOT NULL DEFAULT 0,
        erro          TEXT
    )
    """,
    # ── Eventos do site: o "porquê" que a API não tem ───────────────────────
    # Dado, não análise: o que mudou no site e quando. `tipo` é texto livre com
    # vocabulário sugerido (ver acervo.py) — enum rígido estaria errado, porque
    # evento é o que aconteceu, não o que o esquema previu.
    """
    CREATE TABLE IF NOT EXISTS evento (
        id          INTEGER PRIMARY KEY,
        propriedade TEXT NOT NULL,
        data        TEXT NOT NULL,
        data_fim    TEXT,
        tipo        TEXT NOT NULL,
        descricao   TEXT NOT NULL,
        urls        TEXT,
        fonte       TEXT,
        criado_em   TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_evento_data ON evento (propriedade, data)",
    # ── Coorte de URL de um evento: `evento.urls` RESOLVIDO contra dim_pagina ─
    # `evento.urls` é o texto que o analista digitou (a forma do PROJETO do
    # site); `dim_pagina.url` é a forma que o GSC devolveu. As duas divergem em
    # barra final, www, protocolo e percent-encoding, então cruzar as duas em
    # SQL puro não funciona — a normalização é código (store.chave_pagina, que
    # usa core/urls.py:canonical_path). Esta tabela guarda o resultado desse
    # casamento para que o SQL ad-hoc da análise consiga dizer
    # "tratadas contra não tratadas" com um JOIN e nada mais.
    #
    # É CACHE, não verdade: é recalculada no `anotar` e de novo no `pacote`,
    # porque uma URL do evento pode só entrar em dim_pagina numa ingestão
    # posterior (URL publicada depois do evento ser anotado).
    """
    CREATE TABLE IF NOT EXISTS evento_pagina (
        evento_id INTEGER NOT NULL REFERENCES evento(id) ON DELETE CASCADE,
        pagina_id INTEGER NOT NULL REFERENCES dim_pagina(id),
        PRIMARY KEY (evento_id, pagina_id)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS ix_evento_pagina_pagina ON evento_pagina (pagina_id)",
    # ── Detector passivo de superfícies novas ───────────────────────────────
    # Um valor NOVO de searchAppearance é precisamente como uma superfície de IA
    # apareceria primeiro na API existente — sem ninguém rodar sonda nenhuma.
    """
    CREATE TABLE IF NOT EXISTS dim_aparencia_vista (
        valor        TEXT PRIMARY KEY,
        primeira_vez TEXT NOT NULL,
        ultima_vez   TEXT NOT NULL
    )
    """,
)

# ---------------------------------------------------------------------------
# Views — a superfície "burra" de análise: pivot e re-derivação, zero veredito.
# ---------------------------------------------------------------------------

# O guard de NULL em posicao_ponderada não é cosmético: um
# SUM(position*impressions)/SUM(impressions) puro enviesa o resultado para baixo
# sempre que algum dia tem position IS NULL. Espelha a posição ponderada por
# impressões já usada no health score (core/analytics.py).
_ROLLUP_METRICAS = """
    SUM(clicks)      AS clicks,
    SUM(impressions) AS impressions,
    CASE WHEN SUM(impressions) > 0
         THEN 1.0*SUM(clicks)/SUM(impressions) END AS ctr_recalculado,
    CASE WHEN SUM(CASE WHEN position IS NOT NULL THEN impressions END) > 0
         THEN SUM(CASE WHEN position IS NOT NULL THEN position*impressions END)
            / SUM(CASE WHEN position IS NOT NULL THEN impressions END) END
                                                   AS posicao_ponderada,
    COUNT(*) AS dias_com_dado
"""

VIEWS = (
    """
    CREATE VIEW IF NOT EXISTS v_pagina_dia AS
    SELECT f.propriedade, f.tipo, f.data, p.url AS pagina,
           f.clicks, f.impressions, f.ctr, f.position, f.data_state, f.fetched_at
    FROM fato_pagina f JOIN dim_pagina p ON p.id = f.pagina_id
    """,
    """
    CREATE VIEW IF NOT EXISTS v_query_dia AS
    SELECT f.propriedade, f.tipo, f.data, q.termo AS query,
           f.clicks, f.impressions, f.ctr, f.position, f.data_state, f.fetched_at
    FROM fato_query f JOIN dim_query q ON q.id = f.query_id
    """,
    """
    CREATE VIEW IF NOT EXISTS v_query_pagina_dia AS
    SELECT f.propriedade, f.tipo, f.data, q.termo AS query, p.url AS pagina,
           f.clicks, f.impressions, f.ctr, f.position, f.data_state, f.fetched_at
    FROM fato_query_pagina f
    JOIN dim_query  q ON q.id = f.query_id
    JOIN dim_pagina p ON p.id = f.pagina_id
    """,
    f"""
    CREATE VIEW IF NOT EXISTS v_pagina_mes AS
    SELECT propriedade, tipo, substr(data, 1, 7) AS ano_mes, pagina,
           {_ROLLUP_METRICAS}
    FROM v_pagina_dia
    GROUP BY propriedade, tipo, ano_mes, pagina
    """,
    f"""
    CREATE VIEW IF NOT EXISTS v_query_mes AS
    SELECT propriedade, tipo, substr(data, 1, 7) AS ano_mes, query,
           {_ROLLUP_METRICAS}
    FROM v_query_dia
    GROUP BY propriedade, tipo, ano_mes, query
    """,
    f"""
    CREATE VIEW IF NOT EXISTS v_site_mes AS
    SELECT propriedade, tipo, substr(data, 1, 7) AS ano_mes,
           {_ROLLUP_METRICAS}
    FROM fato_total
    GROUP BY propriedade, tipo, ano_mes
    """,
    # Semana identificada pela SEGUNDA-feira (strftime %w: 0=domingo..6=sábado),
    # não por número de semana: número de semana tem convenções divergentes, a
    # data da segunda não tem.
    f"""
    CREATE VIEW IF NOT EXISTS v_site_semana AS
    SELECT propriedade, tipo,
           date(data, '-' || ((CAST(strftime('%w', data) AS INTEGER) + 6) % 7) || ' days')
               AS semana_inicio,
           {_ROLLUP_METRICAS}
    FROM fato_total
    GROUP BY propriedade, tipo, semana_inicio
    """,
    # O artefato de honestidade: o que existe, o que falta, o que bateu no teto.
    """
    CREATE VIEW IF NOT EXISTS v_cobertura AS
    SELECT propriedade, tipo, grao, status,
           COUNT(*) AS dias, MIN(data) AS primeiro, MAX(data) AS ultimo,
           SUM(linhas) AS linhas, AVG(cobertura_impressoes) AS cobertura_media
    FROM ingestao
    GROUP BY propriedade, tipo, grao, status
    """,
    """
    CREATE VIEW IF NOT EXISTS v_evento AS
    SELECT id, propriedade, data, COALESCE(data_fim, data) AS data_fim,
           tipo, descricao, urls, fonte
    FROM evento
    """,
    # A coorte do evento em forma utilizável: uma linha por (evento, URL do GSC).
    """
    CREATE VIEW IF NOT EXISTS v_evento_pagina AS
    SELECT e.id AS evento_id, e.propriedade, e.data, COALESCE(e.data_fim, e.data) AS data_fim,
           e.tipo, e.descricao, ep.pagina_id, p.url AS pagina
    FROM evento_pagina ep
    JOIN evento     e ON e.id = ep.evento_id
    JOIN dim_pagina p ON p.id = ep.pagina_id
    """,
)

# Migrações: {versao_destino: (stmt, ...)}. Cada uma roda na sua própria
# transação, em ordem, e só depois `PRAGMA user_version` é atualizado.
#
# v2 (P7.2) acrescenta `evento_pagina`. É aditiva e idempotente: um banco v1 com
# 700 mil linhas de fato ganha a tabela vazia em milissegundos, sem tocar em
# fato nenhum — e a coorte é reconstruída no `anotar`/`pacote` seguinte.
MIGRACOES: dict = {
    2: (
        """
        CREATE TABLE IF NOT EXISTS evento_pagina (
            evento_id INTEGER NOT NULL REFERENCES evento(id) ON DELETE CASCADE,
            pagina_id INTEGER NOT NULL REFERENCES dim_pagina(id),
            PRIMARY KEY (evento_id, pagina_id)
        ) WITHOUT ROWID
        """,
        "CREATE INDEX IF NOT EXISTS ix_evento_pagina_pagina ON evento_pagina (pagina_id)",
    ),
}


def aplicar_pragmas(conn: sqlite3.Connection) -> None:
    """Aplica os PRAGMAS de conexão (não persistem entre conexões, menos o WAL)."""
    for pragma in PRAGMAS:
        conn.execute(pragma)


def aplicar_esquema(conn: sqlite3.Connection) -> int:
    """Cria ou migra o esquema. Idempotente. Retorna a versão final.

    Banco novo (user_version == 0) recebe o DDL completo e já nasce na
    VERSAO_ESQUEMA atual. Banco existente aplica só as MIGRACOES que faltam.

    As views são recriadas em toda abertura (CREATE VIEW IF NOT EXISTS): são
    derivadas, não guardam dado, e assim acompanham a ferramenta sem migração.
    """
    versao = conn.execute("PRAGMA user_version").fetchone()[0]

    if versao > VERSAO_ESQUEMA:
        raise RuntimeError(
            f"Banco na versao {versao}, mais nova que esta ferramenta "
            f"({VERSAO_ESQUEMA}). Atualize o gsc-monitor antes de usar o acervo."
        )

    if versao == 0:
        with conn:
            for stmt in DDL:
                conn.execute(stmt)
        conn.execute(f"PRAGMA user_version = {VERSAO_ESQUEMA}")
    else:
        for alvo in range(versao + 1, VERSAO_ESQUEMA + 1):
            with conn:
                for stmt in MIGRACOES.get(alvo, ()):
                    conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {alvo}")

    with conn:
        for stmt in VIEWS:
            conn.execute(stmt)

    return VERSAO_ESQUEMA
