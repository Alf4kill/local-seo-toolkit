"""
store.py — Camada SQLite do acervo: abertura, upsert, escrituração e eventos.

Não fala com a rede. Recebe as linhas lógicas de rows.py e o plano de plan.py e
persiste tudo de forma IDEMPOTENTE: re-ingerir o mesmo dia produz a mesma
contagem de linhas, com os valores atualizados.

Duas propriedades de correção, nesta ordem de importância:

1. Fatos e escrituração de um lote são gravados numa ÚNICA transação. Um crash
   nunca deixa um dia marcado `ok` sem suas linhas, nem linhas sem marca. Um
   commit por lote significa que um backfill de 480 dias interrompido perde no
   máximo o lote em voo, e re-rodar retoma de onde parou sem refazer requisição.

2. `ingestao` tem uma linha por DIA, mesmo quando um lote de 30 dias a produziu.
   Inclusive para dia sem dado (status='vazio') — sem isso, dia vazio seria
   re-buscado em toda execução, para sempre.

O caminho do banco é derivado de storage.RELATORIOS_DIR em TEMPO DE CHAMADA, não
no import: é o que permite ao conftest.py redirecionar a pasta de relatórios para
um tmp durante os testes (mesma razão documentada em core/batch.py).
"""

import json
import os
import sqlite3
from datetime import UTC, datetime

from core.warehouse import schema
from core.warehouse.plan import GRAOS, dia_definitivo

# Colunas de métrica/proveniência comuns a toda tabela de fato.
_METRICAS = ("clicks", "impressions", "ctr", "position")
_PROVENIENCIA = ("data_state", "fetched_at", "alterado_em", "revisoes")

# Dimensões internadas: chave lógica -> (tabela, coluna de valor)
_DIMENSOES = {
    "pagina": ("dim_pagina", "url"),
    "query": ("dim_query", "termo"),
}

STATUS_OK = "ok"
STATUS_VAZIO = "vazio"
STATUS_TETO = "teto"
STATUS_CAPADO = "pagina_capada"
STATUS_ERRO = "erro"

# Dia com um destes status e já definitivo não é re-pedido: o GSC não vai mudar
# de ideia. 'erro' fica de fora de propósito — erro se tenta de novo.
_STATUS_RESOLVIDO = (STATUS_OK, STATUS_VAZIO, STATUS_TETO, STATUS_CAPADO)


def agora() -> str:
    """Timestamp ISO em UTC, no formato usado por core/cache.py."""
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Abertura
# ---------------------------------------------------------------------------


def caminho_banco(site: str) -> str:
    """relatorios/{dominio}/acervo/acervo.sqlite3 — resolvido em tempo de chamada."""
    from core import storage

    return storage.acervo_db_path(site)


def abrir(site: str) -> sqlite3.Connection:
    """Abre (criando se preciso) o banco do site, com pragmas e esquema aplicados."""
    return abrir_caminho(caminho_banco(site))


def abrir_caminho(caminho: str) -> sqlite3.Connection:
    """Abre um banco por caminho explícito (usado pelos testes e pelo snapshot)."""
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    schema.aplicar_pragmas(conn)
    schema.aplicar_esquema(conn)
    return conn


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------


def definir_meta(conn: sqlite3.Connection, chave: str, valor) -> None:
    texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
    with conn:
        conn.execute(
            "INSERT INTO meta (chave, valor) VALUES (?, ?) "
            "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor",
            (chave, texto),
        )


def ler_meta(conn: sqlite3.Connection, chave: str) -> "str | None":
    linha = conn.execute("SELECT valor FROM meta WHERE chave = ?", (chave,)).fetchone()
    return linha["valor"] if linha else None


def semear_meta(conn: sqlite3.Connection, *, propriedade: str) -> None:
    """Grava os metadados que o pacote de análise precisa declarar."""
    if ler_meta(conn, "criado_em") is None:
        definir_meta(conn, "criado_em", agora())
    # O GSC rotula o dia pelo horário da Califórnia. Registrar isso aqui é o que
    # impede uma análise futura de juntar estas datas com GA4 ou log de servidor
    # como se fossem o mesmo dia.
    definir_meta(conn, "fuso_dados", "America/Los_Angeles")
    definir_meta(conn, "versao_esquema", str(schema.VERSAO_ESQUEMA))
    anteriores = ler_meta(conn, "propriedades")
    conhecidas = json.loads(anteriores) if anteriores else []
    if propriedade not in conhecidas:
        conhecidas.append(propriedade)
        definir_meta(conn, "propriedades", conhecidas)


