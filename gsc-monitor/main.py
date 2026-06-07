"""
main.py — GSC Monitor: relatório de indexação via terminal.

Uso básico:
    python main.py --site exemplo.com.br

Opções:
    --site     Domínio a inspecionar (obrigatório).
               Ex: exemplo.com.br  ou  sc-domain:exemplo.com.br (Domain Property)

    --limit N  Inspeciona apenas as N primeiras URLs (útil para testes).

    --verbose  Exibe resultado detalhado por URL no terminal.

    --txt      Salva relatório legível em .txt além dos arquivos JSON.

Exemplos:
    python main.py --site exemplo.com.br --verbose --txt
    python main.py --site sc-domain:exemplo.com.br --limit 20 --verbose
"""

import sys

# Força UTF-8 no stdout/stderr para caracteres Unicode funcionarem em qualquer
# terminal Windows (que usa cp1252 por padrão no Python 3.13).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
from datetime import date

from core.auth import build_service
from core.sitemap import fetch_urls
from core.storage import (
    append_historico,
    build_snapshot,
    save_consolidated_report,
    save_csv_indexacao,
    save_detailed_report,
    save_text_report,
)
from core.urls import normalize_domain
from fetchers.inspector import inspect_urls
from reporters.reporter import (
    build_consolidated,
    build_detailed,
    print_consolidated,
    print_detailed,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor de Indexação via Google Search Console API"
    )
    parser.add_argument(
        "--site",
        required=True,
        help=(
            "Domínio a inspecionar. Ex: exemplo.com.br  "
            "ou sc-domain:exemplo.com.br para Domain Property."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limita o número de URLs inspecionadas (útil para testes).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Exibe resultado detalhado por URL no terminal.",
    )
    parser.add_argument(
        "--txt",
        action="store_true",
        help="Salva relatório legível em arquivo .txt além do JSON.",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Salva relatório de indexação em arquivo .csv (compatível com Excel).",
    )
    parser.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        help="Ignora o cache e força novas chamadas à API (consome cota).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    today = date.today().isoformat()  # ex: "2026-04-27"
    domain = normalize_domain(args.site)

    print(f"\n=== GSC Monitor — {domain} — {today} ===\n")

    # 1. Autenticação
    print("[main] Autenticando no Google Search Console...")
    try:
        service = build_service()
    except FileNotFoundError as exc:
        print(f"\n[ERRO] {exc}")
        sys.exit(1)

    # 2. Fetch do sitemap
    print("[main] Buscando URLs no sitemap...")
    try:
        urls = fetch_urls(domain)
    except RuntimeError as exc:
        print(f"\n[ERRO] {exc}")
        sys.exit(1)

    if not urls:
        print("[main] Nenhuma URL encontrada no sitemap. Encerrando.")
        sys.exit(0)

    if args.limit:
        urls = urls[: args.limit]
        print(f"[main] Limite aplicado: inspecionando {len(urls)} URLs.")

    # 3. Inspeção via API
    print(f"[main] Inspecionando {len(urls)} URL(s)...\n")
    url_results = inspect_urls(service, args.site, urls, use_cache=not args.no_cache)

    # 4. Gera relatórios
    detailed = build_detailed(domain, today, url_results)
    consolidated = build_consolidated(domain, today, url_results)

    # 5. Salva arquivos
    save_detailed_report(domain, today, detailed)
    save_consolidated_report(domain, today, consolidated)

    snapshot = build_snapshot(domain, today, url_results)
    append_historico(snapshot)

    # 6. Exibe no terminal
    if args.verbose:
        print_detailed(detailed)
    print_consolidated(consolidated)

    # 7. Salva .txt se solicitado
    if args.txt:
        save_text_report(domain, today, detailed, consolidated)

    # 8. Salva .csv se solicitado
    if args.csv:
        save_csv_indexacao(domain, today, detailed)

    print("[main] Concluído.")


if __name__ == "__main__":
    main()
