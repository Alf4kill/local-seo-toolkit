"""
normalize.py — Keyword normalization and deduplication (pure logic).

The normalized key is used ONLY for comparisons (dedupe, filter-set lookups);
the original accented form is always what gets stored and displayed.
"""

import unicodedata


def normalize_key(kw: str) -> str:
    """Lowercase, strip accents (NFKD), collapse whitespace.

    "Configuração  SSR" and "configuracao ssr" map to the same key.
    """
    text = unicodedata.normalize("NFKD", kw.lower())
    text = text.encode("ascii", "ignore").decode("ascii")
    return " ".join(text.split())


def dedupe_rows(rows: list[dict]) -> list[dict]:
    """Drop duplicate keywords by normalized key.

    First occurrence wins, keeping its original (accented) form and metadata.
    Rows whose keyword normalizes to empty are dropped.
    """
    seen: set[str] = set()
    out = []
    for row in rows:
        key = normalize_key(row.get("keyword", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out
