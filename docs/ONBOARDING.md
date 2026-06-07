# Onboarding guide

How to get the whole project running on a fresh machine and produce your first
useful analysis. Written for the solo maintainer returning after a break or
setting up a new computer. Target: first ranking report in well under an hour
(most of that is Google Cloud setup).

## Environment setup

You need **Python 3.13** ([python.org/downloads](https://www.python.org/downloads/))
and a Google account with Search Console access to the domains you care about.
The project is built and tested on Windows; the `setup.sh` script covers
Linux/Mac for `gsc-monitor`.

Clone or open the project folder. The two tools install separately.

### gsc-monitor

```powershell
cd gsc-monitor
.\setup.ps1            # Windows — creates .venv, installs deps, verifies
# ./setup.sh           # Linux/Mac
```

`setup.ps1` creates a virtual environment in `.venv/` and installs everything
from `requirements.txt`. From here on, run the tool with that interpreter:
`.\.venv\Scripts\python.exe <script>` (the docs abbreviate this as `py`).

### semantic-analyzer

```powershell
cd ..\semantic-analyzer
pip install -r requirements.txt
```

The clusterer core and its tests run with just `numpy`. `sentence-transformers`
is what you need for *real* semantic clustering — its first run downloads the
model (~470 MB). The optional local-LLM layer is set up separately (see below).

## Credentials (gsc-monitor only)

`semantic-analyzer` needs no credentials. `gsc-monitor` needs Google ones.

**1. OAuth2 for Search Console (required).** In
[console.cloud.google.com](https://console.cloud.google.com), enable the
**Google Search Console API**, then create an **OAuth client ID → Desktop app**
credential. Download the JSON, rename it to `client_secrets.json`, and place it
in `gsc-monitor/`. On first run a browser opens for login; the resulting
`token.json` is saved and refreshed automatically afterward.

**2. API key for Knowledge Graph and NLP (optional).** Enable the Knowledge Graph
Search API and Cloud Natural Language API, create an API key, and put it in
`gsc-monitor/google_api_key.txt` (or the `GOOGLE_API_KEY` env var, or pass
`--api-key`). NLP is only consumed when you use the `--nlp` flag.

All credential files are gitignored.

## How the systems connect

Before running anything, it helps to hold the mental model from the
[architecture doc](ARCHITECTURE.md): two independent tools that hand off through
files.

1. `gsc-monitor` pulls ranking/indexing data from Search Console and writes
   `relatorios/<site>/YYYY-MM-DD_posicao.json` plus Excel/HTML/CSV.
2. `semantic-analyzer` reads a site backup, clusters pages by meaning, and —
   when you pass `--gsc` pointing at that snapshot — uses real performance to
   decide which duplicate page to keep.

So the natural order is: run `gsc-monitor` first to get a fresh snapshot, then
run `semantic-analyzer` against it.

## Common tasks (walkthroughs)

### Your first ranking report

```powershell
cd gsc-monitor
.\.venv\Scripts\python.exe posicao.py --site www.exemplo.com.br --excel
```

This authenticates (browser opens the first time), fetches the sitemap, pulls
Search Analytics data, computes the health score and cannibalization, and writes
a JSON snapshot, an Excel workbook, and a refreshed `dashboard.html` under
`relatorios/www.exemplo.com.br/`. Open the dashboard in a browser to read it.

Add analysis as needed (flags combine):

```powershell
.\.venv\Scripts\python.exe posicao.py --site www.exemplo.com.br `
  --excel --queries --content --nlp
#   --queries  cannibalization     --content  content-quality verdict
#   --nlp      entity NLP (uses quota)         --trends  Google Trends
```

### Run through the GUI instead

```powershell
.\.venv\Scripts\python.exe app.py
```

The window lets you enter a domain, pick analyses and output formats, set a URL
limit, toggle cache, watch live output, and open the report folder. It drives the
same code as the CLI.

### Check indexing (mind the quota)

URL Inspection is capped at **2,000 calls/day**, so use `--limit` while testing:

```powershell
.\.venv\Scripts\python.exe main.py --site www.exemplo.com.br --limit 10
```

### Cluster a site's content by meaning

```powershell
cd ..\semantic-analyzer
py analisar.py --primeweb "E:\projetos\backup\exemplo" --html clusters.html
```

To turn that into a consolidation plan that knows which page to keep, point
`--gsc` at the snapshot `gsc-monitor` just produced:

```powershell
py analisar.py --primeweb "E:\projetos\backup\exemplo" `
  --gsc "E:\projetos\local-seo-toolkit\gsc-monitor\relatorios\www.exemplo.com" `
  --html plano.html
```

The full command cookbook — differentiation plans, link graphs, threshold
tuning, scenario recipes — lives in
[`semantic-analyzer/COMANDOS.md`](../semantic-analyzer/COMANDOS.md).

### Optional: enable the local LLM (GPU)

Only needed for `--llm` / `--differentiate`. One-time setup with Ollama:

```powershell
winget install --id Ollama.Ollama
cd semantic-analyzer
.\setup-ollama.ps1            # enables GPU (Vulkan) + downloads qwen2.5:7b-instruct
ollama ps                     # should report "100% GPU"
```

On the RX 6750 XT, GPU acceleration requires `OLLAMA_VULKAN=1` (the script
persists it) because Ollama's ROCm doesn't support that card on Windows. See
`COMANDOS.md` for model choices (7B vs 14B) and troubleshooting.

## Verify your setup

Run both test suites. They're fast, fully offline, and spend no API quota.

```powershell
cd gsc-monitor        ; py -m pytest        # ~154 tests
cd ..\semantic-analyzer ; py -m pytest      # ~80 tests
```

Green suites mean the pure logic and report generators work; a real end-to-end
check is running one `posicao.py` against a test domain and confirming the
dashboard appears.

## Where things live

| You need… | Look in… |
|-----------|----------|
| Generated reports | `<tool>/relatorios/<site>/` |
| Cached API/embedding data | `<tool>/relatorios/<site>/.cache/` or `semantic-analyzer/.cache/` |
| Credentials | `gsc-monitor/client_secrets.json`, `token.json`, `google_api_key.txt` |
| Tool-level design + context | `gsc-monitor/CLAUDE.md` |
| Command recipes | `semantic-analyzer/COMANDOS.md` |
| Recurring tasks / recovery | [`RUNBOOK.md`](RUNBOOK.md) |

## Who to ask for what

This is a solo project, so "who" is mostly "which document." For *why a decision
was made*, read `gsc-monitor/CLAUDE.md` (it logs the rationale per change). For
*how to run a specific command*, `COMANDOS.md`. For *test coverage and gaps*,
`ESTRATEGIA_TESTES.md`. For Google API quotas and console settings, the Google
Cloud console for the project that owns `client_secrets.json`.
