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
py posicao.py (--site <domain> | --batch <file>) [flags]
```

Provide either a single `--site` or a `--batch` file (not both).

| Flag | Type | Description |
|------|------|-------------|
| `--site` | str | Domain to analyze. Accepts `exemplo.com.br` or `sc-domain:exemplo.com.br` for a Domain Property. |
| `--batch FILE` | str | Headless batch mode: a file with one domain per line (`#` starts a comment). Runs the standard pipeline (positions + queries + content) for each site without aborting on errors. |
| `--batch-report` | flag | With `--batch`: write a consolidated summary to `relatorios/_batch/YYYY-MM-DD_resumo.csv`. |
| `--excel` | flag | Generate the `.xlsx` workbook (position bands, CTR opportunities, cannibalization, content quality, 301 plan…). |
| `--csv` | flag | Save the ranking report as `.csv`. |
| `--txt` | flag | Save a human-readable `.txt` alongside the JSON. |
| `--queries` | flag | Analyze keyword cannibalization (fetches query+page data). Also triggers the 301 consolidation plan when competing groups exist. |
| `--trends` | flag | Demand trends. Default source is the GSC `date` dimension (first-party, 90 days, site-specific). |
| `--trends-source` | `gsc`\|`pytrends` | Trend source. `gsc` (default, first-party) or `pytrends` (legacy, unofficial global index; requires `pip install pytrends`). |
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

### `poda.py` — pruning plan (old URLs outside the sitemap)

