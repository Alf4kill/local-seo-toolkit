"""Tests for fetchers/dataforseo.py — HTTP fully mocked.

The two cost guardrails are pinned here as regression tests:
`priority` and `include_clickstream_data` must NEVER appear in any payload.
"""

import json

import pytest
import requests
from core import ledger
from fetchers.dataforseo import DataForSEOClient, DataForSEOError


def _api_response(result=None, cost=0.05, status_code=20000, task_status=20000, tasks=None):
    if tasks is None:
        tasks = [
            {
                "id": "task-1",
                "status_code": task_status,
                "status_message": "Ok." if task_status == 20000 else "Erro.",
                "result": result or [],
            }
        ]
    return {
        "status_code": status_code,
        "status_message": "Ok.",
        "cost": cost,
        "tasks_count": len(tasks),
        "tasks": tasks,
    }


class FakeHTTP:
    """Records every requests.request call and replays scripted responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, auth=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "auth": auth, "payload": json})

        class _Resp:
            def __init__(self, data, status=200):
                self._data = data
                self.status_code = status

            def json(self):
                return self._data

        item = self.responses.pop(0)
        if isinstance(item, tuple):
            return _Resp(*item)
        return _Resp(item)


@pytest.fixture
def client(tmp_path):
    return DataForSEOClient(
        "login", "senha", ledger_path=str(tmp_path / "costs.csv"), monthly_cap=5.0
    )


def _install(monkeypatch, responses):
    fake = FakeHTTP(responses)
    monkeypatch.setattr(requests, "request", fake)
    return fake


# ---------------------------------------------------------------------------
# from_env / available
# ---------------------------------------------------------------------------


def test_from_env_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    with pytest.raises(DataForSEOError, match="DATAFORSEO_LOGIN"):
        DataForSEOClient.from_env()
    assert DataForSEOClient.available() is False


def test_from_env_reads_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAFORSEO_LOGIN", "user@x")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "s3nha")
    c = DataForSEOClient.from_env(ledger_path=str(tmp_path / "l.csv"))
    assert (c.login, c.password) == ("user@x", "s3nha")
    assert DataForSEOClient.available() is True


def test_monthly_cap_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DATAFORSEO_MONTHLY_CAP", "2.5")
    c = DataForSEOClient("l", "p", ledger_path=str(tmp_path / "l.csv"))
    assert c.monthly_cap == 2.5


# ---------------------------------------------------------------------------
# _request: envelope, ledger, budget pre-flight
# ---------------------------------------------------------------------------


def test_request_unwraps_20000(monkeypatch, client):
    _install(monkeypatch, [_api_response(result=[{"keyword": "kw"}])])
    data = client._request("POST", "/v3/teste", [{}])
    assert data["status_code"] == 20000


def test_api_level_error_raises_with_message(monkeypatch, client):
    resp = _api_response()
    resp["status_code"] = 40100
    resp["status_message"] = "Authentication failed."
    _install(monkeypatch, [resp])
    with pytest.raises(DataForSEOError, match="40100"):
        client._request("POST", "/v3/teste", [{}])


def test_task_level_error_raises(monkeypatch, client):
    _install(monkeypatch, [_api_response(task_status=40501)])
    with pytest.raises(DataForSEOError, match="40501"):
        client.keyword_ideas(["kw"])


def test_cost_logged_on_every_call_including_task_failures(monkeypatch, client):
    _install(monkeypatch, [_api_response(task_status=40501, cost=0.03)])
    with pytest.raises(DataForSEOError):
        client.keyword_ideas(["kw"])
    # HTTP exchange succeeded -> it was billed -> it must be in the ledger.
    assert ledger.month_total(client.ledger_path) == pytest.approx(0.03)


def test_budget_preflight_blocks_before_any_http(monkeypatch, client):
    ledger.append_cost(client.ledger_path, "/v3/anterior", 5.0)  # cap reached
    fake = _install(monkeypatch, [_api_response()])
    with pytest.raises(ledger.BudgetExceededError):
        client.search_volume(["kw"])
    assert fake.calls == []  # zero HTTP traffic after the cap


def test_http_4xx_surfaces_api_message(monkeypatch, client):
    body = {
        "status_code": 40104,
        "status_message": "Please verify your account before using the API.",
    }
    _install(monkeypatch, [(body, 403)])
    with pytest.raises(DataForSEOError, match="40104.*verify your account"):
        client.keyword_ideas(["kw"])


def test_http_failure_raises_and_logs_nothing(monkeypatch, client):
    def boom(*a, **kw):
        raise requests.ConnectionError("sem rede")

    monkeypatch.setattr(requests, "request", boom)
    with pytest.raises(DataForSEOError, match="falha HTTP"):
        client.keyword_ideas(["kw"])
    assert ledger.month_total(client.ledger_path) == 0.0


# ---------------------------------------------------------------------------
# Guardrail regression: forbidden fields never sent, basic auth always used
# ---------------------------------------------------------------------------


def _assert_no_forbidden_fields(calls):
    dumped = json.dumps([c["payload"] for c in calls])
    assert "priority" not in dumped
    assert "include_clickstream_data" not in dumped


def test_no_priority_or_clickstream_in_any_payload(monkeypatch, client):
    fake = _install(
        monkeypatch,
        [
            _api_response(result=[{"items": []}]),  # keyword_ideas
            _api_response(result=[{"items": []}]),  # related_keywords
            _api_response(result=[]),  # search_volume
            _api_response(result=[{"items": []}]),  # search_intent
            _api_response(tasks=[{"id": "t1", "status_code": 20100, "data": {"keyword": "kw"}}]),
        ],
    )
    client.keyword_ideas(["kw"])
    client.related_keywords("kw")
    client.search_volume(["kw"])
    client.search_intent(["kw"])
    client.serp_task_post(["kw"])

    _assert_no_forbidden_fields(fake.calls)
    assert all(c["auth"] == ("login", "senha") for c in fake.calls)


# ---------------------------------------------------------------------------
# search_volume chunking
# ---------------------------------------------------------------------------


def test_search_volume_chunks_at_1000(monkeypatch, client):
    keywords = [f"kw {i}" for i in range(2500)]
    fake = _install(monkeypatch, [_api_response(result=[]) for _ in range(3)])
    client.search_volume(keywords)

    assert len(fake.calls) == 3  # 1000 + 1000 + 500
    sizes = [len(c["payload"][0]["keywords"]) for c in fake.calls]
    assert sizes == [1000, 1000, 500]
    assert all(c["payload"][0]["location_code"] == 2076 for c in fake.calls)
    assert all(c["payload"][0]["language_code"] == "pt" for c in fake.calls)


# ---------------------------------------------------------------------------
# SERP methods
# ---------------------------------------------------------------------------


def test_serp_task_post_returns_ids_and_isolates_rejections(monkeypatch, client):
    tasks = [
        {"id": "t1", "status_code": 20100, "data": {"keyword": "kw um"}},
        {"id": "t2", "status_code": 40501, "status_message": "Invalid Field."},
        {"id": "t3", "status_code": 20100, "data": {"keyword": "kw tres"}},
    ]
    fake = _install(monkeypatch, [_api_response(tasks=tasks)])
    posted = client.serp_task_post(["kw um", "kw dois", "kw tres"])

    assert posted == [
        {"keyword": "kw um", "task_id": "t1"},
        {"keyword": "kw tres", "task_id": "t3"},
    ]
    payload = fake.calls[0]["payload"]
    assert [t["keyword"] for t in payload] == ["kw um", "kw dois", "kw tres"]
    assert all(t["depth"] == 10 and t["device"] == "desktop" for t in payload)


def test_serp_task_get_returns_first_result(monkeypatch, client):
    serp = {"keyword": "kw", "items": [{"type": "organic"}]}
    _install(monkeypatch, [_api_response(result=[serp])])
    assert client.serp_task_get("t1") == serp


def test_serp_tasks_ready(monkeypatch, client):
    ready = [{"id": "t1"}, {"id": "t2"}]
    fake = _install(monkeypatch, [_api_response(result=ready)])
    assert client.serp_tasks_ready() == ready
    assert fake.calls[0]["method"] == "GET"
