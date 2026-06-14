# Evaluation & Improvement Roadmap — local-seo-toolkit

**Date:** 2026-06-09 · **Status:** Proposed
**Purpose:** Architecture / feature / results evaluation, followed by improvement paths
written as **ready-to-send prompts for a Claude coding session**.

---

## Part 1 — Architecture evaluation

**Verdict: solid for its constraints. Grade: A-.**

| Dimension | Assessment |
|-----------|------------|
| Separation of concerns | **Strong.** `core/` (pure logic) / `fetchers/` (network IO) / `reporters/` (output) layering makes the brain testable without spending API quota. |
| Coupling between tools | **Deliberately loose.** File handoff (`*_posicao.json`), no import edge. Heavy ML deps stay isolated in semantic-analyzer. Correct call. |
| Quota economics | **First-class.** Per-domain caches with sane TTLs, opt-in expensive paths (`--nlp`, `--trends`, `--llm`), errors never cached. |
| Testability | **Good and improving.** 384 tests total (303 gsc-monitor + 81 semantic-analyzer), unified under pytest, zero network in tests, `conftest.py` isolates `RELATORIOS_DIR`. A CI coverage gate now floors source coverage (40% gsc / 38% semantic). |
| Honesty engineering | **The differentiator.** Conservative verdicts, re-normalized health score weights, cannibalization thresholds against false positives. Rare discipline. |

**Weak points (all known, most documented in CLAUDE.md):**

1. **Duplicated helpers** — ~~`_normalize_domain` lives in both `posicao.py` and `position_fetcher.py`~~ ✓ **RESOLVED** — centralized in `core/urls.py` (`normalize_domain`).
2. **Two call sites per report parameter** (`posicao.py` + `gui/runner.py`) — GUI silently lags CLI when someone forgets.
3. **String-scraped logging** — GUI colorizes by matching `print` output (`[CACHE]`, `[ERRO]`). Fragile contract, blocks structured progress reporting.
4. **Hardcoded constants scattered** — DAYS_BACK, CTR benchmarks, thresholds, `geo="BR"`, NLP noise classes for one specific template.
5. **`pytrends` dependency** — unofficial and fragile. ✓ **ADDRESSED** — the default trends source is now first-party GSC `date`; `pytrends` was demoted to an opt-in legacy source and removed from the default `requirements.txt` (`pip install pytrends` only if you use `--trends-source pytrends`). Note: it is *not* fully redundant — it measures global search interest, which the first-party GSC signal does not.
6. **Code size:** gsc-monitor ~7.3k LOC, semantic-analyzer ~2.3k LOC — still small enough to refactor cheaply. Now is the time to fix 1–4.

---

## Part 2 — Feature evaluation

| Feature | Maturity | Notes |
|---------|----------|-------|
| Ranking report (Search Analytics) | ✅ Mature | Cache, history (30 snapshots), Excel/HTML/CSV. |
| Indexing report (URL Inspection) | ✅ Mature | Quota-aware (`--limit`), classifier tested. |
| Health score | ✅ Mature | Impression-weighted, honest re-normalization. Decomposition > composite. |
| Cannibalization detection | ✅ Mature | Thresholded + severity. Detected the real case (122 groups, canilmansur). |
| Content quality (over-optimization / thin) | ✅ Mature | Local signals + optional NLP enrichment; conservative 4-level verdict. |
| Measurement loop (Move 2) | ⚠️ Built, **starving** | Mechanism works; only 3 snapshots on 1 site, 1 on others. See Part 3. |
| Knowledge Graph / Trends / NLP entities | ✅ / ⚠️ / ✅ | Trends rides fragile pytrends. |
| Tkinter GUI | ✅ Functional | No progress bar / cancel; string-scraping. |
| Semantic clustering (embeddings) | ✅ Mature | Agglomerative + threshold, embedding cache, TF-IDF fallback. |
| GSC cross-reference (`--gsc`) | ✅ Works | Picks page-to-keep by real performance. |
| Local LLM judgment + `--differentiate` | ✅ Works | Contract-safe alternative to 301s — a feature nobody else has. |
| Internal link graph (`--linkgraph`) | ✅ Works | Real orphan detection, money-page analysis, hub→spoke plan. |
| Dashboard HTML | ✅ Mature | Self-contained, degrades gracefully, escaped. |

**Feature gaps that matter:**

