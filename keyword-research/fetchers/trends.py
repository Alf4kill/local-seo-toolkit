"""
trends.py — Stage 1 seed expansion via Google Trends (pytrends, optional).

pytrends is an UNOFFICIAL scraper that breaks periodically — same defensive
posture as gsc-monitor/fetchers/trends_fetcher.py: optional import, per-seed
cache, per-seed exception isolation, never crash. Trends values are relative
interest (normalized 0-100), NEVER search volume — every emitted row carries
that warning in `notes` (repo honesty rule).
"""

import time
from datetime import date

from config import TRENDS_DELAY_S, TRENDS_GEO, TTL_TRENDS_HOURS
from core.cache import _safe_key, get_cached, set_cached

try:
    from pytrends.request import TrendReq

    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False

NOTES_WARNING = "interesse relativo — NAO e volume"


def _related_for_seed(pytrends, seed: str, geo: str) -> dict:
    """Fetch related queries for one seed. Returns {"top": [...], "rising": [...]}."""
    pytrends.build_payload([seed], cat=0, timeframe="today 12-m", geo=geo, gprop="")
    related = pytrends.related_queries()
    data = {"top": [], "rising": []}
    seed_data = related.get(seed) or {}
    for kind in ("top", "rising"):
        df = seed_data.get(kind)
        if df is not None and not df.empty and "query" in df.columns:
            data[kind] = [q for q in df["query"].tolist() if isinstance(q, str) and q.strip()]
    return data


def fetch_related_queries(
    seeds: list[str],
    project: str,
    geo: str = TRENDS_GEO,
    use_cache: bool = True,
    delay: float = TRENDS_DELAY_S,
) -> list[dict]:
    """Harvest top + rising related queries for each seed as Stage 1 rows.

    Returns rows {keyword, source: "trends-top"|"trends-rising", seed,
    date_collected, notes}. Any failure yields nothing for that seed (with a
    printed warning) and is never cached — a discovery run cannot crash here.
    """
    if not PYTRENDS_AVAILABLE:
        print(
            "[trends] pytrends nao instalado — fonte ignorada. "
            "Para usar: pip install pytrends==4.9.2"
        )
        return []
    if not seeds:
        return []

    today = date.today().isoformat()
    rows: list[dict] = []
    # No retries= param: pytrends is incompatible with urllib3 v2 there; the
    # per-seed except already isolates network failures.
    pytrends = TrendReq(hl="pt-BR", tz=180, timeout=(10, 30))

    for seed in seeds:
        key = f"trends_related_{_safe_key(seed)}_{geo}"
        data = get_cached(project, key, TTL_TRENDS_HOURS) if use_cache else None
        if data is not None:
            print(f"[trends] [CACHE] '{seed}'")
        else:
            print(f"[trends] Buscando related queries: '{seed}'...")
            try:
                data = _related_for_seed(pytrends, seed, geo)
                if use_cache:
                    set_cached(project, key, data)
            except Exception as exc:  # noqa: BLE001 — pytrends (unofficial) raises many types; isolate per seed
                print(f"[trends] ERRO para '{seed}': {exc}")
                data = {"top": [], "rising": []}
            time.sleep(delay)

        for kind in ("top", "rising"):
            for q in data.get(kind, []):
                rows.append(
                    {
                        "keyword": q,
                        "source": f"trends-{kind}",
                        "seed": seed,
                        "date_collected": today,
                        "notes": NOTES_WARNING,
                    }
                )

    print(f"[trends] {len(rows)} keywords de related queries.")
    return rows