# ---------------------------------------------------------------------------
# Interning das dimensões de alta cardinalidade
# ---------------------------------------------------------------------------


def _internar(conn: sqlite3.Connection, dimensao: str, valor: str, cache: dict) -> int:
    """Texto -> id em dim_pagina/dim_query, com cache por lote."""
    chave = (dimensao, valor)
    if chave in cache:
        return cache[chave]

    tabela, coluna = _DIMENSOES[dimensao]
    linha = conn.execute(f"SELECT id FROM {tabela} WHERE {coluna} = ?", (valor,)).fetchone()
    if linha is None:
        cursor = conn.execute(f"INSERT INTO {tabela} ({coluna}) VALUES (?)", (valor,))
        ident = int(cursor.lastrowid)
    else:
        ident = int(linha["id"])

    cache[chave] = ident
    return ident


# ---------------------------------------------------------------------------
# Upsert dos fatos
# ---------------------------------------------------------------------------


def _sql_upsert(grao: str) -> str:
    """Monta o INSERT ... ON CONFLICT DO UPDATE de um grão.

    `revisoes` e `alterado_em` só mudam quando ALGUM VALOR muda — não a cada
    re-busca. A diferença importa: o `diario` re-busca os 13 dias de ponta em
    toda execução, e contar re-buscas encheria a coluna de ruído em vez de
    mostrar quais dias o GSC realmente revisou.

    A comparação usa `IS NOT` (não `<>`) porque é null-safe: `position` pode ser
    NULL, e `NULL <> NULL` é NULL, o que faria o CASE nunca disparar.
    """
    spec = GRAOS[grao]
    tabela = spec["tabela"]
    chaves = ("propriedade", "tipo", "data") + tuple(spec["colunas"])
    colunas = chaves + _METRICAS + _PROVENIENCIA
    marcadores = ", ".join("?" for _ in colunas)

    mudou = " OR ".join(
        f"{tabela}.{c} IS NOT excluded.{c}" for c in ("clicks", "impressions", "position")
    )

    return (
        f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({marcadores}) "
        f"ON CONFLICT ({', '.join(chaves)}) DO UPDATE SET "
        "clicks = excluded.clicks, "
        "impressions = excluded.impressions, "
        "ctr = excluded.ctr, "
        "position = excluded.position, "
        "data_state = excluded.data_state, "
        "fetched_at = excluded.fetched_at, "
        f"revisoes = {tabela}.revisoes + CASE WHEN {mudou} THEN 1 ELSE 0 END, "
        f"alterado_em = CASE WHEN {mudou} THEN excluded.fetched_at "
        f"ELSE {tabela}.alterado_em END"
    )


_SQL_INGESTAO = """
INSERT INTO ingestao (propriedade, tipo, grao, data, status, data_state, linhas,
                      paginas, lote_inicio, lote_fim, cobertura_impressoes,
                      agregacao_resposta, fetched_at, erro)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT (propriedade, tipo, grao, data) DO UPDATE SET
    status = excluded.status,
    data_state = excluded.data_state,
    linhas = excluded.linhas,
    paginas = excluded.paginas,
    lote_inicio = excluded.lote_inicio,
    lote_fim = excluded.lote_fim,
    cobertura_impressoes = excluded.cobertura_impressoes,
    agregacao_resposta = excluded.agregacao_resposta,
    fetched_at = excluded.fetched_at,
    erro = excluded.erro
"""


