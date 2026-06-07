"""
inspector.py — Chamadas à URL Inspection API do Google Search Console.
Respeita o rate limit com delay entre requisições e trata erros por URL.
Suporta cache em disco para evitar rechamadas desnecessárias (cota: 2000/dia).
"""

import time
from datetime import date
from googleapiclient.errors import HttpError

from core.classifier import classify
from core.urls import build_site_url, normalize_domain

DELAY_BETWEEN_REQUESTS = 0.5  # segundos — evita burst na quota (2000 req/dia)


def inspect_urls(
    service,
    domain: str,
    urls: list[str],
    use_cache: bool = True,
) -> list[dict]:
    """
    Para cada URL da lista, chama a URL Inspection API e retorna uma lista
    de dicts com os campos: url, verdict, category, coverageState, lastCrawlTime.

    Parâmetros:
        service    — cliente autenticado da GSC API
        domain     — domínio ou sc-domain: a inspecionar
        urls       — lista de URLs a inspecionar
        use_cache  — se True (padrão), utiliza cache em disco e pula URLs já
                     inspecionadas hoje. Use False (--no-cache) para forçar
                     chamadas frescas à API.

    Comportamento do cache:
        - Cada resultado bem-sucedido é salvo em
          relatorios/{domain}/.cache/inspect_YYYY-MM-DD.json
        - TTL: 24 horas
        - Erros de API (HttpError, exceções) NÃO são cacheados — serão
          retentados na próxima execução
    """
    from core.cache import get_inspect_cache, set_inspect_cache

    site_url   = build_site_url(domain)
    cache_site = normalize_domain(domain)
    today_str  = date.today().isoformat()
    results    = []
    total      = len(urls)

    for idx, url in enumerate(urls, start=1):

        # ── Tentativa de cache hit ──────────────────────────────────────────
        if use_cache:
            cached = get_inspect_cache(cache_site, today_str, url)
            if cached is not None:
                print(f"[inspector] ({idx}/{total}) [CACHE] {url}")
                results.append(cached)
                continue  # não chama a API nem dorme

        # ── Chamada à API ───────────────────────────────────────────────────
        print(f"[inspector] ({idx}/{total}) Inspecionando: {url}")

        try:
            response = (
                service.urlInspection()
                .index()
                .inspect(
                    body={
                        "inspectionUrl": url,
                        "siteUrl":       site_url,
                    }
                )
                .execute()
            )

            index_result  = (
                response.get("inspectionResult", {})
                .get("indexStatusResult", {})
            )
            verdict        = index_result.get("verdict",       "VERDICT_UNSPECIFIED")
            coverage_state = index_result.get("coverageState", "")
            last_crawl     = index_result.get("lastCrawlTime", "")
            api_error      = False

        except HttpError as exc:
            print(f"[inspector] ERRO HTTP em {url}: {exc.status_code} — {exc.reason}")
            verdict        = "VERDICT_UNSPECIFIED"
            coverage_state = f"http_error_{exc.status_code}"
            last_crawl     = ""
            api_error      = True

        except Exception as exc:  # noqa: BLE001
            print(f"[inspector] ERRO inesperado em {url}: {exc}")
            verdict        = "VERDICT_UNSPECIFIED"
            coverage_state = "fetch_error"
            last_crawl     = ""
            api_error      = True

        result = {
            "url":           url,
            "verdict":       verdict,
            "category":      classify(verdict),
            "coverageState": coverage_state,
            "lastCrawlTime": last_crawl,
        }
        results.append(result)

        # ── Salva no cache apenas resultados sem erro de API ────────────────
        if use_cache and not api_error:
            set_inspect_cache(cache_site, today_str, url, result)

        if idx < total:
            time.sleep(DELAY_BETWEEN_REQUESTS)

    return results
