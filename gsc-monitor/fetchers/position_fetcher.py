"""
position_fetcher.py — Consulta a Search Analytics API do Google Search Console.
Retorna cliques, impressões, CTR e posição média por URL.
Suporta cache em disco para evitar rechamadas desnecessárias.
"""

from datetime import date, timedelta

from config import DAYS_BACK, GSC_DELAY_DAYS, ROW_LIMIT
from core.urls import build_site_url, normalize_domain
from googleapiclient.errors import HttpError


def _build_date_range(days_back: int = DAYS_BACK) -> tuple[str, str]:
    """
    Retorna (start_date, end_date) como strings ISO 8601.
    O GSC tem delay de ~2-3 dias, então end_date = hoje - 3 dias.
    """
    end = date.today() - timedelta(days=GSC_DELAY_DAYS)
    start = end - timedelta(days=days_back)
    return start.isoformat(), end.isoformat()


def fetch_positions(
    service,
    domain: str,
    sitemap_urls: list[str],
    use_cache: bool = True,
    days_back: int = DAYS_BACK,
) -> dict:
    """
    Consulta a Search Analytics API e cruza os resultados com as URLs do sitemap.

    Parâmetros:
        service       — cliente autenticado da GSC API (de auth.build_service)
        domain        — domínio ou sc-domain: a consultar
        sitemap_urls  — lista de URLs extraídas do sitemap.xml
        use_cache     — se True (padrão), utiliza cache em disco para o período.
                        Use False (--no-cache) para forçar chamada fresca à API.
        days_back     — janela retroativa em dias (padrão: config.DAYS_BACK).
                        O Plano de Poda usa janela longa (até ~16 meses, o
                        máximo do GSC) para enxergar URLs antigas.

    Comportamento do cache:
        - A resposta completa da API (dict URL → métricas) é cacheada em
          relatorios/{domain}/.cache/posicao_START_END.json
        - TTL: 72 horas
        - O cruzamento com o sitemap é sempre refeito em memória

    Retorna dict com:
    {
        "start_date": "YYYY-MM-DD",
        "end_date":   "YYYY-MM-DD",
        "country":    "global",
        "rows": [
            {
                "url":         str,
                "position":    float | None,
                "clicks":      int,
                "impressions": int,
                "ctr":         float,   # percentual (ex: 4.75)
                "has_data":    bool,
            },
            ...
        ],
        "ghost_rows": [              # URLs com dados no GSC mas FORA do sitemap
            {"url", "clicks", "impressions", "ctr", "position"},
            ...                      # base do Plano de Poda (core/pruning.py)
        ]
    }

    Ordenação: URLs com dados primeiro (por posição crescente), sem dados ao final.
    """
    from core.cache import get_posicao_cache, set_posicao_cache

    site_url = build_site_url(domain)
    cache_site = normalize_domain(domain)
    start_date, end_date = _build_date_range(days_back)

    print(f"[position_fetcher] Período  : {start_date}  a  {end_date}  ({days_back} dias)")
    print("[position_fetcher] País     : Global (sem filtro)")

    # ── Tentativa de cache hit ──────────────────────────────────────────────
    api_data = None
    if use_cache:
        api_data = get_posicao_cache(cache_site, start_date, end_date)
        if api_data is not None:
            print(f"[position_fetcher] [CACHE] Dados carregados do cache ({len(api_data)} URLs).")

    # ── Chamada à API (somente se cache miss ou --no-cache) ─────────────────
    if api_data is None:
        print("[position_fetcher] Consultando Search Analytics API...")

        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["page"],
            "rowLimit": ROW_LIMIT,
            "dataState": "final",
        }

        try:
            response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        except HttpError as exc:
            print(f"[position_fetcher] ERRO HTTP: {exc.status_code} — {exc.reason}")
            raise

        api_data = {}
        for row in response.get("rows", []):
            url = row["keys"][0]
            api_data[url] = {
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": round(row.get("ctr", 0.0) * 100, 2),
                "position": round(row.get("position", 0.0), 1),
            }

        if use_cache:
            set_posicao_cache(cache_site, start_date, end_date, api_data)

    print(f"[position_fetcher] URLs com dados no GSC  : {len(api_data)}")
    print(f"[position_fetcher] URLs no sitemap        : {len(sitemap_urls)}")

    # ── Cruzamento sitemap × API (sempre em memória, nunca cacheado) ─────────
    rows = []
    for url in sitemap_urls:
        if url in api_data:
            d = api_data[url]
            rows.append(
                {
                    "url": url,
                    "position": d["position"],
                    "clicks": d["clicks"],
                    "impressions": d["impressions"],
                    "ctr": d["ctr"],
                    "has_data": True,
                }
            )
        else:
            rows.append(
                {
                    "url": url,
                    "position": None,
                    "clicks": 0,
                    "impressions": 0,
                    "ctr": 0.0,
                    "has_data": False,
                }
            )

    rows.sort(key=lambda r: (not r["has_data"], r["position"] or 9999))

    # URLs fantasma: têm dados no GSC mas estão fora do sitemap. Na convenção
    # de sitemap completo, são páginas antigas — insumo do Plano de Poda.
    from core.pruning import find_ghost_urls

    ghost_rows = find_ghost_urls(api_data, sitemap_urls)
    if ghost_rows:
        print(f"[position_fetcher] URLs fora do sitemap (antigas?): {len(ghost_rows)}")

    return {
        "start_date": start_date,
        "end_date": end_date,
        "country": "global",
        "rows": rows,
        "ghost_rows": ghost_rows,
    }


