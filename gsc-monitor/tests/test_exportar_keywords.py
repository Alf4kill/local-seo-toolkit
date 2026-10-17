"""Testes de exportar_keywords.py — lógica pura (sem service, sem rede)."""

from exportar_keywords import (
    aggregate_queries,
    build_weak_csv_rows,
    filter_url_rows,
    weak_queries,
)


def _row(query, url, clicks=0, impressions=0, position=None):
    return {
        "query": query,
        "url": url,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": 0.0,
        "position": position,
    }


# ---------------------------------------------------------------------------
# aggregate_queries
# ---------------------------------------------------------------------------


def test_aggregate_sums_metrics_and_keeps_best_position():
    rows = [
        _row("kw", "https://a", clicks=2, impressions=100, position=15.0),
        _row("kw", "https://b", clicks=1, impressions=50, position=8.0),
    ]
    agg = aggregate_queries(rows)
    assert len(agg) == 1
    assert agg[0]["clicks"] == 3
    assert agg[0]["impressions"] == 150
    assert agg[0]["position"] == 8.0
    assert agg[0]["url"] == "https://b"  # URL da linha mais bem posicionada


def test_aggregate_skips_rows_without_query():
    rows = [_row("", "https://a", impressions=10, position=12.0)]
    assert aggregate_queries(rows) == []


# ---------------------------------------------------------------------------
# weak_queries (limites: posição exatamente 10.0 e impressões 0 ficam de fora)
# ---------------------------------------------------------------------------


def test_weak_requires_position_above_10():
    agg = aggregate_queries(
        [
            _row("na primeira pagina", "https://a", impressions=100, position=10.0),
            _row("fraca", "https://b", impressions=100, position=10.1),
        ]
    )
    weak = weak_queries(agg)
    assert [r["query"] for r in weak] == ["fraca"]


def test_weak_requires_impressions():
    agg = aggregate_queries(
        [
            _row("sem demanda", "https://a", impressions=0, position=50.0),
            _row("com demanda", "https://b", impressions=1, position=50.0),
        ]
    )
    weak = weak_queries(agg)
    assert [r["query"] for r in weak] == ["com demanda"]


def test_weak_ignores_position_none():
    agg = [{"query": "sem posicao", "url": "", "clicks": 0, "impressions": 9, "position": None}]
    assert weak_queries(agg) == []


def test_weak_not_triggered_when_another_page_ranks_top10():
    # A query tem uma página em 15.0 e OUTRA em 4.0 — o site já ranqueia bem;
    # a agregação (melhor posição) impede o falso positivo.
    rows = [
        _row("kw forte", "https://fraca", impressions=200, position=15.0),
        _row("kw forte", "https://forte", impressions=300, position=4.0),
    ]
    assert weak_queries(aggregate_queries(rows)) == []


def test_weak_sorted_by_impressions_desc():
    agg = aggregate_queries(
        [
            _row("pouca", "https://a", impressions=10, position=20.0),
            _row("muita", "https://b", impressions=500, position=12.0),
        ]
    )
    assert [r["query"] for r in weak_queries(agg)] == ["muita", "pouca"]


# ---------------------------------------------------------------------------
# build_weak_csv_rows (contrato com o keyword-research)
# ---------------------------------------------------------------------------


def test_build_weak_csv_rows_format():
    weak = [
        {
            "query": "como fazer x",
            "url": "https://a/p",
            "clicks": 1,
            "impressions": 230,
            "position": 14.2,
        }
    ]
    rows = build_weak_csv_rows(weak, "2026-07-15")
    assert rows == [
        {
            "keyword": "como fazer x",
            "source": "gsc-weak",
            "seed": "",
            "date_collected": "2026-07-15",
            "notes": "pos=14.2;impr=230;url=https://a/p",
        }
    ]


# ---------------------------------------------------------------------------
# filter_url_rows (Stage 4)
# ---------------------------------------------------------------------------


def test_filter_url_rows_matches_trailing_slash_and_case():
    rows = [
        _row("q1", "https://site/post/", impressions=50, position=9.0),
        _row("q2", "HTTPS://site/post", impressions=80, position=12.0),
        _row("q3", "https://site/outro", impressions=999, position=3.0),
    ]
    matched = filter_url_rows(rows, "https://site/post")
    assert [r["query"] for r in matched] == ["q2", "q1"]  # impressões desc
