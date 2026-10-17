"""Tests for core/ledger.py — cost log and budget enforcement."""

from datetime import UTC, datetime

import pytest
from core import ledger


def test_append_and_month_total_roundtrip(tmp_path):
    path = str(tmp_path / "costs.csv")
    ledger.append_cost(path, "/v3/x", 0.05, tasks=1, note="teste")
    ledger.append_cost(path, "/v3/y", 0.075, tasks=2)
    assert ledger.month_total(path) == pytest.approx(0.125)


def test_month_total_isolates_months(tmp_path):
    path = str(tmp_path / "costs.csv")
    ledger.append_cost(path, "/v3/x", 0.10)
    # Hand-write a row from another month.
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write("2020-01-01T00:00:00+00:00,/v3/velho,1,9.990000,antigo\n")
    current = datetime.now(UTC).strftime("%Y-%m")
    assert ledger.month_total(path, current) == pytest.approx(0.10)
    assert ledger.month_total(path, "2020-01") == pytest.approx(9.99)


def test_month_total_missing_file_is_zero(tmp_path):
    assert ledger.month_total(str(tmp_path / "nao_existe.csv")) == 0.0


def test_month_total_skips_malformed_rows(tmp_path):
    path = str(tmp_path / "costs.csv")
    ledger.append_cost(path, "/v3/x", 0.05)
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write("linha,quebrada,sem,numero,aqui\n")
        f.write(",,,nao-e-float,\n")
    assert ledger.month_total(path) == pytest.approx(0.05)


def test_check_budget_under_cap_returns_total(tmp_path):
    path = str(tmp_path / "costs.csv")
    ledger.append_cost(path, "/v3/x", 1.00)
    assert ledger.check_budget(path, cap_usd=5.0) == pytest.approx(1.00)


def test_check_budget_at_cap_raises(tmp_path):
    path = str(tmp_path / "costs.csv")
    ledger.append_cost(path, "/v3/x", 5.00)
    with pytest.raises(ledger.BudgetExceededError):
        ledger.check_budget(path, cap_usd=5.0)


def test_ledger_path_respects_relatorios_dir(_isolate_relatorios):
    path = ledger.ledger_path()
    assert path.startswith(_isolate_relatorios)
    assert path.endswith("dataforseo_costs.csv")
