"""Tests for core/keyword_map.py — markdown parsing + graceful degradation."""

from core.keyword_map import load_keyword_map

FIXTURE_MD = """\
# Keyword map — seotecnico.dev.br

| Keyword | Artigo | Status |
|---------|--------|--------|
| next.js seo | /posts/next-seo | publicado |
| Configuração de sitemap | /posts/sitemap | rascunho |

Backlog:

- core web vitals no next.js
* renderização no servidor

Também cobrimos `hidratação seletiva` no capítulo 3.
"""


def test_parses_tables_bullets_and_inline_code(tmp_path):
    path = tmp_path / "keyword-map.md"
    path.write_text(FIXTURE_MD, encoding="utf-8")
    keys = load_keyword_map(str(path))
    assert "next.js seo" in keys
    assert "configuracao de sitemap" in keys  # normalized (accent-stripped)
    assert "core web vitals no next.js" in keys
    assert "renderizacao no servidor" in keys
    assert "hidratacao seletiva" in keys


def test_table_header_not_treated_as_keyword(tmp_path):
    path = tmp_path / "keyword-map.md"
    path.write_text(FIXTURE_MD, encoding="utf-8")
    keys = load_keyword_map(str(path))
    assert "keyword" not in keys


def test_missing_file_returns_empty_set():
    assert load_keyword_map("E:/nao/existe/keyword-map.md") == set()


def test_none_path_returns_empty_set():
    assert load_keyword_map(None) == set()