- **Keyword density vs slug/dominant n-gram** — pages optimized for the slug show 0% density → "falsely clean" verdict. This undermines the project's core promise (honest over-optimization detection).
- **Component-level health alerts** — canilmansur scored "Good" (70.7) while CTR was 8.7/100. The composite masked the real problem.
- **No consolidation executor** — the tool *recommends* 301 consolidation but doesn't generate the redirect map / canonical plan as an artifact.
- **Single-site workflow** — with access to 100+ sites, everything is one-domain-at-a-time, GUI-driven.

---

## Part 3 — Feature results evaluation

What the tools have actually produced (data on disk, June 2026):

| Site | Snapshots | Latest summary |
|------|-----------|----------------|
| www.canilmansur.com | 3 (05-30 → 06-02) | 295 URLs, avg pos 27.0, **81,130 impressions → 257 clicks (CTR 0.41%)**, 122 cannibalization groups |
| www.oliplas.com.br | 1 (06-06) | 230 URLs, avg pos 8.6, 70,575 impr → 859 clicks (CTR 1.33%) |
| nobrehomecare / pix.eng.br / tucujus | 1 each (05-31) | Baseline only |

semantic-analyzer produced link-graph reports for canilmansur and a full plan
(`plano-completo`) for oliplas.

**Honest read of results:**

1. **Diagnosis works.** The toolkit correctly identified canilmansur as a doorway-page site: ranks and indexes, catastrophic CTR, 122 cannibalization groups (up to 8 URLs per keyword). The diagnosis is grounded, multi-signal, and reproducible. This is a *validated* capability.
2. **The central empirical question is still unanswered.** The project exists to measure "does fixing the content help?" — but the measurement loop has 3 snapshots on one site and single baselines elsewhere. **No intervention has been executed and measured yet.** The consolidation recommendation for canilmansur (2026-06-02 baseline) is pending.
3. **Why the loop is starving:** snapshots require a manual run per site. There is no scheduler and no batch mode, so longitudinal data accumulates only as fast as the maintainer remembers to click "Executar".

> The single highest-leverage improvement in this project is not a new feature —
> it is **feeding the measurement loop**: execute one consolidation, capture
> snapshots automatically, and produce the before/after evidence. That converts
> the toolkit from "diagnostic tool" into "proven methodology" (the portfolio goal).

---

## Part 4 — Improvement analysis

Four axes, ordered by leverage:

**A. Results (highest leverage).** The project's credibility thesis needs one
completed experiment: consolidate canilmansur's permutation pages → 301 → track
recovery via Move 2. Everything blocking that (manual snapshots, no redirect-map
artifact) is the priority.

**B. Analysis correctness.** Two known "falsely clean/falsely good" holes:
slug-based density blindness and composite-score masking. Both are quick wins
and protect the #1 project value (analytical honesty).

**C. Growth / scale.** The maintainer has 100+ sites; the tooling is built for
~5. A headless batch mode + cross-site portfolio summary multiplies the value of
every existing feature without new analysis code. This is "Direction B" in
CLAUDE.md — it becomes justified the moment the methodology is proven on one site.

**D. Engineering hygiene.** Central config, deduplicated helpers, structured
logging, IO-path tests. Cheap now (~10k LOC), expensive later.

---

## Part 5 — Improvement paths (Claude-ready prompts)

Each path below is written to be pasted into a Claude Code / Cowork session in
this repo. They assume the standing rules: **free tier / local only · honesty
over confidence · run `py -m pytest` in each tool folder after changes · update
tests with behavior, never silence them · propagate report params to both
`posicao.py` and `gui/runner.py`.**

Recommended order: P1 → P2 → P3 → P4 → P5, then P6+ as needed.

---

### P1 — Feed the measurement loop: scheduled/batch snapshots `[results · quick]`

> In `gsc-monitor`, add a headless batch mode: `py posicao.py --batch sites.txt`
> (one domain per line, `#` comments) that runs the standard ranking pipeline
> (positions + queries + content quality, cache-aware, no GUI) for each site
> sequentially, appends to each site's `historico_posicao.json`, regenerates each
> dashboard, and prints a one-line summary per site (health score + grade +
> snapshot count). Errors on one site must not abort the batch. Add a
> `--batch-report` flag that writes `relatorios/_batch/YYYY-MM-DD_resumo.csv`
> with site, health, avg position, CTR, cannibalization groups, content verdict
> counts. Include a sample `sites.example.txt`. Add unit tests for the batch
> orchestrator with mocked pipeline functions. Document a Windows Task Scheduler
> one-liner in the README so snapshots accumulate weekly without manual runs.

Why first: removes the bottleneck that starves Move 2. Everything in Part 3
depends on snapshot cadence.

