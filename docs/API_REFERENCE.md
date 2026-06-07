# API reference

Reference for the command-line interfaces and the public functions of each
module. Signatures are taken directly from the source; private helpers (leading
`_`) are omitted. For conceptual context see [`ARCHITECTURE.md`](ARCHITECTURE.md).

- [gsc-monitor CLI](#gsc-monitor-cli)
- [gsc-monitor modules](#gsc-monitor-modules)
- [semantic-analyzer CLI](#semantic-analyzer-cli)
- [semantic-analyzer modules](#semantic-analyzer-modules)

---

## gsc-monitor CLI

### `posicao.py` — ranking report

```
py posicao.py --site <domain> [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--site` | required | Domain to analyze. Accepts `exemplo.com.br` or `sc-domain:exemplo.com.br` for a Domain Property. |
| `--excel` | flag | Generate the `.xlsx` workbook (position bands + CTR opportunities). |
| `--csv` | flag | Save the ranking report as `.csv`. |
| `--txt` | flag | Save a human-readable `.txt` alongside the JSON. |
| `--queries` | flag | Analyze keyword cannibalization (fetches query+page data). |
| `--trends` | flag | Google Trends for the top 10 keywords (requires `pytrends`). |
| `--nlp` | flag | Entity/category NLP on opportunity pages via `annotateText` (**uses API quota**). |
| `--content` | flag | Content-quality verdict (over-optimization / thin content). Local signals, no quota; enriched by `--nlp`. |
| `--no-cache` | flag | Ignore cache and force fresh API calls. |
| `--api-key KEY` | str | Google Cloud API key for KG/NLP. Alternatives: `GOOGLE_API_KEY` env var or `google_api_key.txt`. |

### `main.py` — indexing report

```
py main.py --site <domain> [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--site` | required | Domain to inspect (same format as above). |
| `--limit N` | int | Limit number of URLs inspected — **use this when testing** (URL Inspection is capped at 2,000/day). |
| `--verbose`, `-v` | flag | Print detailed per-URL results. |
| `--txt` | flag | Save a readable `.txt` alongside the JSON. |
| `--csv` | flag | Save the indexing report as `.csv`. |
| `--no-cache` | flag | Ignore cache and force fresh API calls (uses quota). |

### `app.py` — GUI

```
py app.py
```

No arguments. Opens a Tkinter window that drives the same indexing/ranking code
on a background thread, with live output and a button to open the report folder.

---

## gsc-monitor modules

### `config.py`

`BASE_DIR` — absolute path to the `gsc-monitor/` directory, used to anchor all
file paths.

### `core/auth.py`

| Function | Purpose |
|----------|---------|
| `build_service()` | Build an authenticated Search Console API service; handles OAuth2 and silent token refresh. |

### `core/sitemap.py`

| Function | Purpose |
|----------|---------|
| `fetch_urls(domain) -> list[str]` | Fetch and parse the site's `sitemap.xml`, with a robots.txt fallback. |

### `core/classifier.py`

| Function | Purpose |
|----------|---------|
| `classify(verdict) -> str` | Map a URL Inspection verdict to a category; safe fallback for unknown API values. |

### `core/analytics.py`

| Function | Purpose |
|----------|---------|
| `calculate_health_score(...) -> dict` | Composite 0–100 score (indexing×0.4 + position×0.4 + ctr×0.2), impression-weighted, re-normalized when indexing is absent. |
| `print_health_score(health)` | Print the score and its decomposition. |
| `detect_orphan_pages(position_report) -> list` | Pages with no impressions (note: historically mislabeled "orphans"). |
| `print_orphan_pages(orphans, max_display=20)` | Print pages with no impressions. |
| `detect_cannibalization(query_rows) -> list` | Groups of URLs genuinely competing (impressions ≥ 10, position ≤ 30) with a `severity` field. |
| `print_cannibalization(cannibalization, max_display=10)` | Print cannibalization groups. |

### `core/content_quality.py`

| Function | Purpose |
|----------|---------|
| `keyword_density(text, keyword) -> tuple` | Density of a keyword in the text. |
| `vocab_diversity(text) -> float` | Lexical diversity signal. |
| `salience_concentration(nlp_result) -> float \| None` | How concentrated entity salience is (NLP signal). |
| `target_keywords_for_url(...)` | Derive a page's target keyword(s) from its real GSC queries. |
| `analyze_content_quality(...) -> dict` | Conservative verdict: `ok` / `atencao` / `over_otimizado` / `raso`. |
| `print_content_quality(url, cq)` | Print the per-URL verdict. |
| `build_content_tracking(historico) -> dict` | Cross-reference content metrics × position over snapshots (the measurement loop). |
| `print_content_tracking(tracking)` | Print the tracking table. |

### `core/cache.py`

Per-domain JSON cache in `relatorios/<site>/.cache/`. API errors are never cached.

| Function | Purpose |
|----------|---------|
| `get_posicao_cache(site, start_date, end_date) -> dict \| None` | Read cached position data (72h TTL). |
| `set_posicao_cache(site, start_date, end_date, api_data)` | Write position cache. |
| `get_query_cache(site, start_date, end_date) -> list \| None` | Read cached query+page rows (72h). |
| `set_query_cache(site, start_date, end_date, rows)` | Write query cache. |
| `get_inspect_cache(site, date_str, url) -> dict \| None` | Read cached inspection (24h). |
| `set_inspect_cache(site, date_str, url, result)` | Write inspection cache. |

### `core/storage.py`

All report/snapshot file IO. Selected public functions:

| Function | Purpose |
|----------|---------|
| `build_snapshot(site, date, url_results) -> dict` | Build an indexing snapshot dict. |
| `append_historico(snapshot)` / `load_historico() -> list[dict]` | Indexing history append/read. |
| `append_historico_posicao(...)` / `load_historico_posicao(site) -> dict` | Position history (capped at 30 per domain). |
| `save_detailed_report` / `save_consolidated_report` / `save_text_report` | Write indexing reports. |
| `save_position_report` / `save_position_txt` / `save_csv_posicao` | Write ranking reports. |
| `save_excel_report(site, date, workbook) -> str` | Persist the Excel workbook. |
| `save_dashboard(site, html) -> str` | Persist `dashboard.html`. |
| `save_nlp_report(site, date, html) -> str` | Persist the NLP report. |
| `load_latest_consolidated(site) -> dict \| None` | Load the newest consolidated indexing report. |

### `fetchers/` (network IO)

| Module · function | Purpose |
|-------------------|---------|
| `position_fetcher.fetch_positions(...)` | Pull per-page Search Analytics data. |
| `position_fetcher.fetch_query_positions(...)` | Pull query+page data (for cannibalization). |
| `inspector.inspect_urls(...)` | URL Inspection API (indexing status). |
| `knowledge_graph.search_entity(...)` | Knowledge Graph Search with false-positive guard. |
| `knowledge_graph.load_api_key()` / `save_api_key(key)` / `brand_from_domain(domain)` | API-key handling and brand inference. |
| `knowledge_graph.print_kg_result(result)` | Print the KG match. |
| `nlp_analyzer.analyze_page_nlp(url, api_key) -> dict` | Cloud NL `annotateText` on one page. |
| `nlp_analyzer.analyze_opportunity_urls(...)` | NLP across opportunity pages. |
| `nlp_analyzer.print_nlp_results(nlp_results)` | Print NLP output. |
| `trends_fetcher.fetch_trends(...)` | Google Trends via `pytrends` (fragile, optional). |
| `trends_fetcher.top_keywords_from_queries(query_rows, max_kw=10)` | Pick keywords to send to Trends. |
| `trends_fetcher.print_trends(trends_data)` | Print trend classifications. |
| `content_fetcher.fetch_page_text_cached(site, url, use_cache=True) -> str \| None` | Fetch page text (72h text cache). |
| `content_fetcher.analyze_opportunity_content_quality(...)` | Orchestrate content-quality analysis (no quota). |

### `reporters/`

| Module · function | Purpose |
|-------------------|---------|
| `position_reporter.build_position_report(domain, today, data) -> dict` | Build the ranking report structure. |
| `position_reporter.print_position_report(domain, today, data)` | Print the ranking report. |
| `position_reporter.build_position_txt_lines(...)` | Build TXT lines. |
| `reporter.build_detailed(site, date, url_results) -> dict` | Build detailed indexing report. |
| `reporter.build_consolidated(site, date, url_results) -> dict` | Build consolidated indexing report. |
| `reporter.print_consolidated` / `print_detailed` | Print indexing reports. |
| `excel_reporter.generate_excel(...)` | Build the multi-sheet workbook (Summary, Positioning, CTR Opportunities, History, Trends, Cannibalization, No-Impressions, Content Quality). |
| `html_reporter.generate_dashboard(...)` | Build the Chart.js dashboard; each section appears only if its data exists. |

> When adding a parameter to `generate_dashboard` or `generate_excel`, propagate
> it through **both** `posicao.py` and `gui/runner.py`.

---

## semantic-analyzer CLI

### `analisar.py`

```
py analisar.py (--primeweb DIR | --folder DIR | --urls FILE) [flags]
```

Exactly one source is required.

**Source (pick one):**

| Flag | Value | Description |
|------|-------|-------------|
| `--primeweb` | DIR | primeWeb site base folder; reads `include/parametros.php` (`$blog` + `$palavras_chave`). |
| `--folder` | DIR | Any folder of `.php`/`.html` files. |
| `--urls` | FILE | `.txt` with one URL per line (fetches and extracts text). |

**Clustering:**

| Flag | Default | Values | Description |
|------|---------|--------|-------------|
| `--threshold` | `0.85` | 0..1 | Minimum similarity to group. Higher = stricter groups. |
| `--method` | `agglomerative` | `agglomerative`, `threshold` | Cohesive (sklearn) vs single-linkage (numpy). |
| `--linkage` | `complete` | `complete`, `average` | Agglomerative linkage. |
| `--min-chars` | `300` | int | Ignore pages with less text. |

**Embeddings:**

| Flag | Default | Values | Description |
|------|---------|--------|-------------|
| `--backend` | `auto` | `auto`, `st`, `tfidf` | Vector engine; `auto` uses sentence-transformers if installed, `tfidf` is lexical-only. |
| `--model` | multilingual MiniLM | ST name | Swap the sentence-transformers model. |
| `--no-cache` | off | flag | Ignore the embedding cache and recompute. |

**GSC cross-reference:**

| Flag | Value | Description |
|------|-------|-------------|
| `--gsc` | PATH | A `YYYY-MM-DD_posicao.json` file **or** its folder (picks the newest). Chooses the page to keep by real performance and orders groups by impressions in dispute. |

**Local LLM layer:**

| Flag | Default | Description |
|------|---------|-------------|
| `--llm` | off | Judge the largest groups (`spun`/`raso`/`ok` + base + gaps). |
| `--differentiate` | off | Contract-safe plan: distinct intent/keyword/title per page (head + spokes), keeps every article. Runs cross-group keyword dedup. Combinable with `--llm`. |
| `--llm-backend` | `http` | `http` (Ollama/LM Studio, GPU) or `transformers` (CPU, no server, slow). |
| `--llm-url` | Ollama `localhost:11434/v1` | OpenAI-compatible endpoint (LM Studio = `localhost:1234/v1`). |
| `--llm-model` | `qwen2.5:7b-instruct` | Server model name (or HF id for `transformers`). |
| `--llm-max` | `8` | How many groups to judge (prioritized by impressions in dispute). |
| `--llm-unload` | off | Unload the model from memory immediately when done (Ollama `keep_alive=0`). |
| `--site-context` | — | One line about the niche; significantly improves gap suggestions. |

**Internal-link graph:**

| Flag | Description |
|------|-------------|
| `--linkgraph` | Build the internal-link graph (reads page markup, no API). Classifies pages as contextual-linked / index-widget-only / truly orphan, finds money pages with no contextual inlinks, anchor cannibalization, and the hub→spoke link plan. No LLM needed. |

**Output:**

| Flag | Value | Description |
|------|-------|-------------|
| `--html` | FILE | Save the HTML report (includes GSC, LLM verdicts, differentiation plan, and link graph when present). Defaults to an auto-named file under `relatorios/<site>/`. |

---

## semantic-analyzer modules

### `core/loaders.py`

| Function | Purpose |
|----------|---------|
| `slugify(s) -> str` | URL-style slug from a string. |
| `extract_text(markup) -> str` | Strip markup to readable text. |
| `load_from_folder(...)` / `load_from_primeweb(base_path, min_chars=300)` / `load_from_urls(urls, min_chars=300, timeout=12)` | Load page text from each source (returns `{label: text}`). |
| `load_sources_from_folder/primeweb/urls(...)` | Load raw markup (for the link graph). |

### `core/embedder.py`

| Function | Purpose |
|----------|---------|
| `embed_texts(texts, model_name=DEFAULT_MODEL, backend="auto")` | Embed texts; returns vectors + backend used. |
| `embed_texts_cached(labels, texts, model_name=None, backend="auto", ...)` | Same, with on-disk cache keyed by model + content; returns `(emb, backend, hit)`. |

### `core/clusterer.py`

| Function | Purpose |
|----------|---------|
| `normalize(embeddings) -> np.ndarray` | L2-normalize. |
| `cosine_similarity_matrix(embeddings) -> np.ndarray` | Pairwise cosine matrix. |
| `cluster_by_threshold(sim, threshold) -> list` | Single-linkage grouping. |
| `cluster_agglomerative(embeddings, threshold, linkage="complete") -> list` | Agglomerative grouping. |
| `cluster_cohesion(indices, sim) -> float` | Group cohesion score. |
| `build_clusters(embeddings, labels, threshold=0.85, ...)` | Top-level clustering; returns `(clusters, sim)`. |
| `nearest_pairs(sim, labels, top=15) -> list` | Most-similar page pairs. |

### `core/gsc_link.py`

| Function | Purpose |
|----------|---------|
| `load_gsc_positions(path)` | Load a GSC snapshot (file or folder); returns `(positions, name)`. |
| `enrich_clusters(clusters, gsc) -> list` | Attach GSC performance to cluster members and pick the canonical to keep. |

### `core/llm.py`

| Symbol | Purpose |
|--------|---------|
| `LLMClient` | OpenAI-compatible HTTP client (Ollama/LM Studio). |
| `TransformersClient` | Local CPU client via `transformers`. |
| `LLMUnavailable` | Raised when no server is reachable. |
| `parse_json_block(text) -> dict` | Extract a JSON object from model output. |

### `core/hybrid.py`

| Function | Purpose |
|----------|---------|
| `build_prompt(cluster, pages, max_chars=1500, ...)` | Build the judgment prompt. |
| `judge_clusters(clusters, pages, client, ...)` | Judge groups as spun/thin/ok with a base page and gaps. |
| `build_diff_prompt(cluster, pages, max_chars=1200, ...)` | Build the differentiation prompt. |
| `differentiate_clusters(clusters, pages, client, ...)` | Produce the contract-safe differentiation plan. |

### `core/dedup.py`

| Function | Purpose |
|----------|---------|
| `normalize_kw(s) -> str` | Normalize a keyword for comparison. |
| `find_keyword_collisions(diffed, fuzzy_threshold=0.7) -> list` | Detect keyword collisions across differentiated groups. |

### `core/linkgraph.py`

| Function | Purpose |
|----------|---------|
| `extract_links(markup) -> list` | Pull links from page markup. |
| `normalize_href(href) -> str \| None` | Canonicalize an href to a slug. |
| `build_link_graph(sources, known=None) -> dict` | Build the internal-link graph. |
| `find_orphans(graph, targets=None) -> list` | Pages with no inbound links. |
| `inlink_report(graph, targets=None, ...)` | Inbound-link counts per page. |
| `underlinked_money_pages(rows, max_inlinks=1, ...)` | High-traffic pages with too few contextual inlinks. |
| `anchor_collisions(graph, min_targets=2) -> list` | Same anchor text pointing at different pages. |
| `parse_primeweb_arrays(base_path) -> dict` | Read template arrays from `parametros.php`. |
| `classify_pages(targets, graph, template_inbound) -> dict` | Classify pages: contextual / index-widget / orphan. |
| `cluster_link_plan(clusters, graph, min_size=2) -> list` | Hub→spoke link plan per group. |

### `core/report.py`

| Function | Purpose |
|----------|---------|
| `generate_html(clusters, title, backend, threshold, ...)` | Render the base clusters report. |
| `generate_html_gsc(clusters, title, backend, threshold, ...)` | Render the GSC-enriched consolidation report. |
| `print_clusters` / `print_clusters_gsc` / `print_nearest` | Console output for clusters. |
| `print_llm_judgments(judged)` | Console output for LLM verdicts. |
| `print_differentiation(diffed)` | Console output for the differentiation plan. |
| `print_keyword_collisions(collisions)` | Console output for cross-group collisions. |
| `print_link_audit(lg)` / `print_link_plan(planned)` | Console output for the link graph and plan. |
