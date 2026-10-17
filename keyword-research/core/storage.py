"""
storage.py — File IO: per-project report folders and CSV helpers.

Folder layout (everything under `relatorios/`, which the repo root .gitignore
already ignores at any depth — nothing here can leak into the public repo):

    relatorios/
        _ledger/dataforseo_costs.csv     # global cost ledger (core/ledger.py)
        {project}/
            .cache/*.json                # fetcher caches (core/cache.py)
            {date}_descoberta.csv        # Stage 1 output
            {date}_validacao.csv         # Stage 2 full audit trail
            {date}_stage3_input.csv      # Stage 2 kept keywords
            {date}_serp_review.csv       # Stage 3 analyst-editable review

Machine-consumed CSVs are comma-delimited with dot decimals, utf-8-sig for
Excel compatibility. Only the analyst-edited SERP review uses `;` plus leading
`#` comment lines (same convention as gsc-monitor's editable poda CSV).
"""

import csv
import os
import re

from config import BASE_DIR

RELATORIOS_DIR = os.path.join(BASE_DIR, "relatorios")

# Header of the Stage 1 discovery CSV — also the exchange format consumed via
# --gsc-csv (produced by gsc-monitor/exportar_keywords.py).
KEYWORD_CSV_COLUMNS = ["keyword", "source", "seed", "date_collected", "notes"]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _safe_filename(name: str) -> str:
    """Strip characters that are invalid in file/folder names."""
    return re.sub(r"[^\w\-.]", "_", name)


def _get_project_dir(project: str) -> str:
    """Return (and create) the project's report folder."""
    path = os.path.join(RELATORIOS_DIR, _safe_filename(project))
    os.makedirs(path, exist_ok=True)
    return path


def _report_path(project: str, date: str, suffix: str, ext: str = "csv") -> str:
    """Full path of a dated report file, e.g. relatorios/x/2026-07-15_descoberta.csv."""
    return os.path.join(_get_project_dir(project), f"{date}_{suffix}.{ext}")


def latest_report(project: str, suffix: str, ext: str = "csv") -> "str | None":
    """Return the newest `{date}_{suffix}.{ext}` for the project, or None."""
    folder = _get_project_dir(project)
    pattern = re.compile(rf"^(\d{{4}}-\d{{2}}-\d{{2}})_{re.escape(suffix)}\.{re.escape(ext)}$")
    candidates = sorted(name for name in os.listdir(folder) if pattern.match(name))
    return os.path.join(folder, candidates[-1]) if candidates else None


# ---------------------------------------------------------------------------
# Generic CSV IO (dict rows)
# ---------------------------------------------------------------------------


def write_csv(
    path: str,
    header: list[str],
    rows: list[dict],
    delimiter: str = ",",
    comments: "list[str] | None" = None,
) -> str:
    """Write dict rows as CSV (utf-8-sig). Optional leading `# ...` comment lines."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        for line in comments or []:
            f.write(f"# {line}\n")
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(col, "") for col in header])
    return path


def read_csv(path: str) -> list[dict]:
    """Read a CSV written by write_csv back into dict rows.

    Skips leading `#` comment lines and auto-detects `,` vs `;` delimiter
    (same tolerance as gsc-monitor's pruning CSV parser).
    """
    with open(path, encoding="utf-8-sig") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    if not lines:
        return []
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    return [dict(row) for row in reader]
