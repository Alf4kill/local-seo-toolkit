"""
config.py — Central constants for the keyword research pipeline.

All tunables live here (repo convention: no .env loading, plain module-level
constants). Secrets NEVER live here — DataForSEO credentials come from
environment variables only (see fetchers/dataforseo.py).
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Stage 1 — Google Autocomplete (unofficial endpoint; may break at any time)
# ---------------------------------------------------------------------------

SUGGEST_URL = "https://suggestqueries.google.com/complete/search"
SUGGEST_PARAMS = {"client": "firefox", "hl": "pt-BR", "gl": "br"}
SUGGEST_TIMEOUT = 10
SUGGEST_DELAY_S = 1.0  # base delay between requests (never hammer the endpoint)
SUGGEST_JITTER_S = 0.5  # + random.uniform(0, SUGGEST_JITTER_S) on every miss
QUESTION_PREFIXES = ["como", "o que é", "por que", "qual", "vale a pena"]
ALPHABET = "abcdefghijklmnopqrstuvwxyz"
RECURSE_TOP_N = 5  # max suggestions per seed re-expanded (one level only)
TTL_SUGGEST_HOURS = 168  # 7 days — suggestions are stable within a research cycle

# ---------------------------------------------------------------------------
# Stage 1 — Google Trends (pytrends, optional dependency)
# ---------------------------------------------------------------------------

TRENDS_GEO = "BR"
TRENDS_DELAY_S = 2.0  # anti rate-limit delay between seeds
TTL_TRENDS_HOURS = 24

# ---------------------------------------------------------------------------
# Stages 2/3 — DataForSEO
# ---------------------------------------------------------------------------

DATAFORSEO_BASE_URL = "https://api.dataforseo.com"
DATAFORSEO_TIMEOUT = 60
LOCATION_BRAZIL = 2076  # DataForSEO location_code for Brazil
LANGUAGE_PT = "pt"

# Cost guardrails. The monthly cap is checked BEFORE every paid request
# (core/ledger.py raises BudgetExceededError). Override the cap with the env
# var DATAFORSEO_MONTHLY_CAP or the --budget CLI flag.
MONTHLY_BUDGET_USD = 5.0
SEARCH_VOLUME_BATCH = 1000  # API max keywords per search_volume task
KEYWORD_IDEAS_LIMIT = 700  # max rows returned per keyword_ideas request
IDEAS_SEEDS_MAX = 20  # seeds sent to keyword_ideas (single request)
RELATED_SEEDS_TOP = 5  # seeds expanded via related_keywords (1 request each)

# Rough per-request cost estimates (USD) used ONLY by --dry-run to print an
# order-of-magnitude preview. Real costs come from each response's `cost`
# field and are logged to the ledger. Verify at https://dataforseo.com/pricing.
EST_COST_USD = {
    "keyword_ideas": 0.12,
    "related_keywords": 0.12,
    "search_volume": 0.075,  # per task of up to 1000 keywords
    "search_intent": 0.01,
    "serp_task": 0.002,  # per keyword, standard (non-priority) queue
}

# Stage 2 → 3 filter threshold
MIN_VOLUME_BR = 10  # keep keywords with >= this monthly search volume in BR

# Stage 3 — SERP spot-check (standard queue = async task_post/task_get)
SERP_DEPTH = 10
SERP_DEVICE = "desktop"
SERP_LIMIT_DEFAULT = 30  # spot-check, not a crawl
SERP_POLL_SECONDS = 30
SERP_POLL_TIMEOUT_S = 900
SERP_TASKS_PER_POST = 100  # API max tasks per task_post call
TTL_PAID_HOURS = 24 * 365  # paid responses effectively never expire (money rule)

# ---------------------------------------------------------------------------
# Stage 3 — SERP analysis heuristics (SUGGESTIONS only; analyst has final say)
# ---------------------------------------------------------------------------

BIG_BR_PLAYERS = {
    "conversion.com.br",
    "rockcontent.com",
    "resultadosdigitais.com.br",
}
OFFICIAL_DOCS_DOMAINS = {
    "vercel.com",
    "nextjs.org",
    "developers.google.com",
    "developer.mozilla.org",
    "react.dev",
    "web.dev",
}
# Case/accent-insensitive markers of fresh, framework-specific content in
# titles. Absence across the whole top 10 suggests a "target-now" verdict.
FRESHNESS_MARKERS = [
    "app router",
    "next 13",
    "next 14",
    "next 15",
    "next.js 13",
    "next.js 14",
    "next.js 15",
    "server components",
    "2024",
    "2025",
    "2026",
]
