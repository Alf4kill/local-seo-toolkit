"""
autocomplete.py — Stage 1 discovery via Google Autocomplete.

UNOFFICIAL endpoint (no SLA — may change shape or start blocking at any
time). Posture copied from gsc-monitor's pytrends handling: defensive
parsing, never crash, cache aggressively, 1 req/s with jitter. Partial
results always survive an aborted run because every response is cached
before the next request goes out.
"""

import random
import time
from datetime import date

import requests
from config import (
    ALPHABET,
    QUESTION_PREFIXES,
    RECURSE_TOP_N,
    SUGGEST_DELAY_S,
    SUGGEST_JITTER_S,
    SUGGEST_PARAMS,
    SUGGEST_TIMEOUT,
    SUGGEST_URL,
    TTL_SUGGEST_HOURS,
)
from core.cache import _safe_key, get_cached, set_cached


def fetch_suggestions(query: str, timeout: int = SUGGEST_TIMEOUT) -> "list[str] | None":
    """GET the suggest endpoint for one query.

    The firefox client returns a JSON array: ["query", ["sug 1", "sug 2", ...]].
    Returns the suggestion list ([] when Google has none) or None on error —
    errors are never cached (repo rule), genuinely-empty results are.
    """
    try:
        resp = requests.get(SUGGEST_URL, params={**SUGGEST_PARAMS, "q": query}, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"[autocomplete] ERRO para '{query}': {exc}")
        return None
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        print(f"[autocomplete] resposta inesperada para '{query}' — ignorada")
        return None
    return [s.strip() for s in payload[1] if isinstance(s, str) and s.strip()]


def build_query_plan(seed: str) -> list[tuple[str, str]]:
    """(query, note) pairs for one seed: itself, a-z suffixes, question prefixes.

    32 queries per seed (1 + 26 + 5). Pure — fully unit-testable. The note
    records which expansion produced the query (goes into the CSV `notes`).
    """
    seed = seed.strip()
    plan = [(seed, "seed")]
    plan += [(f"{seed} {letter}", f"letra:{letter}") for letter in ALPHABET]
    plan += [(f"{prefix} {seed}", f"prefixo:{prefix}") for prefix in QUESTION_PREFIXES]
    return plan


def pick_recursion_candidates(
    suggestions: list[str], seed: str, top_n: int = RECURSE_TOP_N
) -> list[str]:
    """High-signal suggestions worth one extra expansion level.

    A candidate must extend the seed (startswith + strictly longer + at least
    one extra word), so recursion digs into long-tail variations instead of
    wandering off-topic. Capped at top_n, which bounds the worst case at
    32 + top_n*32 requests per seed.
    """
    seed_norm = seed.strip().lower()
    seed_words = len(seed_norm.split())
    out: list[str] = []
    for sug in suggestions:
        s = sug.strip().lower()
        if s != seed_norm and s.startswith(seed_norm) and len(s.split()) > seed_words:
            out.append(sug.strip())
            if len(out) >= top_n:
                break
    return out


def expand_seed(
    seed: str,
    project: str,
    use_cache: bool = True,
    delay: float = SUGGEST_DELAY_S,
    recursive: bool = True,
) -> list[dict]:
    """Expand one seed into candidate keyword rows via autocomplete.

    Cache-first per full query (key `suggest_{query}`, TTL 7 days); the
    rate-limit sleep happens ONLY on cache misses, so re-runs are instant.
    Returns Stage 1 rows: {keyword, source, seed, date_collected, notes}.
    """
    today = date.today().isoformat()
    rows: list[dict] = []
    stats = {"hits": 0, "misses": 0}

    def _get(query: str) -> list[str]:
        key = f"suggest_{_safe_key(query)}"
        if use_cache:
            cached = get_cached(project, key, TTL_SUGGEST_HOURS)
            if cached is not None:
                stats["hits"] += 1
                return cached
        suggestions = fetch_suggestions(query)
        if suggestions is not None:
            set_cached(project, key, suggestions)
        stats["misses"] += 1
        # Unofficial endpoint: 1 req/s base + jitter, even after errors.
        time.sleep(delay + random.uniform(0, SUGGEST_JITTER_S))
        return suggestions or []

    def _add(suggestions: list[str], note: str) -> None:
        for sug in suggestions:
            rows.append(
                {
                    "keyword": sug,
                    "source": "autocomplete",
                    "seed": seed,
                    "date_collected": today,
                    "notes": note,
                }
            )

    plain_suggestions: list[str] = []
    for query, note in build_query_plan(seed):
        suggestions = _get(query)
        _add(suggestions, note)
        if note == "seed":
            plain_suggestions = suggestions

    if recursive:
        for child in pick_recursion_candidates(plain_suggestions, seed):
            for query, _note in build_query_plan(child):
                _add(_get(query), f"recursao:{child}")

    print(
        f"[autocomplete] '{seed}': {len(rows)} sugestoes brutas "
        f"({stats['misses']} consultas, {stats['hits']} cache hits)"
    )
    return rows
