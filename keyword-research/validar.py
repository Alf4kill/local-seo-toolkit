"""
validar.py — Stage 2: validacao de keywords via DataForSEO.

Le o CSV de descoberta (Stage 1), expande via Labs (Keyword Ideas + Related
Keywords), valida volume via Google Ads Search Volume (batch), aplica as
regras de filtragem e grava:

    {data}_validacao.csv     — trilha de auditoria completa (mantidas + descartadas
                               com drop_reason)
    {data}_stage3_input.csv  — apenas as mantidas, entrada do serp.py

Custos: cada resposta tem seu campo `cost` gravado no ledger; o teto mensal
e verificado ANTES de cada chamada. Use --dry-run para ver o plano de
requisicoes e o custo estimado sem gastar nada (nem exige credenciais).

Uso:
    py validar.py --projeto seotecnico.dev.br --dry-run
    py validar.py --projeto seotecnico.dev.br --keyword-map E:\\blog\\keyword-map.md
    py validar.py --projeto X --entrada CSV --intent --drop-intent commercial,transactional
    py validar.py --projeto X --max-keywords 200 --budget 0.50
"""

import sys

# Force UTF-8 stdout/stderr (default Windows terminals use cp1252).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import math
import os
from dataclasses import dataclass
from datetime import date

from config import (
    EST_COST_USD,
    IDEAS_SEEDS_MAX,
    KEYWORD_IDEAS_LIMIT,
    RELATED_SEEDS_TOP,
    SEARCH_VOLUME_BATCH,
)
from core import ledger
from core.filters import filter_for_stage3
from core.keyword_map import load_keyword_map
from core.normalize import dedupe_rows, normalize_key
from core.storage import _report_path, latest_report, read_csv, write_csv
from fetchers.dataforseo import DataForSEOClient, DataForSEOError

VALIDATION_CSV_COLUMNS = [
    "keyword",
    "normalized",
    "volume",
    "cpc",
    "competition",
    "intent",
    "source",
    "seed",
    "keep",
    "drop_reason",
]
STAGE3_CSV_COLUMNS = ["keyword", "volume", "intent", "source"]


class PipelineError(RuntimeError):
    """Fatal error in a validation run (missing input, missing credentials)."""


@dataclass(frozen=True)
class ValidationOptions:
    """Validation toggles — single source of truth for the CLI."""

    entrada: "str | None" = None
    keyword_map: "str | None" = None
    intent: bool = False
    drop_intent: tuple = ()
    max_keywords: int = 2000
    budget: "float | None" = None
    dry_run: bool = False
    sem_expansao: bool = False
    related_depth: int = 1


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested without any client)
# ---------------------------------------------------------------------------


def _keys_by_source(rows: list[dict], sources: set[str]) -> set[str]:
    """Normalized keys of the Stage 1 rows coming from the given sources."""
    return {
        normalize_key(r["keyword"]) for r in rows if r.get("keyword") and r.get("source") in sources
    }


