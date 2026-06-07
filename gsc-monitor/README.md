# GSC Monitor

Ferramenta de análise do Google Search Console para múltiplos domínios.
Gera relatórios de indexação e posicionamento com Excel, dashboard HTML interativo e análises de NLP, Knowledge Graph e Google Trends.

---

## Pré-requisitos

- **Python 3.13** — [python.org/downloads](https://www.python.org/downloads/)
- **Conta Google** com acesso ao Search Console dos domínios desejados
- **Google Cloud Project** com as seguintes APIs habilitadas:
  - Google Search Console API (obrigatória)
  - Knowledge Graph Search API (opcional)
  - Cloud Natural Language API (opcional, flag `--nlp`)

---

## Setup (primeira vez)

### Windows

```powershell
# Na pasta gsc-monitor/, execute:
.\setup.ps1
```

O script cria um ambiente virtual `.venv/`, instala todas as dependências e verifica a instalação.

### Linux / Mac

```bash
chmod +x setup.sh && ./setup.sh
```

---

## Configuração de credenciais

### 1. OAuth2 — Google Search Console (obrigatório)

1. Acesse [console.cloud.google.com](https://console.cloud.google.com)
2. Vá em **APIs e Serviços → Credenciais**
3. Clique em **Criar credencial → ID do cliente OAuth2 → Aplicativo de desktop**
4. Baixe o arquivo JSON e renomeie para `client_secrets.json`
5. Coloque `client_secrets.json` na pasta `gsc-monitor/`

Na primeira execução o navegador abrirá para login. O token é salvo em `token.json` e reutilizado automaticamente nas execuções seguintes.

### 2. API Key — Knowledge Graph e NLP (opcional)

Crie um arquivo `google_api_key.txt` na pasta `gsc-monitor/` com a sua API key do Google Cloud, ou passe via campo na interface gráfica, ou pela flag `--api-key`.

```
AIzaSy...sua_chave_aqui
```

---

## Como executar

### Interface gráfica

```powershell
.\.venv\Scripts\python.exe app.py
```

### CLI — Posicionamento

```powershell
.\.venv\Scripts\python.exe posicao.py --site www.exemplo.com.br --excel
```

**Flags disponíveis:**

| Flag | Descrição |
|------|-----------|
| `--site` | Domínio a analisar (obrigatório) |
| `--excel` | Gera relatório `.xlsx` |
| `--csv` | Gera relatório `.csv` |
| `--txt` | Gera relatório `.txt` legível |
| `--queries` | Analisa canibalização de keywords |
| `--trends` | Busca tendências no Google Trends |
| `--nlp` | Analisa entidades e categorias NLP (consome cota de API) |
| `--no-cache` | Ignora cache e força dados frescos da API |
| `--api-key KEY` | API key do Google Cloud |

### CLI — Indexação

```powershell
.\.venv\Scripts\python.exe main.py --site www.exemplo.com.br --limit 10
```

### CLI — Crawl Budget (logs do servidor)

Análise **100% local** do access log do servidor (Apache/Nginx) — **sem cota de
API**. Mede o comportamento real do Googlebot: frequência de crawl por URL,
páginas do sitemap **nunca rastreadas**, *money pages* com muitas impressões mas
**zero crawl**, e desperdício em URLs com parâmetro / erros 4xx.

```powershell
.\.venv\Scripts\python.exe logs.py --site www.exemplo.com.br --logs access.log
```

| Flag | Descrição |
|------|-----------|
| `--site` | Domínio analisado (obrigatório) |
| `--logs` | Um ou mais arquivos de log (aceita `.gz`) — obrigatório |
| `--format` | `combined` ou `common` (padrão: detecta automaticamente) |
| `--gsc` | Cruza com o último `*_posicao.json` salvo (money pages subcrawladas) |
| `--no-sitemap` | Não busca o sitemap (pula a lista "nunca rastreadas") |
| `--verify-googlebot` | Confirma cada IP por DNS reverso+direto (lento; elimina bot falsificado) |
| `--top N` | Quantas linhas mostrar nas tabelas "top" |

> **Honestidade analítica:** sem `--verify-googlebot`, a detecção do bot é só por
> User-Agent — que é **falsificável**. O relatório rotula isso explicitamente
> ("por UA, não verificado") em vez de afirmar certeza.

#### Como exportar o access log para a sua máquina

O log fica **no servidor**; a análise roda **local**. Baixe o arquivo antes:

- **Plesk:** *Sites & Domains → (domínio) → Logs* — baixe `access_log` (ou os
  rotacionados `*.processed` / `*.gz`). Via SSH/SFTP eles ficam em
  `/var/www/vhosts/system/{dominio}/logs/`.
- **Apache padrão:** `/var/log/apache2/access.log*`
- **Nginx padrão:** `/var/log/nginx/access.log*`

Copie para a máquina local e aponte `--logs` para o arquivo. Os logs **não** são
versionados (`*.log` está no `.gitignore`).

---

## Relatórios gerados

Todos os arquivos ficam em `relatorios/{dominio}/`:

| Arquivo | Conteúdo |
|---------|----------|
| `YYYY-MM-DD_posicao.json` | Dados brutos de posicionamento |
| `YYYY-MM-DD_posicao.xlsx` | Excel com abas: Resumo, Posicionamento, Oportunidades CTR, Histórico, Trends, Canibalização, Sem Impressões |
| `dashboard.html` | Dashboard interativo com gráficos Chart.js |
| `YYYY-MM-DD_indexacao.json` | Dados brutos de indexação |
| `YYYY-MM-DD_crawl.html` | Dashboard de crawl budget (Googlebot via access log) |
| `YYYY-MM-DD_crawl.json/.csv/.txt` | Crawl por URL, nunca-rastreadas e money pages subcrawladas |

---

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Saída esperada: **202 testes OK**. Toda a suíte roda no pytest (config em
`pytest.ini`); as chamadas de rede são mockadas, então nenhum teste gasta cota.

---

## Estrutura do projeto

```
gsc-monitor/
  app.py          ← entrada GUI
  posicao.py      ← CLI: posicionamento
  main.py         ← CLI: indexação
  logs.py         ← CLI: crawl budget (Googlebot via access log, local)
  config.py       ← BASE_DIR + constantes transversais
  core/           ← lógica de negócio
    auth.py       ← OAuth2 Google
    cache.py      ← cache JSON por domínio
    storage.py    ← I/O de arquivos
    analytics.py  ← health score, páginas sem impressões, canibalização
    classifier.py ← mapeamento verdict → categoria
    sitemap.py    ← parser de sitemap.xml
    log_analyzer.py ← parser/agregação de access log (crawl budget; puro)
  fetchers/       ← integração com APIs externas
    inspector.py         ← URL Inspection API
    position_fetcher.py  ← Search Analytics API
    knowledge_graph.py   ← Knowledge Graph Search API
    nlp_analyzer.py      ← Cloud Natural Language API
    trends_fetcher.py    ← Google Trends via pytrends
  reporters/      ← geração de saída
    reporter.py          ← relatórios de indexação
    position_reporter.py ← relatórios de posicionamento
    excel_reporter.py    ← geração de Excel
    html_reporter.py     ← dashboard HTML
    crawl_reporter.py    ← relatório de crawl budget (HTML/TXT)
  gui/
    main_window.py ← janela Tkinter
    runner.py      ← execução em thread
  tests/             ← suíte pytest: test_storage, test_cache, test_analytics,
                       test_ctr, test_classifier, test_sitemap, test_content_quality,
                       test_position_fetcher, test_log_analyzer, test_crawl_reporter,
                       test_phase5 (APIs), test_phase6 (dashboard)
  relatorios/
    {dominio}/     ← arquivos por domínio
      .cache/      ← cache de API
      dashboard.html
      YYYY-MM-DD_*.json/xlsx/csv
```

---

## Notas

- O cache tem TTL de 72h para posicionamento/NLP e 24h para indexação. Use `--no-cache` para forçar dados frescos.
- `pytrends` é necessário para `--trends`: `pip install pytrends` (já incluso no `requirements.txt`).
- O dashboard HTML é gerado automaticamente a cada execução de posicionamento.
- A flag `--nlp` consome cota da Cloud Natural Language API (2 unidades por URL, gratuito até 5.000/mês).
- `logs.py` analisa o access log do servidor **localmente** (crawl budget do Googlebot), **sem cota de API**; aceita `.gz` e múltiplos arquivos. Combine com `--gsc` (após rodar `posicao.py`) para cruzar crawl × impressões.