def gravar_lote(
    conn: sqlite3.Connection,
    *,
    grao: str,
    propriedade: str,
    tipo: str,
    linhas: list,
    dias_do_lote,
    data_state: str,
    lote_inicio: "str | None" = None,
    lote_fim: "str | None" = None,
    paginas: int = 1,
    agregacao: "str | None" = None,
    cobertura: "dict | None" = None,
    status_por_dia: "dict | None" = None,
    fetched_at: "str | None" = None,
) -> dict:
    """Grava fatos + escrituração de um lote numa ÚNICA transação.

    `dias_do_lote` são TODOS os dias que o lote cobriu, inclusive os que não
    voltaram com linha — esses ficam status='vazio' e param de ser re-pedidos.

    Retorna {"linhas": n, "dias": n, "por_dia": {data: n}}.
    """
    spec = GRAOS[grao]
    sql_fato = _sql_upsert(grao)
    internar = spec.get("internar", {})
    quando = fetched_at or agora()
    cobertura = cobertura or {}
    status_por_dia = status_por_dia or {}
    dias = list(dias_do_lote)

    por_dia: dict = {}
    cache: dict = {}

    with conn:
        for linha in linhas:
            chaves = []
            for coluna in spec["colunas"]:
                valor = linha["chaves"][coluna]
                dimensao = internar.get(coluna)
                chaves.append(_internar(conn, dimensao, valor, cache) if dimensao else valor)

            conn.execute(
                sql_fato,
                (
                    propriedade,
                    tipo,
                    linha["data"],
                    *chaves,
                    linha["clicks"],
                    linha["impressions"],
                    linha["ctr"],
                    linha["position"],
                    data_state,
                    quando,
                    quando,
                    0,
                ),
            )
            por_dia[linha["data"]] = por_dia.get(linha["data"], 0) + 1

        for dia in dias:
            n = por_dia.get(dia, 0)
            status = status_por_dia.get(dia) or (STATUS_OK if n else STATUS_VAZIO)
            conn.execute(
                _SQL_INGESTAO,
                (
                    propriedade,
                    tipo,
                    grao,
                    dia,
                    status,
                    data_state,
                    n,
                    paginas,
                    lote_inicio or (dias[0] if dias else None),
                    lote_fim or (dias[-1] if dias else None),
                    cobertura.get(dia),
                    agregacao,
                    quando,
                    None,
                ),
            )

    return {"linhas": len(linhas), "dias": len(dias), "por_dia": por_dia}


def marcar_erro(
    conn: sqlite3.Connection,
    *,
    grao: str,
    propriedade: str,
    tipo: str,
    dias,
    data_state: str,
    erro: str,
) -> None:
    """Marca os dias de um lote que falhou. Dia com erro VOLTA a ser pendente."""
    quando = agora()
    with conn:
        for dia in dias:
            conn.execute(
                _SQL_INGESTAO,
                (
                    propriedade,
                    tipo,
                    grao,
                    dia,
                    STATUS_ERRO,
                    data_state,
                    0,
                    0,
                    None,
                    None,
                    None,
                    None,
                    quando,
                    erro[:500],
                ),
            )


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def dias_pendentes(
    conn: sqlite3.Connection,
    *,
    propriedade: str,
    tipo: str,
    grao: str,
    dias: list,
    hoje=None,
    forcar: bool = False,
) -> list:
    """Dias que ainda precisam de ingestão. É isto que faz o resume funcionar.

    Pendente =
      - sem registro em `ingestao`; OU
      - status='erro'; OU
      - dia ainda dentro da janela de assentamento (re-ingerido para sobrescrever
        o que o GSC revisou).

    NÃO pendente = dia definitivo com status resolvido ('ok', 'vazio', 'teto',
    'pagina_capada'). Dia vazio ou truncado definitivo não é re-pedido: o GSC
    não vai mudar de ideia, e re-pedir só gastaria cota.

    `forcar` ignora tudo isso e devolve todos os dias.
    """
    if forcar:
        return list(dias)

    registrados = {
        linha["data"]: linha["status"]
        for linha in conn.execute(
            "SELECT data, status FROM ingestao WHERE propriedade=? AND tipo=? AND grao=?",
            (propriedade, tipo, grao),
        )
    }

    pendentes = []
    for dia in dias:
        status = registrados.get(dia)
        if status is None or status not in _STATUS_RESOLVIDO:
            pendentes.append(dia)
        elif not dia_definitivo(dia, hoje=hoje):
            pendentes.append(dia)
    return pendentes


