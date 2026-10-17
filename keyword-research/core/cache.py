"""
cache.py — JSON disk cache with TTL, one folder per project.

Same pattern as gsc-monitor/core/cache.py (copied, not imported — tools in
this monorepo never cross-import). Every entry is a single JSON file:

    relatorios/{project}/.cache/{key}.json
    {"cached_at": "<UTC ISO>", "data": ...}

The `cached_at` stamp doubles as the "dated" requirement for Stage 1
autocomplete snapshots.
"""

import json
import os
import re
from datetime import UTC, datetime, timedelta

from core import storage

CACHE_SUBDIR = ".cache"


# ---------------------------------------------------------------------------
# Internal IO helpers
# ---------------------------------------------------------------------------


def _cache_dir(project: str) -> str:
    """Return (and create) the project's cache folder."""
    path = os.path.join(storage._get_project_dir(project), CACHE_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def _safe_key(key: str) -> str:
    """Strip characters that are invalid in cache file names."""
    return re.sub(r"[^\w\-.]", "_", key)


def _cache_path(project: str, key: str) -> str:
    return os.path.join(_cache_dir(project), f"{_safe_key(key)}.json")


def _read_entry(path: str) -> "dict | None":
    """Read a cache file. Returns None when missing or unreadable."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_entry(path: str, data) -> None:
    """Persist data with a write timestamp."""
    entry = {
        # Timezone-aware UTC stamp — unambiguous instant, immune to DST.
        "cached_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "data": data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)


def _is_fresh(entry: dict, max_age_hours: float) -> bool:
    """True while the entry is within its TTL."""
    try:
        cached_at = datetime.fromisoformat(entry["cached_at"])
    except (KeyError, ValueError):
        return False
    # Compat with naive local-time stamps (interpreted as host-local instants).
    if cached_at.tzinfo is None:
        cached_at = cached_at.astimezone()
    return (datetime.now(UTC) - cached_at) <= timedelta(hours=max_age_hours)


# ---------------------------------------------------------------------------
# Public API — generic get/set (fetchers pick their own key prefixes/TTLs)
# ---------------------------------------------------------------------------


def get_cached(project: str, key: str, ttl_hours: float):
    """Return cached data for the key, or None when missing/expired."""
    entry = _read_entry(_cache_path(project, key))
    if entry is None or not _is_fresh(entry, ttl_hours):
        return None
    return entry["data"]


def set_cached(project: str, key: str, data) -> None:
    """Persist data under the key (entry is timestamped on write)."""
    _write_entry(_cache_path(project, key), data)
