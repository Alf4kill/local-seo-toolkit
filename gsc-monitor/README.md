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
| `--site` | Domínio a analisar |
| `--excel` | Gera relatório `.xlsx` |
| `--csv` | Gera relatório `.csv` |
| `--txt` | Gera relatório `.txt` legível |
| `--queries` | Analisa canibalização de keywords |
| `--trends` | Tendências de demanda — padrão: dimensão `date` do GSC (90 dias, impressões/dia do próprio site) |
| `--trends-source pytrends` | Fonte legada: índice global 0–100 do Google Trends (não-oficial, frágil) |
| `--nlp` | Analisa entidades e categorias NLP (consome cota de API) |
| `--content` | Diagnóstico de qualidade de conteúdo (sem cota) |
| `--no-cache` | Ignora cache e força dados frescos da API |
| `--api-key KEY` | API key do Google Cloud |
| `--batch ARQUIVO` | Modo lote headless: pipeline padrão para cada domínio do arquivo |
| `--batch-report` | Com `--batch`: resumo do lote em `relatorios/_batch/YYYY-MM-DD_resumo.csv` |

### CLI — Batch (vários domínios de uma vez)

```powershell
.\.venv\Scripts\python.exe posicao.py --batch sites.txt --batch-report
```

O modo batch roda o pipeline padrão de ranking (**posições + queries +
qualidade de conteúdo**, cache-aware, sem GUI) para cada domínio listado em
`sites.txt` — um por linha; linhas com `#` são comentários (modelo em
`sites.example.txt`). Para cada site, o histórico (`historico_posicao.json`)
recebe um novo snapshot e o dashboard é regenerado. Erros em um site **não
interrompem** os demais; ao final é impressa uma linha-resumo por site
(health score + grade + nº de snapshots).

Com `--batch-report`, um CSV consolidado é gravado em
`relatorios/_batch/YYYY-MM-DD_resumo.csv` com colunas: site, status, health,
grade, posição média, CTR, grupos de canibalização, contagem de vereditos de
conteúdo (ok / atenção / over-otimizado / raso) e total de snapshots.

#### Snapshots semanais automáticos (Windows Task Scheduler)

Para acumular snapshots toda semana sem rodar manualmente, crie a tarefa
agendada com uma linha (ajuste o caminho da pasta se necessário):

```powershell
schtasks /Create /TN "GSC Monitor Semanal" /SC WEEKLY /D MON /ST 08:00 /TR "cmd /c cd /d E:\projetos\projetoprst.com.br\gsc-monitor && .venv\Scripts\python.exe posicao.py --batch sites.txt --batch-report"
```

Para conferir ou remover: `schtasks /Query /TN "GSC Monitor Semanal"` e
`schtasks /Delete /TN "GSC Monitor Semanal" /F`. Requisito: `token.json` já
gerado (rode uma vez manualmente antes para autenticar no navegador — a
tarefa agendada usa o refresh silencioso do token, sem abrir janelas).

### CLI — Indexação

```powershell
.\.venv\Scripts\python.exe main.py --site www.exemplo.com.br --limit 10
```

---

## Relatórios gerados

Todos os arquivos ficam em `relatorios/{dominio}/`:

| Arquivo | Conteúdo |
|---------|----------|
| `YYYY-MM-DD_posicao.json` | Dados brutos de posicionamento |
| `YYYY-MM-DD_posicao.xlsx` | Excel com abas: Resumo, Posicionamento, Oportunidades CTR, Histórico, Trends, Canibalização, Sem Impressões |
| `dashboard.html` | Dashboard interativo com gráficos Chart.js |
| `YYYY-MM-DD_indexacao.json` | Dados brutos de indexação |
| `_batch/YYYY-MM-DD_resumo.csv` | Resumo consolidado do modo batch (`--batch-report`) |
| `YYYY-MM-DD_redirects.csv` | **Sugestão** de consolidação 301 (gerado quando há canibalização, via `--queries`) |
| `YYYY-MM-DD_redirects_apache.txt` | Bloco `.htaccess` (Apache) com os 301 sugeridos |
| `YYYY-MM-DD_redirects_nginx.txt` | Bloco `server {}` (nginx) com os 301 sugeridos |

### Plano de Consolidação 301 (sugestão)

Quando a análise de canibalização (`--queries`) encontra grupos de URLs
competindo pela mesma keyword, a ferramenta gera automaticamente um **plano de
consolidação 301**: para cada grupo, escolhe a URL canônica (mais cliques →
melhor posição → mais impressões) e lista as demais como origens de redirect.
O plano sai em três formatos prontos para aplicar (CSV + Apache + nginx), além
da sheet "Plano 301" no Excel e de uma seção no dashboard.

> ⚠ **O plano é uma sugestão automática — nunca aplique sem revisão humana.**
> Confirme que as páginas são de fato redundantes (e não intencionalmente
> distintas) antes de criar redirects 301, que são difíceis de reverter.
> Conflitos entre grupos (URL canônica em um grupo e concorrente em outro) são
> resolvidos por prioridade de severidade e listados nos artefatos.

---

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Saída esperada: **233 testes OK**. Toda a suíte roda no pytest (config em
`pytest.ini`); as chamadas de rede são mockadas, então nenhum teste gasta cota.

---

## Estrutura do projeto

```
gsc-monitor/
  app.py          ← entrada GUI
  posicao.py      ← CLI: posicionamento
  main.py         ← CLI: indexação
  config.py       ← BASE_DIR centralizado
  core/           ← lógica de negócio
    auth.py       ← OAuth2 Google
    cache.py      ← cache JSON por domínio
    storage.py    ← I/O de arquivos
    analytics.py  ← health score, páginas sem impressões, canibalização
    classifier.py ← mapeamento verdict → categoria
    sitemap.py    ← parser de sitemap.xml
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
  gui/
    main_window.py ← janela Tkinter
    runner.py      ← execução em thread
  tests/             ← suíte pytest: test_storage, test_cache, test_analytics,
                       test_ctr, test_classifier, test_sitemap, test_content_quality,
                       test_position_fetcher, test_phase5 (APIs), test_phase6 (dashboard)
  relatorios/
    {dominio}/     ← arquivos por domínio
      .cache/      ← cache de API
      dashboard.html
      YYYY-MM-DD_*.json/xlsx/csv
```

---

## Notas

- O cache tem TTL de 72h para posicionamento/NLP e 24h para indexação. Use `--no-cache` para forçar dados frescos.
- `--trends` usa por padrão a dimensão `date` do GSC (oficial, sem dependência extra). `pytrends` só é necessário para o caminho legado `--trends-source pytrends`.
- O dashboard HTML é gerado automaticamente a cada execução de posicionamento.
- A flag `--nlp` consome cota da Cloud Natural Language API (2 unidades por URL, gratuito até 5.000/mês).
