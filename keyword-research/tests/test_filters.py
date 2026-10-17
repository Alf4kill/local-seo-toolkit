"""Tests for core/filters.py — Stage 2 -> 3 keep/drop rules (table-driven)."""

from core.filters import filter_for_stage3
from core.normalize import normalize_key


def _row(keyword, volume=0, intent=""):
    return {"keyword": keyword, "volume": volume, "intent": intent}


def test_keep_by_volume():
    kept, dropped = filter_for_stage3([_row("kw", volume=10)])
    assert len(kept) == 1 and dropped == []
    assert kept[0]["keep"] == "sim"


def test_drop_below_volume_without_other_signal():
    kept, dropped = filter_for_stage3([_row("kw", volume=9)])
    assert kept == []
    assert dropped[0]["drop_reason"] == "sem-demanda-comprovada"


def test_keep_zero_volume_present_in_autocomplete():
    kept, _ = filter_for_stage3(
        [_row("configuração ssr", volume=0)],
        autocomplete_keys={normalize_key("configuracao ssr")},  # accent-insensitive
    )
    assert len(kept) == 1


def test_low_but_nonzero_volume_not_saved_by_autocomplete():
    # Spec rule is literal: volume == 0 AND present in autocomplete.
    kept, dropped = filter_for_stage3(
        [_row("kw", volume=5)], autocomplete_keys={normalize_key("kw")}
    )
    assert kept == []
    assert dropped[0]["drop_reason"] == "sem-demanda-comprovada"


def test_keep_gsc_weak_regardless_of_volume():
    kept, _ = filter_for_stage3([_row("kw", volume=0)], gsc_weak_keys={normalize_key("kw")})
    assert len(kept) == 1


def test_keep_radar_regardless_of_volume():
    kept, _ = filter_for_stage3([_row("kw", volume=0)], radar_keys={normalize_key("kw")})
    assert len(kept) == 1


def test_drop_when_already_in_keyword_map():
    kept, dropped = filter_for_stage3(
        [_row("kw", volume=100)], existing_map_keys={normalize_key("kw")}
    )
    assert kept == []
    assert dropped[0]["drop_reason"] == "ja-no-keyword-map"


def test_drop_by_intent_only_when_requested():
    rows = [_row("contratar agencia seo", volume=100, intent="commercial")]

    kept, dropped = filter_for_stage3(rows)
    assert len(kept) == 1  # no drop_intents passed -> intent never drops

    kept, dropped = filter_for_stage3(rows, drop_intents=frozenset({"commercial"}))
    assert kept == []
    assert dropped[0]["drop_reason"] == "intent-fora-do-escopo"


def test_volume_as_string_is_coerced():
    kept, _ = filter_for_stage3([_row("kw", volume="120")])
    assert len(kept) == 1


def test_dropped_rows_keep_all_fields_for_audit():
    rows = [{"keyword": "kw", "volume": 0, "intent": "", "source": "autocomplete", "cpc": "1.2"}]
    _, dropped = filter_for_stage3(rows)
    assert dropped[0]["source"] == "autocomplete"
    assert dropped[0]["cpc"] == "1.2"
    assert dropped[0]["keep"] == "nao"
