# Architecture

This document explains how the two tools are built, how data flows through them,
and the design decisions that matter when you change something. It assumes you've
read the [project README](../README.md) for context on *why* the project exists.

## Context and goals

The project diagnoses two failure modes that recent Google core updates punish:
**content cannibalization** (many pages competing for the same intent) and
**over-optimization / thin content** (keyword-heavy pages with little substance).
The maintainer works at an SEO company that builds article-per-keyword sites at
scale, which produces exactly these problems. The tools exist to detect the
problems empirically, propose fixes, and then *measure whether the fixes worked*.

Two hard constraints drive the architecture:

- **No paid services.** Everything is a free API tier or runs locally. This rules
  out hosted LLM "insights" and forces rule-based verdicts plus optional local
  models.
- **Quota, not compute, is the scarce resource.** URL Inspection is capped at
  2,000 calls/day and Cloud NLP at 5,000 units/month, so caching and opt-in
  expensive paths are first-class concerns, while RAM is plentiful.

## High-level design

The repository is three independent Python programs that share data through the
filesystem. There is no shared package and no import edge between them — the
couplings are that `semantic-analyzer` reads JSON snapshots written by
`gsc-monitor`, and `keyword-research` consumes GSC query CSVs exported by
`gsc-monitor/exportar_keywords.py`.

```
┌──────────────────────────── gsc-monitor ────────────────────────────┐
│  entry points        core (pure logic)        fetchers (network IO)  │
│  ┌───────────┐       ┌──────────────┐         ┌──────────────────┐   │
│  │ app.py    │       │ analytics    │         │ position_fetcher │   │
│  │ app_poda  │       │ content_qual │         │ inspector        │   │
│  │ posicao.py│──────▶│ pruning      │◀────────│ knowledge_graph  │   │
│  │ poda.py   │       │ batch        │         │ nlp_analyzer     │   │
│  │ main.py   │       │ classifier   │         │ trends_fetcher   │   │
│  └───────────┘       │ sitemap      │         │ content_fetcher  │   │
│        │             │ cache·storage│         └──────────────────┘   │
│        │             │ ctr·urls     │                                │
│        ▼             └──────────────┘                                │
│  reporters: position_reporter · reporter · excel_reporter ·          │
│             html_reporter · nlp_report_generator                     │
│        │                                                             │
│        ▼ relatorios/<site>/                                          │
│   YYYY-MM-DD_posicao.json · .xlsx · dashboard.html · CSV ·          │
│   YYYY-MM-DD_redirects.* (301 plan) · poda/ (pruning blocks)        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ (file handoff via --gsc)
┌──────────────────────────────▼──── semantic-analyzer ────────────────┐
│  analisar.py (CLI) · app.py (GUI) → run_analysis()                    │
│  core: loaders → embedder → clusterer → gsc_link → hybrid (llm) →     │
│        dedup → linkgraph → report                                     │
│  output: relatorios/<site>/YYYY-MM-DD_<tipo>.html                     │
└───────────────────────────────────────────────────────────────────────┘
```

## gsc-monitor

The codebase is layered so that pure logic stays free of network and disk IO
wherever possible — that's what makes the bulk of it unit-testable without
spending quota.

The **entry points** are thin orchestrators. `posicao.py` produces ranking
reports (and the headless `--batch` mode), `main.py` produces indexing reports,
`poda.py` produces the pruning plan, and `app.py` / `app_poda.py` launch Tkinter
GUIs that drive the same code paths on a background thread (`gui/runner.py` and
`gui/poda_runner.py` stream output back to the window through a `QueueStream`).
Each entry point reconfigures stdout/stderr to UTF-8 so the Unicode in console
output renders correctly. `posicao.py` also defines `ReportOptions` — a frozen
dataclass that is the single source of truth for report toggles, threaded through
both the CLI (`run_pipeline`) and the GUI so the two can't drift.

The **`core/`** layer is the rule-based brain:

- `analytics.py` computes the health score (with per-component alerts), detects
  cannibalization, finds pages with no impressions, builds the 301 consolidation
  plan, and computes first-party demand trends.
- `content_quality.py` produces the over-optimization / thin-content verdict from
  local signals (word count, keyword density, exact repetitions, vocabulary
  diversity) plus optional NLP signals (salience concentration, entity count).
