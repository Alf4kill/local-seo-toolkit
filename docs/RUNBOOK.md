# Runbook

Step-by-step procedures for the recurring tasks and failure modes of this
project. Use this when you're *operating* the tools, not reading about them. For
setup from scratch see [`ONBOARDING.md`](ONBOARDING.md); for design see
[`ARCHITECTURE.md`](ARCHITECTURE.md).

All commands assume Windows PowerShell. In `gsc-monitor`, `py` is shorthand for
`.\.venv\Scripts\python.exe`.

---

## Procedure: full analysis of a site

**When:** you want a complete, current picture of one site and a consolidation
plan. **Prerequisites:** credentials in place (see Onboarding); for the
consolidation step, a content backup of the site and a matching GSC property.

1. **Pull a fresh ranking snapshot** (this also feeds step 3):

   ```powershell
   cd gsc-monitor
   py posicao.py --site www.exemplo.com --excel --queries --content
   ```

   Confirm `relatorios/www.exemplo.com/<today>_posicao.json` and
   `dashboard.html` were written.

2. **Read the decomposition, not just the score.** Open the dashboard. A "Good"
   composite can hide a critical component (the classic case: healthy ranking but
   catastrophic CTR) — any component below 40 raises an explicit alert. Check each
   health-score component and the cannibalization and content-quality sections
   separately. When `--queries` finds competing groups, the run also writes a
   **suggested** 301 consolidation plan (`YYYY-MM-DD_redirects.csv` plus Apache and
   nginx blocks, the Excel "Plano 301" sheet, and a dashboard section). Review it
   before applying anything — 301s are hard to reverse.

3. **Build the consolidation plan** from the snapshot:

   ```powershell
   cd ..\semantic-analyzer
   py analisar.py --primeweb "E:\projetos\backup\exemplo" `
     --gsc "E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com" `
     --html plano.html
   ```

   `--gsc` picks the page to keep by real performance and orders groups by
   impressions in dispute.

4. **(Optional) Add a local-LLM judgment or a contract-safe plan.** See the LLM
   procedure below and the recipes in
   [`COMANDOS.md`](../semantic-analyzer/COMANDOS.md).

**Rollback / re-run:** these tools only read external data and write into
`relatorios/`. Re-running is always safe; the dashboard is regenerated each time
and the JSON snapshot is dated. To discard a run, delete its dated files.

---

## Procedure: measure whether a fix worked

**When:** you applied a consolidation/differentiation and want to know if ranking
improved. The measurement loop is built into `gsc-monitor`.

1. Make sure you have a **baseline** snapshot from before the change (each
   `posicao.py --content` run appends one to `historico_posicao.json`, capped at
   30 per domain).
2. After the change has had time to take effect, run `posicao.py --content` again.
3. Read the **"Acompanhamento" (tracking)** section of the dashboard — it
   cross-references content verdict against position delta since baseline.

---

## Procedure: recurring batch snapshots

**When:** you want to feed the measurement loop across many sites without running
each by hand. **Prerequisite:** `token.json` already generated (run `posicao.py`
once interactively first so the browser consent flow completes).

1. List the domains in a file, one per line (`#` for comments; copy
   `sites.example.txt`):

   ```
   www.exemplo.com.br
   www.exemplo-b.com.br
   # www.exemplo-c.com.br   (paused)
   ```

2. Run the headless batch:

   ```powershell
   cd gsc-monitor
   py posicao.py --batch sites.txt --batch-report
   ```

   Each site gets a fresh snapshot, an appended `historico_posicao.json`, and a
   regenerated dashboard. An error on one site does **not** abort the rest; a
   one-line summary prints per site, and `--batch-report` writes
   `relatorios/_batch/YYYY-MM-DD_resumo.csv`.

3. **Automate weekly** via Windows Task Scheduler so snapshots accumulate without
   manual runs:

   ```powershell
   schtasks /Create /TN "GSC Monitor Semanal" /SC WEEKLY /D MON /ST 08:00 ^
     /TR "cmd /c cd /d E:\projetos\local-seo-toolkit\gsc-monitor && .venv\Scripts\python.exe posicao.py --batch sites.txt --batch-report"
   ```

   The scheduled run uses the silent token refresh, so no browser window opens.

---

## Procedure: build a pruning plan (old URLs)

**When:** a site has accumulated stale URLs that Google still knows but the
sitemap no longer lists. **Prerequisite:** the sitemap convention holds (it lists
every active page).

1. **Generate the editable plan** (stage 1):

   ```powershell
   py poda.py --site www.exemplo.com.br
   ```

   Writes `relatorios/www.exemplo.com.br/poda/<today>_poda.csv`. For old URLs with
   zero impressions the API can't see, add the manual GSC "Pages" export:
   `--importar-gsc export.csv`.

2. **Review the CSV.** Edit `acao_final` (`410`/`404`/`301`/`manter`) and
   `destino_final`. No-traffic ghosts default to `410`; ghosts with traffic are
   marked `revisar` — *you* decide, never the tool. The CSV is `;`-delimited with
   comma decimals so it opens in columns in pt-BR Excel.

3. **Compile** the reviewed CSV into redirect blocks (stage 2):

   ```powershell
   py poda.py --site www.exemplo.com.br --compilar
   ```

   Produces four formats in the `poda/` subfolder: anchored Apache `RedirectMatch`,
   simple `mod_alias` `Redirect 301`, nginx `server {}`, and a standalone PHP file.
   The compiler warns if too many URLs redirect to the home (Google treats mass
   home redirects as soft-404). Or use the dedicated GUI: `py app_poda.py`.

