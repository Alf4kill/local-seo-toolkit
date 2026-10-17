"""
keyword_map.py — Duplicate check against the blog's keyword-map.md.

The keyword map lives in the user's blog project (NOT in this repo), so the
file is optional by design: a missing path prints a warning, returns an empty
set, and the duplicate filter simply does nothing.

Parses three markdown shapes for keywords, all normalized via normalize_key:
  - table rows   -> first cell of each `| ... |` line (header + divider skipped)
  - bullet items -> `- keyword` / `* keyword`
  - inline code  -> `keyword`
"""

import os
import re

from core.normalize import normalize_key

_TABLE_DIVIDER = re.compile(r"^\|?[\s:|-]+\|?$")
_BULLET = re.compile(r"^\s*[-*]\s+(.+)$")
_INLINE_CODE = re.compile(r"`([^`]+)`")


def _table_first_cells(lines: list[str]) -> list[str]:
    """First cell of every table data row (header and divider rows skipped)."""
    cells: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|") or _TABLE_DIVIDER.match(stripped):
            continue
        # A row immediately followed by the divider line is the header.
        next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if next_line.startswith("|") and _TABLE_DIVIDER.match(next_line):
            continue
        parts = [p.strip() for p in stripped.strip("|").split("|")]
        if parts and parts[0]:
            cells.append(parts[0])
    return cells


def load_keyword_map(path: "str | None") -> set[str]:
    """Normalized keys of every keyword already covered by the keyword map."""
    if not path:
        return set()
    if not os.path.exists(path):
        print(f"[keyword-map] arquivo nao encontrado: {path} — checagem de duplicatas desativada")
        return set()

    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    candidates = _table_first_cells(lines)
    for line in lines:
        m = _BULLET.match(line)
        if m:
            candidates.append(m.group(1))
        candidates.extend(_INLINE_CODE.findall(line))

    keys: set[str] = set()
    for cand in candidates:
        key = normalize_key(cand.strip().strip("*_`"))
        if key:
            keys.add(key)
    print(f"[keyword-map] {len(keys)} keywords carregadas de {os.path.basename(path)}")
    return keys
