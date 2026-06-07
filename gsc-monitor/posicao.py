"""
posicao.py — Relatório de posicionamento GSC por URL via Search Analytics API.

Uso básico:
    python posicao.py --site exemplo.com.br

Opções:
    --site     Domínio a analisar (obrigatório).
               Ex: exemplo.com.br  ou  sc-domain:exemplo.com.br

    --txt      Salva relatório legível em .txt além do JSON.

Exemplos:
    python posicao.py --site www.exemplo.com.br
    python posicao.py --site www.exemplo.com.br --txt
    python posicao.py --site sc-domain:exemplo.com.br --txt
"""

import sys
import os

# Força UTF-8 no stdout/stderr para caracteres Unicode funcionarem em qualquer
# terminal Windows (que usa cp1252 por padrão no Python 3.13).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Adiciona a pasta vendor/ ao path para uso em servidores sem pip global
_vendor = os.path.join(os.path.dirname(__file__), "vendor")
if os.path.isdir(_vendor) and _vendor not in sys.path:
    sys.path.insert(0, _vendor)

import argparse
from datetime import date

from core.auth import build_service
from core.sitemap import fetch_urls
from core.urls import normalize_domain
from fetchers.position_fetcher import fetch_positions
from reporters.position_reporter import build_position_report, print_position_report
from core.storage import (
    save_position_report, save_position_txt, save_excel_report, save_csv_posicao,
    append_historico_posicao, load_historico_posicao, load_latest_consolidated,
    save_dashboard, save_nlp_report,
)
from core.analytics import (
    calculate_health_score, print_health_score,
    detect_orphan_pages, print_orphan_pages,
    detect_cannibalization, print_cannibalization,
)
from fetchers.knowledge_graph import search_entity, print_kg_result, load_api_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Relatório de Posicionamento via Google Search Console API"
    )
    parser.add_argument(
        "--site",
        required=True,
        help=(
            "Domínio a analisar. Ex: exemplo.com.br  "
            "ou sc-domain:exemplo.com.br para Domain Property."
        ),
    )
    parser.add_argument(
        "--txt",
        action="store_true",
        help="Salva relatório legível em arquivo .txt além do JSON.",
    )
    parser.add_argument(
        "--excel",
        action="store_true",
        help="Gera relatório Excel (.xlsx) com faixas de posição e oportunidades de CTR.",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Salva relatório de posicionamento em arquivo .csv (compatível com Excel).",
    )
    parser.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        help="Ignora o cache e força nova chamada à API.",
    )
    parser.add_argument(
        "--queries",
        action="store_true",
        help="Analisa canibalização de keywords (busca dados query+página da API).",
    )
    parser.add_argument(
        "--trends",
        action="store_true",
        help="Busca tendências Google Trends para as top 10 keywords (requer pytrends).",
    )
    parser.add_argument(
        "--nlp",
        action="store_true",
        help="Analisa entidades e categorias NLP das páginas de oportunidade via annotateText (consome cota API).",
    )
    parser.add_argument(
        "--content",
        action="store_true",
        help="Diagnóstico de qualidade de conteúdo (over-optimization / conteúdo raso). "
             "Sinais locais sem cota; baixa o HTML das páginas de oportunidade. Enriquecido por --nlp.",
    )
    parser.add_argument(
        "--api-key",
        dest="api_key",
        default=None,
        help="API key Google Cloud (KG, NLP). Alternativa: env GOOGLE_API_KEY ou google_api_key.txt.",
    )
    return parser.parse_args()