---

## Procedure: run the local LLM layer

**When:** you want `--llm` (judge groups) or `--differentiate` (contract-safe
plan). **Prerequisite:** a running local LLM server.

1. Start the server: open the Ollama tray app, or run `ollama serve`.
2. Confirm GPU: `ollama ps` should show **100% GPU**. If it shows CPU, the Vulkan
   env var is missing — see the failure below.
3. Run with the LLM enabled:

   ```powershell
   py analisar.py --primeweb "E:\projetos\backup\exemplo" `
     --gsc "E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com" `
     --llm --llm-model qwen2.5:7b-instruct `
     --site-context "Canil de cães de raça" --html plano.html
   ```

4. To free VRAM immediately when done instead of waiting ~5 min, add
   `--llm-unload`.

No GPU server available? Use `--llm-backend transformers` to run a small model on
CPU (slow; testing only).

---

## Failure: browser doesn't open / auth fails on first run

`gsc-monitor` can't find or use `client_secrets.json`.

- Confirm `client_secrets.json` is in `gsc-monitor/` and is an **OAuth Desktop
  app** credential (not a service account or web client).
- Delete `token.json` and re-run to force a fresh consent flow.
- Verify the Google account has Search Console access to the `--site` domain.

---

## Failure: API quota exhausted

The real bottleneck. Symptoms are quota/429 errors from Google.

- **URL Inspection (`main.py`)** — 2,000 calls/day. Always test with `--limit`.
  Cached inspections (24h TTL) don't count again; avoid `--no-cache` unless
  necessary.
- **Cloud NLP (`--nlp`)** — 5,000 units/month (≈2 units/URL). Only spent when you
  pass `--nlp`; results cache for 72h. Drop `--nlp` to stay within free tier.
- General rule: let the cache do its job. API errors are **never** cached, so a
  failed call doesn't poison future runs.

---

## Failure: `pytrends` / `--trends` breaks

`--trends` now defaults to the first-party GSC `date` dimension, which is official
and not rate-limited — prefer it. The legacy `pytrends` path is the only fragile
one.

- Treat `--trends` as fully optional — drop the flag and the rest of the report
  still works.
- Only `--trends-source pytrends` hits the unofficial, rate-limited endpoint. If
  it's flaky, wait out the rate limit, drop back to the default `gsc` source, or
  skip trends entirely. `pytrends` is not installed by default
  (`pip install pytrends` to use the legacy path).

---

## Failure: LLM runs on CPU (slow) or no server found

- **`[llm] Nenhum servidor LLM em ...`** — the server isn't running. Start it
  (`ollama serve` or the tray app), or fall back to `--llm-backend transformers`.
- **Running on CPU despite a GPU** — `OLLAMA_VULKAN=1` is missing. Run
  `.\setup-ollama.ps1` (it persists the var) and confirm with `ollama ps`. On the
  RX 6750 XT, ROCm doesn't support the card on Windows, so Vulkan is required.
- **14B model spilling to CPU / slow** — keep context at 8192
  (`OLLAMA_CONTEXT_LENGTH=8192`); 16k pushes the KV-cache past 12 GB VRAM.

---

## Failure: `FileNotFoundError: ...\include\parametros.php`

You copied a `COMANDOS.md` example containing a literal `"..."`. Python tried to
open a folder named `...`. Replace `"..."` with the real path from the paths
table in [`COMANDOS.md`](../semantic-analyzer/COMANDOS.md).

---

## Failure: everything clusters into one giant group

Single-linkage chaining. Switch to the default `--method agglomerative` and raise
`--threshold` (single-theme sites often need 0.83–0.88).

---

## Failure: `--gsc` matched 0 URLs

The backup and the GSC report are for different sites (slugs don't match), or you
pointed `--gsc` at `historico_posicao.json`. Point it at the site's
`relatorios/<site>/` folder or a specific `YYYY-MM-DD_posicao.json`.

---

## Failure: broken accents / `UnicodeEncodeError`

Entry points already force UTF-8. If you wrote a one-off script that imports the
library code directly, set `PYTHONIOENCODING=utf-8`, and keep flow-level `print`s
ASCII (emoji belongs only in HTML/Excel artifacts).

---

## Procedure: refresh stale data

Both tools cache per site and degrade nothing by re-running. To force fresh data:

```powershell
py posicao.py --site www.exemplo.com.br --no-cache      # gsc-monitor
py analisar.py --primeweb "<dir>" --no-cache            # semantic-analyzer (re-embeds)
```

Cache TTLs (gsc-monitor): position 72h, queries 72h, inspect 24h, KG 7d, NLP 72h,
trends 24h, page text 72h. Use `--no-cache` sparingly — it spends quota.

---

## Escalation

Solo project, so escalation is to documentation and the source:

- *Why* something is built a certain way → `gsc-monitor/CLAUDE.md`.
- Exact command syntax and scenario recipes → `semantic-analyzer/COMANDOS.md`.
- Test coverage and known gaps → `ESTRATEGIA_TESTES.md`.
- Google quotas / API enablement → the Google Cloud console for the project that
  owns `client_secrets.json`.
