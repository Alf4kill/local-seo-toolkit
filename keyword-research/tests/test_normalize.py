"""Tests for core/normalize.py — normalization key and dedupe."""

from core.normalize import dedupe_rows, normalize_key


def test_normalize_strips_accents_and_case():
    assert normalize_key("Configuração SSR") == "configuracao ssr"
    assert normalize_key("POR QUE usar Next.js?") == "por que usar next.js?"
    assert normalize_key("ç Ã É ô") == "c a e o"


def test_normalize_collapses_whitespace():
    assert normalize_key("  next.js   seo \t dicas ") == "next.js seo dicas"


def test_accent_variants_share_the_same_key():
    assert normalize_key("otimização") == normalize_key("otimizacao")


def test_dedupe_keeps_first_original_form():
    rows = [
        {"keyword": "otimização de imagens", "source": "autocomplete"},
        {"keyword": "otimizacao de imagens", "source": "gsc-weak"},
        {"keyword": "OTIMIZAÇÃO DE IMAGENS", "source": "trends-top"},
    ]
    result = dedupe_rows(rows)
    assert len(result) == 1
    assert result[0]["keyword"] == "otimização de imagens"
    assert result[0]["source"] == "autocomplete"


def test_dedupe_preserves_distinct_keywords_in_order():
    rows = [
        {"keyword": "kw b"},
        {"keyword": "kw a"},
        {"keyword": "kw b"},
    ]
    assert [r["keyword"] for r in dedupe_rows(rows)] == ["kw b", "kw a"]


def test_dedupe_drops_empty_keywords():
    rows = [{"keyword": ""}, {"keyword": "   "}, {"notes": "sem keyword"}]
    assert dedupe_rows(rows) == []