### P2 — Consolidation executor: redirect map artifact `[results · quick]`

> In `gsc-monitor/core/analytics.py`, extend cannibalization output with an
> actionable consolidation plan: for each group, pick the canonical URL
> (clicks desc, then position asc, then impressions desc) and list the others as
> redirect sources. Emit a new artifact `relatorios/<site>/YYYY-MM-DD_redirects.csv`
> (columns: from_url, to_url, keyword, severity, clicks_from, clicks_to) plus an
> Apache `.htaccess` 301 block and an nginx `return 301` block as `.txt` files,
> so the plan can be applied to a real site directly. Mark the plan clearly as a
> *suggestion* in all outputs (honesty rule). Surface it as a new Excel sheet
> "Plano 301" and a dashboard section. Propagate parameters to both `posicao.py`
> and `gui/runner.py`. Pure-logic tests for the canonical-pick ordering and the
> file formats.

Why: turns the canilmansur recommendation into an executable artifact, enabling
the before/after experiment.

### P3 — Density vs slug and dominant n-gram `[analysis · quick win]`

> In `gsc-monitor/core/content_quality.py`, keyword density currently uses only
> the natural GSC query, so pages optimized for their slug report ~0% density and
> get a falsely clean verdict. Add two additional density measurements: (a) the
> slug converted to a phrase (split on `-`, strip stopwords), and (b) the
> dominant repeated n-gram (2–3 words) in the page text. The reported
> `keyword_density` becomes the max of the three, and the verdict explanation
> must say which keyword triggered it. Keep the verdict conservative. Update the
> Excel sheet and dashboard section to show the triggering keyword. Update
> existing tests, and add cases: slug-stuffed page with no GSC query match must
> NOT report ok; clean page must stay ok.

### P4 — Component-level health alerts `[analysis · quick win]`

> In `gsc-monitor/core/analytics.py`, the composite health score can mask a
> critical component (real case: 70.7 "Bom" with CTR component 8.7/100). Add
> `component_alerts` to `calculate_health_score`'s return: any component below
> 40 generates an alert dict (component, value, severity, plain-language
> one-liner in pt-BR about what it means). Show alerts in `print_health_score`,
> in the GUI status bar (red badge), in the Excel "Resumo" sheet, and as a
> highlighted box in the dashboard's health section. Never suppress the
> composite — show both. Tests: composite good + one critical component must
> alert; all-good must not.

### P5 — First-party trends via GSC `date` dimension `[feature · medium]`

> In `gsc-monitor`, replace the pytrends dependency path as default trends
> source. Add `fetch_date_trends` in `fetchers/position_fetcher.py` querying
> Search Analytics with dimensions `["date"]` (site-level) and
> `["date","query"]` for top-10 queries over the last 90 days (cache TTL 24h,
> same cache module). Compute per-query and site trend (first-third vs
> last-third average clicks/impressions → rising/stable/declining) in a pure
> function in `core/analytics.py`. Wire `--trends` to use this by default with
> `--trends-source pytrends` as legacy fallback. New dashboard line chart +
> Excel sheet reuse the existing "Trends" surfaces. Pure-function tests with
> synthetic date rows. This removes the fragile unofficial dependency while
> making trends *site-specific* instead of global.

### P6 — Template-agnostic NLP noise stripping `[analysis · medium]`

> `gsc-monitor/fetchers/nlp_analyzer.py` `_strip_inner_noise` hardcodes section
> classes from one site template and doesn't generalize to the 100+ sites. Refactor:
> (1) introduce `relatorios/<site>/site_config.json` (optional, schema documented)
> with `noise_selectors`; (2) default path uses a generic readability heuristic —
> keep the largest contiguous text block, strip nav/footer/aside/script by tag,
> drop link-dense blocks (>50% anchor text); (3) the hardcoded classes move into
> a sample config for that one site. `content_fetcher` and `nlp_analyzer` both
> read the config. Tests with synthetic HTML: template A, template B, no config.

### P7 — Cross-site portfolio dashboard `[growth · medium]`

> In `gsc-monitor`, add `py portfolio.py`: reads the latest snapshot of every
> site under `relatorios/`, no API calls, and generates
> `relatorios/_portfolio/dashboard.html` — a Chart.js overview ranking all sites
> by health score with columns for avg position, CTR vs benchmark, cannibalization
> group count, content verdict distribution, and snapshot count (flag sites with
> <2 snapshots as "sem histórico"). Include a trend sparkline per site from
> `historico_posicao.json`. Same self-contained HTML + `html.escape` discipline
> as the existing dashboard. Pure-logic tests on the aggregation with fixture
> snapshot files. This is the management view for scaling to 100+ sites.

