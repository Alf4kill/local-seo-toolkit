"""
serp_analysis.py — Stage 3 SERP analysis heuristics (pure logic).

Everything here produces SUGGESTIONS: the emitted verdict is
`verdict_sugerido` with a `motivo`, and the analyst gives the final call in
the editable review CSV — same honesty convention as gsc-monitor's poda/301
plans. The freshness heuristic looks at result TITLES only (honest label:
it cannot see actual publish dates).
"""

from urllib.parse import urlparse

from core.normalize import normalize_key


def extract_top_domains(serp_result: dict, top_n: int = 10) -> list[dict]:
    """Organic items only -> [{rank, domain, url, title}], first top_n."""
    out: list[dict] = []
    for item in serp_result.get("items") or []:
        if item.get("type") != "organic":
            continue
        url = item.get("url") or ""
        domain = (item.get("domain") or urlparse(url).netloc or "").lower()
        out.append(
            {
                "rank": item.get("rank_absolute") or item.get("rank_group") or len(out) + 1,
                "domain": domain.removeprefix("www."),
                "url": url,
                "title": item.get("title") or "",
            }
        )
        if len(out) >= top_n:
            break
    return out


def analyze_serp(
    top_items: list[dict],
    big_players: set[str],
    official_docs: set[str],
    freshness_markers: list[str],
) -> dict:
    """Aggregate signals from the top organic results.

    `official_docs_count` counts SLOTS (a docs domain twice = 2), which is
    what "the SERP is dominated by docs" actually means; the *_present lists
    are distinct domains for display.
    """
    domains = [i["domain"] for i in top_items]
    titles_norm = [normalize_key(i["title"]) for i in top_items]
    markers_norm = [normalize_key(m) for m in freshness_markers]
    return {
        "top_domains": domains,
        "big_players_present": sorted({d for d in domains if d in big_players}),
        "official_docs_present": sorted({d for d in domains if d in official_docs}),
        "official_docs_count": sum(1 for d in domains if d in official_docs),
        "has_fresh_specific_content": any(m in t for t in titles_norm for m in markers_norm),
    }


def suggest_verdict(analysis: dict) -> tuple[str, str]:
    """Heuristic verdict SUGGESTION (verdict, motivo) — analyst decides.

    Spec heuristic: no post-2024 framework-specific content anywhere in the
    top 10 -> "target-now" regardless of difficulty.
    """
    if not analysis.get("has_fresh_specific_content"):
        return "target-now", "sem conteudo pos-2024 especifico no top 10"
    if analysis.get("official_docs_count", 0) >= 3:
        return "target-later", "SERP dominada por docs oficiais"
    return "target-later", "revisar manualmente"
