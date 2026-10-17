"""Tests for core/storage.py — path helpers and CSV round-trips."""

from core import storage


def test_safe_filename_strips_invalid_chars():
    assert storage._safe_filename("seotecnico.dev.br") == "seotecnico.dev.br"
    assert storage._safe_filename("a b/c:d") == "a_b_c_d"


def test_write_read_csv_roundtrip(tmp_path):
    path = str(tmp_path / "out.csv")
    header = ["keyword", "source", "notes"]
    rows = [
        {"keyword": "next.js seo", "source": "autocomplete", "notes": "letra:a"},
        {"keyword": "configuração ssr", "source": "gsc-weak", "notes": ""},
    ]
    storage.write_csv(path, header, rows)
    back = storage.read_csv(path)
    assert back == [
        {"keyword": "next.js seo", "source": "autocomplete", "notes": "letra:a"},
        {"keyword": "configuração ssr", "source": "gsc-weak", "notes": ""},
    ]


def test_write_csv_missing_columns_become_empty(tmp_path):
    path = str(tmp_path / "out.csv")
    storage.write_csv(path, ["a", "b"], [{"a": "1"}])
    assert storage.read_csv(path) == [{"a": "1", "b": ""}]


def test_read_csv_skips_comment_lines(tmp_path):
    path = str(tmp_path / "out.csv")
    storage.write_csv(
        path,
        ["keyword", "verdict"],
        [{"keyword": "kw", "verdict": "target-now"}],
        comments=["SUGESTAO — o veredito final e do analista", "valores: target-now/skip"],
    )
    rows = storage.read_csv(path)
    assert rows == [{"keyword": "kw", "verdict": "target-now"}]


def test_read_csv_detects_semicolon_delimiter(tmp_path):
    path = str(tmp_path / "out.csv")
    storage.write_csv(path, ["keyword", "volume"], [{"keyword": "kw", "volume": "10"}], ";")
    assert storage.read_csv(path) == [{"keyword": "kw", "volume": "10"}]


def test_read_csv_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    assert storage.read_csv(str(path)) == []


def test_latest_report_picks_newest_date():
    project = "proj-latest"
    for date in ["2026-07-01", "2026-07-10", "2026-06-30"]:
        storage.write_csv(
            storage._report_path(project, date, "descoberta"), ["keyword"], [{"keyword": "x"}]
        )
    latest = storage.latest_report(project, "descoberta")
    assert latest is not None
    assert "2026-07-10_descoberta.csv" in latest


def test_latest_report_none_when_absent():
    assert storage.latest_report("proj-vazio", "descoberta") is None


def test_latest_report_ignores_other_suffixes():
    project = "proj-suffix"
    storage.write_csv(storage._report_path(project, "2026-07-15", "validacao"), ["keyword"], [])
    assert storage.latest_report(project, "descoberta") is None
