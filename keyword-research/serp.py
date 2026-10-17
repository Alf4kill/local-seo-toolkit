"""
serp.py — Stage 3: spot-check de SERP via DataForSEO (fila standard, assincrona).

Le o {data}_stage3_input.csv (saida do validar.py), posta tasks de SERP
organica (google.com.br, pt, desktop, top-10) na fila STANDARD — nunca a
prioritaria —, faz polling ate coletar os resultados e grava o CSV de revisao
editavel do analista:

    {data}_serp_review.csv   (delimitado por ';', com aviso de SUGESTAO)

Resiliencia: os task_ids pendentes ficam em .cache/serp_pending.json. Se a
fila demorar alem do timeout, o script sai com instrucao de re-rodar com
--fetch (so coleta, nao posta nada novo). SERPs ja pagas ficam em cache
"eterno" e nunca sao recompradas.

Uso:
    py serp.py --projeto seotecnico.dev.br
    py serp.py --projeto seotecnico.dev.br --limite 10
    py serp.py --projeto seotecnico.dev.br --fetch      # so drena pendencias
"""

import sys

# Force UTF-8 stdout/stderr (default Windows terminals use cp1252).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import date

from config import (
    BIG_BR_PLAYERS,
    FRESHNESS_MARKERS,
    OFFICIAL_DOCS_DOMAINS,
    SERP_DEVICE,
    SERP_LIMIT_DEFAULT,
    SERP_POLL_SECONDS,
    SERP_POLL_TIMEOUT_S,
    TTL_PAID_HOURS,
)
from core import ledger
from core.cache import _cache_dir, _safe_key, get_cached, set_cached
from core.normalize import normalize_key
from core.serp_analysis import analyze_serp, extract_top_domains, suggest_verdict
from core.storage import _report_path, latest_report, read_csv, write_csv
from fetchers.dataforseo import DataForSEOClient, DataForSEOError

SERP_REVIEW_COLUMNS = [
    "keyword",
    "volume",
    "verdict_sugerido",
    "motivo",
    "verdict_final",
    "big_players",
    "docs_oficiais",
    "top_dominios",
    "gap_notes",
]
REVIEW_COMMENTS = [
    "SUGESTAO — o veredito final e do analista. Edite verdict_final e gap_notes.",
    "Valores de verdict_final: target-now / target-later / skip",
]


class PipelineError(RuntimeError):
    """Fatal error in a SERP run (missing input, missing credentials)."""


@dataclass(frozen=True)
class SerpOptions:
    """SERP spot-check toggles — single source of truth for the CLI."""

    entrada: "str | None" = None
    limite: int = SERP_LIMIT_DEFAULT
    fetch_only: bool = False
    budget: "float | None" = None
    mobile: bool = False


# ---------------------------------------------------------------------------
# Pending-task persistence (crash/timeout resilience)
# ---------------------------------------------------------------------------


def _pending_path(project: str) -> str:
    return os.path.join(_cache_dir(project), "serp_pending.json")


