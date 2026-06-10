"""
analisar.py — CLI do Semantic Analyzer.

Agrupa páginas por SIGNIFICADO (embeddings) para revelar conteúdo duplicado /
mesma intenção (doorway pages, canibalização). 100% local, sem cota de API.

Exemplos:
  # Backup local de um site primeWeb (lê $blog + $palavras_chave):
  py analisar.py --primeweb "E:/projetos/backup/exemplo" --html clusters.html

  # Qualquer pasta de arquivos .php/.html:
  py analisar.py --folder "E:/.../site" --threshold 0.82

  # Forçar TF-IDF (sem instalar sentence-transformers; resultado só léxico):
  py analisar.py --primeweb "..." --backend tfidf
"""

import argparse
import datetime
import os
import sys

# UTF-8 no stdout (Windows cp1252 quebraria com acentos/emoji)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.loaders import (
    load_from_folder, load_from_primeweb, load_from_urls,
    load_sources_from_folder, load_sources_from_urls,
)
from core.embedder import embed_texts_cached
from core.clusterer import build_clusters, nearest_pairs
from core.report import (
    print_clusters, print_nearest, generate_html,
    print_clusters_gsc, generate_html_gsc, print_llm_judgments, print_differentiation,
    print_keyword_collisions, print_link_audit, print_link_plan,
)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
RELATORIOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "relatorios")


def _report_path(title: str, args) -> str:
    """
    Caminho organizado do relatório, no estilo do gsc-monitor:
        relatorios/<site>/<YYYY-MM-DD>_<tipo>.html
    O <tipo> reflete o que a execução produziu (clusters / consolidacao / links /
    diferenciacao / plano-completo). Cria a pasta do site se necessário.
    """
    if args.differentiate and args.linkgraph:
        kind = "plano-completo"
    elif args.differentiate:
        kind = "diferenciacao"
    elif args.linkgraph:
        kind = "links"
    elif args.llm:
        kind = "consolidacao-llm"
    elif args.gsc:
        kind = "consolidacao"
    else:
        kind = "clusters"
    site_dir = os.path.join(RELATORIOS_DIR, title)
    os.makedirs(site_dir, exist_ok=True)
    return os.path.join(site_dir, f"{datetime.date.today().isoformat()}_{kind}.html")


