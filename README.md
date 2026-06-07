# local-seo-toolkit

A personal, local-only SEO toolkit for diagnosing and fixing **content
cannibalization** and **over-optimization** across the 100+ sites the maintainer
has access to. Everything runs on one Windows machine, uses only free API tiers
or local processing, and never depends on a paid LLM service. Analytical honesty
is the guiding principle: verdicts are rule-based or come from a *local* model,
never presented as more certain than the data supports.

The repository holds two cooperating tools plus a few project-level notes:

| Path | What it is |
|------|------------|
| [`gsc-monitor/`](gsc-monitor/) | Google Search Console analyzer — indexing + ranking reports, health score, cannibalization, content-quality NLP, Excel/HTML/CSV output, Tkinter GUI. |
| [`semantic-analyzer/`](semantic-analyzer/) | Local embeddings tool that clusters a site's pages by *meaning* to surface duplicate/doorway content, with an optional local-LLM judgment layer and internal-link graph. |
| [`ESTRATEGIA_TESTES.md`](ESTRATEGIA_TESTES.md) | Test-suite strategy and coverage map for both tools. |
| [`docs/`](docs/) | Project-wide documentation (this set). |

## Why two tools

They answer two different questions about the same problem and deliberately stay
decoupled. `gsc-monitor` sees cannibalization only through the *queries that
already rank* in Search Console. `semantic-analyzer` compares the *content* of
**every** page, so it catches duplicates that have no traffic yet. Keeping the
heavy ML dependencies (`sentence-transformers` + `torch`) isolated in
`semantic-analyzer` means `gsc-monitor` stays lightweight. The two cooperate
through **files**, not imports: `semantic-analyzer` reads the `*_posicao.json`
snapshots that `gsc-monitor` writes, so it can pick which duplicate page to keep
based on real Search Console performance.

```
                 Google Search Console API (free tier)
                              │
                     ┌────────▼─────────┐
                     │   gsc-monitor    │  ranking + indexing + content quality
                     └────────┬─────────┘
                              │ writes relatorios/<site>/YYYY-MM-DD_posicao.json
                              ▼
                     ┌──────────────────┐
   site backups ───▶ │ semantic-analyzer │  meaning-based clustering + link graph
   (primeWeb)        └──────────────────┘  reads the GSC snapshot via --gsc
```

## Quick start

Both tools are Python and run from their own folders. `gsc-monitor` ships setup
scripts; `semantic-analyzer` installs with plain `pip`.

```powershell
# gsc-monitor — first time creates .venv and installs everything
cd gsc-monitor
.\setup.ps1                                   # Windows  (./setup.sh on Linux/Mac)
.\.venv\Scripts\python.exe app.py            # launch the GUI
#   or a CLI ranking report:
.\.venv\Scripts\python.exe posicao.py --site www.exemplo.com.br --excel

# semantic-analyzer — clusters a site's pages by meaning
cd ..\semantic-analyzer
pip install -r requirements.txt
py analisar.py --primeweb "E:\projetos\backup\exemplo" --html clusters.html
```

For the full setup-from-scratch walkthrough see [`docs/ONBOARDING.md`](docs/ONBOARDING.md).

## Documentation map

| Document | Read it when you want to… |
|----------|---------------------------|
| [`docs/ONBOARDING.md`](docs/ONBOARDING.md) | Set up the whole project on a fresh machine and run your first analysis. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Understand how the modules fit together and the key design decisions. |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Perform a recurring task or recover from a failure (auth, quotas, GPU, cache). |
| [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) | Look up CLI flags and the public functions of each module. |
| [`gsc-monitor/README.md`](gsc-monitor/README.md) · [`gsc-monitor/CLAUDE.md`](gsc-monitor/CLAUDE.md) | Tool-specific setup and the deeper design/context log for gsc-monitor. |
| [`semantic-analyzer/README.md`](semantic-analyzer/README.md) · [`semantic-analyzer/COMANDOS.md`](semantic-analyzer/COMANDOS.md) | Tool-specific overview and the copy-paste command cookbook. |
| [`ESTRATEGIA_TESTES.md`](ESTRATEGIA_TESTES.md) | Review or extend the test suites. |

## Ground rules

These constraints shape every decision in the project and are worth keeping in
mind before changing anything:

- **Local and permanent.** Nothing runs on the company server. A prior PHP
  project took down the Plesk panel, and the server's Python is old and frozen;
  running locally on Python 3.13 sidesteps all of that.
- **Free tiers or local only.** No paid APIs — including hosted LLMs. Allowed:
  Search Console, Knowledge Graph, Cloud Natural Language (free 5,000 units/mo),
  and local models via Ollama/LM Studio. The bottleneck is **API quota**, not RAM.
- **Honesty over confidence.** Heuristics are never presented as certainty. The
  Cloud NLP API is not Google's ranking algorithm, and the tools say so.

## Security

Credentials (Google OAuth client, token, API key) are **never** committed — they
are git-ignored and a zero-dependency pre-commit scanner (`scripts/check_secrets.py`)
blocks them from being added by mistake. Bring your own credentials by following
[`SECURITY.md`](SECURITY.md). All example data in code and docs uses placeholder
domains like `exemplo.com.br` — never a real client.

## Tech stack

Python 3.13 throughout. `gsc-monitor` uses `google-api-python-client`,
`openpyxl`, `requests`, Tkinter, and optional `pytrends`; tests run with
`pytest` as the single runner.
`semantic-analyzer` uses `numpy`, `sentence-transformers` (+`torch`),
`scikit-learn`, and talks to a local LLM over an OpenAI-compatible HTTP API.

> Code, comments, and generated reports are in **Portuguese**; this `docs/` set
> is in English. The two tool READMEs and `COMANDOS.md` are in Portuguese and
> remain the canonical tool-level references.

## License

Released under the [MIT License](LICENSE) — © 2026 Alf4kill.
