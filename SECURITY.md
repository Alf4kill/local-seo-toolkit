# Security & secret handling

This is a **local-first** toolkit. It uses **your own** Google credentials
(Search Console, Knowledge Graph, Cloud Natural Language) and a **local** LLM
(Ollama / LM Studio). No secret is ever sent anywhere except Google's own APIs.

## What counts as a secret here

| File / value | What it is | Where it lives |
|--------------|------------|----------------|
| `gsc-monitor/client_secrets.json` | Google OAuth2 **desktop** client (id + secret) | local only |
| `gsc-monitor/token.json` | OAuth2 token minted after first login (holds a refresh token) | generated, local only |
| `gsc-monitor/google_api_key.txt` *or* the `GOOGLE_API_KEY` env var | Google Cloud API key (Knowledge Graph / NLP) | local only |

**None of these are in the repository.** They are listed in `.gitignore`, and a
pre-commit scanner (below) blocks them even if you `git add -f` by mistake.

## First-time setup (bring your own credentials)

1. **OAuth client** — Google Cloud Console → APIs & Services → Credentials →
   Create credentials → OAuth client ID → *Desktop app*. Download the JSON,
   rename it to `client_secrets.json`, and put it in `gsc-monitor/`.
   See [`gsc-monitor/client_secrets.json.example`](gsc-monitor/client_secrets.json.example)
   for the expected shape.
2. **API key** (only for the Knowledge Graph / NLP features) — create an API key
   in the same console, then either:
   - set an environment variable `GOOGLE_API_KEY`, **or**
   - paste it into `gsc-monitor/google_api_key.txt`
     (see `google_api_key.txt.example`).
3. Run the tool — on first run a browser opens for Google login and `token.json`
   is created automatically.

## Defense in depth

1. **`.gitignore`** at the repo root ignores every credential file, every
   environment file, and all client data (reports, exports, crawl lists).
2. **Pre-commit secret scanner** — [`scripts/check_secrets.py`](scripts/check_secrets.py)
   (pure Python, no dependencies) refuses to commit known credential files or
   anything that looks like an API key / token / private key.

   Enable it either way:

   ```bash
   # Option A — pre-commit framework (cross-platform)
   pip install pre-commit
   pre-commit install

   # Option B — native git hook, no extra tools (run from the repo root)
   cp scripts/check_secrets.py .git/hooks/pre-commit   # on Unix also: chmod +x .git/hooks/pre-commit
   ```

   Audit the whole tree at any time:

   ```bash
   python scripts/check_secrets.py --all
   ```

## If a secret is ever exposed — rotate, don't just delete

- **OAuth client secret** → Cloud Console → Credentials → delete/recreate the
  OAuth client, then remove `token.json` so a fresh login mints a new token.
- **API key** → Cloud Console → Credentials → regenerate (or delete) the key.
- If a secret was ever **committed**, rotating is mandatory — scrubbing it from
  history is *not* enough, because clones and forks keep the old value.

## Client confidentiality

Generated reports embed real client domains, Search Console metrics and page
content. They are git-ignored (`relatorios/`, `relatorios-analise/`, `*.docx`,
`*.xlsx`, `*_urls.txt`). All example data in code and docs uses placeholder
domains like `exemplo.com.br` — never a real client.
