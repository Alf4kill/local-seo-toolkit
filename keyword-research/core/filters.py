"""
filters.py — Stage 2 -> 3 filtering rules (pure logic, the business core).

Keep/drop decisions are auditable: dropped rows carry a `drop_reason` and are
returned alongside the kept ones, never silently discarded (honesty rule).
Intent dropping happens ONLY when the analyst explicitly passes intents to
drop — the tool never guesses content scope by itself.
"""

from config import MIN_VOLUME_BR

from core.normalize import normalize_key


def filter_for_stage3(
    rows: list[dict],
    *,
    autocomplete_keys: "set[str] | frozenset" = frozenset(),
    gsc_weak_keys: "set[str] | frozenset" = frozenset(),
    radar_keys: "set[str] | frozenset" = frozenset(),
    existing_map_keys: "set[str] | frozenset" = frozenset(),
    min_volume: int = MIN_VOLUME_BR,
    drop_intents: "set[str] | frozenset" = frozenset(),
) -> tuple[list[dict], list[dict]]:
    """Split validated rows into (kept, dropped).

    KEEP if ANY of:
      volume >= min_volume                        -> proven demand (Ads/Labs)
      volume == 0 and key in autocomplete_keys    -> typed demand proven
      key in gsc_weak_keys                        -> already ranks, winnable
      key in radar_keys                           -> news topic, volume N/A
    Then DROP (with reason) when:
      key in existing_map_keys  -> "ja-no-keyword-map"
      intent in drop_intents    -> "intent-fora-do-escopo"
    Rows that never matched a keep rule drop as "sem-demanda-comprovada".

    All key sets must be pre-normalized with normalize_key.
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    for row in rows:
        key = normalize_key(row.get("keyword", ""))
        volume = int(row.get("volume") or 0)
        keep = (
            volume >= min_volume
            or (volume == 0 and key in autocomplete_keys)
            or key in gsc_weak_keys
            or key in radar_keys
        )
        reason = None
        if not keep:
            reason = "sem-demanda-comprovada"
        elif key in existing_map_keys:
            reason = "ja-no-keyword-map"
        elif drop_intents and str(row.get("intent", "")).lower() in drop_intents:
            reason = "intent-fora-do-escopo"

        if reason:
            dropped.append({**row, "keep": "nao", "drop_reason": reason})
        else:
            kept.append({**row, "keep": "sim", "drop_reason": ""})
    return kept, dropped