def load_pending(project: str) -> dict:
    """{keyword: task_id} still waiting in the standard queue."""
    path = _pending_path(project)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_pending(project: str, pending: dict) -> None:
    with open(_pending_path(project), "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)


def _serp_key(keyword: str) -> str:
    return f"serp_{_safe_key(normalize_key(keyword))}"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _drain_pending(
    client: DataForSEOClient,
    project: str,
    pending: dict,
    poll_seconds: "float | None" = None,
    timeout_s: "float | None" = None,
) -> dict:
    """Poll tasks_ready and collect finished SERPs into the paid cache.

    The pending file is rewritten after every collection, so an interrupted
    run never loses (nor re-buys) results. Returns what is still pending.
    Defaults resolve at call time so tests can patch the module constants.
    """
    if poll_seconds is None:
        poll_seconds = SERP_POLL_SECONDS
    if timeout_s is None:
        timeout_s = SERP_POLL_TIMEOUT_S
    deadline = time.monotonic() + timeout_s
    by_task_id = {tid: kw for kw, tid in pending.items()}
    while pending:
        ready = client.serp_tasks_ready()
        for task in ready:
            kw = by_task_id.get(task.get("id"))
            if kw is None:
                continue  # task from another run/tool — leave it alone
            result = client.serp_task_get(task["id"])
            set_cached(project, _serp_key(kw), result)
            by_task_id.pop(task["id"], None)
            pending.pop(kw, None)
            save_pending(project, pending)
            print(f"[serp] coletado: '{kw}' ({len(pending)} pendentes)")
        if not pending or time.monotonic() >= deadline:
            break
        print(f"[serp] aguardando fila standard... ({len(pending)} pendentes)")
        time.sleep(poll_seconds)
    return pending


def run_serp_check(
    project: str,
    options: "SerpOptions | None" = None,
    client: "DataForSEOClient | None" = None,
) -> dict:
    """Run Stage 3. `client` is injectable for tests. Raises PipelineError
    on missing input; exits gracefully (not an error) on queue timeouts."""
    if options is None:
        options = SerpOptions()

    input_csv = options.entrada or latest_report(project, "stage3_input")
    if not input_csv or not os.path.exists(input_csv):
        raise PipelineError(
            "nenhum stage3_input encontrado — rode validar.py antes (ou use --entrada)."
        )
    rows = read_csv(input_csv)
    volumes = {normalize_key(r["keyword"]): r.get("volume", "") for r in rows if r.get("keyword")}
    keywords = [r["keyword"] for r in rows if r.get("keyword")][: options.limite]
    print(f"[serp] {len(keywords)} keywords no escopo (de {os.path.basename(input_csv)})")

    pending = load_pending(project)

    if not options.fetch_only:
        to_post = [
            kw
            for kw in keywords
            if kw not in pending and get_cached(project, _serp_key(kw), TTL_PAID_HOURS) is None
        ]
        if to_post:
            if client is None:
                client = DataForSEOClient.from_env(monthly_cap=options.budget)
            spent = ledger.month_total(client.ledger_path)
            print(f"[custo] mes atual: ${spent:.2f} / limite ${client.monthly_cap:.2f}")
            device = "mobile" if options.mobile else SERP_DEVICE
            print(f"[serp] postando {len(to_post)} tasks na fila standard ({device})...")
            for p in client.serp_task_post(to_post, device=device, tag=project):
                pending[p["keyword"]] = p["task_id"]
            save_pending(project, pending)
        else:
            print("[serp] nada novo a postar (cache/pendencias ja cobrem o escopo).")

    if pending:
        if client is None:
            client = DataForSEOClient.from_env(monthly_cap=options.budget)
        pending = _drain_pending(client, project, pending)

    # Build the analyst review from whatever is cached now.
    analyzed: list[dict] = []
    missing: list[str] = []
    for kw in keywords:
        serp = get_cached(project, _serp_key(kw), TTL_PAID_HOURS)
        if serp is None:
            missing.append(kw)
            continue
        analysis = analyze_serp(
            extract_top_domains(serp), BIG_BR_PLAYERS, OFFICIAL_DOCS_DOMAINS, FRESHNESS_MARKERS
        )
        verdict, motivo = suggest_verdict(analysis)
        analyzed.append(
            {
                "keyword": kw,
                "volume": volumes.get(normalize_key(kw), ""),
                "verdict_sugerido": verdict,
                "motivo": motivo,
                "verdict_final": "",
                "big_players": " | ".join(analysis["big_players_present"]),
                "docs_oficiais": " | ".join(analysis["official_docs_present"]),
                "top_dominios": " | ".join(analysis["top_domains"]),
                "gap_notes": "",
            }
        )

    today = date.today().isoformat()
    review_path = None
    if analyzed:
        review_path = write_csv(
            _report_path(project, today, "serp_review"),
            SERP_REVIEW_COLUMNS,
            analyzed,
            delimiter=";",
            comments=REVIEW_COMMENTS,
        )
        print(f"[serp] revisao gravada ({len(analyzed)} keywords): {review_path}")
    if missing:
        print(f"[serp] {len(missing)} keywords ainda sem resultado (fila standard demora).")
        print(f"[serp] Re-rode mais tarde: py serp.py --projeto {project} --fetch")

    return {
        "project": project,
        "date": today,
        "analyzed": len(analyzed),
        "missing": missing,
        "review_path": review_path,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 3 — spot-check de SERP (google.com.br, pt, fila standard)"
    )
    parser.add_argument("--projeto", required=True, help="Nome do projeto (pasta em relatorios/).")
    parser.add_argument(
        "--entrada",
        default=None,
        metavar="CSV",
        help="stage3_input.csv a usar (padrao: o mais recente do projeto).",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=SERP_LIMIT_DEFAULT,
        help=f"Maximo de keywords a checar (spot-check; padrao: {SERP_LIMIT_DEFAULT}).",
    )
    parser.add_argument(
        "--fetch",
        dest="fetch_only",
        action="store_true",
        help="So coleta tasks pendentes de uma execucao anterior (nao posta nada novo).",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Teto de gasto mensal em USD para esta execucao.",
    )
    parser.add_argument(
        "--mobile",
        action="store_true",
        help="Usa device mobile (padrao: desktop; use so para topicos mobile-first).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    options = SerpOptions(
        entrada=args.entrada,
        limite=args.limite,
        fetch_only=args.fetch_only,
        budget=args.budget,
        mobile=args.mobile,
    )
    try:
        run_serp_check(args.projeto, options)
    except (PipelineError, DataForSEOError, ledger.BudgetExceededError) as exc:
        print(f"[serp] ERRO: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