- `pruning.py` builds the pruning ("Poda") plan and compiles redirect blocks.
- `batch.py` orchestrates the headless multi-site run.
- `classifier.py` maps a Search Console inspection verdict to a category.
- `sitemap.py` fetches and parses `sitemap.xml` (with a robots.txt fallback).
- `ctr.py` interpolates expected CTR per position; `urls.py` centralizes domain
  normalization so the CLI and the fetcher produce identical cache keys.
- `cache.py` and `storage.py` handle the per-domain JSON cache and all file IO.

The **`fetchers/`** layer is the only place that touches external APIs:
Search Analytics (`position_fetcher`, including the `date`-dimension trends and
the `ghost_rows` that feed pruning), URL Inspection (`inspector`), Knowledge
Graph (`knowledge_graph`), Cloud Natural Language (`nlp_analyzer`), the legacy
`pytrends` path (`trends_fetcher`), and page-text fetching for content quality
(`content_fetcher`).

The **`reporters/`** layer turns the computed data into artifacts: a multi-sheet
Excel workbook (`excel_reporter`), an interactive Chart.js dashboard
(`html_reporter`), and plain console/CSV/TXT output.

### Ranking pipeline

The flow for a ranking run is:

```
auth → sitemap → fetch_positions → build_report → analytics
     → content_quality → consolidation plan → reports (excel / html / csv)
```

The HTML dashboard is **regenerated on every run**. Each run also appends a
snapshot to `historico_posicao.json` (capped at 30 per domain), which is what
makes longitudinal measurement possible. The `--batch` mode runs this exact
pipeline per site from a sites file, isolating errors so one site's failure never
aborts the rest, and (with `--batch-report`) writes a cross-site summary CSV.

### Key concepts

- **Health score (0–100)** = `indexing×0.4 + position×0.4 + ctr×0.2`. Position is
  **weighted by impressions** so it reflects where traffic actually ranks. When
  indexing data is absent, the weights are **re-normalized** onto position/CTR
  (0.667 / 0.333) rather than assuming a placeholder. Grades: Excelente ≥80, Bom
  ≥60, Regular ≥40, Crítico <40. The value is in the *decomposition*, not the
  composite number, so **`build_component_alerts` flags any component below 40**
  (`critico` < 20, `alto` < 40) with a plain-language message — surfaced in the
  terminal, the GUI status bar, the Excel "Resumo" sheet, and the dashboard. The
  composite is never suppressed; both appear together.
- **Cannibalization** counts only URLs that genuinely compete (impressions ≥ 10,
  position ≤ 30) and tags each group with a `severity` derived from the
  impressions in dispute, avoiding the false positives of "any query with 2+ URLs."
- **301 consolidation plan.** `build_consolidation_plan` turns cannibalization
  into a *suggested* redirect map: per group it picks the canonical URL (clicks →
  position → impressions) and lists the rest as redirect sources, resolving
  cross-group conflicts by severity. Emitted as `*_redirects.csv` plus
  ready-to-apply Apache/nginx blocks, an Excel "Plano 301" sheet, and a dashboard
  section — every output labeled a suggestion (honesty rule).
- **Content quality** combines quota-free local signals with optional NLP signals
  into a conservative verdict: `ok` / `atencao` / `over_otimizado` / `raso`. The
  density is the **max of three sources** — the real GSC query, the slug as a
  phrase (`slug_phrase`), and the dominant repeated n-gram (`dominant_ngram`) —
  so a page optimized for its slug no longer reports a falsely clean 0%;
  `density_source` records which one triggered.
- **First-party demand trends.** `--trends` defaults to the Search Console `date`
  dimension (`fetch_date_trends` + `compute_date_trends`): site-specific,
  official, and free, classifying rising/stable/declining from the first-third vs
  last-third of daily impressions over 90 days. The old `pytrends` global index is
  a legacy opt-in (`--trends-source pytrends`).
- **Measurement loop.** Every snapshot also stores the content metrics, and
  `build_content_tracking` cross-references position against verdict over time.
  This is how the project answers, empirically, "does fixing the content help?"

### Pruning plan (Poda)

A separate subsystem (`core/pruning.py`, `poda.py`, `app_poda.py`) handles **old
URLs** rather than competing ones. The company convention is that the sitemap
lists *every* active page, so any URL Google still knows but the sitemap omits is
a stale page. `fetch_positions` returns those as `ghost_rows` at zero extra API
cost.

