"""
runner.py — Executa as tarefas de indexação e posicionamento em thread separada.

Redireciona sys.stdout/stderr para uma queue.Queue durante a execução, permitindo
que a GUI exiba o output em tempo real sem bloquear o event loop do Tkinter.
"""

import os
import sys
import queue
import threading
import traceback
from datetime import date

# Garante que gsc-monitor/ está no sys.path para todos os imports do projeto
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)


# ---------------------------------------------------------------------------
# Redirect de stdout para a queue
# ---------------------------------------------------------------------------

class QueueStream:
    """
    Stream que redireciona write() para uma queue.Queue thread-safe.
    Substitui sys.stdout e sys.stderr durante a execução da task.

    Implementa os atributos mínimos do protocolo io.TextIOBase para
    compatibilidade com código que inspeciona sys.stdout (ex: encoding).
    """
    encoding = "utf-8"   # atributo de classe — evita AttributeError em
                         # código que faz sys.stdout.encoding ou getattr

    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text: str) -> None:
        if text:
            self._q.put(text)

    def flush(self) -> None:
        pass  # necessário para compatibilidade com print()

    def isatty(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_domain(site: str) -> str:
    if site.startswith("sc-domain:"):
        return site[len("sc-domain:"):]
    return site.removeprefix("https://").removeprefix("http://").rstrip("/")


# ---------------------------------------------------------------------------
# Lógica de cada tarefa
# ---------------------------------------------------------------------------

def _run_indexation(
    service,
    site: str,
    domain: str,
    today: str,
    limit: int | None,
    formats: set,
    use_cache: bool,
) -> None:
    """Executa o relatório de indexação (URL Inspection API)."""
    from core.sitemap import fetch_urls
    from fetchers.inspector import inspect_urls
    from reporters.reporter import build_detailed, build_consolidated, print_consolidated
    from core.storage import (
        build_snapshot, append_historico,
        save_detailed_report, save_consolidated_report,
        save_text_report, save_csv_indexacao,
    )

    print(f"\n{'─' * 55}")
    print(f"  INDEXAÇÃO — {domain}")
    print(f"{'─' * 55}")

    print("[indexação] Buscando URLs no sitemap...")
    try:
        urls = fetch_urls(domain)
    except RuntimeError as exc:
        print(f"\n[ERRO] {exc}")
        return

    if not urls:
        print("[indexação] Nenhuma URL encontrada no sitemap.")
        return

    if limit:
        urls = urls[:limit]
        print(f"[indexação] Limite aplicado: {len(urls)} URLs.")

    print(f"[indexação] Inspecionando {len(urls)} URL(s)...\n")
    url_results = inspect_urls(service, site, urls, use_cache=use_cache)

    detailed     = build_detailed(domain, today, url_results)
    consolidated = build_consolidated(domain, today, url_results)

    save_detailed_report(domain, today, detailed)
    save_consolidated_report(domain, today, consolidated)
    append_historico(build_snapshot(domain, today, url_results))

    print_consolidated(consolidated)

    if "txt" in formats:
        save_text_report(domain, today, detailed, consolidated)
    if "csv" in formats:
        save_csv_indexacao(domain, today, detailed)


def _run_position(
    service,
    site: str,
    domain: str,
    today: str,
    formats: set,
    use_cache: bool,
    do_queries: bool = False,
    do_trends: bool = False,
    trends_source: str = "gsc",
    do_nlp: bool = False,
    do_content: bool = False,
    api_key: "str | None" = None,
    result_store: "dict | None" = None,
) -> None:
    """Executa o relatório de posicionamento (Search Analytics API) + Fase 4."""
    from core.sitemap import fetch_urls
    from fetchers.position_fetcher import fetch_positions
    from reporters.position_reporter import build_position_report, print_position_report
    from core.storage import (
        save_position_report, save_position_txt,
        save_excel_report, save_csv_posicao,
        append_historico_posicao, load_historico_posicao, load_latest_consolidated,
        save_dashboard, save_nlp_report, save_redirects_csv, save_redirects_txt,
    )
    from core.analytics import (
        calculate_health_score, print_health_score,
        detect_orphan_pages, print_orphan_pages,
        detect_cannibalization, print_cannibalization,
        build_consolidation_plan, print_consolidation_plan,
        build_htaccess_block, build_nginx_block,
    )

    print(f"\n{'─' * 55}")
    print(f"  POSICIONAMENTO — {domain}")
    print(f"{'─' * 55}")

    print("[posicionamento] Buscando URLs no sitemap...")
    try:
        urls = fetch_urls(domain)
    except RuntimeError as exc:
        print(f"\n[ERRO] {exc}")
        return

    if not urls:
        print("[posicionamento] Nenhuma URL encontrada.")
        return

    print(f"[posicionamento] {len(urls)} URLs encontradas.\n")

    try:
        data = fetch_positions(service, site, urls, use_cache=use_cache)
    except Exception as exc:
        print(f"\n[ERRO] Falha na Search Analytics API: {exc}")
        return

    report = build_position_report(domain, today, data)
    save_position_report(domain, today, report)
    print_position_report(domain, today, data)

    # Período (histórico salvo mais abaixo, após o diagnóstico de conteúdo — Move 2)
    period = {"start": data["start_date"], "end": data["end_date"]}

    # Fase 4d — score de saúde
    consolidated = load_latest_consolidated(domain)
    health = calculate_health_score(report, consolidated)
    print_health_score(health)
    if result_store is not None:
        result_store["health"] = health

    # Fase 4a — páginas órfãs
    orphans = detect_orphan_pages(report)
    print_orphan_pages(orphans)

    # Fase 5a — Knowledge Graph
    from fetchers.knowledge_graph import search_entity, print_kg_result, load_api_key
    if api_key is None:
        api_key = load_api_key()
    kg_result = search_entity(domain, api_key=api_key, use_cache=use_cache)
    print_kg_result(kg_result)

    # Fetch de queries (se canibalização, tendências ou qualidade de conteúdo)
    query_rows = None
    if do_queries or do_trends or do_content:
        from fetchers.position_fetcher import fetch_query_positions
        try:
            query_rows = fetch_query_positions(service, site, use_cache=use_cache)
        except Exception as exc:
            print(f"\n[ERRO] Falha ao buscar queries: {exc}")

    # Fase 4b — canibalização
    cannibalization = None
    if do_queries and query_rows:
        cannibalization = detect_cannibalization(query_rows)
        print_cannibalization(cannibalization)

    # P2 — Plano de consolidação 301 (SUGESTÃO; derivado da canibalização)
    consolidation_plan = None
    if cannibalization:
        consolidation_plan = build_consolidation_plan(cannibalization)
        print_consolidation_plan(consolidation_plan)
        if consolidation_plan["redirects"]:
            save_redirects_csv(domain, today, consolidation_plan)
            save_redirects_txt(
                domain, today,
                build_htaccess_block(consolidation_plan, today),
                build_nginx_block(consolidation_plan, today),
            )

    # Fase 5b / P5 — tendências de demanda
    trends_data = None
    if do_trends:
        if trends_source == "pytrends":
            # Legado: índice global via pytrends (não-oficial, frágil)
            if query_rows:
                from fetchers.trends_fetcher import fetch_trends, top_keywords_from_queries, print_trends
                top_kws = top_keywords_from_queries(query_rows)
                if top_kws:
                    trends_data = fetch_trends(top_kws, domain, use_cache=use_cache)
                    print_trends(trends_data)
                else:
                    print("[trends] Nenhuma keyword Top 10 para buscar tendências.")
        else:
            # P5 — padrão: dimensão `date` do GSC (demanda real, 90 dias)
            from fetchers.position_fetcher import fetch_date_trends
            from core.analytics import compute_date_trends, print_date_trends
            try:
                raw_trends  = fetch_date_trends(service, site, use_cache=use_cache)
                trends_data = compute_date_trends(raw_trends)
                print_date_trends(trends_data)
            except Exception as exc:
                print(f"\n[ERRO] Falha ao buscar tendências GSC: {exc}")

    # Fase 5c — NLP (opt-in)
    nlp_results = None
    if do_nlp:
        from fetchers.nlp_analyzer import analyze_opportunity_urls, print_nlp_results
        nlp_results = analyze_opportunity_urls(
            report["urls"], domain, api_key=api_key, use_cache=use_cache,
        )
        print_nlp_results(nlp_results)

        # Relatório NLP detalhado — sempre gerado quando NLP está ativo
        from reporters.nlp_report_generator import generate_nlp_report
        nlp_html = generate_nlp_report(
            domain, today, nlp_results, query_rows=query_rows,
        )
        save_nlp_report(domain, today, nlp_html)

    # Move 1 — Diagnóstico de qualidade de conteúdo (opt-in)
    content_results = None
    if do_content:
        from fetchers.content_fetcher import analyze_opportunity_content_quality
        content_results = analyze_opportunity_content_quality(
            report["urls"], domain, query_rows=query_rows,
            nlp_results=nlp_results, use_cache=use_cache,
        )

    # Fase 4c + Move 2 — histórico de posição por URL (com métricas de conteúdo)
    append_historico_posicao(domain, today, period, data["rows"], content_results=content_results)
    historico_posicao = load_historico_posicao(domain)

    # Move 2 — acompanhamento conteúdo × posição
    from core.content_quality import build_content_tracking, print_content_tracking
    tracking = build_content_tracking(historico_posicao)
    print_content_tracking(tracking)

    if "txt" in formats:
        save_position_txt(domain, today, data, report)
    if "csv" in formats:
        save_csv_posicao(domain, today, report)

    # Dashboard HTML (sempre gerado)
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
        consolidation_plan=consolidation_plan,
    )
    dashboard_path = save_dashboard(domain, html)
    if result_store is not None:
        result_store["dashboard_path"] = dashboard_path

    if "excel" in formats:
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
            consolidation_plan=consolidation_plan,
        )
        save_excel_report(domain, today, wb)


