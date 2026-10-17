# Project status & roadmap — local-seo-toolkit

**Last updated:** 2026-07-15 · **Status:** active, single-maintainer

The single source of truth for *where the project stands and what's next*. It
consolidates and supersedes the earlier `IMPROVEMENT_ROADMAP.md`,
`TECH_DEBT_AUDIT.md`, and the private `REMEDIATION_PLAN.md` working file — those
disagreed on what was already done, so they were merged here and reconciled
against the current code.

For *how the system is built* see [`ARCHITECTURE.md`](ARCHITECTURE.md); for *how
to operate it* see [`RUNBOOK.md`](RUNBOOK.md); for the per-change rationale log see
[`../gsc-monitor/CLAUDE.md`](../gsc-monitor/CLAUDE.md) and
[`../gsc-monitor/PROGRESSO.md`](../gsc-monitor/PROGRESSO.md).

---

## At a glance

| Dimension | State | Notes |
|-----------|-------|-------|
| Architecture | **Solid (A-)** | `core` (pure) / `fetchers` (IO) / `reporters` (output); three tools, file-coupled, no import edge. |
| Feature coverage | **Mature** | Diagnosis is the validated strength; the measurement loop is built but data-starved; keyword pipeline shipped (paid stages awaiting a DataForSEO account). |
| Tests | **514 passing** | 318 gsc-monitor + 81 semantic-analyzer + 115 keyword-research, fully offline, CI coverage floor (40% / 38% / 85%). |
| Lint / format | **Green** | `ruff check` + `ruff format --check` pinned to 0.15.16 in CI, pre-commit, dev reqs. |
| Security hygiene | **Good** | Git-ignored credentials, blocking pre-commit secret scanner, `pip-audit` + Dependabot. |
| Biggest gap | **Proof, not features** | No intervention has been executed *and measured* end-to-end yet. |

---

## What's shipped

### Features

| Feature | Maturity | Notes |
|---------|----------|-------|
| Ranking report (Search Analytics) | Mature | Cache, history (30 snapshots), Excel/HTML/CSV. |
| Indexing report (URL Inspection) | Mature | Quota-aware (`--limit`), classifier tested. |
| Health score + component alerts | Mature | Impression-weighted, honest re-normalization; any component < 40 raises an explicit alert so the composite can't mask it. |
| Cannibalization detection | Mature | Thresholded (impressions ≥ 10, position ≤ 30) + severity. |
| 301 consolidation plan | Mature | Suggested redirect map: CSV + Apache/nginx blocks + Excel sheet + dashboard section, always labeled a suggestion. |
| Content quality (over-optimization / thin) | Mature | Conservative 4-level verdict; density is the max of GSC-query / slug-phrase / dominant-n-gram, so slug-stuffed pages aren't falsely clean. |
| Demand trends (first-party) | Mature | Defaults to the GSC `date` dimension (site-specific, official); `pytrends` demoted to an opt-in legacy source. |
| Pruning plan ("Poda") | Mature | Two-stage human-in-the-loop: editable CSV → compiled Apache/nginx/PHP redirect blocks; GSC "Pages" import for zero-impression URLs. |
| Batch / headless mode | Mature | `--batch sites.txt` runs the standard pipeline per site with error isolation; `--batch-report` writes a cross-site summary; weekly Task Scheduler one-liner documented. |
| Measurement loop | Built, **data-starved** | Mechanism works; needs more snapshots per site to produce before/after evidence. |
| Knowledge Graph / NLP entities | Mature | KG false-positive guard; NLP enriches the content verdict. |
| Semantic clustering (embeddings) | Mature | Agglomerative + threshold, embedding cache, TF-IDF fallback. |
| GSC cross-reference (`--gsc`) | Mature | Picks the page to keep by real performance. |
| Local-LLM judgment + `--differentiate` | Works | Contract-safe alternative to 301s — keeps every page, gives each a distinct intent. |
| Internal link graph (`--linkgraph`) | Works | Orphan / money-page detection, hub→spoke plan. |
| Dashboards (HTML, both tools) | Mature | Self-contained, escaped, degrade gracefully. |
| Keyword research pipeline (`keyword-research/`) | Built, **awaiting paid account** | 4 stages: free discovery (Autocomplete + GSC mining + optional Trends) works end-to-end today; DataForSEO validation + SERP spot-check are implemented and fully mock-tested, with structural cost guardrails (pre-flight budget cap, append-only ledger, `priority`/clickstream never sent). First real run needs a DataForSEO account (~$1 trial credit covers the smoke test). |
| GSC keyword export (`exportar_keywords.py`) | Built | Additive gsc-monitor entry point: "ranked but weak" mining (Stage 1) + per-URL T+28d ground truth (Stage 4, forward-compatible with the planned `experimento.py`). |

### Engineering hardening (done)

- **Single test runner** (`pytest`) for both tools; `conftest.py` isolates
  `RELATORIOS_DIR` so tests never touch real `relatorios/`.
- **CI guardrails:** coverage floor (40% / 38%), `pip-audit` + Dependabot,
  CI Python pinned to a patch release.
- **Reproducibility:** semantic-analyzer's `numpy`/`scikit-learn`/`requests`
  pinned exactly; a `pip-compile --generate-hashes` recipe documented for the
  heavy ML stack.
