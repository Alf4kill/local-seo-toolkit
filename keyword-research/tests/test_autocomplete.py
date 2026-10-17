"""Tests for fetchers/autocomplete.py — no network, everything mocked."""

import time

import pytest
import requests
from config import RECURSE_TOP_N
from fetchers import autocomplete


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


# ---------------------------------------------------------------------------
# build_query_plan
# ---------------------------------------------------------------------------


def test_query_plan_has_exactly_32_queries():
    plan = autocomplete.build_query_plan("next.js seo")
    assert len(plan) == 32  # 1 seed + 26 letters + 5 question prefixes


def test_query_plan_shapes():
    plan = dict(autocomplete.build_query_plan("next.js seo"))
    assert plan["next.js seo"] == "seed"
    assert plan["next.js seo a"] == "letra:a"
    assert plan["next.js seo z"] == "letra:z"
    assert plan["como next.js seo"] == "prefixo:como"
    assert plan["vale a pena next.js seo"] == "prefixo:vale a pena"


def test_query_plan_strips_seed():
    plan = autocomplete.build_query_plan("  cwv  ")
    assert plan[0] == ("cwv", "seed")


# ---------------------------------------------------------------------------
# pick_recursion_candidates
# ---------------------------------------------------------------------------


def test_recursion_candidates_must_extend_seed():
    suggestions = [
        "next.js seo",  # identical to the seed — excluded
        "next.js seo tutorial",  # extends — kept
        "seo para next.js",  # does not start with the seed — excluded
        "next.js seo 2026 guia",  # extends — kept
    ]
    result = autocomplete.pick_recursion_candidates(suggestions, "next.js seo")
    assert result == ["next.js seo tutorial", "next.js seo 2026 guia"]


def test_recursion_candidates_need_extra_word():
    # Longer string but same word count (just a longer last word) — excluded.
    result = autocomplete.pick_recursion_candidates(["next.js seotools"], "next.js seo")
    assert result == []


def test_recursion_candidates_capped_at_top_n():
    suggestions = [f"seed extra{i}" for i in range(RECURSE_TOP_N + 5)]
    result = autocomplete.pick_recursion_candidates(suggestions, "seed")
    assert len(result) == RECURSE_TOP_N


# ---------------------------------------------------------------------------
# fetch_suggestions (parsing)
# ---------------------------------------------------------------------------


def test_fetch_parses_firefox_payload(monkeypatch):
    payload = ["next.js", ["next.js tutorial", "  next.js seo  ", "", 42]]
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(payload))
    assert autocomplete.fetch_suggestions("next.js") == ["next.js tutorial", "next.js seo"]


def test_fetch_empty_suggestions_is_empty_list_not_none(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(["q", []]))
    assert autocomplete.fetch_suggestions("q") == []


@pytest.mark.parametrize("payload", [{"nao": "lista"}, ["so-um-elemento"], ["q", "nao-lista"]])
def test_fetch_malformed_payload_returns_none(monkeypatch, payload):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResponse(payload))
    assert autocomplete.fetch_suggestions("q") is None


def test_fetch_network_error_returns_none(monkeypatch):
    def boom(*a, **kw):
        raise requests.ConnectionError("sem rede")

    monkeypatch.setattr(requests, "get", boom)
    assert autocomplete.fetch_suggestions("q") is None


# ---------------------------------------------------------------------------
# expand_seed (cache behavior, notes, recursion)
# ---------------------------------------------------------------------------


@pytest.fixture
def no_sleep(monkeypatch):
    calls = {"n": 0}

    def fake_sleep(_secs):
        calls["n"] += 1

    monkeypatch.setattr(time, "sleep", fake_sleep)
    return calls


def test_expand_seed_without_recursion(monkeypatch, no_sleep):
    fetches = {"n": 0}

    def fake_fetch(query, timeout=10):
        fetches["n"] += 1
        return [f"{query} sugestao"]

    monkeypatch.setattr(autocomplete, "fetch_suggestions", fake_fetch)
    rows = autocomplete.expand_seed("cwv", "proj-auto1", recursive=False)

    assert fetches["n"] == 32
    assert no_sleep["n"] == 32  # one rate-limit sleep per miss
    assert len(rows) == 32
    assert {r["source"] for r in rows} == {"autocomplete"}
    assert {r["seed"] for r in rows} == {"cwv"}
    notes = {r["notes"] for r in rows}
    assert "seed" in notes and "letra:a" in notes and "prefixo:como" in notes


def test_expand_seed_second_run_hits_cache(monkeypatch, no_sleep):
    fetches = {"n": 0}

    def fake_fetch(query, timeout=10):
        fetches["n"] += 1
        return ["alguma sugestao"]

    monkeypatch.setattr(autocomplete, "fetch_suggestions", fake_fetch)
    autocomplete.expand_seed("ssg", "proj-auto2", recursive=False)

    fetches["n"] = 0
    no_sleep["n"] = 0
    rows = autocomplete.expand_seed("ssg", "proj-auto2", recursive=False)

    assert fetches["n"] == 0  # every query served from cache
    assert no_sleep["n"] == 0  # no sleeping on cache hits
    assert len(rows) == 32


def test_expand_seed_recursion_marks_notes(monkeypatch, no_sleep):
    def fake_fetch(query, timeout=10):
        # The plain seed yields one extending suggestion; that child's own
        # plain query yields a longer variation. Everything else is empty.
        if query == "hidratacao":
            return ["hidratacao no next.js"]
        if query == "hidratacao no next.js":
            return ["hidratacao no next.js como funciona"]
        return []

    monkeypatch.setattr(autocomplete, "fetch_suggestions", fake_fetch)
    rows = autocomplete.expand_seed("hidratacao", "proj-auto3", recursive=True)

    recursion_notes = {r["notes"] for r in rows if r["notes"].startswith("recursao:")}
    assert recursion_notes == {"recursao:hidratacao no next.js"}
    assert any(r["keyword"] == "hidratacao no next.js como funciona" for r in rows)


def test_expand_seed_errors_not_cached(monkeypatch, no_sleep):
    state = {"fail": True, "n": 0}

    def flaky_fetch(query, timeout=10):
        state["n"] += 1
        return None if state["fail"] else ["ok"]

    monkeypatch.setattr(autocomplete, "fetch_suggestions", flaky_fetch)
    autocomplete.expand_seed("erro", "proj-auto4", recursive=False)
    assert state["n"] == 32

    # Second run: errors were NOT cached, so every query is retried.
    state["fail"] = False
    state["n"] = 0
    rows = autocomplete.expand_seed("erro", "proj-auto4", recursive=False)
    assert state["n"] == 32
    assert len(rows) == 32
