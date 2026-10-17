"""Tests for core/cache.py — TTL JSON cache."""

import json
import os
from datetime import UTC, datetime, timedelta

from core import cache


def test_set_get_roundtrip():
    cache.set_cached("proj-cache", "suggest_abc", ["kw um", "kw dois"])
    assert cache.get_cached("proj-cache", "suggest_abc", ttl_hours=1) == ["kw um", "kw dois"]


def test_get_missing_returns_none():
    assert cache.get_cached("proj-cache", "nao_existe", ttl_hours=1) is None


def test_expired_entry_returns_none():
    project = "proj-cache"
    key = "suggest_velho"
    path = cache._cache_path(project, key)
    old_stamp = (datetime.now(UTC) - timedelta(hours=48)).isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cached_at": old_stamp, "data": ["velho"]}, f)
    assert cache.get_cached(project, key, ttl_hours=24) is None
    # Still fresh under a longer TTL — the entry itself is intact.
    assert cache.get_cached(project, key, ttl_hours=72) == ["velho"]


def test_malformed_file_returns_none():
    project = "proj-cache"
    key = "suggest_quebrado"
    path = cache._cache_path(project, key)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{nao é json")
    assert cache.get_cached(project, key, ttl_hours=1) is None


def test_missing_timestamp_treated_as_stale():
    project = "proj-cache"
    key = "suggest_sem_stamp"
    path = cache._cache_path(project, key)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"data": ["x"]}, f)
    assert cache.get_cached(project, key, ttl_hours=999) is None


def test_safe_key_sanitizes_filenames():
    assert cache._safe_key("como usar next.js?") == "como_usar_next.js_"
    path = cache._cache_path("proj-cache", "a/b:c")
    assert os.path.basename(path) == "a_b_c.json"
