"""
exportar_keywords.py — Exporta dados de queries do GSC para o keyword-research.

Contrato por arquivo com a ferramenta irmã keyword-research/ (as ferramentas
deste monorepo nunca se importam entre si — cooperam via CSV em disco).

Dois modos:

1. Sem --url  → mineração "ranked but weak" (Stage 1 do pipeline):
   queries com impressões > 0 e melhor posição > 10 — demanda comprovada,
   posição fraca, oportunidade ganhável. Gera:
       relatorios/{dominio}/{data}_keywords_gsc.csv
   Colunas (formato de descoberta do keyword-research):
       keyword,source,seed,date_collected,notes

2. Com --url  → ground truth pós-publicação (Stage 4, T+28 dias):
   todas as queries que a URL recebeu na janela. Gera:
       relatorios/{dominio}/{data}_keywords_url.csv
   Colunas (métricas cruas, compatível com o futuro experimento.py):
       query,url,clicks,impressions,ctr,position,date_start,date_end

Uso:
    py exportar_keywords.py --site seotecnico.dev.br
    py exportar_keywords.py --site seotecnico.dev.br --dias 90
    py exportar_keywords.py --site seotecnico.dev.br --url https://seotecnico.dev.br/post --dias 28
"""

import sys

# Força UTF-8 no stdout/stderr (terminais Windows usam cp1252 por padrão).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import csv
import os
from datetime import date

from core.storage import _get_domain_dir
from core.urls import normalize_domain

# Colunas do CSV de descoberta do keyword-research (contrato entre as tools).
KEYWORD_CSV_COLUMNS = ["keyword", "source", "seed", "date_collected", "notes"]
URL_CSV_COLUMNS = [
    "query",
    "url",
    "clicks",
    "impressions",
    "ctr",
    "position",
    "date_start",
    "date_end",
]

DIAS_WEAK_DEFAULT = 90  # janela p/ mineração de oportunidades
DIAS_URL_DEFAULT = 28  # janela p/ ground truth pós-publicação (T+28)


# ---------------------------------------------------------------------------
# Lógica pura (testável sem service)
# ---------------------------------------------------------------------------


def aggregate_queries(rows: list[dict]) -> list[dict]:
    """Agrega linhas query×página por query: melhor posição, métricas somadas.

    A URL mantida é a da linha mais bem posicionada — a página que o Google
    já prefere para a query. Agregar antes de filtrar evita exportar como
    "fraca" uma query em que OUTRA página do site já ranqueia no top 10.
    """
    by_query: dict[str, dict] = {}
    for r in rows:
        q = r.get("query")
        if not q:
            continue
        agg = by_query.get(q)
        if agg is None:
            by_query[q] = {
                "query": q,
                "url": r.get("url", ""),
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "position": r.get("position"),
            }
            continue
        agg["clicks"] += r.get("clicks", 0)
        agg["impressions"] += r.get("impressions", 0)
        pos = r.get("position")
        if pos is not None and (agg["position"] is None or pos < agg["position"]):
            agg["position"] = pos
            agg["url"] = r.get("url", "")
    return list(by_query.values())


def weak_queries(
    aggregated: list[dict], min_impressions: int = 1, max_position: float = 10.0
) -> list[dict]:
    """Filtra queries "ranked but weak": impressões >= min e posição > max.

    Posição exatamente 10.0 NÃO é fraca (já está na 1ª página).
    Retorna ordenado por impressões desc (maior demanda primeiro).
    """
    weak = [
        r
        for r in aggregated
        if r.get("impressions", 0) >= min_impressions
        and r.get("position") is not None
        and r["position"] > max_position
    ]
    weak.sort(key=lambda r: -r["impressions"])
    return weak


def _norm_page_url(url: str) -> str:
    """Comparação tolerante de URL de página (barra final, caixa do host)."""
    return url.strip().rstrip("/").lower()


