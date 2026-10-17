# keyword-research

Hybrid keyword research pipeline for **seotecnico.dev.br** (BR Portuguese dev
niche): free local discovery first, cheap DataForSEO validation second. Built
for a niche where commercial keyword databases are weak and long-tail dev
queries often show **zero volume despite real demand** — so typed-demand
signals (Autocomplete, GSC impressions) can rescue keywords the volume
databases are blind to.

Third tool of the `local-seo-toolkit` monorepo. Like its siblings, it never
imports from the other tools — cooperation happens through CSV files on disk.
Per this tool's spec: **CLI strings and output in Portuguese; docs and code
comments in English** (the reverse of gsc-monitor).

## Pipeline at a glance

```
STAGE 1 — DISCOVERY (free, broad)
  descobrir.py            Google Autocomplete expansion (a-z + question
                          prefixes + 1 recursion level), optional pytrends
  exportar_keywords.py    GSC "ranked but weak" mining (lives in gsc-monitor/)
      -> {date}_descoberta.csv  (hundreds of candidates)

STAGE 2 — VALIDATION (DataForSEO, cents)
  validar.py              Labs Keyword Ideas + Related Keywords (expansion),
                          Google Ads Search Volume (batch), keep/drop rules
      -> {date}_validacao.csv (full audit) + {date}_stage3_input.csv (kept)

STAGE 3 — SERP SPOT-CHECK (DataForSEO, cents)
  serp.py                 Google Organic top-10, standard queue, google.com.br
      -> {date}_serp_review.csv  (analyst-editable; final verdict is HUMAN)

STAGE 4 — GROUND TRUTH (free, post-publication)
  exportar_keywords.py --url   T+28d GSC queries per published URL
      -> {date}_keywords_url.csv  (new seeds / FAQ gaps -> back to Stage 1)
```

| Stage | Script | Cost |
|------|--------|------|
| 1 | `descobrir.py` (+ `gsc-monitor/exportar_keywords.py`) | free |
| 2 | `validar.py` | ~$0.30–0.50 per research cycle |
| 3 | `serp.py` | ~$0.002 per keyword (standard queue) |
| 4 | `gsc-monitor/exportar_keywords.py --url` | free |

## Setup

```powershell
cd keyword-research
pip install -r requirements.txt        # requests only; pytrends is optional
py -m pytest                           # suite is fully offline
```

### DataForSEO credentials (Stages 2–3 only)

Stage 1 needs no account at all. For Stages 2–3, create a DataForSEO account
(pay-as-you-go): the **signup trial credit (~$1) covers the first smoke tests
and a small research cycle**; a real top-up has a **$50 minimum**, but the
balance never expires and this pipeline budgets **< $10 for the initial
cluster research and < $5/month** ongoing.

Credentials are read from environment variables only — there is no file
fallback, because this repo is public:

```powershell
$env:DATAFORSEO_LOGIN    = "<login da conta>"
$env:DATAFORSEO_PASSWORD = "<senha da API>"
$env:DATAFORSEO_MONTHLY_CAP = "5.0"    # optional; default 5.0 USD
```

## Stage 1 — discovery (free)

```powershell
# Expand seeds from a file (see seeds.example.txt) and/or ad-hoc seeds:
py descobrir.py --projeto seotecnico.dev.br --seeds seeds.txt
py descobrir.py --projeto seotecnico.dev.br --seed "next.js seo" --seed "cwv"

# Merge GSC opportunities exported by gsc-monitor (see below):
py descobrir.py --projeto seotecnico.dev.br --seeds seeds.txt --gsc-csv CAMINHO\2026-07-15_keywords_gsc.csv

# Optional Google Trends related queries (requires pip install pytrends==4.9.2):
py descobrir.py --projeto seotecnico.dev.br --seeds seeds.txt --trends
```

- The Autocomplete endpoint is **unofficial**: the fetcher does 1 req/s with
  jitter, caches every response for 7 days (re-runs are instant and free),
  never caches errors, and degrades to partial results instead of crashing.
- Per seed: the seed itself + a–z suffixes + question prefixes (`como`,
  `o que é`, `por que`, `qual`, `vale a pena`) = 32 queries, plus one
  recursion level on up to 5 high-signal suggestions (`--no-recursion` to
  disable). Dedupe is accent-insensitive and keeps the original form.
- Trends rows are **relative interest, never volume** — each row says so in
  its `notes` column.

### GSC mining (runs inside gsc-monitor, where the OAuth already lives)

```powershell
cd ..\gsc-monitor
py exportar_keywords.py --site seotecnico.dev.br            # "ranked but weak"
```

Exports queries with impressions > 0 and best position > 10 — proven demand
the site already ranks for, just not well. Aggregation is per query with the
**best** position across pages, so a query that another page already ranks
top-10 for is not a false "weak" positive.

## Stage 2 — validation (DataForSEO)

Always start with a dry run — it prints the request plan and a rough cost
estimate without touching the network (and without credentials):

```powershell
py validar.py --projeto seotecnico.dev.br --dry-run
py validar.py --projeto seotecnico.dev.br --keyword-map E:\blog\keyword-map.md
py validar.py --projeto seotecnico.dev.br --intent --drop-intent commercial,transactional
py validar.py --projeto seotecnico.dev.br --max-keywords 200 --budget 0.50   # cheap smoke
```

What it does: expands the top seeds via Labs **Keyword Ideas** (one request)
and **Related Keywords** (up to 5 seeds, `--related-depth 1|2`); validates the
Stage 1 list via **Google Ads Search Volume** in batches of 1,000 (expansion
keywords reuse the volume already present in the Labs response — no double
spend); optionally labels intent (`--intent`).

