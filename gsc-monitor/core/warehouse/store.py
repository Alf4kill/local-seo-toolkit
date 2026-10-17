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
from urllib.parse import unquote

from core.urls import canonical_path, normalize_domain
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
    """Registra uma mudança no site. Dado, não análise.

    `urls` é a peça que transforma a análise em COMPARAÇÃO: com ela, "reescrevi
    o texto destas 40 URLs nesta data" vira um grupo tratado contra o resto do
    site. É guardada como JSON array na forma exata em que foi informada (a do
    projeto do site); o casamento com a forma do GSC fica em
    `casar_urls_evento`, e o texto original permanece intacto para auditoria.
    """
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
    """Eventos, com a contagem de URLs informadas e de URLs casadas em dim_pagina."""
    if propriedade:
        sql = "SELECT * FROM v_evento WHERE propriedade = ? ORDER BY data, id"
        linhas = [dict(linha) for linha in conn.execute(sql, (propriedade,))]
    else:
        linhas = [dict(linha) for linha in conn.execute("SELECT * FROM v_evento ORDER BY data, id")]

    casadas = {
        linha["evento_id"]: linha["n"]
        for linha in conn.execute(
            "SELECT evento_id, COUNT(*) AS n FROM evento_pagina GROUP BY evento_id"
        )
    }
    for linha in linhas:
        linha["urls_informadas"] = len(urls_informadas(linha.get("urls")))
        linha["urls_casadas"] = casadas.get(linha["id"], 0)
    return linhas


def remover_evento(conn: sqlite3.Connection, evento_id: int) -> bool:
    """Remove o evento e a coorte de URLs que pendia dele."""
    with conn:
        # Explícito em vez de confiar no ON DELETE CASCADE: `PRAGMA foreign_keys`
        # não persiste entre conexões, e um banco aberto por outra ferramenta
        # (ou pelo `sqlite3` do terminal) deixaria órfãos silenciosos.
        conn.execute("DELETE FROM evento_pagina WHERE evento_id = ?", (evento_id,))
        cur = conn.execute("DELETE FROM evento WHERE id = ?", (evento_id,))
    return bool(cur.rowcount)


# ---------------------------------------------------------------------------
# Casamento das URLs do evento com dim_pagina
# ---------------------------------------------------------------------------


def _tirar_host_nu(url: str, host: "str | None") -> str:
    """'exemplo.com.br/a' -> '/a', mas SÓ quando o host é o da propriedade.

    `urlsplit` só reconhece netloc depois de '//': sem esquema, o host inteiro
    vazia para dentro do caminho, e 'exemplo.com.br/a' virava a chave
    '/exemplo.com.br/a', que não casa com nada. A forma sem protocolo é comum
    justamente nas listas que o analista cola (projeto do site, planilha, export
    de crawler), e uma URL que não casa vai para o grupo NÃO TRATADO —
    contaminando o controle da comparação que `evento_pagina` existe para
    sustentar.

    A decisão não pode sair da string sozinha: 'arquivo.pdf/x' é um caminho
    relativo legítimo e também tem ponto. Por isso o corte só acontece quando o
    primeiro segmento é o host DA PROPRIEDADE (com ou sem www) — que já está em
    `evento.propriedade`. Fora disso não se adivinha nada.
    """
    if not host or "//" in url:
        return url
    nu = url.lstrip("/")
    primeiro = nu.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].lower()
    base = host.lower().removeprefix("www.")
    if primeiro not in (base, f"www.{base}"):
        return url
    resto = nu[len(nu.split("/", 1)[0]) :]
    return resto or "/"


def chave_pagina(url: str, *, host: "str | None" = None) -> str:
    """Chave de casamento entre a URL do PROJETO do site e a que o GSC devolveu.

    Parte de `core/urls.py:canonical_path` (que já derruba protocolo, host — e
    com ele o www —, query, fragmento e barra final) e acrescenta DUAS coisas:

      - o percent-encoding é desfeito. O GSC devolve o caminho codificado
        ('/categoria/pe%C3%A7as') e o projeto do site costuma ter o acentuado
        ('/categoria/peças'); sem desfazer, os dois nunca casariam;
      - o host nu de uma URL sem esquema é retirado quando é o host de `host`
        (ver `_tirar_host_nu`).

    Mora aqui, e não em `core/urls.py`, de propósito: `canonical_path` é a chave
    do cruzamento sitemap × access log × GSC, e mexer nela mudaria o
    comportamento da poda e do analisador de log. Esta variante é só do acervo.

    `host` é o host da propriedade (de `core/urls.py:normalize_domain`). Sem
    ele, uma URL sem esquema com host nu continua não casando — é o preço de não
    adivinhar, e quem chama tem a propriedade à mão.
    """
    return unquote(canonical_path(_tirar_host_nu(url.strip(), host)))