def _distinct_seeds(rows: list[dict]) -> list[str]:
    """Distinct seed terms from Stage 1 rows, first-seen order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for r in rows:
        seed = (r.get("seed") or "").strip()
        key = normalize_key(seed)
        if key and key not in seen:
            seen.add(key)
            out.append(seed)
    return out


def _unwrap_items(result: list) -> list:
    """Labs live results wrap rows as result[0]["items"]; Ads results are flat.

    Handles both shapes so every parse_* helper takes the raw task result.
    """
    items: list = []
    for block in result or []:
        if isinstance(block, dict) and isinstance(block.get("items"), list):
            items.extend(block["items"])
        elif isinstance(block, dict):
            items.append(block)
    return items


def parse_labs_items(result: list, source: str, seed: str = "") -> list[dict]:
    """Normalize Labs items (keyword_ideas / related_keywords) into candidates.

    related_keywords nests data under "keyword_data"; keyword_ideas is flat.
    Both carry keyword_info with search_volume/cpc/competition — used as the
    expansion rows' volume so they don't need a second (paid) Ads lookup.
    """
    out: list[dict] = []
    for item in _unwrap_items(result):
        data = item.get("keyword_data") or item
        kw = data.get("keyword")
        if not kw or not isinstance(kw, str):
            continue
        info = data.get("keyword_info") or {}
        out.append(
            {
                "keyword": kw.strip(),
                "source": source,
                "seed": seed,
                "volume": info.get("search_volume") or 0,
                "cpc": info.get("cpc") if info.get("cpc") is not None else "",
                "competition": info.get("competition")
                if info.get("competition") is not None
                else "",
            }
        )
    return out


def parse_volume_items(result: list) -> dict[str, dict]:
    """Map normalized keyword -> {volume, cpc, competition} from Ads results."""
    out: dict[str, dict] = {}
    for item in _unwrap_items(result):
        kw = item.get("keyword")
        if not kw:
            continue
        out[normalize_key(kw)] = {
            "volume": item.get("search_volume") or 0,
            "cpc": item.get("cpc") if item.get("cpc") is not None else "",
            "competition": item.get("competition") if item.get("competition") is not None else "",
        }
    return out


def parse_intent_items(result: list) -> dict[str, str]:
    """Map normalized keyword -> intent label from Search Intent results."""
    out: dict[str, str] = {}
    for item in _unwrap_items(result):
        kw = item.get("keyword")
        if kw:
            out[normalize_key(kw)] = (item.get("keyword_intent") or {}).get("label", "")
    return out


def build_validated_rows(
    candidates: list[dict], volume_map: dict[str, dict], intent_map: dict[str, str]
) -> list[dict]:
    """Merge candidates with Ads volume + intent lookups into audit rows."""
    rows: list[dict] = []
    for c in candidates:
        key = normalize_key(c["keyword"])
        volume = c.get("volume")
        cpc = c.get("cpc", "")
        competition = c.get("competition", "")
        vol_info = volume_map.get(key)
        if vol_info is not None:
            volume = vol_info["volume"]
            cpc = vol_info["cpc"]
            competition = vol_info["competition"]
        rows.append(
            {
                "keyword": c["keyword"],
                "normalized": key,
                "volume": int(volume or 0),
                "cpc": cpc,
                "competition": competition,
                "intent": intent_map.get(key, ""),
                "source": c.get("source", ""),
                "seed": c.get("seed", ""),
            }
        )
    return rows


def estimate_plan(n_stage1: int, n_seeds: int, options: ValidationOptions) -> dict:
    """Request plan + rough cost preview for --dry-run (uses EST_COST_USD).

    Estimates only — real costs come from the API's `cost` field and land in
    the ledger. Verify prices at https://dataforseo.com/pricing.
    """
    ideas_calls = 0 if (options.sem_expansao or n_seeds == 0) else 1
    related_calls = 0 if options.sem_expansao else min(n_seeds, RELATED_SEEDS_TOP)
    est_expansion = ideas_calls * KEYWORD_IDEAS_LIMIT + related_calls * 100
    est_candidates = min(n_stage1 + est_expansion, options.max_keywords)
    volume_chunks = math.ceil(min(n_stage1, options.max_keywords) / SEARCH_VOLUME_BATCH)
    intent_chunks = math.ceil(est_candidates / SEARCH_VOLUME_BATCH) if options.intent else 0
    est_cost = (
        ideas_calls * EST_COST_USD["keyword_ideas"]
        + related_calls * EST_COST_USD["related_keywords"]
        + volume_chunks * EST_COST_USD["search_volume"]
        + intent_chunks * EST_COST_USD["search_intent"]
    )
    return {
        "ideas_calls": ideas_calls,
        "related_calls": related_calls,
        "volume_chunks": volume_chunks,
        "intent_chunks": intent_chunks,
        "est_candidates": est_candidates,
        "est_cost_usd": round(est_cost, 4),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_validation(
    project: str,
    options: "ValidationOptions | None" = None,
    client: "DataForSEOClient | None" = None,
) -> dict:
    """Run Stage 2. `client` is injectable for tests; --dry-run needs neither
    client nor credentials. Raises PipelineError on fatal input problems."""
    if options is None:
        options = ValidationOptions()

    input_csv = options.entrada or latest_report(project, "descoberta")
    if not input_csv or not os.path.exists(input_csv):
        raise PipelineError(
            "nenhum CSV de descoberta encontrado — rode descobrir.py antes (ou use --entrada)."
        )
    stage1_rows = read_csv(input_csv)
    if not stage1_rows:
        raise PipelineError(f"CSV de descoberta vazio: {input_csv}")
    print(f"[validar] {len(stage1_rows)} keywords de {os.path.basename(input_csv)}")

    autocomplete_keys = _keys_by_source(stage1_rows, {"autocomplete"})
    gsc_weak_keys = _keys_by_source(stage1_rows, {"gsc-weak"})
    radar_keys = _keys_by_source(stage1_rows, {"radar"})
    seeds = _distinct_seeds(stage1_rows)
    map_keys = load_keyword_map(options.keyword_map)

    if options.dry_run:
        plan = estimate_plan(len(stage1_rows), len(seeds), options)
        print("[validar] --dry-run: nenhuma chamada sera feita.")
        print(f"[validar]   keyword_ideas : {plan['ideas_calls']} req ({len(seeds)} seeds)")
        print(f"[validar]   related_kw    : {plan['related_calls']} req")
        print(f"[validar]   search_volume : {plan['volume_chunks']} req (lotes de 1000)")
        print(f"[validar]   search_intent : {plan['intent_chunks']} req")
        print(f"[validar]   custo estimado: ~${plan['est_cost_usd']:.2f} (verifique o pricing)")
        return {"project": project, "dry_run": True, **plan}

    if client is None:
        client = DataForSEOClient.from_env(monthly_cap=options.budget)
    spent = ledger.month_total(client.ledger_path)
    print(f"[custo] mes atual: ${spent:.2f} / limite ${client.monthly_cap:.2f}")

    # Stage 1 keywords: volume unknown (None) -> resolved via Ads batch below.
    stage1_candidates = [
        {
            "keyword": r["keyword"],
            "source": r.get("source", ""),
            "seed": r.get("seed", ""),
            "volume": None,
        }
        for r in stage1_rows
        if r.get("keyword")
    ]

    expansion_rows: list[dict] = []
    if not options.sem_expansao:
        ideas_seeds = seeds[:IDEAS_SEEDS_MAX]
        if ideas_seeds:
            print(f"[validar] Keyword Ideas para {len(ideas_seeds)} seed(s)...")
            expansion_rows.extend(
                parse_labs_items(client.keyword_ideas(ideas_seeds), "dataforseo-ideas")
            )
        for seed in seeds[:RELATED_SEEDS_TOP]:
            print(f"[validar] Related Keywords: '{seed}'...")
            expansion_rows.extend(
                parse_labs_items(
                    client.related_keywords(seed, depth=options.related_depth),
                    "dataforseo-related",
                    seed=seed,
                )
            )
        print(f"[validar] {len(expansion_rows)} candidatas da expansao")

    # Stage 1 first: discovery keywords never lose their slot to expansion.
    candidates = dedupe_rows(stage1_candidates + expansion_rows)[: options.max_keywords]

    need_volume = [c["keyword"] for c in candidates if c.get("volume") is None]
    volume_map: dict[str, dict] = {}
    if need_volume:
        print(f"[validar] Volume (Google Ads) para {len(need_volume)} keywords...")
        volume_map = parse_volume_items(client.search_volume(need_volume))

    intent_map: dict[str, str] = {}
    if options.intent:
        all_kw = [c["keyword"] for c in candidates]
        print(f"[validar] Search Intent para {len(all_kw)} keywords...")
        intent_map = parse_intent_items(client.search_intent(all_kw))

    validated = build_validated_rows(candidates, volume_map, intent_map)
    kept, dropped = filter_for_stage3(
        validated,
        autocomplete_keys=autocomplete_keys,
        gsc_weak_keys=gsc_weak_keys,
        radar_keys=radar_keys,
        existing_map_keys=map_keys,
        drop_intents=frozenset(i.lower() for i in options.drop_intent),
    )

    today = date.today().isoformat()
    audit_path = write_csv(
        _report_path(project, today, "validacao"), VALIDATION_CSV_COLUMNS, kept + dropped
    )
    stage3_path = write_csv(_report_path(project, today, "stage3_input"), STAGE3_CSV_COLUMNS, kept)

    print(f"[validar] {len(kept)} mantidas / {len(dropped)} descartadas (auditoria no CSV).")
    print(f"[validar] Auditoria : {audit_path}")
    print(f"[validar] Stage 3   : {stage3_path}")

    return {
        "project": project,
        "date": today,
        "kept": len(kept),
        "dropped": len(dropped),
        "audit_path": audit_path,
        "stage3_path": stage3_path,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 2 — validacao de keywords via DataForSEO (volume/CPC + filtros)"
    )
    parser.add_argument("--projeto", required=True, help="Nome do projeto (pasta em relatorios/).")
    parser.add_argument(
        "--entrada",
        default=None,
        metavar="CSV",
        help="CSV de descoberta a validar (padrao: o mais recente do projeto).",
    )
    parser.add_argument(
        "--keyword-map",
        dest="keyword_map",
        default=None,
        metavar="MD",
        help="Caminho do keyword-map.md do blog para descartar duplicatas (opcional).",
    )
    parser.add_argument(
        "--intent",
        action="store_true",
        help="Consulta o Search Intent (barato) e grava o rotulo por keyword.",
    )
    parser.add_argument(
        "--drop-intent",
        dest="drop_intent",
        default="",
        metavar="LISTA",
        help="Intents a descartar, separadas por virgula (ex: commercial,transactional). "
        "Sem essa flag, nenhuma keyword e descartada por intent.",
    )
    parser.add_argument(
        "--max-keywords",
        dest="max_keywords",
        type=int,
        default=2000,
        help="Teto de keywords enviadas para validacao (fusivel de custo; padrao: 2000).",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Teto de gasto mensal em USD para esta execucao "
        "(padrao: config/env DATAFORSEO_MONTHLY_CAP).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Mostra o plano de requisicoes e o custo estimado sem chamar a API.",
    )
    parser.add_argument(
        "--sem-expansao",
        dest="sem_expansao",
        action="store_true",
        help="Pula Keyword Ideas / Related Keywords (valida so o CSV de entrada).",
    )
    parser.add_argument(
        "--related-depth",
        dest="related_depth",
        type=int,
        choices=[1, 2],
        default=1,
        help="Profundidade do Related Keywords (1 ou 2; padrao: 1).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    drop_intent = tuple(i.strip() for i in args.drop_intent.split(",") if i.strip())
    options = ValidationOptions(
        entrada=args.entrada,
        keyword_map=args.keyword_map,
        intent=args.intent,
        drop_intent=drop_intent,
        max_keywords=args.max_keywords,
        budget=args.budget,
        dry_run=args.dry_run,
        sem_expansao=args.sem_expansao,
        related_depth=args.related_depth,
    )
    try:
        run_validation(args.projeto, options)
    except (PipelineError, DataForSEOError, ledger.BudgetExceededError) as exc:
        print(f"[validar] ERRO: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
