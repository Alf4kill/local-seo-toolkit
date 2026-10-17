"""
descobrir.py — Stage 1: descoberta gratuita de keywords.

Expande seeds via Google Autocomplete (a-z + prefixos de pergunta + 1 nivel
de recursao), opcionalmente mescla Google Trends (--trends) e o export do
gsc-monitor (--gsc-csv), deduplica (chave sem acentos) e grava o CSV de
descoberta consumido pelo Stage 2 (validar.py).

Uso:
    py descobrir.py --projeto seotecnico.dev.br --seeds seeds.txt
    py descobrir.py --projeto seotecnico.dev.br --seed "next.js seo" --seed "cwv"
    py descobrir.py --projeto X --seeds seeds.txt --gsc-csv CAMINHO\2026-07-15_keywords_gsc.csv
    py descobrir.py --projeto X --seeds seeds.txt --trends --no-cache
"""

import sys

# Force UTF-8 stdout/stderr so Unicode output works on default Windows
# terminals (cp1252). Same preamble as every gsc-monitor entry point.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import os
from dataclasses import dataclass
from datetime import date

from config import SUGGEST_DELAY_S
from core.normalize import dedupe_rows
from core.storage import KEYWORD_CSV_COLUMNS, _report_path, read_csv, write_csv
from fetchers.autocomplete import expand_seed


class PipelineError(RuntimeError):
    """Fatal error in a discovery run (bad input file, no seeds)."""


@dataclass(frozen=True)
class DiscoveryOptions:
    """Discovery toggles — single source of truth for the CLI (ReportOptions idiom)."""

    trends: bool = False
    gsc_csv: "str | None" = None
    no_cache: bool = False
    no_recursion: bool = False
    delay: float = SUGGEST_DELAY_S


def load_seeds_file(path: str) -> list[str]:
    """One seed per line; blank lines and # comments ignored."""
    if not os.path.exists(path):
        raise PipelineError(f"arquivo de seeds nao encontrado: {path}")
    seeds = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                seeds.append(line)
    return seeds


def load_gsc_rows(path: str) -> list[dict]:
    """Load Stage-1 rows exported by gsc-monitor/exportar_keywords.py."""
    if not os.path.exists(path):
        raise PipelineError(f"CSV do GSC nao encontrado: {path}")
    rows = read_csv(path)
    if rows:
        missing = [c for c in KEYWORD_CSV_COLUMNS if c not in rows[0]]
        if missing:
            raise PipelineError(f"CSV do GSC sem colunas esperadas: {', '.join(missing)}")
    print(f"[descobrir] {len(rows)} keywords importadas de {os.path.basename(path)}")
    return rows


def run_discovery(
    project: str, seeds: list[str], options: "DiscoveryOptions | None" = None
) -> dict:
    """Run Stage 1 for a project and write {date}_descoberta.csv.

    Raises PipelineError on fatal input problems (instead of sys.exit, so the
    function stays importable). Returns a run summary dict.
    """
    if options is None:
        options = DiscoveryOptions()
    if not seeds:
        raise PipelineError("nenhuma seed informada (--seeds ARQUIVO ou --seed TERMO).")

    today = date.today().isoformat()
    print(f"[descobrir] projeto: {project} — {len(seeds)} seed(s)")

    rows: list[dict] = []
    for seed in seeds:
        rows.extend(
            expand_seed(
                seed,
                project,
                use_cache=not options.no_cache,
                delay=options.delay,
                recursive=not options.no_recursion,
            )
        )

    if options.trends:
        from fetchers.trends import fetch_related_queries

        rows.extend(fetch_related_queries(seeds, project, use_cache=not options.no_cache))

    if options.gsc_csv:
        rows.extend(load_gsc_rows(options.gsc_csv))

    total_raw = len(rows)
    rows = dedupe_rows(rows)

    by_source: dict[str, int] = {}
    for row in rows:
        by_source[row["source"]] = by_source.get(row["source"], 0) + 1

    csv_path = write_csv(_report_path(project, today, "descoberta"), KEYWORD_CSV_COLUMNS, rows)
    print(f"[descobrir] {total_raw} brutas -> {len(rows)} unicas. CSV: {csv_path}")
    for source, count in sorted(by_source.items()):
        print(f"[descobrir]   {source}: {count}")

    return {
        "project": project,
        "date": today,
        "seeds": seeds,
        "keywords_total": len(rows),
        "by_source": by_source,
        "csv_path": csv_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 1 — descoberta gratuita de keywords (Autocomplete + GSC + Trends)"
    )
    parser.add_argument(
        "--projeto",
        required=True,
        help="Nome do projeto (ex: seotecnico.dev.br). Define a pasta em relatorios/.",
    )
    parser.add_argument(
        "--seeds",
        default=None,
        metavar="ARQUIVO",
        help="Arquivo com uma seed por linha (# comenta). Modelo: seeds.example.txt",
    )
    parser.add_argument(
        "--seed",
        action="append",
        default=[],
        help="Seed avulsa (repetivel). Pode combinar com --seeds.",
    )
    parser.add_argument(
        "--gsc-csv",
        dest="gsc_csv",
        default=None,
        metavar="CSV",
        help="CSV exportado por gsc-monitor/exportar_keywords.py para mesclar (fonte gsc-weak).",
    )
    parser.add_argument(
        "--trends",
        action="store_true",
        help="Inclui related queries do Google Trends (requer pytrends; "
        "interesse relativo — NAO e volume).",
    )
    parser.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        help="Ignora o cache e consulta tudo de novo.",
    )
    parser.add_argument(
        "--no-recursion",
        dest="no_recursion",
        action="store_true",
        help="Desliga o nivel extra de expansao das sugestoes de alto sinal.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=SUGGEST_DELAY_S,
        help=f"Delay base entre consultas, em segundos (padrao: {SUGGEST_DELAY_S}).",
    )
    args = parser.parse_args()
    if not args.seeds and not args.seed:
        parser.error("informe --seeds ARQUIVO e/ou --seed TERMO.")
    return args


def main() -> None:
    args = parse_args()
    seeds = list(args.seed)
    if args.seeds:
        seeds = load_seeds_file(args.seeds) + seeds
    options = DiscoveryOptions(
        trends=args.trends,
        gsc_csv=args.gsc_csv,
        no_cache=args.no_cache,
        no_recursion=args.no_recursion,
        delay=args.delay,
    )
    try:
        run_discovery(args.projeto, seeds, options)
    except PipelineError as exc:
        print(f"[descobrir] ERRO: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