Keep/drop rules (Stage 2 → 3), applied in this order:

- **KEEP** if any: volume ≥ 10/month BR; **or** volume = 0 but the keyword
  appeared in Autocomplete (typed demand proven); **or** it came from GSC
  "ranked but weak"; **or** it is tagged `radar` (news topic — volume N/A).
- **DROP** (with an auditable `drop_reason`): already covered by
  `keyword-map.md` (`--keyword-map`; missing file just disables the check),
  or intent explicitly listed in `--drop-intent` — the tool never guesses
  content scope by itself.

Dropped keywords are never silently discarded: `{date}_validacao.csv` holds
every candidate with `keep` and `drop_reason` columns.

## Stage 3 — SERP spot-check

```powershell
py serp.py --projeto seotecnico.dev.br                 # default: top 30 keywords
py serp.py --projeto seotecnico.dev.br --limite 10
py serp.py --projeto seotecnico.dev.br --fetch         # resume: only collect pending
py serp.py --projeto seotecnico.dev.br --mobile        # mobile-skewed topics only
```

Google Organic, top-10, google.com.br / pt / desktop, posted to the
**standard queue** (async, flat pricing — the client never sends `priority`).
Task ids persist in `.cache/serp_pending.json`; if the queue is slow the run
exits cleanly with instructions to re-run with `--fetch`. Paid SERPs are
cached effectively forever and are never re-bought.

The output `{date}_serp_review.csv` (`;`-delimited, opens in Excel pt-BR) is
an **analyst worksheet**: `verdict_sugerido` + `motivo` are heuristic
suggestions (spec rule: no post-2024 App Router-specific title in the top 10
→ `target-now`; ≥3 official-docs slots → `target-later`); the analyst fills
`verdict_final` (`target-now` / `target-later` / `skip`) and `gap_notes`
(outdated? translated? no code? no App Router?). The freshness heuristic reads
result **titles only** — it cannot see real publish dates, and says so.

## Stage 4 — ground truth (T+28 days)

For each published post, 28 days later:

```powershell
cd ..\gsc-monitor
py exportar_keywords.py --site seotecnico.dev.br --url https://seotecnico.dev.br/posts/exemplo --dias 28
```

Review `{date}_keywords_url.csv`: queries with impressions that the article
does **not** cover become new seeds (`descobrir.py --seed ...`) or FAQ
additions. The CSV keeps raw metrics (clicks/impressions/ctr/position + the
date window) so it stays forward-compatible with gsc-monitor's planned
`experimento.py` before/after report. Scheduling is a calendar reminder — no
code.

## Radar (news) posts — editorial checklist, no code

Volume research does not apply. Publish when ALL of:

1. **Primary source** — Search Central blog/changelog, Next.js releases,
   Vercel changelog, web.dev / CWV metric announcements.
2. **No substantial PT-BR coverage yet** (quick `site:.br` check).
3. **Concrete Next.js implication** — every Radar post includes an
   "o que isso muda no seu Next.js" section.
4. **Publish within 24–72h**, linking to an evergreen chapter so the value
   persists after the news cycle.

To push a Radar topic through the pipeline anyway, add it to the discovery
CSV with `source=radar` — the Stage 2 filter keeps it regardless of volume.

## Data contracts (all under gitignored `relatorios/`)

| File | Producer → Consumer | Delim. | Columns |
|------|--------------------|--------|---------|
| `{date}_descoberta.csv` | descobrir.py → validar.py | `,` | `keyword,source,seed,date_collected,notes` |
| `gsc-monitor/.../{date}_keywords_gsc.csv` | exportar_keywords.py → `--gsc-csv` | `,` | same 5 columns, `source=gsc-weak` |
| `gsc-monitor/.../{date}_keywords_url.csv` | exportar_keywords.py `--url` → analyst | `,` | `query,url,clicks,impressions,ctr,position,date_start,date_end` |
| `{date}_validacao.csv` | validar.py (audit) | `,` | `keyword,normalized,volume,cpc,competition,intent,source,seed,keep,drop_reason` |
| `{date}_stage3_input.csv` | validar.py → serp.py | `,` | `keyword,volume,intent,source` |
| `{date}_serp_review.csv` | serp.py → analyst (editable) | `;` | `keyword;volume;verdict_sugerido;motivo;verdict_final;big_players;docs_oficiais;top_dominios;gap_notes` |
| `_ledger/dataforseo_costs.csv` | client (append-only) | `,` | `timestamp_utc,endpoint,tasks,cost_usd,note` |

`source` values in the discovery format: `autocomplete`, `trends-top`,
`trends-rising`, `gsc-weak`, `radar`, `manual`.

## Cost guardrails (three layers)

1. **Pre-flight budget check** — every paid request first checks the monthly
   ledger total against the cap (`config.MONTHLY_BUDGET_USD`, env
   `DATAFORSEO_MONTHLY_CAP`, or `--budget`) and refuses to spend past it.
2. **Append-only ledger** — the `cost` field of every response (including
   billed failures) lands in `relatorios/_ledger/dataforseo_costs.csv`.
3. **Volume fuses** — `--dry-run` cost preview, `--max-keywords` (Stage 2)
   and `--limite` (Stage 3).

Two fields are **never sent**, pinned by regression tests: `priority`
(real-time pricing) and `include_clickstream_data` (doubles cost).

## Tests

```powershell
py -m pytest        # from keyword-research/ — fully offline, everything mocked
```

Same repo rules as the sibling tools: tests never touch the network, the
`relatorios/` folder is redirected to a tempdir for the whole session, and
errors are never cached.