It is a deliberate two-stage, human-in-the-loop flow:

1. **Generate** (`build_pruning_plan`) writes an editable `poda/{date}_poda.csv`:
   `410` suggested for ghosts with no traffic, `revisar` for ghosts that still
   earn clicks/impressions (never an automatic directive when traffic exists).
   A 301 target is suggested by shared query → similar slug → optional home
   fallback, always canonicalized to a live sitemap URL.
2. **Compile** (`--compilar`) validates the analyst-reviewed CSV and emits four
   formats with identical semantics: anchored Apache `RedirectMatch`, simple
   `mod_alias` `Redirect 301` (prefix-match), nginx `server {}`, and a standalone
   PHP file for hosts where the server config can't be edited. The Search
   Analytics window defaults to ~16 months (the GSC maximum); `--importar-gsc`
   ingests the manual "Pages" export to cover URLs with zero impressions the API
   can't see.

## semantic-analyzer

A single pipeline (`analisar.run_analysis`, called by both the CLI and the GUI
`app.py`) orchestrates a sequence of pure-ish `core/` modules. The design splits
cheap, deterministic clustering from the expensive, optional LLM judgment —
clustering finds candidate groups, and the LLM (if enabled) only judges the
flagged ones (a "hybrid" strategy).

```
loaders → embedder → clusterer → [gsc_link] → [hybrid/llm] → [dedup] → [linkgraph] → report
```

- `loaders.py` reads page text from one of three sources: a primeWeb site backup
  (parses `include/parametros.php` for the article list), any folder of
  `.php`/`.html`, or a text file of URLs to fetch.
- `embedder.py` turns each page into a vector with `sentence-transformers`
  (multilingual MiniLM, CPU) or a TF-IDF fallback, with an on-disk embedding cache
  keyed by model + content.
- `clusterer.py` is the pure numpy/sklearn core: cosine similarity, then either
  agglomerative (default, cohesive) or threshold (single-linkage) clustering. Each
  group of 2+ pages is a consolidation candidate; the most central page is the
  suggested canonical.
- `gsc_link.py` (optional, `--gsc`) cross-references clusters with a `gsc-monitor`
  position snapshot to pick the page to **keep** by real performance.
- `llm.py` is the local-LLM client layer (HTTP + transformers backends + JSON
  parsing); `hybrid.py` (optional, `--llm`) judges the largest groups as
  spun/thin/ok, and in `--differentiate` mode produces a contract-safe plan that
  keeps every page but gives each a distinct intent/keyword/title.
- `dedup.py` finds keyword collisions *across* groups after differentiation.
- `linkgraph.py` (optional, `--linkgraph`) builds the internal-link graph,
  distinguishing contextual links from index/widget links, and surfaces
  under-linked money pages and a hub-and-spoke link plan.
- `report.py` renders console output and the HTML report.

### Local-LLM layer

The LLM is always local and always optional. The default `http` backend speaks
the OpenAI-compatible API of **Ollama** (port 11434) or **LM Studio** (port 1234),
running the model on the GPU. A `transformers` backend runs a small model on CPU
with no server, intended only for testing. The pipeline runs the LLM *before*
generating reports so its judgments land in the HTML.

## keyword-research

A 4-stage keyword research pipeline (spec: hybrid free-discovery + cheap
DataForSEO validation) feeding blog content production for seotecnico.dev.br.
Three CLI entry points, each runnable standalone and importable
(`run_discovery`, `run_validation`, `run_serp_check` raise `PipelineError`
instead of exiting):

```
descobrir.py  (Stage 1, free)    autocomplete + [trends] + [--gsc-csv]  -> {date}_descoberta.csv
validar.py    (Stage 2, paid)    Labs expansion + Ads volume + filters  -> {date}_validacao.csv + {date}_stage3_input.csv
serp.py       (Stage 3, paid)    standard-queue SERP top-10 + verdicts  -> {date}_serp_review.csv (analyst-editable)
```

- `core/` is pure logic (`normalize`, `filters`, `keyword_map`,
  `serp_analysis`, `ledger`) plus the copied cache/storage patterns;
  `fetchers/` holds the IO (`autocomplete`, `trends`, `dataforseo`).