def impressoes_total_por_dia(
    conn: sqlite3.Connection, *, propriedade: str, tipo: str, dias: list
) -> dict:
    """{data: impressões do site} do grão `total` — a régua da cobertura."""
    if not dias:
        return {}
    marcadores = ",".join("?" for _ in dias)
    sql = (
        "SELECT data, impressions FROM fato_total "
        f"WHERE propriedade=? AND tipo=? AND data IN ({marcadores})"
    )
    return {
        linha["data"]: linha["impressions"]
        for linha in conn.execute(sql, (propriedade, tipo, *dias))
    }


def media_linhas_por_dia(conn: sqlite3.Connection, *, propriedade: str, tipo: str) -> dict:
    """{grao: média de linhas/dia} medida na escrituração.

    Troca palpite por medição nas estimativas do --dry-run a partir da segunda
    execução num site.
    """
    sql = (
        "SELECT grao, AVG(linhas) AS media FROM ingestao "
        "WHERE propriedade=? AND tipo=? AND status=? GROUP BY grao"
    )
    return {
        linha["grao"]: float(linha["media"] or 0.0)
        for linha in conn.execute(sql, (propriedade, tipo, STATUS_OK))
    }


# ---------------------------------------------------------------------------
# Re-ingestão
# ---------------------------------------------------------------------------


def apagar_intervalo(
    conn: sqlite3.Connection,
    *,
    propriedade: str,
    tipo: str,
    graos,
    de: str,
    ate: str,
    apagar_fatos: bool = False,
) -> dict:
    """Prepara uma re-ingestão: apaga a escrituração do intervalo (os fatos
    ficam, o upsert sobrescreve).

    `apagar_fatos=True` apaga também as linhas de fato — necessário quando uma
    página ou query genuinamente desapareceu de um dia e a linha velha ficaria
    pendurada, já que o upsert só sobrescreve o que volta.
    """
    contagem = {"ingestao": 0, "fatos": 0}
    with conn:
        for grao in graos:
            cur = conn.execute(
                "DELETE FROM ingestao WHERE propriedade=? AND tipo=? AND grao=? "
                "AND data BETWEEN ? AND ?",
                (propriedade, tipo, grao, de, ate),
            )
            contagem["ingestao"] += cur.rowcount or 0
            if apagar_fatos:
                tabela = GRAOS[grao]["tabela"]
                cur = conn.execute(
                    f"DELETE FROM {tabela} WHERE propriedade=? AND tipo=? AND data BETWEEN ? AND ?",
                    (propriedade, tipo, de, ate),
                )
                contagem["fatos"] += cur.rowcount or 0
    return contagem


# ---------------------------------------------------------------------------
# Aparências vistas (detector passivo de superfície nova)
# ---------------------------------------------------------------------------


def registrar_aparencias(conn: sqlite3.Connection, valores, *, quando: "str | None" = None) -> list:
    """Upsert em dim_aparencia_vista. Retorna os valores vistos pela PRIMEIRA vez.

    Um valor novo aqui é como uma superfície de IA apareceria primeiro na API
    existente — sem gastar requisição com sonda nenhuma.
    """
    quando = quando or agora()
    novos = []
    with conn:
        for valor in valores:
            existe = conn.execute(
                "SELECT 1 FROM dim_aparencia_vista WHERE valor = ?", (valor,)
            ).fetchone()
            if existe is None:
                novos.append(valor)
            conn.execute(
                "INSERT INTO dim_aparencia_vista (valor, primeira_vez, ultima_vez) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT (valor) DO UPDATE SET ultima_vez = excluded.ultima_vez",
                (valor, quando, quando),
            )
    return novos


# ---------------------------------------------------------------------------
# Log de execução
# ---------------------------------------------------------------------------


def iniciar_execucao(conn: sqlite3.Connection, *, comando: str, propriedade: str) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO execucao (iniciado_em, comando, propriedade) VALUES (?, ?, ?)",
            (agora(), comando, propriedade),
        )
    return int(cur.lastrowid)


