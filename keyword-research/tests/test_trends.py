"""Tests for fetchers/trends.py — pytrends fully mocked (never installed in CI)."""

import time

import pytest
from fetchers import trends


class FakeFrame:
    """Duck-typed stand-in for the pandas DataFrame pytrends returns."""

    def __init__(self, queries):
        self._queries = queries
        self.columns = ["query", "value"]

    @property
    def empty(self):
        return not self._queries

    def __getitem__(self, col):
        assert col == "query"

        class _Col:
            def __init__(self, values):
                self._values = values

            def tolist(self):
                return self._values

        return _Col(self._queries)

    def __contains__(self, item):
        return item in self.columns


class FakeTrendReq:
    """Programmable TrendReq double; `plans` maps seed -> dict|Exception."""

    plans = {}
    build_calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def build_payload(self, kw_list, **kwargs):
        FakeTrendReq.build_calls += 1
        self._seed = kw_list[0]
        plan = FakeTrendReq.plans.get(self._seed)
        if isinstance(plan, Exception):
            raise plan

    def related_queries(self):
        plan = FakeTrendReq.plans.get(self._seed) or {}
        return {
            self._seed: {
                "top": FakeFrame(plan.get("top", [])),
                "rising": FakeFrame(plan.get("rising", [])),
            }
        }


@pytest.fixture
def fake_pytrends(monkeypatch):
    monkeypatch.setattr(trends, "PYTRENDS_AVAILABLE", True)
    monkeypatch.setattr(trends, "TrendReq", FakeTrendReq, raising=False)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    FakeTrendReq.plans = {}
    FakeTrendReq.build_calls = 0
    return FakeTrendReq


def test_missing_pytrends_returns_empty(monkeypatch):
    monkeypatch.setattr(trends, "PYTRENDS_AVAILABLE", False)
    assert trends.fetch_related_queries(["seed"], "proj-trends") == []


def test_rows_carry_source_and_honesty_note(fake_pytrends):
    fake_pytrends.plans = {"next.js": {"top": ["next.js tutorial"], "rising": ["next.js 15"]}}
    rows = trends.fetch_related_queries(["next.js"], "proj-trends1", use_cache=False)

    by_source = {r["source"]: r["keyword"] for r in rows}
    assert by_source == {"trends-top": "next.js tutorial", "trends-rising": "next.js 15"}
    assert all(r["notes"] == trends.NOTES_WARNING for r in rows)
    assert all(r["seed"] == "next.js" for r in rows)


def test_per_seed_error_isolation(fake_pytrends):
    fake_pytrends.plans = {
        "quebra": RuntimeError("bloqueado 429"),
        "funciona": {"top": ["funciona bem"]},
    }
    rows = trends.fetch_related_queries(["quebra", "funciona"], "proj-trends2", use_cache=False)
    assert [r["keyword"] for r in rows] == ["funciona bem"]


def test_second_call_served_from_cache(fake_pytrends):
    fake_pytrends.plans = {"cacheado": {"top": ["kw"]}}
    trends.fetch_related_queries(["cacheado"], "proj-trends3")

    fake_pytrends.build_calls = 0
    rows = trends.fetch_related_queries(["cacheado"], "proj-trends3")
    assert fake_pytrends.build_calls == 0  # no network on cache hit
    assert [r["keyword"] for r in rows] == ["kw"]


def test_errors_are_not_cached(fake_pytrends):
    fake_pytrends.plans = {"instavel": RuntimeError("falhou")}
    assert trends.fetch_related_queries(["instavel"], "proj-trends4") == []

    # Source recovers: the failed result must NOT have been cached.
    fake_pytrends.plans = {"instavel": {"top": ["recuperou"]}}
    fake_pytrends.build_calls = 0
    rows = trends.fetch_related_queries(["instavel"], "proj-trends4")
    assert fake_pytrends.build_calls == 1
    assert [r["keyword"] for r in rows] == ["recuperou"]


def test_empty_seed_list(fake_pytrends):
    assert trends.fetch_related_queries([], "proj-trends5") == []