def parse_args():
    p = argparse.ArgumentParser(description="Clustering semântico de páginas (local).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--primeweb", metavar="DIR", help="Pasta-base de site primeWeb (lê include/parametros.php).")
    src.add_argument("--folder", metavar="DIR", help="Pasta com arquivos .php/.html.")
    src.add_argument("--urls", metavar="ARQ", help="Arquivo .txt com uma URL por linha.")
    p.add_argument("--threshold", type=float, default=0.85,
                   help="Limiar de similaridade p/ agrupar (0..1). Maior = grupos mais estritos. Padrão 0.85.")
    p.add_argument("--method", choices=["agglomerative", "threshold"], default="agglomerative",
                   help="agglomerative (sklearn, coeso, recomendado) ou threshold (numpy, single-linkage).")
    p.add_argument("--linkage", choices=["complete", "average"], default="complete",
                   help="Linkage do agglomerative. complete = grupos bem coesos (padrão).")
    p.add_argument("--backend", choices=["auto", "st", "tfidf"], default="auto",
                   help="Motor de embeddings. Padrão auto (semântico se instalado).")
    p.add_argument("--model", default=None, help="Nome do modelo sentence-transformers (opcional).")
    p.add_argument("--html", metavar="ARQ", default=None,
                   help="Caminho custom p/ o HTML. Por padrão salva organizado em "
                        "relatorios/<site>/<data>_<tipo>.html (estilo gsc-monitor).")
    p.add_argument("--gsc", metavar="PATH", default=None,
                   help="Arquivo *_posicao.json (ou diretório) do gsc-monitor: escolhe a "
                        "canônica de cada grupo pela performance real (cliques/posição).")
    p.add_argument("--llm", action="store_true",
                   help="Julga os maiores grupos com um LLM LOCAL (útil/raso/spun + base + lacunas).")
    p.add_argument("--differentiate", action="store_true",
                   help="Gera um PLANO DE DIFERENCIAÇÃO por página (intenção/keyword/título distintos) "
                        "p/ parar a canibalização SEM apagar/301 — mantém todos os artigos.")
    p.add_argument("--linkgraph", action="store_true",
                   help="Monta o GRAFO DE LINKS INTERNOS: acha páginas órfãs, money-pages "
                        "sub-linkadas, canibalização de âncora e o plano de links hub→spoke por grupo. "
                        "100% local (lê o markup das páginas), sem API.")
    p.add_argument("--llm-backend", choices=["http", "transformers"], default="http",
                   help="http = Ollama/LM Studio (GPU, recomendado); transformers = CPU local (lento).")
    p.add_argument("--llm-url", default=None, help="URL OpenAI-compat (padrão Ollama localhost:11434/v1).")
    p.add_argument("--llm-model", default=None, help="Modelo (ex.: qwen2.5:7b-instruct; ou HF id no transformers).")
    p.add_argument("--llm-max", type=int, default=8, help="Quantos grupos julgar (padrão 8).")
    p.add_argument("--llm-unload", action="store_true",
                   help="Descarrega o modelo da memória assim que o LLM termina (Ollama), "
                        "em vez de esperar o keep_alive (~5 min). Libera VRAM/RAM na hora.")
    p.add_argument("--site-context", default=None,
                   help="1 linha sobre o site/nicho p/ contextualizar o LLM "
                        "(ex.: 'canil que vende filhotes de Cane Corso e Rottweiler').")
    p.add_argument("--min-chars", type=int, default=300, help="Ignora páginas com menos texto que isso.")
    p.add_argument("--no-cache", action="store_true", help="Ignora o cache de embeddings e recalcula.")
    return p.parse_args()


def make_options(**overrides) -> argparse.Namespace:
    """
    Namespace com os MESMOS defaults do CLI, para chamadas programáticas
    (ex.: GUI do app.py). Mantém os defaults em um lugar só.
    """
    opts = argparse.Namespace(
        primeweb=None, folder=None, urls=None,
        threshold=0.85, method="agglomerative", linkage="complete",
        backend="auto", model=None, html=None, gsc=None,
        llm=False, differentiate=False, linkgraph=False,
        llm_backend="http", llm_url=None, llm_model=None, llm_max=8,
        llm_unload=False, site_context=None,
        min_chars=300, no_cache=False,
    )
    for k, v in overrides.items():
        if not hasattr(opts, k):
            raise TypeError(f"Opção desconhecida: {k}")
        setattr(opts, k, v)
    return opts


class AnalysisError(RuntimeError):
    """Erro fatal da análise (fonte inválida, páginas insuficientes etc.)."""


def _make_llm_client(args):
    """Cria o cliente LLM local (http/Ollama por padrão, ou transformers/CPU). None se indisponível."""
    if args.llm_backend == "transformers":
        from core.llm import TransformersClient
        print("[llm] Carregando modelo local (transformers, CPU — pode demorar)...")
        return TransformersClient(model=args.llm_model or "Qwen/Qwen2.5-0.5B-Instruct")
    from core.llm import LLMClient, DEFAULT_URL, DEFAULT_MODEL
    client = LLMClient(url=args.llm_url or DEFAULT_URL, model=args.llm_model or DEFAULT_MODEL)
    if not client.available():
        print(f"[llm] Nenhum servidor LLM em {client.url}.")
        print("[llm] Inicie o Ollama ('ollama serve') ou o LM Studio (Local Server),")
        print("[llm] ou use --llm-backend transformers (CPU, sem servidor).")
        return None
    return client