def finalizar_execucao(
    conn: sqlite3.Connection,
    execucao_id: int,
    *,
    requisicoes: int = 0,
    linhas: int = 0,
    retentativas: int = 0,
    esperas_carga: int = 0,
    erro: "str | None" = None,
) -> None:
    with conn:
        conn.execute(
            "UPDATE execucao SET terminado_em=?, requisicoes=?, linhas=?, "
            "retentativas=?, esperas_carga=?, erro=? WHERE id=?",
            (
                agora(),
                requisicoes,
                linhas,
                retentativas,
                esperas_carga,
                erro[:500] if erro else None,
                execucao_id,
            ),
        )


# ---------------------------------------------------------------------------
# Eventos do site
# ---------------------------------------------------------------------------


def adicionar_evento(
    conn: sqlite3.Connection,
    *,
    propriedade: str,
    data: str,
    tipo: str,
    descricao: str,
    data_fim: "str | None" = None,
    urls: "list | None" = None,
    fonte: str = "manual",
) -> int:
    """Registra uma mudança no site. Dado, não análise."""
    with conn:
        cur = conn.execute(
            "INSERT INTO evento (propriedade, data, data_fim, tipo, descricao, urls, "
            "fonte, criado_em) VALUES (?,?,?,?,?,?,?,?)",
            (
                propriedade,
                data,
                data_fim,
                tipo,
                descricao,
                json.dumps(urls, ensure_ascii=False) if urls else None,
                fonte,
                agora(),
            ),
        )
    return int(cur.lastrowid)


def listar_eventos(conn: sqlite3.Connection, *, propriedade: "str | None" = None) -> list:
    if propriedade:
        sql = "SELECT * FROM v_evento WHERE propriedade = ? ORDER BY data, id"
        return [dict(linha) for linha in conn.execute(sql, (propriedade,))]
    return [dict(linha) for linha in conn.execute("SELECT * FROM v_evento ORDER BY data, id")]


def remover_evento(conn: sqlite3.Connection, evento_id: int) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM evento WHERE id = ?", (evento_id,))
    return bool(cur.rowcount)


# ---------------------------------------------------------------------------
# Leitura para status / pacote
# ---------------------------------------------------------------------------


def cobertura(conn: sqlite3.Connection, *, propriedade: "str | None" = None) -> list:
    if propriedade:
        sql = "SELECT * FROM v_cobertura WHERE propriedade = ? ORDER BY grao, tipo, status"
        return [dict(linha) for linha in conn.execute(sql, (propriedade,))]
    return [dict(linha) for linha in conn.execute("SELECT * FROM v_cobertura ORDER BY grao, tipo")]


def contar_linhas(conn: sqlite3.Connection, tabela: str) -> int:
    """Contagem de linhas de uma tabela de fato (usado por status e testes)."""
    return int(conn.execute(f"SELECT COUNT(*) AS n FROM {tabela}").fetchone()["n"])


def dias_provisorios(conn: sqlite3.Connection, *, propriedade: str) -> list:
    """Dias gravados como ainda assentando — a ponta da série, instável.

    Quem analisa precisa saber quais são para não tirar conclusão deles.
    """
    sql = (
        "SELECT DISTINCT data FROM ingestao "
        "WHERE propriedade=? AND data_state <> 'final' ORDER BY data"
    )
    return [linha["data"] for linha in conn.execute(sql, (propriedade,))]


def ultimas_execucoes(conn: sqlite3.Connection, limite: int = 5) -> list:
    sql = "SELECT * FROM execucao ORDER BY id DESC LIMIT ?"
    return [dict(linha) for linha in conn.execute(sql, (limite,))]


def snapshot(conn: sqlite3.Connection, destino: str) -> str:
    """Cópia consistente do banco (mesmo com WAL ativo), para o pacote.

    Usa Connection.backup() da stdlib em vez de VACUUM INTO porque não depende
    da versão do SQLite embutida no Python.
    """
    pasta = os.path.dirname(destino)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    if os.path.exists(destino):
        os.remove(destino)
    alvo = sqlite3.connect(destino)
    try:
        with alvo:
            conn.backup(alvo)
    finally:
        alvo.close()
    return destino
