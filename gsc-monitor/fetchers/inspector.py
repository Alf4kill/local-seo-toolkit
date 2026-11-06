"""
inspector.py — Chamadas à URL Inspection API do Google Search Console.

Limites oficiais (developers.google.com/webmaster-tools/limits), POR SITE:
    2.000 QPD (queries por dia)  e  600 QPM (queries por minuto = 10 QPS)

O modo antigo era sequencial com sleep de 0,5 s entre chamadas: ~45 QPM, ou
7% do permitido, o que dava ~25 min num site de 874 URLs. Agora as chamadas
vão num pool de threads com um token bucket segurando a vazão abaixo do QPM.

Três cuidados que o paralelismo exige e que estão implementados aqui:

1. O objeto `service` do google-api-python-client NÃO é thread-safe — o
   httplib2.Http interno é compartilhado e, usado de várias threads, devolve
   respostas trocadas em vez de levantar erro. A recomendação oficial é um
   Http por thread; é o que _thread_http() faz. Sem credenciais (ex.: testes
   com service fake) o modo paralelo é recusado e cai no sequencial.
2. O token é renovado UMA VEZ antes de abrir o pool: google-auth não serializa
   o refresh, e várias threads renovando juntas é corrida.
3. Paralelizar não aumenta a cota diária, só a esgota mais rápido — daí o
   freio explícito de max_calls.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from config import (
    INSPECT_CACHE_FLUSH_EVERY,
    INSPECT_DELAY,
    INSPECT_MAX_CALLS,
    INSPECT_MAX_QPS,
    INSPECT_RETRIES,
    INSPECT_TIMEOUT,
    INSPECT_TTL_OK_DAYS,
    INSPECT_WORKERS,
)
from core.classifier import classify
from core.ratelimit import TokenBucket
from core.urls import build_site_url, normalize_domain
from googleapiclient.errors import HttpError

# Http por thread. O pool reaproveita threads, então cada uma monta o seu
# uma vez só e reusa a conexão nas chamadas seguintes.
_local = threading.local()


def _thread_http(credentials):
    """Devolve (criando na primeira vez) o httplib2.Http desta thread."""
    import google_auth_httplib2
    import httplib2

    chave = id(credentials)
    if getattr(_local, "chave", None) != chave:
        _local.http = google_auth_httplib2.AuthorizedHttp(
            credentials, http=httplib2.Http(timeout=INSPECT_TIMEOUT)
        )
        _local.chave = chave
    return _local.http


def _erro_resultado(url: str, verdict: str, coverage: str) -> dict:
    """Monta o dict de resultado para um caso sem dado da API."""
    return {
        "url": url,
        "verdict": verdict,
        "category": classify(verdict),
        "coverageState": coverage,
        "lastCrawlTime": "",
    }


def _inspect_one(service, site_url: str, url: str, http) -> tuple[dict, bool]:
    """
    Inspeciona uma URL. Retorna (resultado, houve_erro_de_api).

    Resultados com erro não são cacheados — serão retentados na próxima
    execução. Esse comportamento vem do código sequencial e é mantido.
    """
    try:
        request = (
            service.urlInspection()
            .index()
            .inspect(body={"inspectionUrl": url, "siteUrl": site_url})
        )
        # num_retries liga o backoff exponencial nativo do cliente Google para
        # 429/500/502/503/504 — indispensável com concorrência, que torna o
        # 429 bem mais provável do que no modo sequencial.
        if http is not None:
            response = request.execute(http=http, num_retries=INSPECT_RETRIES)
        else:
            response = request.execute(num_retries=INSPECT_RETRIES)

        index_result = response.get("inspectionResult", {}).get("indexStatusResult", {})
        return (
            {
                "url": url,
                "verdict": index_result.get("verdict", "VERDICT_UNSPECIFIED"),
                "category": classify(index_result.get("verdict", "VERDICT_UNSPECIFIED")),
                "coverageState": index_result.get("coverageState", ""),
                "lastCrawlTime": index_result.get("lastCrawlTime", ""),
            },
            False,
        )

    except HttpError as exc:
        print(f"[inspector] ERRO HTTP em {url}: {exc.status_code} — {exc.reason}")
        return (
            _erro_resultado(url, "VERDICT_UNSPECIFIED", f"http_error_{exc.status_code}"),
            True,
        )

    except Exception as exc:  # noqa: BLE001
        print(f"[inspector] ERRO inesperado em {url}: {exc}")
        return _erro_resultado(url, "VERDICT_UNSPECIFIED", "fetch_error"), True


def inspect_urls(
    service,
    domain: str,
    urls: list[str],
    use_cache: bool = True,
    workers: int | None = None,
    credentials=None,
    max_calls: int | None = None,
    ttl_ok_days: int | None = None,
) -> list[dict]:
    """
    Para cada URL da lista, chama a URL Inspection API e retorna uma lista
    de dicts com os campos: url, verdict, category, coverageState,
    lastCrawlTime — SEMPRE na mesma ordem da lista de entrada, mesmo com o
    pool de threads.

    Parâmetros:
        service      — cliente autenticado da GSC API
        domain       — domínio ou sc-domain: a inspecionar
        urls         — lista de URLs a inspecionar
        use_cache    — se True (padrão), utiliza cache em disco e pula URLs já
                       inspecionadas. Use False (--no-cache) para forçar
                       chamadas frescas à API.
        workers      — threads simultâneas (padrão: config.INSPECT_WORKERS).
                       1 força o modo sequencial com INSPECT_DELAY.
        credentials  — objeto Credentials (core.auth.load_credentials()).
                       OBRIGATÓRIO para o modo paralelo: sem ele não há como
                       dar um Http por thread, e compartilhar o do service
                       corromperia as respostas. Ausente → cai no sequencial.
        max_calls    — teto de chamadas de API nesta execução (padrão:
                       config.INSPECT_MAX_CALLS). URLs além do teto voltam
                       como categoria "unknown" com coverageState
                       "quota_guard_skip", nunca como se tivessem sido lidas.
        ttl_ok_days  — janela, em dias, para reaproveitar resultados PASS de
                       execuções anteriores (padrão: config.INSPECT_TTL_OK_DAYS;
                       0 desliga).

    Comportamento do cache:
        - Resultados bem-sucedidos vão para
          relatorios/{domain}/.cache/inspect_YYYY-MM-DD.json
        - O arquivo do dia vale 24 h para qualquer veredito; dias anteriores,
          só para PASS, dentro de ttl_ok_days
        - Gravação em lote a cada INSPECT_CACHE_FLUSH_EVERY resultados (uma
          execução interrompida continua não perdendo tudo)
        - Erros de API NUNCA são cacheados
    """
    from core.cache import load_inspect_window, set_inspect_cache_bulk

    site_url = build_site_url(domain)
    cache_site = normalize_domain(domain)
    today_str = date.today().isoformat()
    total = len(urls)

    if workers is None:
        workers = INSPECT_WORKERS
    if max_calls is None:
        max_calls = INSPECT_MAX_CALLS
    if ttl_ok_days is None:
        ttl_ok_days = INSPECT_TTL_OK_DAYS

    # ── Fase 1: o que já está em cache (uma leitura de disco, não N) ────────
    resultados: list[dict | None] = [None] * total
    pendentes: list[tuple[int, str]] = []

    if use_cache:
        janela = load_inspect_window(cache_site, today_str, ttl_ok_days=ttl_ok_days)
    else:
        janela = {}

    for idx, url in enumerate(urls):
        cached = janela.get(url)
        if cached is not None:
            resultados[idx] = cached
        else:
            pendentes.append((idx, url))

    acertos = total - len(pendentes)
    if acertos:
        print(f"[inspector] {acertos}/{total} URL(s) vieram do cache.")

    # ── Fase 2: freio de cota ───────────────────────────────────────────────
    if max_calls is not None and len(pendentes) > max_calls:
        cortadas = pendentes[max_calls:]
        pendentes = pendentes[:max_calls]
        print(
            f"[inspector] AVISO: {len(cortadas)} URL(s) NAO foram inspecionadas — "
            f"o freio de cota (max_calls={max_calls}) foi atingido. "
            f"A cota da URL Inspection e de 2.000/dia POR SITE."
        )
        for idx, url in cortadas:
            resultados[idx] = _erro_resultado(url, "VERDICT_UNSPECIFIED", "quota_guard_skip")

    if not pendentes:
        return [r for r in resultados if r is not None]

    # ── Fase 3: decide sequencial x paralelo ────────────────────────────────
    # Sem credenciais não dá para montar um Http por thread, e reusar o do
    # service entre threads devolve resposta trocada em silêncio. Preferimos
    # ser lentos a ser errados.
    paralelo = workers > 1 and credentials is not None
    if workers > 1 and credentials is None:
        print(
            "[inspector] Sem credenciais para o modo paralelo "
            "(core.auth.load_credentials) — seguindo em modo sequencial."
        )
    if paralelo:
        # Falha cedo e de forma legível se a dependência não estiver instalada,
        # em vez de 874 threads errando uma a uma.
        try:
            import google_auth_httplib2  # noqa: F401
            import httplib2  # noqa: F401
        except ImportError as exc:
            print(f"[inspector] {exc} — modo paralelo indisponivel, seguindo sequencial.")
            paralelo = False

    if paralelo:
        from core.auth import refresh_if_needed

        # Renova ANTES do pool: refresh concorrente é corrida (ver docstring).
        try:
            refresh_if_needed(credentials)
        except Exception as exc:  # noqa: BLE001
            print(f"[inspector] AVISO: nao foi possivel renovar o token antes do pool: {exc}")

    # ── Fase 4: execução ────────────────────────────────────────────────────
    lock = threading.Lock()
    por_gravar: dict[str, dict] = {}
    concluidas = [0]
    inicio = time.monotonic()

    def _finaliza(idx: int, url: str, resultado: dict, erro: bool) -> None:
        """Registra um resultado, atualiza o progresso e grava o cache em lote."""
        nonlocal por_gravar
        resultados[idx] = resultado
        with lock:
            concluidas[0] += 1
            feitas = concluidas[0]
            if use_cache and not erro:
                por_gravar[url] = resultado
            despejar = None
            if use_cache and len(por_gravar) >= INSPECT_CACHE_FLUSH_EVERY:
                despejar, por_gravar = por_gravar, {}
        print(f"[inspector] ({feitas}/{len(pendentes)}) {url}")
        if despejar:
            set_inspect_cache_bulk(cache_site, today_str, despejar)

    if paralelo:
        bucket = TokenBucket(rate=INSPECT_MAX_QPS)
        print(
            f"[inspector] Inspecionando {len(pendentes)} URL(s) com {workers} thread(s), "
            f"teto de {INSPECT_MAX_QPS:.0f} req/s (~{INSPECT_MAX_QPS * 60:.0f} QPM "
            f"de 600 permitidos)."
        )

        def _tarefa(item: tuple[int, str]) -> None:
            idx, url = item
            try:
                bucket.acquire()
                http = _thread_http(credentials)
            except Exception as exc:  # noqa: BLE001
                # Uma falha aqui (ex.: montar o Http da thread) não pode
                # derrubar o pool inteiro e perder o que já foi inspecionado.
                print(f"[inspector] ERRO ao preparar a thread para {url}: {exc}")
                _finaliza(
                    idx, url, _erro_resultado(url, "VERDICT_UNSPECIFIED", "thread_error"), True
                )
                return
            resultado, erro = _inspect_one(service, site_url, url, http)
            _finaliza(idx, url, resultado, erro)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_tarefa, pendentes))
    else:
        print(f"[inspector] Inspecionando {len(pendentes)} URL(s) em modo sequencial.")
        for ordem, (idx, url) in enumerate(pendentes):
            resultado, erro = _inspect_one(service, site_url, url, None)
            _finaliza(idx, url, resultado, erro)
            if ordem < len(pendentes) - 1:
                time.sleep(INSPECT_DELAY)

    # Último lote: o que não fechou um flush completo.
    if use_cache and por_gravar:
        set_inspect_cache_bulk(cache_site, today_str, por_gravar)

    decorrido = time.monotonic() - inicio
    if decorrido > 0 and pendentes:
        print(
            f"[inspector] {len(pendentes)} chamada(s) em {decorrido:.1f}s "
            f"({len(pendentes) / decorrido * 60:.0f} QPM)."
        )

    # resultados está completo e na ordem de entrada: nenhum None sobra, mas o
    # filtro protege o relatório caso uma tarefa morra de forma inesperada.
    return [r for r in resultados if r is not None]