def urls_informadas(urls_json: "str | None") -> list:
    """Desserializa `evento.urls` (JSON array), tolerando NULL e conteúdo inválido."""
    if not urls_json:
        return []
    try:
        valores = json.loads(urls_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(valores, list):
        return []
    return [str(v).strip() for v in valores if str(v).strip()]


def casar_urls_evento(conn: sqlite3.Connection, *, evento_id: "int | None" = None) -> dict:
    """(Re)constrói `evento_pagina` a partir de `evento.urls`.

    Roda no `anotar` — para o analista ver na hora quantas URLs não casaram, em
    vez de descobrir meses depois, na análise — e de novo no `pacote`, porque
    uma URL do evento pode só entrar em dim_pagina numa ingestão posterior
    (página publicada depois de o evento ter sido anotado).

    Retorna {evento_id: {"informadas": n, "casadas": n, "sem_casamento": [url, ...]}}.
    """
    if evento_id is None:
        eventos = list(
            conn.execute("SELECT id, propriedade, urls FROM evento WHERE urls IS NOT NULL")
        )
    else:
        eventos = list(
            conn.execute(
                "SELECT id, propriedade, urls FROM evento WHERE id = ? AND urls IS NOT NULL",
                (evento_id,),
            )
        )
    if not eventos:
        return {}

    # Um índice por chave canônica de TODA a dim_pagina. Mais de uma URL do GSC
    # pode colapsar na mesma chave (barra final, encoding) — e aí as duas entram
    # na coorte, porque são a mesma página vista em duas formas.
    #
    # Indexado SEM `host`: a URL que a API devolve sempre vem com esquema, então
    # não há host nu para tirar deste lado. O `host` entra só na URL informada
    # pelo analista, que é a que pode vir sem protocolo.
    indice: dict = {}
    for linha in conn.execute("SELECT id, url FROM dim_pagina"):
        indice.setdefault(chave_pagina(linha["url"]), []).append(int(linha["id"]))

    relatorio: dict = {}
    with conn:
        for evento in eventos:
            ident = int(evento["id"])
            host = normalize_domain(evento["propriedade"] or "")
            informadas = urls_informadas(evento["urls"])
            conn.execute("DELETE FROM evento_pagina WHERE evento_id = ?", (ident,))
            casados: set = set()
            sem_casamento = []
            for url in informadas:
                ids = indice.get(chave_pagina(url, host=host))
                if ids:
                    casados.update(ids)
                else:
                    sem_casamento.append(url)
            for pagina_id in sorted(casados):
                conn.execute(
                    "INSERT OR IGNORE INTO evento_pagina (evento_id, pagina_id) VALUES (?, ?)",
                    (ident, pagina_id),
                )
            relatorio[ident] = {
                "informadas": len(informadas),
                "casadas": len(casados),
                "sem_casamento": sem_casamento,
            }
    return relatorio


def paginas_do_evento(conn: sqlite3.Connection, evento_id: int) -> list:
    """As URLs do GSC que casaram com o evento — a coorte tratada, em texto."""
    sql = (
        "SELECT p.url FROM evento_pagina ep JOIN dim_pagina p ON p.id = ep.pagina_id "
        "WHERE ep.evento_id = ? ORDER BY p.url"
    )
    return [linha["url"] for linha in conn.execute(sql, (evento_id,))]


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


def contar_linhas_por_tipo(conn: sqlite3.Connection, tabela: str) -> dict:
    """{tipo: linhas} de uma tabela de fato.

    Com mais de um `type` no acervo, a contagem total da tabela soma coisas que
    NÃO são comparáveis — `web` e `image` são superfícies de busca diferentes,
    com volumes e quedas diferentes. Um número só, sem dizer que mistura os
    dois, é pior que não mostrar número.
    """
    sql = f"SELECT tipo, COUNT(*) AS n FROM {tabela} GROUP BY tipo ORDER BY tipo"
    return {linha["tipo"]: int(linha["n"]) for linha in conn.execute(sql)}


def tipos_ingeridos(conn: sqlite3.Connection, *, propriedade: "str | None" = None) -> list:
    """Os `type` que a ESCRITURAÇÃO registra — o que foi de fato pedido à API.

    Lido de `ingestao`, não das tabelas de fato, e a diferença importa: um tipo
    coletado cujos dias voltaram todos vazios aparece aqui (foi coletado, não
    tem tráfego) e não apareceria numa contagem de linhas. É essa a lista que
    `pacote --todos-os-tipos` usa, para não deixar de fora a escrituração de um
    tipo só porque ele está vazio — "vazio" é exatamente o que ela declara.
    """
    sql = "SELECT DISTINCT tipo FROM ingestao"
    parametros: tuple = ()
    if propriedade:
        sql += " WHERE propriedade = ?"
        parametros = (propriedade,)
    return sorted(linha["tipo"] for linha in conn.execute(sql + " ORDER BY tipo", parametros))


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


def dias_por_grao(conn: sqlite3.Connection, *, propriedade: str, tipo: str) -> list:
    """Por grão: primeiro/último dia, dias por status e os dias que FALTAM.

    "Falta" é medido contra o calendário contínuo entre o primeiro e o último
    dia registrados daquele grão — não contra a janela pedida na CLI. É a única
    definição que não depende de lembrar com que `--dias` o backfill rodou.
    """
    sql = (
        "SELECT grao, status, COUNT(*) AS dias, MIN(data) AS primeiro, MAX(data) AS ultimo, "
        "       SUM(linhas) AS linhas "
        "FROM ingestao WHERE propriedade=? AND tipo=? GROUP BY grao, status"
    )
    por_grao: dict = {}
    for linha in conn.execute(sql, (propriedade, tipo)):
        info = por_grao.setdefault(
            linha["grao"],
            {
                "grao": linha["grao"],
                "por_status": {},
                "primeiro": None,
                "ultimo": None,
                "linhas": 0,
            },
        )
        info["por_status"][linha["status"]] = linha["dias"]
        info["linhas"] += int(linha["linhas"] or 0)
        if info["primeiro"] is None or linha["primeiro"] < info["primeiro"]:
            info["primeiro"] = linha["primeiro"]
        if info["ultimo"] is None or linha["ultimo"] > info["ultimo"]:
            info["ultimo"] = linha["ultimo"]

    for grao, info in por_grao.items():
        registrados = {
            linha["data"]
            for linha in conn.execute(
                "SELECT data FROM ingestao WHERE propriedade=? AND tipo=? AND grao=?",
                (propriedade, tipo, grao),
            )
        }
        info["dias_registrados"] = len(registrados)
        info["faltando"] = (
            [dia for dia in _calendario(info["primeiro"], info["ultimo"]) if dia not in registrados]
            if info["primeiro"]
            else []
        )
        info["dias_teto"] = [
            linha["data"]
            for linha in conn.execute(
                "SELECT data FROM ingestao WHERE propriedade=? AND tipo=? AND grao=? "
                "AND status IN (?, ?) ORDER BY data",
                (propriedade, tipo, grao, STATUS_TETO, STATUS_CAPADO),
            )
        ]
    return [por_grao[grao] for grao in sorted(por_grao)]


def _calendario(inicio: str, fim: str) -> list:
    """Todo dia ISO entre `inicio` e `fim`, inclusive."""
    from datetime import date, timedelta

    primeiro, ultimo = date.fromisoformat(inicio), date.fromisoformat(fim)
    return [(primeiro + timedelta(days=n)).isoformat() for n in range((ultimo - primeiro).days + 1)]


def agregacao_e_cobertura(conn: sqlite3.Connection, *, propriedade: str, tipo: str) -> list:
    """Por grão: `responseAggregationType` declarado pela API + cobertura medida.

    Os dois JUNTOS, nunca separados. A cobertura só é interpretável à luz da
    agregação: `byProperty` conta uma impressão de SERP uma vez para o site
    inteiro (e aí cobertura < 1 mede a cauda anonimizada), enquanto `byPage`
    conta uma vez POR URL do site que apareceu naquela SERP (e aí cobertura > 1
    é o esperado, não defeito). Ver pacote.py, que escreve isso no DADOS.md.
    """
    sql = (
        "SELECT grao, agregacao_resposta AS agregacao, COUNT(*) AS dias, "
        "       AVG(cobertura_impressoes) AS media, MIN(cobertura_impressoes) AS minimo, "
        "       MAX(cobertura_impressoes) AS maximo "
        "FROM ingestao WHERE propriedade=? AND tipo=? AND cobertura_impressoes IS NOT NULL "
        "GROUP BY grao, agregacao_resposta ORDER BY grao, agregacao_resposta"
    )
    return [dict(linha) for linha in conn.execute(sql, (propriedade, tipo))]


def cobertura_por_mes(conn: sqlite3.Connection, *, propriedade: str, tipo: str) -> list:
    """{grao, ano_mes, agregacao, cobertura média do mês} — a série da cauda."""
    sql = (
        "SELECT grao, substr(data, 1, 7) AS ano_mes, agregacao_resposta AS agregacao, "
        "       AVG(cobertura_impressoes) AS media, COUNT(*) AS dias "
        "FROM ingestao WHERE propriedade=? AND tipo=? AND cobertura_impressoes IS NOT NULL "
        "GROUP BY grao, ano_mes, agregacao_resposta ORDER BY grao, ano_mes"
    )
    return [dict(linha) for linha in conn.execute(sql, (propriedade, tipo))]


def coortes_url(conn: sqlite3.Connection, *, propriedade: str, tipo: str) -> dict:
    """Primeiro e último dia em que cada URL apareceu, agrupados por mês.

    Dado que já existe (MIN/MAX de `fato_pagina`), e que de graça mostra as
    ondas de publicação e de mortandade de URLs.

    AS DUAS PONTAS SÃO ARTEFATO, e por isso vêm rotuladas: toda URL que já
    existia quando a janela abriu cai no primeiro mês ("surgiu" ali só porque a
    janela começa ali), e toda URL ainda viva cai no último ("vista por último"
    ali só porque o dado termina ali). Sem o rótulo, as duas pontas são lidas
    como onda real — foi o primeiro erro de leitura que o dado real produziu.

    Retorna as duas distribuições por mês, os meses de borda e a contagem
    exata de URLs censuradas em cada ponta (as que tocam o primeiro/último dia).
    """
    linha = conn.execute(
        "SELECT MIN(data) AS primeiro, MAX(data) AS ultimo FROM fato_pagina "
        "WHERE propriedade=? AND tipo=?",
        (propriedade, tipo),
    ).fetchone()
    primeiro_dia, ultimo_dia = linha["primeiro"], linha["ultimo"]
    vazio = {
        "primeiro_dia": None,
        "ultimo_dia": None,
        "mes_borda_inicial": None,
        "mes_borda_final": None,
        "surgimentos": [],
        "desaparecimentos": [],
        "censuradas_a_esquerda": 0,
        "censuradas_a_direita": 0,
        "urls": 0,
    }
    if not primeiro_dia:
        return vazio

    por_url = {
        int(linha["pagina_id"]): (linha["surgiu"], linha["visto_por_ultimo"])
        for linha in conn.execute(
            "SELECT pagina_id, MIN(data) AS surgiu, MAX(data) AS visto_por_ultimo "
            "FROM fato_pagina WHERE propriedade=? AND tipo=? GROUP BY pagina_id",
            (propriedade, tipo),
        )
    }
    mes_inicial, mes_final = primeiro_dia[:7], ultimo_dia[:7]

    surgimentos: dict = {}
    desaparecimentos: dict = {}
    censuradas_esq = censuradas_dir = 0
    for surgiu, visto in por_url.values():
        surgimentos[surgiu[:7]] = surgimentos.get(surgiu[:7], 0) + 1
        desaparecimentos[visto[:7]] = desaparecimentos.get(visto[:7], 0) + 1
        if surgiu == primeiro_dia:
            censuradas_esq += 1
        if visto == ultimo_dia:
            censuradas_dir += 1

    def _series(contagem: dict, mes_borda: str) -> list:
        return [
            {"ano_mes": mes, "urls": contagem[mes], "borda": mes == mes_borda}
            for mes in sorted(contagem)
        ]

    return {
        "primeiro_dia": primeiro_dia,
        "ultimo_dia": ultimo_dia,
        "mes_borda_inicial": mes_inicial,
        "mes_borda_final": mes_final,
        "surgimentos": _series(surgimentos, mes_inicial),
        "desaparecimentos": _series(desaparecimentos, mes_final),
        "censuradas_a_esquerda": censuradas_esq,
        "censuradas_a_direita": censuradas_dir,
        "urls": len(por_url),
    }


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