Two-stage CLI. Stage 1 generates an editable CSV of "ghost" URLs (known to
Google, absent from the sitemap); the analyst reviews it; stage 2 compiles the
reviewed CSV into redirect blocks. See the
[pruning concept](ARCHITECTURE.md#pruning-plan-poda) for the rationale.

```
py poda.py --site <domain> [flags]            # stage 1 — generate {date}_poda.csv
py poda.py --site <domain> --compilar [CSV]   # stage 2 — compile reviewed CSV
```

| Flag | Type | Description |
|------|------|-------------|
| `--site` | required | Domain to analyze. |
| `--compilar [CSV]` | str? | Stage 2: compile the reviewed CSV into Apache/nginx/PHP blocks. With no value, uses the newest `*_poda.csv` for the domain. |
| `--min-impressoes N` | int | Impressions floor to mark a URL `revisar` instead of `410` (default from `config.PODA_MIN_IMPRESSIONS`). |
| `--dias N` | int | Search Analytics look-back window in days (default ≈ 480 ≈ 16 months, the GSC maximum). |
| `--importar-gsc FILE…` | str+ | One or more files/folders with the GSC "Pages" report export (csv/txt/xlsx) — covers old URLs with zero impressions the API can't see. |
| `--sem-fallback-home` | flag | Disable the home-page fallback: `revisar` URLs with no query/slug target keep `destino_final` blank instead of suggesting the home as a last resort. |
| `--no-cache` | flag | Ignore cache and force fresh API calls. |

### `logs.py` — crawl budget (Googlebot via access log)

Reads the server's access log (Apache/Nginx, `combined` or `common`, `.gz`
transparent) and reports what Googlebot actually crawled. Fully local, no API
quota. See the [crawl-budget concept](ARCHITECTURE.md#crawl-budget-access-logs)
for the honesty constraints.

```
py logs.py --site <domain> --logs access.log [access.log.1.gz …] [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--site` | required | Domain to analyze. |
| `--logs FILE…` | required | One or more access-log files; `.gz` is read transparently. |
| `--format` | `combined`\|`common` | Force the log format. Default: detect (`combined`, then `common`). |
| `--no-sitemap` | flag | Skip the sitemap fetch, and with it the "never crawled" list. |
| `--gsc` | flag | Cross with the newest saved `*_posicao.json` to flag undercrawled money pages. |
| `--verify-googlebot` | flag | Verify each Googlebot IP by reverse+forward DNS (slow, reliable). |
| `--top N` | int | Rows to show in the "top" tables (default from `config.CRAWL_TOP_N`). |

Outputs `{date}_crawl.json`, `.txt`, `.csv` and `.html` under
`relatorios/{domain}/`. Two verdicts are **refused** rather than guessed — with a
`common` log (no User-Agent) nothing can be identified as Googlebot, and with a
log window shorter than `config.UNDERCRAWLED_MIN_LOG_DAYS` "zero crawl" does not
support "undercrawled". Each refusal appears in `result["indisponivel"]` with its
reason, on every surface.

### `app.py` — GUI (ranking / indexing)

```
py app.py
```

No arguments. Opens a Tkinter window that drives the same indexing/ranking code
on a background thread, with live output and a button to open the report folder.

### `app_poda.py` — GUI (pruning plan)

```
py app_poda.py
```

No arguments. A dedicated two-step window for the pruning plan: generate the
editable CSV, review it, then compile the redirect blocks.

---

## gsc-monitor modules

### `config.py`

Centralized constants and paths: `BASE_DIR`, `CTR_BENCHMARK` (expected CTR per
position), `HEALTH_WEIGHTS`, the health grade thresholds
(`HEALTH_GRADE_EXCELENTE/BOM/REGULAR`), cannibalization/day-window constants, and
the pruning defaults (`PODA_MIN_IMPRESSIONS`, `PODA_DAYS_BACK`).

### `core/urls.py`

| Function | Purpose |
|----------|---------|
| `normalize_domain(site) -> str` | Canonicalize a domain so `https://x/` and `sc-domain:x` produce the same cache key. Single source of truth, imported by `posicao.py` and `position_fetcher.py`. |
| `build_site_url(domain) -> str` | Build the Search Console property URL from a domain. |
| `url_path(url) -> str` | Path only, **preserving** the trailing slash — the pruning plan needs the exact form, since a redirect target must match the live sitemap URL. |
| `url_path_with_query(url) -> str` | Path + query. Feeds redirect generation, where `/p?id=1` and `/p?id=2` are different targets. |
| `canonical_path(path_or_url) -> str` | The **join key** for sitemap × access log × GSC: no query or fragment, leading slash guaranteed, trailing slash stripped. Accepts a raw log path or an absolute URL. Single implementation for the same reason `normalize_domain` has one — the cross only works if all three sources produce the same key. |

### `core/ctr.py`

| Function | Purpose |
|----------|---------|
| `expected_ctr(position) -> float \| None` | Interpolated benchmark CTR for a given average position (from `config.CTR_BENCHMARK`); `None` beyond the table. |

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
| `calculate_health_score(...) -> dict` | Composite 0–100 score (indexing×0.4 + position×0.4 + ctr×0.2), impression-weighted, re-normalized when indexing is absent. Returns `component_alerts`. |
| `build_component_alerts(components) -> list` | Per-component alerts when a component falls below 40 (`critico` < 20, `alto` < 40), each with a plain-language pt-BR message. The composite is never suppressed. |
| `print_health_score(health)` | Print the score, its decomposition, and any component alerts. |
| `detect_orphan_pages(position_report) -> list` | Pages with no impressions (note: historically mislabeled "orphans"). |
| `print_orphan_pages(orphans, max_display=20)` | Print pages with no impressions. |
| `detect_cannibalization(query_rows) -> list` | Groups of URLs genuinely competing (impressions ≥ 10, position ≤ 30) with a `severity` field. |
| `print_cannibalization(cannibalization, max_display=10)` | Print cannibalization groups. |
| `build_consolidation_plan(cannibalization) -> dict` | Turn cannibalization into a **suggested** 301 plan: pick the canonical URL (clicks → position → impressions) and list the others as redirect sources; resolve cross-group conflicts by severity. |
| `print_consolidation_plan(plan, max_display=10)` | Print the 301 plan (always labeled a suggestion). |
| `compute_date_trends(date_data, top_n=10, metric="impressions") -> dict` | Pure function: classify site and per-query demand trend (first-third vs last-third of daily impressions → rising/stable/declining). |

### `core/content_quality.py`

| Function | Purpose |
|----------|---------|
| `keyword_density(text, keyword) -> tuple` | Density of a keyword in the text. |
| `slug_phrase(url) -> str \| None` | Convert a URL slug to a phrase (split on `-`/`_`, drop pt-BR stopwords, accent-insensitive) for density measurement. |
| `dominant_ngram(text, min_count=…) -> tuple \| None` | The most-repeated 2–3-word n-gram in the page text (floor of repetitions, non-stopword borders). |
| `vocab_diversity(text) -> float` | Lexical diversity signal. |
| `salience_concentration(nlp_result) -> float \| None` | How concentrated entity salience is (NLP signal). |
| `target_keywords_for_url(...)` | Derive a page's target keyword(s) from its real GSC queries. |
| `analyze_content_quality(...) -> dict` | Conservative verdict: `ok` / `atencao` / `over_otimizado` / `raso`. Density is the max of GSC-query / slug-phrase / dominant-n-gram; `density_source` records the trigger. |
| `print_content_quality(url, cq)` | Print the per-URL verdict. |
| `build_content_tracking(historico) -> dict` | Cross-reference content metrics × position over snapshots (the measurement loop). |
| `print_content_tracking(tracking)` | Print the tracking table. |

### `core/pruning.py`

The pruning ("Poda") engine: diff GSC pages against the sitemap, suggest actions,
and compile redirect blocks. All outputs are clearly marked suggestions.

| Function | Purpose |
|----------|---------|
| `find_ghost_urls(api_pages, sitemap_urls) -> list` | URLs Google knows but the sitemap omits (the pruning candidates). |
| `build_pruning_plan(...) -> dict` | Build the editable plan: `410` for no-traffic ghosts, `revisar` for ghosts with traffic, with a suggested 301 target (shared query → similar slug → optional home fallback), always canonicalized to a live sitemap URL. |
| `parse_plan_csv(lines) -> dict` | Parse the analyst-reviewed CSV (`;`-delimited, comma decimals). |
| `build_poda_htaccess(entries, date) -> str` | Apache `.htaccess` block (anchored `RedirectMatch`). |
| `build_poda_redirect(entries, date) -> str` | Apache `mod_alias` `Redirect 301` block (simple, prefix-match). |
| `build_poda_nginx(entries, date) -> str` | nginx `server {}` block. |
| `build_poda_php(entries, date, filename=…) -> str` | Standalone PHP redirect file for hosts where the server config can't be edited. |
| `print_pruning_plan(plan, max_display=10)` | Print the plan summary. |
| `normalize_for_match(url) -> str` | Normalize a URL (www/https/trailing-slash/percent-encoding) for diffing. |

### `core/log_analyzer.py`

Pure aggregation of an access log, plus an opt-in DNS check (the module does
import `socket` — it is not network-free).

| Function | Purpose |
|----------|---------|
| `analyze_lines(lines, *, sitemap_urls, position_report, resolve_googlebot, format_name, top_n) -> dict` | Aggregate an iterable of log lines into a crawl-budget report. Streamable. Sets `has_user_agent`, `date_range`, the `googlebot` block, and `indisponivel` — the list of verdicts refused, with reasons. |
| `analyze_logs(paths, **kwargs) -> dict` | Thin file wrapper over `analyze_lines`; accepts one path or a list, `.gz` transparent. |
| `classify_googlebot_ip(ip) -> str` | `"verified"` / `"forged"` / `"unverifiable"` by reverse-then-forward DNS (Google's documented method). `unverifiable` means probable CDN/proxy, **not** fraud. |
| `is_googlebot(ua) -> bool` | UA-only match against `config.GOOGLEBOT_UA_PATTERNS`. Forgeable by design — see `classify_googlebot_ip`. |
| `print_crawl_report(result)` | Terminal summary, including every refused verdict and its reason. |

### `core/batch.py`

| Function | Purpose |
|----------|---------|
| `parse_sites_file(path) -> list` | Read a batch file (one domain per line, `#` comments). |
| `run_batch(sites, pipeline_fn) -> list` | Run `pipeline_fn` per site, isolating errors so one failure doesn't abort the batch. |
| `format_site_summary(result) -> str` | One-line per-site summary (health + grade + snapshot count). |
| `write_batch_report(results, date) -> str` | Write `relatorios/_batch/YYYY-MM-DD_resumo.csv`. |

### `core/cache.py`

Per-domain JSON cache in `relatorios/<site>/.cache/`. API errors are never cached.
Cache TTL timestamps are UTC-aware (backward-compatible with older naive caches).

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
| `position_fetcher.fetch_positions(...)` | Pull per-page Search Analytics data; also returns `ghost_rows` (pages with GSC data absent from the sitemap) used by the pruning plan. |
| `position_fetcher.fetch_query_positions(...)` | Pull query+page data (for cannibalization). |
| `position_fetcher.fetch_date_trends(...)` | Pull the `date` and `date+query` series for first-party demand trends (90 days, 24h cache). |
| `inspector.inspect_urls(...)` | URL Inspection API (indexing status). |
| `knowledge_graph.search_entity(...)` | Knowledge Graph Search with false-positive guard. |
| `knowledge_graph.load_api_key()` / `save_api_key(key)` / `brand_from_domain(domain)` | API-key handling and brand inference. |
| `knowledge_graph.print_kg_result(result)` | Print the KG match. |
| `nlp_analyzer.analyze_page_nlp(url, api_key) -> dict` | Cloud NL `annotateText` on one page. |
| `nlp_analyzer.analyze_opportunity_urls(...)` | NLP across opportunity pages. |
| `nlp_analyzer.print_nlp_results(nlp_results)` | Print NLP output. |
| `trends_fetcher.fetch_trends(...)` | Legacy Google Trends via `pytrends` (fragile, optional — only `--trends-source pytrends`). |
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
| `excel_reporter.generate_excel(...)` | Build the multi-sheet workbook (Resumo, Posicionamento, Oportunidades CTR, Histórico, Trends, Canibalização, Plano 301, Sem Impressões, Qualidade Conteúdo). |
| `html_reporter.generate_dashboard(...)` | Build the Chart.js dashboard; each section appears only if its data exists. |

> When adding a report toggle, add it to the `ReportOptions` dataclass in
> `posicao.py` — the single source of truth threaded through both the CLI
> (`run_pipeline`) and the GUI (`gui/runner.py`), so the two can't drift.

---

## semantic-analyzer CLI

### `analisar.py`

```
py analisar.py (--primeweb DIR | --folder DIR | --urls FILE) [flags]
```

Exactly one source is required. `run_analysis(args)` is the public pipeline
entry point that both the CLI and the GUI call.

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

### `app.py` — GUI

```
py app.py
```

No arguments. Opens the same integrated window as gsc-monitor (live terminal
output, "open folder" / "open report" buttons) and calls `analisar.run_analysis`
directly — the GUI runs the exact CLI pipeline, including the GSC cross-reference,
LLM judgment, differentiation, and link graph.

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
