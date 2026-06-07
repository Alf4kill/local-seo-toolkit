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

The repository is two independent Python programs that share data through the
filesystem. There is no shared package and no import edge between them — the only
coupling is that `semantic-analyzer` reads JSON snapshots written by
`gsc-monitor`.

```
┌──────────────────────────── gsc-monitor ────────────────────────────┐
│  entry points        core (pure logic)        fetchers (network IO)  │
│  ┌───────────┐       ┌──────────────┐         ┌──────────────────┐   │
│  │ app.py    │       │ analytics    │         │ position_fetcher │   │
│  │ posicao.py│──────▶│ content_qual │◀────────│ inspector        │   │
│  │ main.py   │       │ classifier   │         │ knowledge_graph  │   │
│  └───────────┘       │ sitemap      │         │ nlp_analyzer     │   │
│        │             │ cache        │         │ trends_fetcher   │   │
│        │             │ storage      │         │ content_fetcher  │   │
│        ▼             └──────────────┘         └──────────────────┘   │
│  reporters: position_reporter · reporter · excel_reporter ·          │
│             html_reporter · nlp_report_generator                     │
│        │                                                             │
│        ▼ relatorios/<site>/                                          │
│   YYYY-MM-DD_posicao.json  ·  .xlsx  ·  dashboard.html  ·  CSV       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ (file handoff via --gsc)
┌──────────────────────────────▼──── semantic-analyzer ────────────────┐
│  analisar.py (CLI)                                                     │
│  core: loaders → embedder → clusterer → gsc_link → hybrid (LLM) →     │
│        dedup → linkgraph → report                                     │
│  output: relatorios/<site>/YYYY-MM-DD_<tipo>.html                     │
└───────────────────────────────────────────────────────────────────────┘
```

## gsc-monitor

The codebase is layered so that pure logic stays free of network and disk IO
wherever possible — that's what makes the bulk of it unit-testable without
spending quota.

The **entry points** are thin orchestrators. `posicao.py` produces ranking
reports, `main.py` produces indexing reports, and `app.py` launches a Tkinter GUI
that drives the same code paths on a background thread (`gui/runner.py` streams
output back to the window through a `QueueStream`). Each entry point reconfigures
stdout/stderr to UTF-8 so the Unicode in console output renders correctly.

The **`core/`** layer is the rule-based brain:

- `analytics.py` computes the health score, detects cannibalization, and finds
  pages with no impressions.
- `content_quality.py` produces the over-optimization / thin-content verdict from
  local signals (word count, keyword density, exact repetitions, vocabulary
  diversity) plus optional NLP signals (salience concentration, entity count).
- `classifier.py` maps a Search Console inspection verdict to a category.
- `sitemap.py` fetches and parses `sitemap.xml` (with a robots.txt fallback).
- `cache.py` and `storage.py` handle the per-domain JSON cache and all file IO.

The **`fetchers/`** layer is the only place that touches external APIs:
Search Analytics (`position_fetcher`), URL Inspection (`inspector`), Knowledge
Graph (`knowledge_graph`), Cloud Natural Language (`nlp_analyzer`), Google Trends
via the unofficial `pytrends` (`trends_fetcher`), and page-text fetching for
content quality (`content_fetcher`).

The **`reporters/`** layer turns the computed data into artifacts: a multi-sheet
Excel workbook (`excel_reporter`), an interactive Chart.js dashboard
(`html_reporter`), and plain console/CSV/TXT output.

### Ranking pipeline

The flow for a ranking run is:

```
auth → sitemap → fetch_positions → build_report → analytics
     → content_quality → reports (excel / html / csv)
```

The HTML dashboard is **regenerated on every run**. Each run also appends a
snapshot to `historico_posicao.json` (capped at 30 per domain), which is what
makes longitudinal measurement possible.

### Key concepts

- **Health score (0–100)** = `indexing×0.4 + position×0.4 + ctr×0.2`. Position is
  **weighted by impressions** so it reflects where traffic actually ranks. When
  indexing data is absent, the weights are **re-normalized** onto position/CTR
  (0.667 / 0.333) rather than assuming a placeholder. The value is in the
  *decomposition*, not the composite number — a site can score "Good" overall
  while one component (e.g. CTR) is the real problem.
- **Cannibalization** counts only URLs that genuinely compete (impressions ≥ 10,
  position ≤ 30) and tags each group with a `severity` derived from the
  impressions in dispute, avoiding the false positives of "any query with 2+ URLs."
- **Content quality** combines quota-free local signals with optional NLP signals
  into a conservative verdict: `ok` / `atencao` / `over_otimizado` / `raso`. The
  target keyword comes from the page's real GSC queries.
- **Measurement loop.** Every snapshot also stores the content metrics, and
  `build_content_tracking` cross-references position against verdict over time.
  This is how the project answers, empirically, "does fixing the content help?"

## semantic-analyzer

A single CLI (`analisar.py`) orchestrates a pipeline of pure-ish `core/` modules.
The design splits cheap, deterministic clustering from the expensive, optional
LLM judgment — clustering finds candidate groups, and the LLM (if enabled) only
judges the flagged ones (a "hybrid" strategy).

```
loaders → embedder → clusterer → [gsc_link] → [hybrid/LLM] → [dedup] → [linkgraph] → report
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
- `hybrid.py` (optional, `--llm`) judges the largest groups as spun/thin/ok, and
  in `--differentiate` mode produces a contract-safe plan that keeps every page
  but gives each a distinct intent/keyword/title.
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

## Data flow and integration points

The integration between the tools is a one-way file handoff. `gsc-monitor` writes
`relatorios/<site>/YYYY-MM-DD_posicao.json`; `semantic-analyzer`'s `--gsc` flag
reads either that file or its folder (picking the newest snapshot). For the
handoff to be meaningful, the site must have **both** a content backup and a GSC
report whose slugs match the GSC URLs — today the fully wired-up case is
`exemplo`.

Both tools cache aggressively and per-site:

| Tool | Cache location | TTLs |
|------|----------------|------|
| gsc-monitor | `relatorios/<site>/.cache/` | position 72h, queries 72h, inspect 24h, KG 7d, NLP 72h, trends 24h, page text 72h |
| semantic-analyzer | `.cache/` | embeddings keyed by model+content (invalidate with `--no-cache`) |

API errors are never cached. `--no-cache` forces fresh data in both tools.

## Key decisions and trade-offs

- **Two programs, file-coupled, no shared package.** Keeps heavy ML deps out of
  `gsc-monitor` and lets each tool evolve independently; the cost is a manual
  file handoff and some duplicated helpers (e.g. `_normalize_domain` exists in
  both `posicao.py` and `position_fetcher.py`).
- **Rule-based verdicts, optional local LLM.** Preserves analytical honesty and
  the no-paid-API rule; the trade-off is more conservative output than a hosted
  model might give.
- **Opt-in expensive paths.** `--nlp`, `--trends`, `--llm`, `--linkgraph` are all
  off by default because they cost quota, time, or a running GPU server. Reports
  degrade gracefully — each section appears only if its data exists.
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
- **`pytrends` is unofficial and fragile.** Always treat `--trends` as optional
  and isolated; a first-party trend via the GSC `date` dimension is the
  recommended replacement.
- **When adding a report parameter**, propagate it to *both* call sites —
  `posicao.py` and `gui/runner.py` — or the GUI path will silently lag the CLI.
