"""Tests for descobrir.py — Stage 1 orchestration (expand_seed mocked)."""

import descobrir
import pytest
from core.storage import KEYWORD_CSV_COLUMNS, read_csv, write_csv
from descobrir import DiscoveryOptions, PipelineError, load_gsc_rows, load_seeds_file


def test_load_seeds_file(tmp_path):
    path = tmp_path / "seeds.txt"
    path.write_text("# comentario\nnext.js seo\n\n  core web vitals  \n", encoding="utf-8")
    assert load_seeds_file(str(path)) == ["next.js seo", "core web vitals"]


def test_load_seeds_file_missing_raises():
    with pytest.raises(PipelineError):
        load_seeds_file("nao_existe.txt")


def test_load_gsc_rows_valid(tmp_path):
    path = str(tmp_path / "gsc.csv")
    rows = [
        {
            "keyword": "como configurar sitemap",
            "source": "gsc-weak",
            "seed": "",
            "date_collected": "2026-07-15",
            "notes": "pos=14.2;impr=230;url=https://exemplo/post",
        }
    ]
    write_csv(path, KEYWORD_CSV_COLUMNS, rows)
    assert load_gsc_rows(path) == rows


def test_load_gsc_rows_missing_file_raises():
    with pytest.raises(PipelineError):
        load_gsc_rows("nao_existe.csv")


def test_load_gsc_rows_wrong_columns_raises(tmp_path):
    path = str(tmp_path / "ruim.csv")
    write_csv(path, ["query", "pos"], [{"query": "x", "pos": "12"}])
    with pytest.raises(PipelineError):
        load_gsc_rows(path)


def test_run_discovery_requires_seeds():
    with pytest.raises(PipelineError):
        descobrir.run_discovery("proj-desc", [])


def _fake_expand(rows_by_seed):
    def fake(seed, project, use_cache=True, delay=1.0, recursive=True):
        return rows_by_seed.get(seed, [])

    return fake


def test_run_discovery_dedupes_and_writes_csv(monkeypatch):
    rows_by_seed = {
        "seed a": [
            {
                "keyword": "kw único",
                "source": "autocomplete",
                "seed": "seed a",
                "date_collected": "2026-07-15",
                "notes": "seed",
            },
            {
                "keyword": "kw comum",
                "source": "autocomplete",
                "seed": "seed a",
                "date_collected": "2026-07-15",
                "notes": "letra:a",
            },
        ],
        "seed b": [
            # Accent variant of "kw único" — must dedupe, first form wins.
            {
                "keyword": "kw unico",
                "source": "autocomplete",
                "seed": "seed b",
                "date_collected": "2026-07-15",
                "notes": "seed",
            },
        ],
    }
    monkeypatch.setattr(descobrir, "expand_seed", _fake_expand(rows_by_seed))

    summary = descobrir.run_discovery("proj-desc", ["seed a", "seed b"])

    assert summary["keywords_total"] == 2
    assert summary["by_source"] == {"autocomplete": 2}
    saved = read_csv(summary["csv_path"])
    assert [r["keyword"] for r in saved] == ["kw único", "kw comum"]


def test_run_discovery_merges_gsc_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(descobrir, "expand_seed", _fake_expand({}))
    gsc_path = str(tmp_path / "gsc.csv")
    write_csv(
        gsc_path,
        KEYWORD_CSV_COLUMNS,
        [
            {
                "keyword": "query fraca",
                "source": "gsc-weak",
                "seed": "",
                "date_collected": "2026-07-15",
                "notes": "pos=15;impr=100;url=u",
            },
        ],
    )
    options = DiscoveryOptions(gsc_csv=gsc_path)
    summary = descobrir.run_discovery("proj-desc2", ["qualquer"], options)

    assert summary["by_source"] == {"gsc-weak": 1}
    saved = read_csv(summary["csv_path"])
    assert saved[0]["keyword"] == "query fraca"
    assert saved[0]["source"] == "gsc-weak"