### P8 — Local spaCy entity backend `[feature · medium]`

> In `gsc-monitor`, make the entity layer pluggable: extract an interface from
> `nlp_analyzer` (entities + salience-like weight) and add a
> `pt_core_news_lg`-based local backend (spaCy) selected via
> `--nlp-backend cloud|spacy` (default cloud, auto-fallback to spacy when no API
> key). spaCy has no quota: it can run on *all* opportunity URLs, not just 5.
> Weight = frequency × position-in-text heuristic; label it honestly in reports
> as "frequência local", never as Google salience. Keep cache layers separate
> (`nlp2_` vs `spacy_`). Tests with mocked spaCy doc objects, no model download
> in CI.

### P9 — Engineering hygiene sweep `[hygiene · medium]`

> Three refactors in `gsc-monitor`, in one session, suite green after each:
> (1) **Central config** — create `core/settings.py` holding DAYS_BACK, CTR
> benchmarks, cannibalization thresholds (impressions≥10, position≤30), content
> quality thresholds, cache TTLs, `geo`; all modules import from it; document
> each constant. (2) **Deduplicate `_normalize_domain`** — single implementation
> in `core/`, imported by `posicao.py` and `position_fetcher.py`; keep the test
> asserting `https://x/` and `sc-domain:x` produce the same cache key.
> (3) **Structured logging** — introduce a tiny event API (`log.event(kind, msg)`)
> emitting both human text and a machine-readable prefix; GUI colorizes on the
> structured kind instead of string-matching; add `(idx/total)` progress events
> so the GUI can later render a progress bar. No behavior changes to reports.

### P10 — IO-path tests `[hygiene · medium]`

> Add the missing test coverage flagged in ESTRATEGIA_TESTES.md §5, all offline:
> (1) `fetchers/nlp_analyzer.py` — parsing of annotateText fixture payloads
> (entities, salience, categories, numeric-type filtering, fallback to
> analyzeEntities); (2) `fetchers/inspector.py` — verdict extraction from
> fixture inspection responses incl. unknown verdicts; (3) `core/auth.py` —
> expired token, missing file, refresh path with mocked `Credentials`;
> (4) smoke tests for `position_reporter.py` and `nlp_report_generator.py`.
> Follow the house style: fixtures, no network, conservative-verdict assertions.

### P11 — GUI progress bar + cancel `[feature · larger]`

> Building on P9's structured events: in `gsc-monitor/gui/`, consume `(idx/total)`
> progress events to drive a determinate `ttk.Progressbar`, add a "Cancelar"
> button setting a `threading.Event` checked between pipeline stages and between
> URL inspections (clean stop, partial artifacts clearly labeled "parcial"),
> and stream stage names to the status bar. Manual test checklist in PROGRESSO.md
> (GUI is excluded from automated tests by strategy).

### P12 — The portfolio story: before/after experiment report `[results · strategic]`

> Once ≥6 weekly snapshots exist around a real intervention (e.g. canilmansur
> consolidation): add `py experimento.py --site <dominio> --intervention-date
> YYYY-MM-DD` to `gsc-monitor`. It reads `historico_posicao.json` + content
> metrics, splits snapshots into before/after, and produces an honest experiment
> report (HTML + Excel): per-URL position/clicks/CTR deltas, group-level rollups
> for consolidated clusters, explicit confounder warnings (core updates,
> seasonality — never claim causality, show evidence), and a plain-language
> pt-BR summary. This artifact IS the portfolio piece: "detected → fixed →
> measured". Pure-logic tests on the delta computation with synthetic history.

---

## Sequencing rationale

```
P1 batch snapshots ──► data accumulates from week 1
P2 redirect map    ──► intervention becomes executable      } the experiment
P12 experiment rpt ──► evidence artifact (needs P1+P2 time)  } that proves the
                                                               methodology
P3, P4             ──► honesty quick wins (any time, 1 session each)
P5, P6, P8         ──► analysis depth, removes fragile/hardcoded paths
P7                 ──► scale to the 100+ sites (after methodology proven)
P9, P10, P11       ──► hygiene; P9 before P11 (events power the progress bar)
```

**Consequences accepted:** batch mode adds a headless path to maintain (mitigated
by reusing the exact CLI pipeline); spaCy adds a heavy-ish local dep (isolated
behind a flag, consistent with the semantic-analyzer precedent); portfolio
dashboard reads-only disk data (zero quota cost).