def fetch_query_positions(
    service,
    domain: str,
    use_cache: bool = True,
    days_back: int = DAYS_BACK,
) -> list:
    """
    Consulta Search Analytics com dimensões [query, page] para análise de canibalização.

    Retorna lista de dicts: {"query", "url", "clicks", "impressions", "ctr", "position"}
    Ordenados por query ASC, posição ASC.

    Cache: posicao_queries_{start}_{end}.json — TTL 72h (mesmo do posicionamento).
    """
    from core.cache import get_query_cache, set_query_cache

    site_url = build_site_url(domain)
    cache_site = normalize_domain(domain)
    start_date, end_date = _build_date_range(days_back)

    print("[position_fetcher] Consultando queries (canibalização)...")

    if use_cache:
        cached = get_query_cache(cache_site, start_date, end_date)
        if cached is not None:
            print(f"[position_fetcher] [CACHE] Queries carregadas do cache ({len(cached)} linhas).")
            return cached

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["query", "page"],
        "rowLimit": ROW_LIMIT,
        "dataState": "final",
    }

    try:
        response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    except HttpError as exc:
        print(f"[position_fetcher] ERRO HTTP ao buscar queries: {exc.status_code} — {exc.reason}")
        raise

    rows = []
    for row in response.get("rows", []):
        rows.append(
            {
                "query": row["keys"][0],
                "url": row["keys"][1],
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": round(row.get("ctr", 0.0) * 100, 2),
                "position": round(row.get("position", 0.0), 1),
            }
        )

    rows.sort(key=lambda r: (r["query"], r["position"]))

    if use_cache:
        set_query_cache(cache_site, start_date, end_date, rows)

    print(f"[position_fetcher] {len(rows)} combinações query+URL obtidas.")
    return rows


# ---------------------------------------------------------------------------
# P5 — Tendências first-party via dimensão `date` do GSC
# ---------------------------------------------------------------------------
#
# Substitui o pytrends como fonte padrão: oficial, sem rate-limit, e mede a
# demanda do PRÓPRIO site (impressões/dia na busca) em vez do índice global
# 0–100 do Google Trends. O pytrends continua disponível como legado
# (--trends-source pytrends).

DAYS_BACK_TRENDS = 90  # janela das tendências (≈ 3 meses → terços de ~30 dias)


def fetch_date_trends(
    service,
    domain: str,
    use_cache: bool = True,
    days_back: int = DAYS_BACK_TRENDS,
) -> dict:
    """
    Consulta a Search Analytics em duas passadas:
      1. dimensions ["date"]          — série diária do site inteiro
      2. dimensions ["date","query"]  — série diária por query

    Cache: date_trends_{start}_{end}.json — TTL 24h (core.cache).

    Retorna (bruto — a classificação fica em core.analytics.compute_date_trends):
    {
        "start_date": str, "end_date": str,
        "site_rows":  [{"date", "clicks", "impressions"}, ...],
        "query_rows": [{"date", "query", "clicks", "impressions"}, ...],
    }
    """
    from core.cache import get_date_trends_cache, set_date_trends_cache

    site_url = build_site_url(domain)
    cache_site = normalize_domain(domain)
    start_date, end_date = _build_date_range(days_back)

    if use_cache:
        cached = get_date_trends_cache(cache_site, start_date, end_date)
        if cached is not None:
            print(
                f"[position_fetcher] [CACHE] Tendências por data carregadas "
                f"({len(cached.get('site_rows', []))} dias)."
            )
            return cached

    print(f"[position_fetcher] Consultando tendências por data ({start_date} a {end_date})...")

    def _query(dimensions: list) -> list:
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "rowLimit": ROW_LIMIT,
            "dataState": "final",
        }
        try:
            response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        except HttpError as exc:
            print(f"[position_fetcher] ERRO HTTP em {dimensions}: {exc.status_code} — {exc.reason}")
            raise
        return response.get("rows", [])

    site_rows = [
        {
            "date": row["keys"][0],
            "clicks": int(row.get("clicks", 0)),
            "impressions": int(row.get("impressions", 0)),
        }
        for row in _query(["date"])
    ]

    query_rows = [
        {
            "date": row["keys"][0],
            "query": row["keys"][1],
            "clicks": int(row.get("clicks", 0)),
            "impressions": int(row.get("impressions", 0)),
        }
        for row in _query(["date", "query"])
    ]

    data = {
        "start_date": start_date,
        "end_date": end_date,
        "site_rows": site_rows,
        "query_rows": query_rows,
    }

    if use_cache:
        set_date_trends_cache(cache_site, start_date, end_date, data)

    print(f"[position_fetcher] {len(site_rows)} dias; {len(query_rows)} linhas date×query.")
    return data
