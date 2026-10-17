"""Tests for validar.py — Stage 2 orchestration with a fake client."""

import pytest
from core.storage import KEYWORD_CSV_COLUMNS, _report_path, read_csv, write_csv
from validar import (
    PipelineError,
    ValidationOptions,
    build_validated_rows,
    estimate_plan,
    parse_intent_items,
    parse_labs_items,
    parse_volume_items,
    run_validation,
)


class FakeClient:
    """Scripted DataForSEOClient double."""

    def __init__(self):
        self.ledger_path = "ignorado.csv"
        self.monthly_cap = 5.0
        self.calls = []

    def keyword_ideas(self, keywords, **kw):
        self.calls.append(("ideas", tuple(keywords)))
        return [
            {
                "items": [
                    {"keyword": "ideia nova", "keyword_info": {"search_volume": 90, "cpc": 0.4}}
                ]
            }
        ]

    def related_keywords(self, keyword, **kw):
        self.calls.append(("related", keyword))
        return [
            {
                "items": [
                    {
                        "keyword_data": {
                            "keyword": f"{keyword} relacionada",
                            "keyword_info": {"search_volume": 30},
                        }
                    }
                ]
            }
        ]

    def search_volume(self, keywords, **kw):
        self.calls.append(("volume", tuple(keywords)))
        return [{"keyword": kw_, "search_volume": 50, "cpc": 1.0} for kw_ in keywords]

    def search_intent(self, keywords, **kw):
        self.calls.append(("intent", tuple(keywords)))
        return [
            {"items": [{"keyword": kw_, "keyword_intent": {"label": "informational"}}]}
            for kw_ in keywords
        ]


def _stage1_csv(project, rows, date="2026-07-15"):
    path = _report_path(project, date, "descoberta")
    write_csv(path, KEYWORD_CSV_COLUMNS, rows)
    return path


def _row(keyword, source="autocomplete", seed="seed x"):
    return {
        "keyword": keyword,
        "source": source,
        "seed": seed,
        "date_collected": "2026-07-15",
        "notes": "",
    }


# ---------------------------------------------------------------------------
# Pure parsers
# ---------------------------------------------------------------------------


def test_parse_labs_items_flat_and_nested():
    result = [
        {
            "items": [
                {"keyword": "flat kw", "keyword_info": {"search_volume": 10, "cpc": 0.5}},
                {"keyword_data": {"keyword": "nested kw", "keyword_info": {"search_volume": 0}}},
                {"sem_keyword": True},
            ]
        }
    ]
    rows = parse_labs_items(result, "dataforseo-ideas", seed="s")
    assert [(r["keyword"], r["volume"]) for r in rows] == [("flat kw", 10), ("nested kw", 0)]
    assert all(r["source"] == "dataforseo-ideas" and r["seed"] == "s" for r in rows)


def test_parse_volume_items_maps_normalized_keys():
    result = [{"keyword": "Configuração SSR", "search_volume": 70, "cpc": None}]
    vol = parse_volume_items(result)
    assert vol["configuracao ssr"]["volume"] == 70
    assert vol["configuracao ssr"]["cpc"] == ""


def test_parse_volume_items_none_volume_is_zero():
    vol = parse_volume_items([{"keyword": "kw", "search_volume": None}])
    assert vol["kw"]["volume"] == 0


def test_parse_intent_items():
    result = [{"items": [{"keyword": "kw", "keyword_intent": {"label": "commercial"}}]}]
    assert parse_intent_items(result) == {"kw": "commercial"}


def test_build_validated_rows_prefers_ads_volume():
    candidates = [{"keyword": "kw", "source": "autocomplete", "seed": "s", "volume": None}]
    rows = build_validated_rows(
        candidates, {"kw": {"volume": 40, "cpc": 2.0, "competition": 0.3}}, {}
    )
    assert rows[0]["volume"] == 40
    assert rows[0]["cpc"] == 2.0
    assert rows[0]["normalized"] == "kw"