- **Correctness:** cache-TTL timestamps are UTC-aware (backward-compatible).
- **Maintainability:** `normalize_domain` centralized in `core/urls.py`; health
  grade thresholds moved into `config.py`; report toggles unified behind a single
  `ReportOptions` dataclass (CLI ↔ GUI can no longer drift); the three
  highest-complexity well-tested `core` functions refactored below threshold;
  intentional broad `except` blocks documented with `# noqa: BLE001` reasons.

---

## Results so far (honest read)

1. **Diagnosis works and is validated.** On a real doorway-page site the toolkit
   correctly identified the pattern — ranks and indexes, catastrophic CTR, 122
   cannibalization groups (up to 8 URLs per keyword). Grounded, multi-signal,
   reproducible. (All examples in docs use placeholder domains; client data lives
   only in git-ignored `relatorios/`.)
2. **The central empirical question is still open.** The project exists to measure
   *"does fixing the content help?"* — but the measurement loop has only a few
   snapshots on one site and single baselines elsewhere. **No intervention has been
   executed and measured yet.**
3. **Why the loop was starving — and the fix.** Snapshots used to require a manual
   run per site. The batch mode + Task Scheduler path now removes that bottleneck;
   the remaining work is to *run* a real consolidation and capture the before/after.

> The single highest-leverage next step is not a new feature — it is **completing
> one experiment end-to-end**: execute a consolidation, let weekly snapshots
> accumulate, and produce the before/after evidence. That converts the toolkit
> from "diagnostic tool" into "proven methodology" (the portfolio goal).

---

## Open backlog

Scored with `Priority = (Impact + Risk) × (6 − Effort)`, each 1–5, effort
inverted. Grouped by theme; ordered by leverage within each.

### Results (highest leverage)

- **Before/after experiment report.** Once ≥6 weekly snapshots exist around a real
  intervention, add an `experimento.py` that splits history into before/after and
  produces an honest report (per-URL deltas, group rollups, explicit confounder
  warnings — never claims causality). This artifact *is* the portfolio piece.

### Analysis depth

- **Template-agnostic NLP noise stripping.** `nlp_analyzer._strip_inner_noise`
  hardcodes section classes for one site template. Move to optional per-site
  config + a generic readability fallback so it generalizes to the 100+ sites.
- **Local spaCy entity backend.** Make the entity layer pluggable with a
  `pt_core_news`-based offline backend (no quota → can run on *all* opportunity
  URLs), labeled honestly as local frequency, never as Google salience.

### Engineering debt

| Item | Impact | Risk | Effort | Priority | Note |
|------|:------:|:----:|:------:|:--------:|------|
| Split the >1,000-LOC reporters + extract shared HTML/CSS | 3 | 2 | 3 | 15 | `excel_reporter` (1.2k), `nlp_report_generator` (1.1k), `html_reporter` (1.0k), semantic `report.py` (0.8k); CSS duplicated across three files. Verify output byte-identical. |
| Logging framework; move GUI off string-scraping | 4 | 3 | 4 | 14 | ~390 `print()` calls; the GUI colorizes by matching `[CACHE]`/`[ERRO]`. Replace with structured records → log levels, file logs, and a real progress bar. Highest-impact structural fix; do as a dedicated phase with the coverage floor as the net. |
| Refactor remaining high-complexity functions | 3 | 3 | 3 | 12 | `find_keyword_collisions`, the Excel sheet builders, semantic `run_analysis`. One function per change, behavior-preserving. |
| Windows CI runner | 2 | 3 | 2 | 20 | Product ships `.ps1` + Tkinter + Windows paths but CI is Linux-only. Add a `windows-latest` matrix entry when path/encoding code is next touched. |
| Finish the ML lockfile | 2 | 3 | 2 | 20 | Run the documented `pip-compile --generate-hashes` from a clean env to hash-pin `torch`/`sentence-transformers`. |

### Test debt

- **IO-path tests** (offline): `nlp_analyzer` payload parsing, `inspector` verdict
  extraction (incl. unknown verdicts), `core/auth` error/refresh paths, smoke
  tests for `position_reporter` / `nlp_report_generator`. Pipeline smoke tests
  already cover the toggle routing; this extends coverage to the report writers.

### Growth / scale (after the methodology is proven)

- **Cross-site portfolio dashboard.** A read-only `portfolio.py` that aggregates
  the latest snapshot of every site under `relatorios/` into one Chart.js overview
  (health, avg position, CTR vs benchmark, cannibalization count, content-verdict
  distribution, snapshot count). Zero quota cost — the management view for 100+
  sites.
- **GUI progress bar + cancel.** Built on structured logging: a determinate
  progress bar driven by `(idx/total)` events and a clean cancel between stages.

---

## Sequencing

```
Run a real consolidation ──► weekly snapshots accumulate ──► experiment report   } proves the
                                                                                    methodology
Reporter split / IO tests ──► safe to attack the logging refactor
Logging framework ──────────► unblocks the GUI progress bar
Portfolio dashboard ────────► scale to 100+ sites (after one site is proven)
Windows CI / lockfile ──────► fold in whenever adjacent code is touched
```

**Standing rules for any change:** free tier / local only — scoped per tool:
`keyword-research` alone may spend on the DataForSEO data API, under its coded
budget cap; paid LLMs stay off-limits everywhere · honesty over
confidence · run `py -m pytest` in each tool folder after changes · update tests
*with* behavior, never silence them · add report toggles to `ReportOptions`, not to
two signatures · diff a real generated artifact before claiming a reporter refactor
is behavior-preserving.
