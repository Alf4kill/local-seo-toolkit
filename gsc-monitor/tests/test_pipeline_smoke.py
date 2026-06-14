"""
test_pipeline_smoke.py — Teste de fumaça do pipeline CLI (posicao.run_pipeline).

Mocka TODA a IO (auth, sitemap, Search Analytics, storage, reporters) — rede zero —
e verifica duas coisas:
  1. o resumo retornado tem a forma/valores esperados (a espinha do pipeline);
  2. cada toggle de relatório (queries/trends/nlp/content/excel/csv/txt) roteia
     para a sub-função correta.

Serve de rede de segurança para refatorações do pipeline (ex.: a introdução de
ReportOptions): se um toggle deixar de ser lido/encaminhado, um teste quebra.
"""

from unittest.mock import MagicMock

import posicao
import pytest


@pytest.fixture
def mocks(monkeypatch):
    """Substitui toda a IO de run_pipeline por mocks; devolve os espiões."""
    m: dict = {}

    report = {
        "urls": [{"url": "https://x/a"}],
        "summary": {
            "total_urls_sitemap": 1,
            "urls_with_data": 1,
            "avg_position_site": 5.0,
            "avg_ctr_percent": 3.0,
        },
    }

    # --- Espinha (sempre executada) ---
    monkeypatch.setattr(posicao, "build_service", lambda: object())
    monkeypatch.setattr(
        posicao, "normalize_domain", lambda s: s.replace("https://", "").rstrip("/")
    )
    monkeypatch.setattr(posicao, "fetch_urls", lambda domain: ["https://x/a"])
    monkeypatch.setattr(
        posicao,
        "fetch_positions",
        lambda *a, **k: {
            "start_date": "2026-01-01",
            "end_date": "2026-01-30",
            "rows": [{"url": "https://x/a"}],
        },
    )
    monkeypatch.setattr(posicao, "build_position_report", lambda *a, **k: report)
    monkeypatch.setattr(posicao, "save_position_report", lambda *a, **k: None)
    monkeypatch.setattr(posicao, "print_position_report", lambda *a, **k: None)
    monkeypatch.setattr(posicao, "load_latest_consolidated", lambda *a, **k: None)
    monkeypatch.setattr(
        posicao, "calculate_health_score", lambda *a, **k: {"score": 75.0, "grade": "Bom"}
    )
    monkeypatch.setattr(posicao, "print_health_score", lambda *a, **k: None)
    monkeypatch.setattr(posicao, "detect_orphan_pages", lambda *a, **k: [])
    monkeypatch.setattr(posicao, "print_orphan_pages", lambda *a, **k: None)
    monkeypatch.setattr(posicao, "load_api_key", lambda *a, **k: "")
    monkeypatch.setattr(posicao, "search_entity", lambda *a, **k: {})
    monkeypatch.setattr(posicao, "print_kg_result", lambda *a, **k: None)
    monkeypatch.setattr(posicao, "append_historico_posicao", lambda *a, **k: None)
    monkeypatch.setattr(
        posicao, "load_historico_posicao", lambda *a, **k: {"snapshots": [{"date": "2026-01-30"}]}
    )
    monkeypatch.setattr(posicao, "save_dashboard", lambda *a, **k: None)

    # Lazy: core.content_quality (tracking) + reporters.html_reporter (dashboard)
    import core.content_quality as cq
    import reporters.html_reporter as html

    monkeypatch.setattr(cq, "build_content_tracking", lambda *a, **k: {})
    monkeypatch.setattr(cq, "print_content_tracking", lambda *a, **k: None)
    monkeypatch.setattr(html, "generate_dashboard", lambda *a, **k: "<html></html>")

    # --- Sub-funções controladas por toggle (espiões) ---
    m["detect_cannibalization"] = MagicMock(return_value=[])
    monkeypatch.setattr(posicao, "detect_cannibalization", m["detect_cannibalization"])
    monkeypatch.setattr(posicao, "print_cannibalization", lambda *a, **k: None)

    m["save_position_txt"] = MagicMock()
    monkeypatch.setattr(posicao, "save_position_txt", m["save_position_txt"])
    m["save_csv_posicao"] = MagicMock()
    monkeypatch.setattr(posicao, "save_csv_posicao", m["save_csv_posicao"])
    m["save_excel_report"] = MagicMock()
    monkeypatch.setattr(posicao, "save_excel_report", m["save_excel_report"])

    import fetchers.position_fetcher as pf

    m["fetch_query_positions"] = MagicMock(
        return_value=[{"query": "q", "page": "https://x/a", "position": 3, "impressions": 100}]
    )
    monkeypatch.setattr(pf, "fetch_query_positions", m["fetch_query_positions"])
    m["fetch_date_trends"] = MagicMock(return_value={})
    monkeypatch.setattr(pf, "fetch_date_trends", m["fetch_date_trends"])

    import core.analytics as an

    m["compute_date_trends"] = MagicMock(return_value={})
    monkeypatch.setattr(an, "compute_date_trends", m["compute_date_trends"])
    monkeypatch.setattr(an, "print_date_trends", lambda *a, **k: None)

    import reporters.excel_reporter as xl

    m["generate_excel"] = MagicMock(return_value=object())
    monkeypatch.setattr(xl, "generate_excel", m["generate_excel"])

    import fetchers.content_fetcher as cf

    m["analyze_content"] = MagicMock(return_value={"https://x/a": {"verdict": "ok"}})
    monkeypatch.setattr(cf, "analyze_opportunity_content_quality", m["analyze_content"])

    return m


def test_default_returns_summary(mocks):
    out = posicao.run_pipeline("https://x.com.br")
    assert out["site"] == "x.com.br"
    assert out["health_score"] == 75.0
    assert out["health_grade"] == "Bom"
    assert out["urls_total"] == 1
    assert out["urls_with_data"] == 1
    # queries off → sem canibalização
    assert out["cannibalization_groups"] is None
    mocks["detect_cannibalization"].assert_not_called()


def test_queries_triggers_cannibalization(mocks):
    posicao.run_pipeline("https://x.com.br", posicao.ReportOptions(queries=True))
    mocks["fetch_query_positions"].assert_called_once()
    mocks["detect_cannibalization"].assert_called_once()


def test_excel_toggle(mocks):
    posicao.run_pipeline("https://x.com.br", posicao.ReportOptions(excel=True))
    mocks["generate_excel"].assert_called_once()
    mocks["save_excel_report"].assert_called_once()


def test_csv_and_txt_toggles(mocks):
    posicao.run_pipeline("https://x.com.br", posicao.ReportOptions(csv=True, txt=True))
    mocks["save_csv_posicao"].assert_called_once()
    mocks["save_position_txt"].assert_called_once()


def test_trends_gsc_toggle(mocks):
    posicao.run_pipeline("https://x.com.br", posicao.ReportOptions(trends=True))
    mocks["fetch_date_trends"].assert_called_once()


def test_content_toggle_populates_verdicts(mocks):
    out = posicao.run_pipeline("https://x.com.br", posicao.ReportOptions(content=True))
    mocks["analyze_content"].assert_called_once()
    assert out["content_verdicts"] == {"ok": 1}
