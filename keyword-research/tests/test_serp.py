"""Tests for serp.py — resumable task_post/poll/task_get flow, client faked."""

import time

import pytest
import serp
from core.cache import get_cached, set_cached
from core.storage import _report_path, read_csv, write_csv
from serp import PipelineError, SerpOptions, load_pending, run_serp_check, save_pending

STAGE3_COLUMNS = ["keyword", "volume", "intent", "source"]


def _serp_result(keyword, titles):
    return {
        "keyword": keyword,
        "items": [
            {
                "type": "organic",
                "domain": f"site{i}.com",
                "url": f"https://site{i}.com/p",
                "title": t,
                "rank_absolute": i + 1,
            }
            for i, t in enumerate(titles)
        ],
    }


class FakeSerpClient:
    """task_post assigns ids; tasks_ready releases them over successive polls."""

    def __init__(self, ready_schedule=None):
        self.ledger_path = "ignorado.csv"
        self.monthly_cap = 5.0
        self.posted = []
        self.results = {}
        self._counter = 0
        # List of lists: task ids released at each successive tasks_ready call.
        self.ready_schedule = ready_schedule if ready_schedule is not None else []
        self._ready_calls = 0

    def serp_task_post(self, keywords, **kw):
        out = []
        for kw_ in keywords:
            self._counter += 1
            tid = f"t{self._counter}"
            self.posted.append(kw_)
            self.results[tid] = _serp_result(kw_, ["Post antigo sem marcador"])
            out.append({"keyword": kw_, "task_id": tid})
        return out

    def serp_tasks_ready(self):
        if self._ready_calls < len(self.ready_schedule):
            batch = self.ready_schedule[self._ready_calls]
        else:
            batch = list(self.results)  # everything ready
        self._ready_calls += 1
        return [{"id": tid} for tid in batch]

    def serp_task_get(self, task_id):
        return self.results[task_id]


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)


def _stage3_csv(project, keywords, date="2026-07-15"):
    rows = [
        {"keyword": kw, "volume": "42", "intent": "", "source": "autocomplete"} for kw in keywords
    ]
    path = _report_path(project, date, "stage3_input")
    write_csv(path, STAGE3_COLUMNS, rows)
    return path


def test_requires_stage3_input():
    with pytest.raises(PipelineError):
        run_serp_check("proj-serp-sem-input", SerpOptions())


def test_post_collect_and_review_roundtrip():
    project = "proj-serp-e2e"
    _stage3_csv(project, ["kw um", "kw dois"])
    client = FakeSerpClient()

    summary = run_serp_check(project, SerpOptions(), client=client)

    assert sorted(client.posted) == ["kw dois", "kw um"]
    assert summary["missing"] == []
    assert load_pending(project) == {}  # everything drained

    review = read_csv(summary["review_path"])
    assert len(review) == 2
    row = {r["keyword"]: r for r in review}["kw um"]
    assert row["volume"] == "42"
    assert row["verdict_sugerido"] == "target-now"  # fake titles have no markers
    assert row["verdict_final"] == ""  # analyst's column starts empty


def test_cached_serps_are_never_reposted():
    project = "proj-serp-cache"
    _stage3_csv(project, ["kw pago"])
    set_cached(project, serp._serp_key("kw pago"), _serp_result("kw pago", ["Guia App Router"]))

    client = FakeSerpClient()
    summary = run_serp_check(project, SerpOptions(), client=client)

    assert client.posted == []  # money rule: never re-buy a cached SERP
    review = read_csv(summary["review_path"])
    assert review[0]["verdict_sugerido"] == "target-later"  # marker present


def test_timeout_leaves_pending_and_exits_gracefully(monkeypatch):
    project = "proj-serp-timeout"
    _stage3_csv(project, ["kw lenta"])
    # Queue never releases the task; force immediate deadline.
    client = FakeSerpClient(ready_schedule=[[], [], [], []])
    monkeypatch.setattr(serp, "SERP_POLL_TIMEOUT_S", 0)

    summary = run_serp_check(project, SerpOptions(), client=client)

    assert summary["missing"] == ["kw lenta"]
    assert summary["review_path"] is None
    pending = load_pending(project)
    assert list(pending) == ["kw lenta"]  # resumable state persisted


def test_fetch_only_drains_previous_run_without_posting():
    project = "proj-serp-fetch"
    _stage3_csv(project, ["kw retomada"])
    client = FakeSerpClient()
    # Simulate a previous run: task exists in the fake API and in pending.
    posted = client.serp_task_post(["kw retomada"])
    save_pending(project, {p["keyword"]: p["task_id"] for p in posted})
    client.posted = []

    summary = run_serp_check(project, SerpOptions(fetch_only=True), client=client)

    assert client.posted == []  # --fetch never posts
    assert summary["missing"] == []
    assert load_pending(project) == {}
    assert get_cached(project, serp._serp_key("kw retomada"), 24) is not None


def test_limit_caps_scope():
    project = "proj-serp-limite"
    _stage3_csv(project, [f"kw {i}" for i in range(10)])
    client = FakeSerpClient()
    run_serp_check(project, SerpOptions(limite=3), client=client)
    assert len(client.posted) == 3