def filter_url_rows(rows: list[dict], url: str) -> list[dict]:
    """Linhas query×página de uma URL específica, ordenadas por impressões desc."""
    alvo = _norm_page_url(url)
    matched = [r for r in rows if _norm_page_url(r.get("url", "")) == alvo]
    matched.sort(key=lambda r: -r.get("impressions", 0))
    return matched


def build_weak_csv_rows(weak: list[dict], date_collected: str) -> list[dict]:
    """Converte queries fracas agregadas para o formato de descoberta."""
    return [
        {
            "keyword": r["query"],
            "source": "gsc-weak",
            "seed": "",
            "date_collected": date_collected,
            "notes": f"pos={r['position']};impr={r['impressions']};url={r['url']}",
        }
        for r in weak
    ]


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


def _write_csv(path: str, header: list[str], rows: list[dict]) -> str:
    """CSV separado por vírgula, utf-8-sig (contrato de máquina, decimal ponto)."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(col, "") for col in header])
    return path


def export_weak_queries(
    site: str, days_back: int = DIAS_WEAK_DEFAULT, use_cache: bool = True
) -> str:
    """Exporta oportunidades "ranked but weak" para o CSV de descoberta."""
    from core.auth import build_service
    from fetchers.position_fetcher import fetch_query_positions

    service = build_service()
    rows = fetch_query_positions(service, site, use_cache=use_cache, days_back=days_back)
    weak = weak_queries(aggregate_queries(rows))

    today = date.today().isoformat()
    path = os.path.join(_get_domain_dir(normalize_domain(site)), f"{today}_keywords_gsc.csv")
    _write_csv(path, KEYWORD_CSV_COLUMNS, build_weak_csv_rows(weak, today))

    print(f"[exportar] {len(weak)} queries 'ranked but weak' (de {len(rows)} linhas query+URL).")
    print(f"[exportar] CSV: {path}")
    print("[exportar] Consuma com: py descobrir.py --projeto SITE --seeds ... --gsc-csv CAMINHO")
    return path


def export_url_queries(
    site: str, url: str, days_back: int = DIAS_URL_DEFAULT, use_cache: bool = True
) -> str:
    """Exporta as queries de uma URL publicada (ground truth, Stage 4)."""
    from core.auth import build_service
    from fetchers.position_fetcher import _build_date_range, fetch_query_positions

    service = build_service()
    rows = fetch_query_positions(service, site, use_cache=use_cache, days_back=days_back)
    start_date, end_date = _build_date_range(days_back)

    url_rows = [
        {**r, "date_start": start_date, "date_end": end_date} for r in filter_url_rows(rows, url)
    ]

    today = date.today().isoformat()
    path = os.path.join(_get_domain_dir(normalize_domain(site)), f"{today}_keywords_url.csv")
    _write_csv(path, URL_CSV_COLUMNS, url_rows)

    print(f"[exportar] {len(url_rows)} queries para a URL na janela {start_date} a {end_date}.")
    print(f"[exportar] CSV: {path}")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exporta queries do GSC para o pipeline de keyword research."
    )
    parser.add_argument(
        "--site",
        required=True,
        help="Domínio a consultar. Ex: exemplo.com.br ou sc-domain:exemplo.com.br",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="URL publicada para o modo ground truth (Stage 4). "
        "Sem --url, exporta as oportunidades 'ranked but weak'.",
    )
    parser.add_argument(
        "--dias",
        type=int,
        default=None,
        help=f"Janela retroativa em dias (padrão: {DIAS_WEAK_DEFAULT} sem --url, "
        f"{DIAS_URL_DEFAULT} com --url).",
    )
    parser.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        help="Ignora o cache e força nova chamada à API.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    use_cache = not args.no_cache
    if args.url:
        dias = args.dias if args.dias is not None else DIAS_URL_DEFAULT
        export_url_queries(args.site, args.url, days_back=dias, use_cache=use_cache)
    else:
        dias = args.dias if args.dias is not None else DIAS_WEAK_DEFAULT
        export_weak_queries(args.site, days_back=dias, use_cache=use_cache)


if __name__ == "__main__":
    main()