- **Cost control is structural**: `DataForSEOClient._request` checks the
  monthly ledger cap *before* any HTTP (raising `BudgetExceededError`) and
  appends every response's `cost` to `relatorios/_ledger/dataforseo_costs.csv`
  *after*. `priority` and `include_clickstream_data` are never sent — pinned
  by regression tests. Credentials come from env vars only (public repo).
- Stage 3 uses the async standard queue: task ids persist in
  `.cache/serp_pending.json`, so interrupted runs resume with `--fetch` and
  paid SERPs are cached effectively forever (never re-bought).
- Stages 1 and 4 lean on gsc-monitor's OAuth via the additive entry point
  `gsc-monitor/exportar_keywords.py` ("ranked but weak" mining and per-URL
  T+28d ground truth), keeping GSC credentials in one tool only.

## Data flow and integration points

The integration between the tools is a one-way file handoff. `gsc-monitor` writes
`relatorios/<site>/YYYY-MM-DD_posicao.json`; `semantic-analyzer`'s `--gsc` flag
reads either that file or its folder (picking the newest snapshot). For the
handoff to be meaningful, the site must have **both** a content backup and a GSC
report whose slugs match the GSC URLs — today the fully wired-up case is the
example site `exemplo`.

Both tools cache aggressively and per-site:

| Tool | Cache location | TTLs |
|------|----------------|------|
| gsc-monitor | `relatorios/<site>/.cache/` | position 72h, queries 72h, inspect 24h, KG 7d, NLP 72h, date-trends 24h, page text 72h |
| semantic-analyzer | `.cache/` | embeddings keyed by model+content (invalidate with `--no-cache`) |
| keyword-research | `relatorios/<project>/.cache/` | autocomplete 7d, trends 24h, paid SERPs ~forever (never re-bought) |

API errors are never cached. `--no-cache` forces fresh data in both tools. Cache
TTL timestamps are UTC-aware, with backward compatibility for older naive caches.

## Key decisions and trade-offs

- **Separate programs, file-coupled, no shared package.** Keeps heavy ML deps
  out of `gsc-monitor` and lets each tool evolve independently; the cost is a
  manual file handoff and some duplicated small utilities (cache/CSV patterns
  are copied per tool by design). (The former `_normalize_domain` duplication
  has since been centralized in gsc-monitor's `core/urls.py`.)
- **Rule-based verdicts, optional local LLM.** Preserves analytical honesty and
  the no-paid-LLM rule; the trade-off is more conservative output than a hosted
  model might give.
- **Free-tier rule scoped per tool.** `keyword-research` deliberately uses the
  paid DataForSEO data API (< $5/month) because BR dev-niche keyword data has
  no usable free source; the budget cap is enforced in code, not by discipline.
  Paid LLMs stay off-limits everywhere.
- **Opt-in expensive paths.** `--nlp`, `--trends`, `--llm`, `--linkgraph` are all
  off by default because they cost quota, time, or a running GPU server. Reports
  degrade gracefully — each section appears only if its data exists.
- **Suggestions, never automatic actions.** The 301 plan and the pruning plan are
  generated as reviewable artifacts; nothing is applied to a live site by the
  tool, and every output says so.
- **Pure-logic-first layering.** Maximizes test coverage of the code where
  "confident but wrong" bugs originate, at the cost of some indirection between
  the entry points and the fetchers.

## Known rough edges

These are documented in `gsc-monitor/CLAUDE.md` and worth knowing before you
extend things:

- **stdout encoding.** Entry points force UTF-8, but library code called outside
  them can break on a cp1252 console — keep flow-level `print`s ASCII, and reserve
  emoji for HTML/Excel artifacts.
- **Template-coupled NLP noise stripping.** `nlp_analyzer._strip_inner_noise`
  carries hardcoded section classes for one specific site template; it does not
  generalize to the 100+ sites and should move to per-site config.
- **GUI string-scraping.** The Tkinter GUIs colorize output by matching `print`
  tags (`[CACHE]`, `[ERRO]`), so flow-level print wording is effectively a
  contract. Replacing this with structured logging is the main pending refactor
  (see [`PROJECT_STATUS.md`](PROJECT_STATUS.md)).
- **`pytrends` is unofficial and fragile.** It is now an opt-in legacy source;
  the default first-party GSC `date` trend should cover most needs.
- **When adding a report parameter**, add it to `ReportOptions` rather than to two
  separate signatures, so the CLI (`posicao.py`) and GUI (`gui/runner.py`) stay in
  sync.
