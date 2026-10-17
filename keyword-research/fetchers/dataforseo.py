"""
dataforseo.py — DataForSEO client for Stages 2 (validation) and 3 (SERP).

Cost guardrails, enforced here by construction:

  * PRE-FLIGHT: every request first checks the monthly ledger cap
    (core/ledger.py) and refuses to spend past it (BudgetExceededError is
    raised before any HTTP traffic).
  * POST-FLIGHT: every response's `cost` field is appended to the ledger —
    including task-level failures, since HTTP-successful calls are billed.
  * `priority` is NEVER sent (standard/flat pricing only) and
    `include_clickstream_data` is NEVER sent (doubles cost). Both are pinned
    by regression tests.

Credentials: env vars DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD only. No file
fallback — this is a public repo.
"""

import os

import requests
from config import (
    DATAFORSEO_BASE_URL,
    DATAFORSEO_TIMEOUT,
    KEYWORD_IDEAS_LIMIT,
    LANGUAGE_PT,
    LOCATION_BRAZIL,
    MONTHLY_BUDGET_USD,
    SEARCH_VOLUME_BATCH,
    SERP_DEPTH,
    SERP_DEVICE,
    SERP_TASKS_PER_POST,
)
from core import ledger


class DataForSEOError(RuntimeError):
    """API-level failure (bad credentials, task error, unexpected payload)."""