# ---------------------------------------------------------------------------
# Ponto de entrada chamado pela GUI
# ---------------------------------------------------------------------------

def run_tasks(
    params: dict,
    output_queue: queue.Queue,
    done_callback,
    result_store: "dict | None" = None,
) -> None:
    """
    Inicia a execução das tarefas em uma thread daemon separada.

    Parâmetros:
        params: {
            'site'          : str        — domínio (ex: www.exemplo.com.br)
            'do_indexation' : bool
            'do_position'   : bool
            'formats'       : set[str]   — subconjunto de {'csv', 'excel', 'txt'}
            'limit'         : int | None — limite de URLs (None = todos)
            'no_cache'      : bool
            'do_queries'    : bool       — analisa canibalização (Fase 4b)
        }
        output_queue : queue.Queue onde as mensagens de log são depositadas
        done_callback: callable — chamado ao final na thread worker
        result_store : dict opcional — receberá {"health": dict} após execução
    """

    def worker() -> None:
        old_out = sys.stdout
        old_err = sys.stderr
        try:
            sys.stdout = QueueStream(output_queue)
            sys.stderr = QueueStream(output_queue)

            site       = params["site"].strip()
            domain     = _normalize_domain(site)
            today      = date.today().isoformat()
            use_cache  = not params.get("no_cache", False)
            limit      = params.get("limit")
            formats    = params.get("formats", set())
            do_queries = params.get("do_queries", False)
            do_trends  = params.get("do_trends",  False)
            do_nlp     = params.get("do_nlp",     False)
            do_content = params.get("do_content", False)
            api_key    = params.get("api_key") or None

            # Salva API key se fornecida via GUI
            if api_key:
                from fetchers.knowledge_graph import save_api_key
                save_api_key(api_key)

            print(f"\n{'=' * 55}")
            print(f"  GSC Monitor — {domain} — {today}")
            if not use_cache:
                print(f"  Modo: cache DESATIVADO")
            print(f"{'=' * 55}\n")

            from core.auth import build_service
            try:
                service = build_service()
            except FileNotFoundError as exc:
                print(f"\n[ERRO] {exc}")
                return

            if params.get("do_indexation"):
                _run_indexation(service, site, domain, today, limit, formats, use_cache)

            if params.get("do_position"):
                _run_position(
                    service, site, domain, today, formats, use_cache,
                    do_queries=do_queries,
                    do_trends=do_trends,
                    trends_source=params.get("trends_source", "gsc"),
                    do_nlp=do_nlp,
                    do_content=do_content,
                    api_key=api_key,
                    result_store=result_store,
                )

            print(f"\n{'=' * 55}")
            print(f"  Concluído.")
            print(f"{'=' * 55}\n")

        except Exception as exc:
            print(f"\n[ERRO INESPERADO] {exc}")
            print(traceback.format_exc())

        finally:
            sys.stdout = old_out
            sys.stderr = old_err
            done_callback()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
