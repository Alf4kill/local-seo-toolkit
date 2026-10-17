"""Tests for core/serp_analysis.py — pure SERP heuristics."""

from core.serp_analysis import analyze_serp, extract_top_domains, suggest_verdict

BIG = {"conversion.com.br", "rockcontent.com"}
DOCS = {"vercel.com", "nextjs.org", "web.dev"}
MARKERS = ["app router", "next 14", "2024", "2025"]


def _organic(domain, title, rank=None, type_="organic"):
    return {
        "type": type_,
        "domain": domain,
        "url": f"https://{domain}/x",
        "title": title,
        "rank_absolute": rank,
    }


def test_extract_only_organic_items_capped_at_top_n():
    serp = {
        "items": [
            _organic("a.com", "t1", 1),
            {"type": "people_also_ask", "title": "paa"},
            _organic("b.com", "t2", 3),
        ]
    }
    top = extract_top_domains(serp, top_n=1)
    assert [i["domain"] for i in top] == ["a.com"]


def test_extract_strips_www_and_lowercases():
    serp = {"items": [_organic("WWW.Exemplo.COM.br", "t", 1)]}
    assert extract_top_domains(serp)[0]["domain"] == "exemplo.com.br"


def test_extract_falls_back_to_url_netloc():
    serp = {"items": [{"type": "organic", "url": "https://www.site.dev/post", "title": "t"}]}
    assert extract_top_domains(serp)[0]["domain"] == "site.dev"


def test_extract_empty_serp():
    assert extract_top_domains({}) == []


def test_analyze_detects_players_docs_and_counts_slots():
    top = [
        _organic("vercel.com", "Docs"),
        _organic("vercel.com", "Outra pagina de docs"),
        _organic("rockcontent.com", "Guia SEO"),
        _organic("blog.dev.br", "Post"),
    ]
    analysis = analyze_serp(top, BIG, DOCS, MARKERS)
    assert analysis["big_players_present"] == ["rockcontent.com"]
    assert analysis["official_docs_present"] == ["vercel.com"]
    assert analysis["official_docs_count"] == 2  # slots, not distinct domains
    assert analysis["top_domains"][0] == "vercel.com"


def test_freshness_marker_is_accent_and_case_insensitive():
    top = [_organic("a.com", "Guia do APP ROUTER com otimização")]
    analysis = analyze_serp(top, BIG, DOCS, MARKERS)
    assert analysis["has_fresh_specific_content"] is True


def test_no_freshness_markers():
    top = [_organic("a.com", "SEO em 2019 com Pages Router")]
    analysis = analyze_serp(top, BIG, DOCS, MARKERS)
    assert analysis["has_fresh_specific_content"] is False


def test_verdict_target_now_without_fresh_content():
    verdict, motivo = suggest_verdict(
        {"has_fresh_specific_content": False, "official_docs_count": 5}
    )
    assert verdict == "target-now"
    assert "pos-2024" in motivo


def test_verdict_target_later_when_docs_dominate():
    verdict, motivo = suggest_verdict(
        {"has_fresh_specific_content": True, "official_docs_count": 3}
    )
    assert verdict == "target-later"
    assert "docs oficiais" in motivo


def test_verdict_target_later_manual_review_default():
    verdict, motivo = suggest_verdict(
        {"has_fresh_specific_content": True, "official_docs_count": 0}
    )
    assert verdict == "target-later"
    assert motivo == "revisar manualmente"