class DataForSEOClient:
    """Thin JSON client over the DataForSEO v3 REST API (HTTP Basic auth)."""

    def __init__(
        self,
        login: str,
        password: str,
        timeout: int = DATAFORSEO_TIMEOUT,
        ledger_path: "str | None" = None,
        monthly_cap: "float | None" = None,
    ):
        self.login = login
        self.password = password
        self.timeout = timeout
        self.ledger_path = ledger_path or ledger.ledger_path()
        if monthly_cap is None:
            monthly_cap = float(os.environ.get("DATAFORSEO_MONTHLY_CAP", MONTHLY_BUDGET_USD))
        self.monthly_cap = monthly_cap

    @classmethod
    def from_env(cls, **kwargs) -> "DataForSEOClient":
        login = os.environ.get("DATAFORSEO_LOGIN")
        password = os.environ.get("DATAFORSEO_PASSWORD")
        if not login or not password:
            raise DataForSEOError(
                "credenciais ausentes. Defina as variaveis de ambiente "
                "DATAFORSEO_LOGIN e DATAFORSEO_PASSWORD (nunca em arquivo — repo publico)."
            )
        return cls(login, password, **kwargs)

    @staticmethod
    def available() -> bool:
        """True when both credential env vars are set."""
        return bool(os.environ.get("DATAFORSEO_LOGIN") and os.environ.get("DATAFORSEO_PASSWORD"))

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _request(
        self, method: str, path: str, payload: "list | None" = None, note: str = ""
    ) -> dict:
        """One authenticated API exchange with pre/post-flight cost control."""
        spent = ledger.check_budget(self.ledger_path, self.monthly_cap)  # pre-flight

        try:
            resp = requests.request(
                method,
                DATAFORSEO_BASE_URL + path,
                auth=(self.login, self.password),
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DataForSEOError(f"falha HTTP em {path}: {exc}") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise DataForSEOError(f"resposta nao-JSON em {path} (HTTP {resp.status_code})") from exc
        if resp.status_code >= 400:
            # Surface the API's own diagnosis (e.g. 40104 = account not yet
            # verified in the dashboard) instead of a bare HTTP status.
            raise DataForSEOError(
                f"HTTP {resp.status_code} em {path}: "
                f"{data.get('status_code')} {data.get('status_message')}"
            )

        # Post-flight: log the real billed cost of EVERY exchange, even when
        # the API then reports an error (billed anyway).
        cost = float(data.get("cost") or 0.0)
        tasks_count = int(data.get("tasks_count") or 0)
        ledger.append_cost(self.ledger_path, path, cost, tasks=tasks_count or 1, note=note)
        if cost:
            print(
                f"[custo] {path}: ${cost:.4f} "
                f"(mes: ${spent + cost:.2f} / limite ${self.monthly_cap:.2f})"
            )

        if data.get("status_code") != 20000:
            raise DataForSEOError(
                f"erro da API em {path}: {data.get('status_code')} {data.get('status_message')}"
            )
        return data

    @staticmethod
    def _extract_tasks(response: dict) -> list[dict]:
        tasks = response.get("tasks") or []
        if not tasks:
            raise DataForSEOError("resposta sem tasks.")
        return tasks

    @staticmethod
    def _extract_result(response: dict) -> list:
        """Unwrap tasks[0].result; raises DataForSEOError on task-level errors."""
        task = DataForSEOClient._extract_tasks(response)[0]
        if task.get("status_code") != 20000:
            raise DataForSEOError(
                f"task falhou: {task.get('status_code')} {task.get('status_message')}"
            )
        return task.get("result") or []

    # ------------------------------------------------------------------
    # Stage 2 — validation endpoints
    # ------------------------------------------------------------------

    def keyword_ideas(
        self,
        keywords: list[str],
        location_code: int = LOCATION_BRAZIL,
        language_code: str = LANGUAGE_PT,
        limit: int = KEYWORD_IDEAS_LIMIT,
    ) -> list[dict]:
        """Labs Keyword Ideas — expands seed keywords into candidates w/ metrics."""
        payload = [
            {
                "keywords": keywords,
                "location_code": location_code,
                "language_code": language_code,
                "limit": limit,
            }
        ]
        resp = self._request(
            "POST",
            "/v3/dataforseo_labs/google/keyword_ideas/live",
            payload,
            note=f"{len(keywords)} seeds",
        )
        return self._extract_result(resp)

    def related_keywords(
        self,
        keyword: str,
        depth: int = 1,
        location_code: int = LOCATION_BRAZIL,
        language_code: str = LANGUAGE_PT,
    ) -> list[dict]:
        """Labs Related Keywords — semantic neighbors of one seed (depth 1-2)."""
        payload = [
            {
                "keyword": keyword,
                "location_code": location_code,
                "language_code": language_code,
                "depth": depth,
            }
        ]
        resp = self._request(
            "POST",
            "/v3/dataforseo_labs/google/related_keywords/live",
            payload,
            note=keyword,
        )
        return self._extract_result(resp)

    def search_volume(
        self,
        keywords: list[str],
        location_code: int = LOCATION_BRAZIL,
        language_code: str = LANGUAGE_PT,
    ) -> list[dict]:
        """Google Ads search volume, chunked at 1000 kw/task (flat batch price)."""
        results: list[dict] = []
        for i in range(0, len(keywords), SEARCH_VOLUME_BATCH):
            chunk = keywords[i : i + SEARCH_VOLUME_BATCH]
            payload = [
                {
                    "keywords": chunk,
                    "location_code": location_code,
                    "language_code": language_code,
                }
            ]
            resp = self._request(
                "POST",
                "/v3/keywords_data/google_ads/search_volume/live",
                payload,
                note=f"{len(chunk)}kw",
            )
            results.extend(self._extract_result(resp))
        return results

    def search_intent(self, keywords: list[str], language_code: str = LANGUAGE_PT) -> list[dict]:
        """Labs Search Intent — optional cheap intent labels (Stage 2 filter)."""
        results: list[dict] = []
        for i in range(0, len(keywords), SEARCH_VOLUME_BATCH):
            chunk = keywords[i : i + SEARCH_VOLUME_BATCH]
            payload = [{"keywords": chunk, "language_code": language_code}]
            resp = self._request(
                "POST",
                "/v3/dataforseo_labs/google/search_intent/live",
                payload,
                note=f"{len(chunk)}kw",
            )
            results.extend(self._extract_result(resp))
        return results

    # ------------------------------------------------------------------
    # Stage 3 — SERP (standard queue: async task_post -> tasks_ready -> task_get)
    # ------------------------------------------------------------------

    def serp_task_post(
        self,
        keywords: list[str],
        location_code: int = LOCATION_BRAZIL,
        language_code: str = LANGUAGE_PT,
        device: str = SERP_DEVICE,
        depth: int = SERP_DEPTH,
        tag: str = "",
    ) -> list[dict]:
        """Post SERP tasks to the STANDARD queue (never priority pricing).

        Returns [{"keyword", "task_id"}] for the accepted tasks; rejected
        tasks are reported and skipped (per-keyword isolation).
        """
        posted: list[dict] = []
        for i in range(0, len(keywords), SERP_TASKS_PER_POST):
            chunk = keywords[i : i + SERP_TASKS_PER_POST]
            payload = [
                {
                    "keyword": kw,
                    "location_code": location_code,
                    "language_code": language_code,
                    "device": device,
                    "depth": depth,
                    "tag": tag,
                }
                for kw in chunk
            ]
            resp = self._request(
                "POST",
                "/v3/serp/google/organic/task_post",
                payload,
                note=f"{len(chunk)} serp tasks",
            )
            # task_post replies one task per keyword; 20100 = "Task Created".
            for task in self._extract_tasks(resp):
                if task.get("status_code") in (20000, 20100):
                    kw = (task.get("data") or {}).get("keyword", "")
                    posted.append({"keyword": kw, "task_id": task.get("id")})
                else:
                    print(
                        f"[serp] task recusada: {task.get('status_code')} "
                        f"{task.get('status_message')}"
                    )
        return posted

    def serp_tasks_ready(self) -> list[dict]:
        """Tasks whose results are ready for collection."""
        resp = self._request("GET", "/v3/serp/google/organic/tasks_ready")
        return self._extract_result(resp)

    def serp_task_get(self, task_id: str) -> dict:
        """Collect one finished SERP result (regular format)."""
        resp = self._request("GET", f"/v3/serp/google/organic/task_get/regular/{task_id}")
        results = self._extract_result(resp)
        return results[0] if results else {}