def main() -> None:
    args   = parse_args()
    today  = date.today().isoformat()
    domain = normalize_domain(args.site)

    print(f"\n=== GSC Posicionamento — {domain} — {today} ===\n")

    # 1. Autenticação
    print("[posicao] Autenticando no Google Search Console...")
    try:
        service = build_service()
    except FileNotFoundError as exc:
        print(f"\n[ERRO] {exc}")
        sys.exit(1)

    # 2. URLs do sitemap
    print("[posicao] Buscando URLs no sitemap...")
    try:
        urls = fetch_urls(domain)
    except RuntimeError as exc:
        print(f"\n[ERRO] {exc}")
        sys.exit(1)

    if not urls:
        print("[posicao] Nenhuma URL encontrada no sitemap. Encerrando.")
        sys.exit(0)

    print(f"[posicao] {len(urls)} URLs encontradas no sitemap.\n")

    # 3. Consulta Search Analytics
    try:
        data = fetch_positions(service, args.site, urls, use_cache=not args.no_cache)
    except Exception as exc:
        print(f"\n[ERRO] Falha ao consultar Search Analytics API: {exc}")
        sys.exit(1)

    # 4. Monta relatório
    report = build_position_report(domain, today, data)

    # 5. Salva JSON
    save_position_report(domain, today, report)

    # 6. Exibe no terminal
    print_position_report(domain, today, data)

    # 7. Período (o histórico é salvo mais abaixo, após o diagnóstico de conteúdo,
    #    para que cada snapshot guarde também as métricas de qualidade — Move 2)
    period = {"start": data["start_date"], "end": data["end_date"]}

    # 8. Fase 4d — score de saúde (carrega indexação salva se disponível)
    consolidated = load_latest_consolidated(domain)
    health = calculate_health_score(report, consolidated)
    print_health_score(health)

    # 9. Fase 4a — páginas órfãs
    orphans = detect_orphan_pages(report)
    print_orphan_pages(orphans)

    # Salva API key se fornecida via --api-key
    if args.api_key:
        from fetchers.knowledge_graph import save_api_key
        save_api_key(args.api_key)

    # 10. Fase 5a — Knowledge Graph (sempre, se API key disponível)
    api_key   = args.api_key or load_api_key()
    kg_result = search_entity(domain, api_key=api_key, use_cache=not args.no_cache)
    print_kg_result(kg_result)

    # 11. Fetch de queries (se --queries, --trends ou --content)
    query_rows = None
    if args.queries or args.trends or args.content:
        from fetchers.position_fetcher import fetch_query_positions
        try:
            query_rows = fetch_query_positions(service, args.site, use_cache=not args.no_cache)
        except Exception as exc:
            print(f"\n[ERRO] Falha ao buscar queries: {exc}")

    # 12. Fase 4b — canibalização de keywords
    cannibalization = None
    if args.queries and query_rows:
        cannibalization = detect_cannibalization(query_rows)
        print_cannibalization(cannibalization)

    # 13. Fase 5b — tendências (pytrends)
    trends_data = None
    if args.trends and query_rows:
        from fetchers.trends_fetcher import fetch_trends, top_keywords_from_queries, print_trends
        top_kws = top_keywords_from_queries(query_rows)
        if top_kws:
            trends_data = fetch_trends(top_kws, domain, use_cache=not args.no_cache)
            print_trends(trends_data)
        else:
            print("[trends] Nenhuma keyword Top 10 encontrada para buscar tendências.")

    # 14. Fase 5c — NLP (entidades, opt-in)
    nlp_results = None
    if args.nlp:
        from fetchers.nlp_analyzer import analyze_opportunity_urls, print_nlp_results
        nlp_results = analyze_opportunity_urls(
            report["urls"], domain, api_key=api_key, use_cache=not args.no_cache,
        )
        print_nlp_results(nlp_results)

        # Relatório NLP detalhado — sempre gerado quando --nlp está ativo
        from reporters.nlp_report_generator import generate_nlp_report
        nlp_html = generate_nlp_report(
            domain, today, nlp_results, query_rows=query_rows,
        )
        save_nlp_report(domain, today, nlp_html)

    # 14b. Move 1 — Diagnóstico de qualidade de conteúdo (opt-in)
    content_results = None
    if args.content:
        from fetchers.content_fetcher import analyze_opportunity_content_quality
        content_results = analyze_opportunity_content_quality(
            report["urls"], domain, query_rows=query_rows,
            nlp_results=nlp_results, use_cache=not args.no_cache,
        )

    # 14c. Fase 4c + Move 2 — histórico de posição por URL (com métricas de conteúdo)
    append_historico_posicao(domain, today, period, data["rows"], content_results=content_results)
    historico_posicao = load_historico_posicao(domain)

    # 14d. Move 2 — acompanhamento conteúdo × posição
    from core.content_quality import build_content_tracking, print_content_tracking
    tracking = build_content_tracking(historico_posicao)
    print_content_tracking(tracking)

    # 15. Salva .txt se solicitado
    if args.txt:
        save_position_txt(domain, today, data, report)

    # 16. Gera Excel se solicitado
    if args.excel:
        from reporters.excel_reporter import generate_excel
        hist_for_excel = (
            historico_posicao
            if len(historico_posicao.get("snapshots", [])) >= 2
            else None
        )
        wb = generate_excel(
            domain, today, data, report,
            health=health,
            orphans=orphans if orphans else None,
            historico_posicao=hist_for_excel,
            cannibalization=cannibalization,
            kg_result=kg_result,
            trends_data=trends_data,
            query_rows=query_rows,
            nlp_results=nlp_results if nlp_results else None,
            content_results=content_results,
        )
        save_excel_report(domain, today, wb)

    # 17. Salva .csv se solicitado
    if args.csv:
        save_csv_posicao(domain, today, report)

    # 18. Dashboard HTML (sempre gerado)
    from reporters.html_reporter import generate_dashboard
    html = generate_dashboard(
        domain, today, data, report,
        health=health,
        orphans=orphans if orphans else None,
        historico_posicao=historico_posicao,
        cannibalization=cannibalization,
        kg_result=kg_result,
        trends_data=trends_data,
        consolidated=consolidated,
        nlp_results=nlp_results if nlp_results else None,
        content_results=content_results,
    )
    save_dashboard(domain, html)

    print("[posicao] Concluído.")


if __name__ == "__main__":
    main()