def run_analysis(args) -> str:
    """
    Executa a análise completa (mesmo fluxo do CLI) e retorna o caminho do
    relatório HTML gerado.

    args: Namespace do parse_args() ou de make_options() — é assim que a GUI
    (app.py) reutiliza exatamente o mesmo pipeline, sem segundo call site.

    Levanta AnalysisError em falhas fatais (em vez de sys.exit), para que a
    GUI possa exibir o erro sem encerrar o processo.
    """
    # 1. Carrega textos
    urls = []
    if args.primeweb:
        title = os.path.basename(os.path.normpath(args.primeweb))
        pages = load_from_primeweb(args.primeweb, min_chars=args.min_chars)
    elif args.folder:
        title = os.path.basename(os.path.normpath(args.folder))
        pages = load_from_folder(args.folder, min_chars=args.min_chars)
    else:
        title = os.path.basename(args.urls)
        with open(args.urls, encoding="utf-8") as f:
            urls = [ln.strip() for ln in f if ln.strip()]
        pages = load_from_urls(urls, min_chars=args.min_chars)

    if len(pages) < 2:
        raise AnalysisError(
            f"Só {len(pages)} página(s) com texto suficiente — nada a agrupar."
        )

    labels = list(pages.keys())
    texts = [pages[k] for k in labels]
    print(f"[analisar] {len(labels)} páginas carregadas de '{title}'.")

    # 2. Embeddings (com cache em disco)
    emb, backend, hit = embed_texts_cached(
        labels, texts, model_name=args.model, backend=args.backend,
        cache_dir=CACHE_DIR, use_cache=not args.no_cache,
    )
    print(f"[embed] {'cache HIT — reaproveitado' if hit else 'embeddings gerados'} ({backend}).")

    # 3. Clustering
    clusters, sim = build_clusters(emb, labels, threshold=args.threshold,
                                   method=args.method, linkage=args.linkage)

    # 4. Cruzamento opcional com GSC (canônica por performance real)
    gsc = None
    gsc_name = None
    if args.gsc:
        from core.gsc_link import load_gsc_positions, enrich_clusters
        gsc, gsc_name = load_gsc_positions(args.gsc)
        enrich_clusters(clusters, gsc)
        matched = sum(1 for c in clusters for m in c["members_gsc"] if m.get("has_data"))
        print(f"[gsc] Cruzado com {gsc_name} ({len(gsc)} URLs; {matched} membros com dados).")

    # 5. Camada LLM (opt-in): julgamento e/ou plano de diferenciação. Roda ANTES
    #    dos relatórios p/ entrar também no HTML.
    judged = diffed = None
    client = None
    if args.llm or args.differentiate:
        client = _make_llm_client(args)
        if client:
            if args.llm:
                from core.hybrid import judge_clusters
                print(f"[llm] Julgando até {args.llm_max} grupos...")
                judged = judge_clusters(clusters, pages, client, max_clusters=args.llm_max,
                                        site_context=args.site_context)
            if args.differentiate:
                from core.hybrid import differentiate_clusters
                print(f"[diff] Plano de diferenciação p/ até {args.llm_max} grupos...")
                diffed = differentiate_clusters(clusters, pages, client, max_clusters=args.llm_max,
                                                site_context=args.site_context)
            # Trabalho do LLM acabou: libera a memória agora, se pedido.
            if args.llm_unload:
                print("[llm] modelo descarregado da memória." if client.unload()
                      else "[llm] (nada a descarregar — servidor não-Ollama ou já liberado).")

    # 5b. Dedup de keyword ENTRE grupos — completa a diferenciação (cross-cluster).
    collisions = None
    if diffed:
        from core.dedup import find_keyword_collisions
        collisions = find_keyword_collisions(diffed)
        if collisions:
            print(f"[diff] {len(collisions)} colisão(ões) de keyword entre grupos detectada(s).")

    # 5c. Grafo de links internos (opt-in): órfãs, money-pages sub-linkadas,
    #     canibalização de âncora + plano hub-and-spoke por grupo (usa o diff se houver).
    linkgraph = None
    if args.linkgraph:
        from core.linkgraph import (build_link_graph, find_orphans, inlink_report,
                                     underlinked_money_pages, anchor_collisions,
                                     cluster_link_plan)
        # O grafo precisa do SITE INTEIRO: os artigos linkam p/ páginas de categoria/
        # produto que NÃO estão em $blog/$palavras_chave. Por isso lemos todos os .php
        # da pasta (não só os do array) — senão os destinos caem fora de `known` e o
        # grafo fica falsamente vazio. As páginas ANALISADAS (clusters) seguem sendo as
        # do array; o relatório de órfãs/money-pages reporta só sobre elas (targets=pages).
        if args.primeweb:
            sources = load_sources_from_folder(args.primeweb)
        elif args.folder:
            sources = load_sources_from_folder(args.folder)
        else:
            sources = load_sources_from_urls(urls)
        graph = build_link_graph(sources)
        rows = inlink_report(graph, targets=set(pages), gsc=gsc)

        # Links gerados por ARRAY/template (primeWeb): blog.php faz foreach($blog)→
        # linka TODOS os artigos; more-articles faz array_rand→widget. O PHP é
        # removido na extração estática, então classificamos as páginas em 3 níveis
        # honestos: com link CONTEXTUAL / só template (índice/widget) / órfã de fato.
        from core.linkgraph import (parse_primeweb_arrays, build_template_inbound,
                                     classify_pages)
        base_for_arrays = args.primeweb or args.folder
        classification = None
        if base_for_arrays:
            arrays = parse_primeweb_arrays(base_for_arrays)
            if arrays:
                tin = build_template_inbound(sources, base_for_arrays, arrays,
                                             known=set(graph["known"]))
                classification = classify_pages(set(pages), graph, tin)

        if classification:
            orphans = sorted(s for s, c in classification.items() if c["tier"] == "orphan")
            template_only = sorted(s for s, c in classification.items() if c["tier"] == "template_only")
        else:
            orphans = find_orphans(graph, targets=set(pages))
            template_only = []

        linkgraph = {
            "graph":          graph,
            "classification": classification,
            "orphans":        orphans,
            "template_only":  template_only,
            "money":          underlinked_money_pages(rows) if gsc else [],
            "anchors":        anchor_collisions(graph),
            "planned":        cluster_link_plan(clusters, graph),
            "n_sources":      len(sources),
            "n_edges":        len(graph["edges"]),
        }
        extra = (f"{len(template_only)} só-template; {len(orphans)} órfã(s) de fato"
                 if classification else f"{len(orphans)} órfã(s)")
        print(f"[link] {linkgraph['n_edges']:,} links de corpo entre {len(sources)} páginas; "
              f"{extra}; {len(linkgraph['anchors'])} colisão(ões) de âncora.")

    # 6. Relatórios (console)
    if gsc_name:
        print_clusters_gsc(clusters, backend, args.threshold)
    else:
        print_clusters(clusters, backend, args.threshold)
        print_nearest(nearest_pairs(sim, labels, top=12))
    if judged:
        print_llm_judgments(judged)
    if diffed:
        print_differentiation(diffed)
    if collisions:
        print_keyword_collisions(collisions)
    if linkgraph:
        print_link_audit(linkgraph)
        print_link_plan(linkgraph["planned"])

    # 7. HTML — sempre salvo, organizado por site/data (estilo gsc-monitor:
    #    relatorios/<site>/<data>_<tipo>.html). --html sobrescreve com caminho próprio.
    out_path = args.html or _report_path(title, args)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    if gsc_name:
        html = generate_html_gsc(clusters, title, backend, args.threshold, gsc_name,
                                 collisions=collisions, linkgraph=linkgraph)
    else:
        html = generate_html(clusters, title, backend, args.threshold,
                             collisions=collisions, linkgraph=linkgraph)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[analisar] Relatório salvo em: {out_path}")
    return out_path


def main():
    args = parse_args()
    try:
        run_analysis(args)
    except AnalysisError as exc:
        print(f"[erro] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
