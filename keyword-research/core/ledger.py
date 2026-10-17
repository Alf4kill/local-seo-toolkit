"""
ledger.py — Append-only cost ledger + budget enforcement for DataForSEO.

Every paid API response's `cost` field lands here — including task-level
failures after a successful HTTP exchange, since those are still billed. The
monthly cap is checked BEFORE each request by the client; once the ledger
says the month hit the cap, nothing else can be spent until the cap is
raised explicitly (env DATAFORSEO_MONTHLY_CAP or --budget).

File: relatorios/_ledger/dataforseo_costs.csv (comma, dot decimals, plain
utf-8 — appending with utf-8-sig would inject BOMs mid-file). Machine-read;
do not hand-edit.
"""

import csv
import os
from datetime import UTC, datetime

from core import storage

LEDGER_COLUMNS = ["timestamp_utc", "endpoint", "tasks", "cost_usd", "note"]


class BudgetExceededError(RuntimeError):
    """Monthly spending cap reached — the request is refused BEFORE spending."""


def ledger_path() -> str:
    """Global ledger file path (folder created on demand).

    Derived from storage.RELATORIOS_DIR at call time so the tests' tempdir
    isolation applies here too.
    """
    folder = os.path.join(storage.RELATORIOS_DIR, "_ledger")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "dataforseo_costs.csv")


def append_cost(path: str, endpoint: str, cost: float, tasks: int = 1, note: str = "") -> None:
    """Append one cost line; writes the header when creating the file."""
    new_file = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(LEDGER_COLUMNS)
        writer.writerow(
            [
                datetime.now(UTC).isoformat(timespec="seconds"),
                endpoint,
                tasks,
                f"{cost:.6f}",
                note,
            ]
        )


def month_total(path: str, year_month: "str | None" = None) -> float:
    """Total spent in a month ("YYYY-MM"; default: current UTC month).

    Malformed rows are skipped — a corrupt line must never crash a budget
    check (it would block all spending with no way out).
    """
    if year_month is None:
        year_month = datetime.now(UTC).strftime("%Y-%m")
    if not os.path.exists(path):
        return 0.0
    total = 0.0
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                if str(row.get("timestamp_utc", "")).startswith(year_month):
                    total += float(row.get("cost_usd", ""))
            except (TypeError, ValueError):
                continue
    return total


def check_budget(path: str, cap_usd: float) -> float:
    """Raise BudgetExceededError when the month's spend reached the cap.

    Returns the current month total otherwise (used for [custo] prints).
    """
    total = month_total(path)
    if total >= cap_usd:
        raise BudgetExceededError(
            f"orcamento mensal atingido: ${total:.2f} >= ${cap_usd:.2f}. "
            "Aumente com --budget ou env DATAFORSEO_MONTHLY_CAP."
        )
    return total
