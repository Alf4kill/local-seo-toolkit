"""
logs.py — Analisador de crawl budget a partir do access log do servidor.

100% LOCAL, sem cota de API. Lê o(s) log(s) de acesso (Apache/Nginx, formato
"combined") e mede o comportamento real do Googlebot: frequência de crawl por
URL, status, páginas do sitemap nunca rastreadas, money pages do GSC com muitas
impressões mas zero crawl, e desperdício em URLs com parâmetro / erros 4xx.

Uso básico:
    py logs.py --site www.exemplo.com.br --logs /caminho/access.log

Cruzamentos opcionais:
    --gsc                usa o último relatório de posição salvo do domínio
                         (relatorios/{dom}/{data}_posicao.json) para apontar
                         money pages subcrawladas. Rode o posicao.py antes.
    --no-sitemap         não busca o sitemap (pula "páginas nunca rastreadas").
    --verify-googlebot   confirma cada IP por DNS reverso+direto (LENTO, mas
                         elimina Googlebot falsificado). Sem isso, a detecção é
                         só por User-Agent (falsificável) e o relatório avisa.

Exemplos:
    py logs.py --site www.exemplo.com.br --logs access.log access.log.1.gz
    py logs.py --site www.exemplo.com.br --logs access.log --gsc --verify-googlebot
    py logs.py --site www.exemplo.com.br --logs access.log --format common --no-sitemap

Saídas (em relatorios/{dominio}/): {data}_crawl.json/.txt/.csv/.html
"""

import sys

# Força UTF-8 no stdout/stderr (consoles Windows usam cp1252 por padrão).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import os
from datetime import date

from config import CRAWL_TOP_N
from core import storage
from core.log_analyzer import analyze_logs, print_crawl_report
from core.sitemap import fetch_urls
from core.urls import normalize_domain
from reporters.crawl_reporter import build_crawl_txt_lines, generate_crawl_html


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analisador de crawl budget do Googlebot a partir do access log (local)."
    )
    parser.add_argument("--site", required=True, help="Domínio analisado. Ex: www.exemplo.com.br")
    parser.add_argument(
        "--logs",
        required=True,
        nargs="+",
        metavar="ARQUIVO",
        help="Um ou mais arquivos de access log (.gz é lido transparentemente).",
    )
    parser.add_argument(
        "--format",
        choices=["combined", "common"],
        default=None,
        help="Força o formato do log. Padrão: detecta (combined → common).",
    )
    parser.add_argument(
        "--no-sitemap",
        dest="no_sitemap",
        action="store_true",
        help="Não busca o sitemap (pula a lista de páginas nunca rastreadas).",
    )
    parser.add_argument(
        "--gsc",
        action="store_true",
        help="Cruza com o último relatório de posição salvo (money pages subcrawladas).",
    )
    parser.add_argument(
        "--verify-googlebot",
        dest="verify_googlebot",
        action="store_true",
        help="Verifica cada IP do Googlebot por DNS reverso+direto (lento, confiável).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=CRAWL_TOP_N,
        help=f"Quantas URLs mostrar nas tabelas 'top' (padrão: {CRAWL_TOP_N}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    today = date.today().isoformat()
    domain = normalize_domain(args.site)

    print(f"\n=== GSC Crawl Budget — {domain} — {today} ===\n")

    # Valida os arquivos de log antes de qualquer rede.
    missing = [p for p in args.logs if not os.path.isfile(p)]
    if missing:
        print(f"[ERRO] Arquivo(s) de log não encontrado(s): {', '.join(missing)}")
        sys.exit(1)

    # Sitemap (opcional) — para apontar páginas nunca rastreadas.
    sitemap_urls = None
    if not args.no_sitemap:
        print("[logs] Buscando URLs no sitemap (use --no-sitemap para pular)...")
        try:
            sitemap_urls = fetch_urls(domain)
        except Exception as exc:  # rede/parse/sem sitemap — degrada com aviso
            print(f"[logs] AVISO — sitemap indisponível ({exc}). Pulando 'nunca rastreadas'.")

    # Posição do GSC (opcional) — para apontar money pages subcrawladas.
    position_report = None
    if args.gsc:
        position_report = storage.load_latest_position_report(domain)
        if position_report is None:
            print(
                "[logs] AVISO — nenhum relatório de posição salvo. Rode posicao.py antes de --gsc."
            )
        else:
            print("[logs] Cruzando com o último relatório de posição salvo.")

    if args.verify_googlebot:
        print("[logs] Verificando Googlebot por DNS (pode demorar)...")

    # Análise (streaming; .gz transparente).
    print(f"[logs] Lendo {len(args.logs)} arquivo(s) de log...")
    result = analyze_logs(
        args.logs,
        sitemap_urls=sitemap_urls,
        position_report=position_report,
        resolve_googlebot=args.verify_googlebot,
        format_name=args.format,
        top_n=args.top,
    )

    if result["lines_parsed"] == 0:
        print(
            "[ERRO] Nenhuma linha reconhecida. Confira o formato do log "
            "(--format combined|common) — esperado Apache/Nginx combined."
        )
        sys.exit(1)

    result["site"] = domain
    result["generated"] = today

    # Terminal.
    print()
    print_crawl_report(result)

    # Artefatos (todos locais; relatorios/ é gitignored).
    storage.save_crawl_report(domain, today, result)
    storage.save_crawl_txt(domain, today, "\n".join(build_crawl_txt_lines(result, domain, today)))
    storage.save_crawl_csv(domain, today, result)
    storage.save_crawl_html(domain, today, generate_crawl_html(result, domain, today))

    print("\n[logs] Concluído.")


if __name__ == "__main__":
    main()