def test_build_validated_rows_keeps_labs_volume_when_no_ads_lookup():
    candidates = [{"keyword": "kw", "source": "dataforseo-ideas", "seed": "", "volume": 90}]
    rows = build_validated_rows(candidates, {}, {"kw": "informational"})
    assert rows[0]["volume"] == 90
    assert rows[0]["intent"] == "informational"


# ---------------------------------------------------------------------------
# estimate_plan (dry-run)
# ---------------------------------------------------------------------------


def test_estimate_plan_counts_requests():
    plan = estimate_plan(1500, 8, ValidationOptions())
    assert plan["ideas_calls"] == 1
    assert plan["related_calls"] == 5  # capped at RELATED_SEEDS_TOP
    assert plan["volume_chunks"] == 2  # 1500 kw -> 2 batches
    assert plan["intent_chunks"] == 0
    assert plan["est_cost_usd"] > 0


def test_estimate_plan_sem_expansao():
    plan = estimate_plan(100, 8, ValidationOptions(sem_expansao=True))
    assert plan["ideas_calls"] == 0
    assert plan["related_calls"] == 0
    assert plan["volume_chunks"] == 1


# ---------------------------------------------------------------------------
# run_validation
# ---------------------------------------------------------------------------


def test_run_validation_requires_discovery_csv():
    with pytest.raises(PipelineError):
        run_validation("proj-sem-descoberta", ValidationOptions())


def test_dry_run_needs_no_client_or_credentials():
    project = "proj-val-dry"
    _stage1_csv(project, [_row("kw a"), _row("kw b")])
    summary = run_validation(project, ValidationOptions(dry_run=True))
    assert summary["dry_run"] is True
    assert summary["est_cost_usd"] > 0


def test_run_validation_end_to_end_with_fake_client():
    project = "proj-val-e2e"
    _stage1_csv(
        project,
        [
            _row("kw autocomplete"),
            _row("kw fraca gsc", source="gsc-weak", seed=""),
            _row("kw radar", source="radar", seed=""),
        ],
    )
    client = FakeClient()
    summary = run_validation(project, ValidationOptions(intent=True), client=client)

    # Stage 1 keywords got Ads volume (50) and expansion came from Labs.
    audit = read_csv(summary["audit_path"])
    by_kw = {r["keyword"]: r for r in audit}
    assert by_kw["kw autocomplete"]["volume"] == "50"
    assert by_kw["kw autocomplete"]["keep"] == "sim"
    assert by_kw["ideia nova"]["volume"] == "90"  # Labs volume, no Ads re-lookup
    assert by_kw["kw fraca gsc"]["keep"] == "sim"
    assert by_kw["kw radar"]["keep"] == "sim"
    assert all(r["intent"] == "informational" for r in audit)

    stage3 = read_csv(summary["stage3_path"])
    assert len(stage3) == summary["kept"]

    # Ads volume was requested only for Stage 1 keywords (expansion has Labs volume).
    volume_calls = [c for c in client.calls if c[0] == "volume"]
    assert volume_calls == [("volume", ("kw autocomplete", "kw fraca gsc", "kw radar"))]


def test_run_validation_drops_keyword_map_duplicates(tmp_path):
    project = "proj-val-map"
    _stage1_csv(project, [_row("kw coberta"), _row("kw nova")])
    map_path = tmp_path / "keyword-map.md"
    map_path.write_text("- kw coberta\n", encoding="utf-8")

    client = FakeClient()
    options = ValidationOptions(keyword_map=str(map_path), sem_expansao=True)
    summary = run_validation(project, options, client=client)

    audit = {r["keyword"]: r for r in read_csv(summary["audit_path"])}
    assert audit["kw coberta"]["drop_reason"] == "ja-no-keyword-map"
    assert audit["kw nova"]["keep"] == "sim"


def test_run_validation_max_keywords_caps_candidates():
    project = "proj-val-cap"
    _stage1_csv(project, [_row(f"kw {i}") for i in range(10)])
    client = FakeClient()
    options = ValidationOptions(max_keywords=4, sem_expansao=True)
    summary = run_validation(project, options, client=client)
    assert summary["kept"] + summary["dropped"] == 4
