"""
posicao.py — Relatório de posicionamento GSC por URL via Search Analytics API.

Uso básico:
    python posicao.py --site exemplo.com.br

Opções:
    --site     Domínio a analisar.
               Ex: exemplo.com.br  ou  sc-domain:exemplo.com.br

    --txt      Salva relatório legível em .txt além do JSON.

    --batch ARQUIVO
               Modo lote (headless): roda o pipeline padrão (posições +
               queries + qualidade de conteúdo) para cada domínio listado
               no arquivo (um por linha; linhas com # são comentários).
               Erros em um site não interrompem os demais.

    --batch-report
               Junto com --batch: grava resumo consolidado do lote em
               relatorios/_batch/YYYY-MM-DD_resumo.csv

Exemplos:
    python posicao.py --site www.exemplo.com.br
    python posicao.py --site www.exemplo.com.br --txt
    python posicao.py --site sc-domain:exemplo.com.br --txt
    python posicao.py --batch sites.txt --batch-report
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

from core.analytics import (
    build_consolidation_plan,
    build_htaccess_block,
    build_nginx_block,
    calculate_health_score,
    detect_cannibalization,
    detect_orphan_pages,
    print_cannibalization,
    print_consolidation_plan,
    print_health_score,
    print_orphan_pages,
)
from core.auth import build_service
from core.sitemap import fetch_urls
from core.storage import (
    append_historico_posicao,
    load_historico_posicao,
    load_latest_consolidated,
    save_csv_posicao,
    save_dashboard,
    save_excel_report,
    save_nlp_report,
    save_position_report,
    save_position_txt,
    save_redirects_csv,
    save_redirects_txt,
)
from core.urls import normalize_domain
from fetchers.knowledge_graph import load_api_key, print_kg_result, search_entity
from fetchers.position_fetcher import fetch_positions
from reporters.position_reporter import build_position_report, print_position_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Relatório de Posicionamento via Google Search Console API"
    )
    parser.add_argument(
        "--site",
        default=None,
        help=(
            "Domínio a analisar. Ex: exemplo.com.br  "
            "ou sc-domain:exemplo.com.br para Domain Property."
        ),
    )
    parser.add_argument(
        "--batch",
        default=None,
        metavar="ARQUIVO",
        help=(
            "Modo lote headless: arquivo com um domínio por linha "
            "(linhas iniciadas com # são comentários). Roda o pipeline padrão "
            "(posições + queries + conteúdo) para cada site, sem abortar em erros."
        ),
    )
    parser.add_argument(
        "--batch-report",
        dest="batch_report",
        action="store_true",
        help="Com --batch: grava resumo do lote em relatorios/_batch/YYYY-MM-DD_resumo.csv",
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
        help="Tendências de demanda: por padrão via dimensão date do GSC "
        "(oficial, específico do site). Use --trends-source para o legado.",
    )
    parser.add_argument(
        "--trends-source",
        dest="trends_source",
        choices=["gsc", "pytrends"],
        default="gsc",
        help="Fonte das tendências: gsc (padrão, first-party, 90 dias) ou "
        "pytrends (legado, não-oficial, índice global 12 meses).",
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
    args = parser.parse_args()

    if not args.site and not args.batch:
        parser.error("informe --site DOMINIO ou --batch ARQUIVO.")
    if args.site and args.batch:
        parser.error("--site e --batch não podem ser usados juntos.")
    if args.batch_report and not args.batch:
        parser.error("--batch-report requer --batch.")

    return args


class PipelineError(RuntimeError):
    """Erro fatal em uma execução do pipeline (autenticação, sitemap, API)."""


def run_pipeline(
    site: str,
    *,
    txt: bool = False,
    excel: bool = False,
    csv: bool = False,
    no_cache: bool = False,
    queries: bool = False,
    trends: bool = False,
    trends_source: str = "gsc",
    nlp: bool = False,
    content: bool = False,
    api_key: "str | None" = None,
) -> dict:
    """
    Executa o pipeline completo de posicionamento para um site (sem GUI).

    Mesmo fluxo do CLI: auth → sitemap → posições → relatório → analytics →
    (queries/trends/nlp/conteúdo opcionais) → histórico → dashboard.

    Levanta PipelineError em falhas fatais (em vez de sys.exit), para que o
    modo batch possa isolar erros por site.

    Retorna um resumo da execução:
    {
        "site", "date", "urls_total", "urls_with_data",
        "health_score", "health_grade", "avg_position", "ctr",
        "snapshot_count", "cannibalization_groups",
        "content_verdicts": {"ok": n, "atencao": n, ...},
    }
    """
    today = date.today().isoformat()
    domain = normalize_domain(site)

    print(f"\n=== GSC Posicionamento — {domain} — {today} ===\n")

    # 1. Autenticação
    print("[posicao] Autenticando no Google Search Console...")
    try:
        service = build_service()
    except FileNotFoundError as exc:
        raise PipelineError(str(exc)) from exc

    # 2. URLs do sitemap
    print("[posicao] Buscando URLs no sitemap...")
    try:
        urls = fetch_urls(domain)
    except RuntimeError as exc:
        raise PipelineError(str(exc)) from exc

    if not urls:
        print("[posicao] Nenhuma URL encontrada no sitemap. Encerrando.")
        historico_posicao = load_historico_posicao(domain)
        return {
            "site": domain,
            "date": today,
            "urls_total": 0,
            "urls_with_data": 0,
            "health_score": None,
            "health_grade": None,
            "avg_position": None,
            "ctr": None,
            "snapshot_count": len(historico_posicao.get("snapshots", [])),
            "cannibalization_groups": None,
            "content_verdicts": {},
        }

    print(f"[posicao] {len(urls)} URLs encontradas no sitemap.\n")

    # 3. Consulta Search Analytics
    try:
        data = fetch_positions(service, site, urls, use_cache=not no_cache)
    except Exception as exc:
        raise PipelineError(f"Falha ao consultar Search Analytics API: {exc}") from exc

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
    if api_key:
        from fetchers.knowledge_graph import save_api_key

        save_api_key(api_key)

    # 10. Fase 5a — Knowledge Graph (sempre, se API key disponível)
    api_key = api_key or load_api_key()
    kg_result = search_entity(domain, api_key=api_key, use_cache=not no_cache)
    print_kg_result(kg_result)

    # 11. Fetch de queries (se --queries, --trends ou --content)
    query_rows = None
    if queries or trends or content:
        from fetchers.position_fetcher import fetch_query_positions

        try:
            query_rows = fetch_query_positions(service, site, use_cache=not no_cache)
        except Exception as exc:
            print(f"\n[ERRO] Falha ao buscar queries: {exc}")

    # 12. Fase 4b — canibalização de keywords
    cannibalization = None
    if queries and query_rows:
        cannibalization = detect_cannibalization(query_rows)
        print_cannibalization(cannibalization)

    # 12b. P2 — Plano de consolidação 301 (SUGESTÃO; derivado da canibalização)
    consolidation_plan = None
    if cannibalization:
        consolidation_plan = build_consolidation_plan(cannibalization)
        print_consolidation_plan(consolidation_plan)
        if consolidation_plan["redirects"]:
            save_redirects_csv(domain, today, consolidation_plan)
            save_redirects_txt(
                domain,
                today,
                build_htaccess_block(consolidation_plan, today),
                build_nginx_block(consolidation_plan, today),
            )

    # 13. Fase 5b / P5 — tendências de demanda
    trends_data = None
    if trends:
        if trends_source == "pytrends":
            # Legado (--trends-source pytrends): índice global do Google
            # Trends via biblioteca não-oficial — frágil, mantido como opção.
            if query_rows:
                from fetchers.trends_fetcher import (
                    fetch_trends,
                    print_trends,
                    top_keywords_from_queries,
                )

                top_kws = top_keywords_from_queries(query_rows)
                if top_kws:
                    trends_data = fetch_trends(top_kws, domain, use_cache=not no_cache)
                    print_trends(trends_data)
                else:
                    print("[trends] Nenhuma keyword Top 10 encontrada para buscar tendências.")
        else:
            # P5 — padrão: dimensão `date` do GSC (oficial, sem rate-limit,
            # demanda REAL do próprio site em impressões/dia, 90 dias).
            from core.analytics import compute_date_trends, print_date_trends
            from fetchers.position_fetcher import fetch_date_trends

            try:
                raw_trends = fetch_date_trends(service, site, use_cache=not no_cache)
                trends_data = compute_date_trends(raw_trends)
                print_date_trends(trends_data)
            except Exception as exc:
                print(f"\n[ERRO] Falha ao buscar tendências GSC: {exc}")

    # 14. Fase 5c — NLP (entidades, opt-in)
    nlp_results = None
    if nlp:
        from fetchers.nlp_analyzer import analyze_opportunity_urls, print_nlp_results

        nlp_results = analyze_opportunity_urls(
            report["urls"],
            domain,
            api_key=api_key,
            use_cache=not no_cache,
        )
        print_nlp_results(nlp_results)

        # Relatório NLP detalhado — sempre gerado quando --nlp está ativo
        from reporters.nlp_report_generator import generate_nlp_report

        nlp_html = generate_nlp_report(
            domain,
            today,
            nlp_results,
            query_rows=query_rows,
        )
        save_nlp_report(domain, today, nlp_html)

    # 14b. Move 1 — Diagnóstico de qualidade de conteúdo (opt-in)
    content_results = None
    if content:
        from fetchers.content_fetcher import analyze_opportunity_content_quality

        content_results = analyze_opportunity_content_quality(
            report["urls"],
            domain,
            query_rows=query_rows,
            nlp_results=nlp_results,
            use_cache=not no_cache,
        )

    # 14c. Fase 4c + Move 2 — histórico de posição por URL (com métricas de conteúdo)
    append_historico_posicao(domain, today, period, data["rows"], content_results=content_results)
    historico_posicao = load_historico_posicao(domain)

    # 14d. Move 2 — acompanhamento conteúdo × posição
    from core.content_quality import build_content_tracking, print_content_tracking

    tracking = build_content_tracking(historico_posicao)
    print_content_tracking(tracking)

    # 15. Salva .txt se solicitado
    if txt:
        save_position_txt(domain, today, data, report)

    # 16. Gera Excel se solicitado
    if excel:
        from reporters.excel_reporter import generate_excel

        hist_for_excel = (
            historico_posicao if len(historico_posicao.get("snapshots", [])) >= 2 else None
        )
        wb = generate_excel(
            domain,
            today,
            data,
            report,
            health=health,
            orphans=orphans if orphans else None,
            historico_posicao=hist_for_excel,
            cannibalization=cannibalization,
            kg_result=kg_result,
            trends_data=trends_data,
            query_rows=query_rows,
            nlp_results=nlp_results if nlp_results else None,
            content_results=content_results,
            consolidation_plan=consolidation_plan,
        )
        save_excel_report(domain, today, wb)

    # 17. Salva .csv se solicitado
    if csv:
        save_csv_posicao(domain, today, report)

    # 18. Dashboard HTML (sempre gerado)
    from reporters.html_reporter import generate_dashboard

    html = generate_dashboard(
        domain,
        today,
        data,
        report,
        health=health,
        orphans=orphans if orphans else None,
        historico_posicao=historico_posicao,
        cannibalization=cannibalization,
        kg_result=kg_result,
        trends_data=trends_data,
        consolidated=consolidated,
        nlp_results=nlp_results if nlp_results else None,
        content_results=content_results,
        consolidation_plan=consolidation_plan,
    )
    save_dashboard(domain, html)

    print("[posicao] Concluído.")

    # 19. Resumo da execução (consumido pelo modo batch)
    verdict_counts: dict = {}
    if content_results:
        for cq in content_results.values():
            v = (cq or {}).get("verdict")
            if v:
                verdict_counts[v] = verdict_counts.get(v, 0) + 1

    return {
        "site": domain,
        "date": today,
        "urls_total": report["summary"]["total_urls_sitemap"],
        "urls_with_data": report["summary"]["urls_with_data"],
        "health_score": health["score"],
        "health_grade": health["grade"],
        "avg_position": report["summary"]["avg_position_site"],
        "ctr": report["summary"]["avg_ctr_percent"],
        "snapshot_count": len(historico_posicao.get("snapshots", [])),
        "cannibalization_groups": len(cannibalization) if cannibalization is not None else None,
        "content_verdicts": verdict_counts,
    }


def _run_batch_mode(args: argparse.Namespace) -> None:
    """Modo lote: roda o pipeline padrão para cada site do arquivo."""
    from core.batch import parse_sites_file, run_batch, write_batch_report

    try:
        sites = parse_sites_file(args.batch)
    except (FileNotFoundError, ValueError) as exc:
        print(f"\n[ERRO] {exc}")
        sys.exit(1)

    def _pipeline(site: str) -> dict:
        # Pipeline padrão do batch: posições + queries + qualidade de conteúdo
        # (cache-aware). Demais flags do CLI são repassadas a cada site.
        return run_pipeline(
            site,
            txt=args.txt,
            excel=args.excel,
            csv=args.csv,
            no_cache=args.no_cache,
            queries=True,
            content=True,
            trends=args.trends,
            trends_source=args.trends_source,
            nlp=args.nlp,
            api_key=args.api_key,
        )

    results = run_batch(sites, _pipeline)

    if args.batch_report:
        path = write_batch_report(results, date.today().isoformat())
        print(f"[batch] Relatório do lote salvo em: {path}")

    # Código de saída: 0 se ao menos um site concluiu; 1 se todos falharam.
    sys.exit(0 if any(r["ok"] for r in results) else 1)


def main() -> None:
    args = parse_args()

    if args.batch:
        _run_batch_mode(args)
        return

    try:
        run_pipeline(
            args.site,
            txt=args.txt,
            excel=args.excel,
            csv=args.csv,
            no_cache=args.no_cache,
            queries=args.queries,
            trends=args.trends,
            trends_source=args.trends_source,
            nlp=args.nlp,
            content=args.content,
            api_key=args.api_key,
        )
    except PipelineError as exc:
        print(f"\n[ERRO] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
