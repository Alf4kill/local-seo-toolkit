# GSC Monitor — Progresso do Desenvolvimento

## Status Geral
**Fases 1, 2, 3, 4, 5 e 6 concluídas e validadas. Projeto completo.**

---

## O que foi feito

### Fase 1 — Reorganização de arquivos e CSV ✅
**Arquivos modificados:** `storage.py`, `main.py`, `posicao.py`

**Mudanças:**
- `storage.py` refatorado: relatórios agora salvam em `relatorios/{dominio}/` (pasta por domínio)
- Novo padrão de nome: `{data}_{tipo}.{ext}` (ex: `2026-05-30_posicao.json`)
- Arquivos antigos no formato plano preservados (compatibilidade retroativa)
- Nova função `save_csv_indexacao()` — colunas: URL, Categoria, Verdict, Estado de Cobertura, Ultimo Rastreamento
- Nova função `save_csv_posicao()` — colunas: URL, Posicao, Cliques, Impressoes, CTR(%), Com Dados
- Encoding `utf-8-sig` nos CSVs (compatibilidade com Excel no Windows)
- Flags `--csv` adicionadas em `main.py` e `posicao.py`

**Arquivo de teste:** `test_storage_phase1.py` (11/11 testes — script-based)

---

### Fase 2 — Cache de resultados de API ✅
**Arquivos criados:** `cache.py`
**Arquivos modificados:** `inspector.py`, `position_fetcher.py`, `main.py`, `posicao.py`

**Mudanças:**
- `cache.py`: módulo completo com cache JSON por domínio em `relatorios/{dominio}/.cache/`
  - `get_posicao_cache / set_posicao_cache` — TTL 72h, chave: `posicao_{start}_{end}.json`
  - `get_inspect_cache / set_inspect_cache` — TTL 24h, chave: `inspect_{YYYY-MM-DD}.json`
  - Cache incremental por URL (cada URL inspecionada é adicionada sem sobrescrever as outras)
  - Tolerante a: arquivo inexistente, JSON corrompido, TTL expirado
- `inspector.py`: novo parâmetro `use_cache=True`, log `[CACHE]` quando URL vem do cache
  - Erros de API **não são cacheados** (serão retentados na próxima execução)
- `position_fetcher.py`: novo parâmetro `use_cache=True`, cacheia a resposta completa da API
- Flags `--no-cache` adicionadas em `main.py` e `posicao.py`

**Comportamento validado:**
- 1ª execução: chama API, salva cache
- 2ª+ execução (< TTL): lê do cache, zero chamadas à API
- `--no-cache`: ignora cache, força API fresca

**Arquivo de teste:** `test_cache_phase2.py` (9/9 testes — script-based)

---

### Fase 3 — Interface Gráfica Local (GUI) ✅
**Arquivos criados:** `app.py`, `gui/__init__.py`, `gui/runner.py`, `gui/main_window.py`

**Como usar:** `py app.py` dentro da pasta `gsc-monitor/`

**Estrutura da GUI:**
- Painel "Configuração":
  - Campo Domínio (aceita `www.exemplo.com.br` ou `sc-domain:exemplo.com.br`)
  - Checkboxes: ☑ Indexação, ☑ Posicionamento
  - Checkboxes de formato: ☑ CSV, ☑ Excel, ☐ TXT (JSON sempre salvo)
  - Campo "Limite de URLs" + checkbox "Ignorar cache (–no-cache)"
  - Botões: "Abrir pasta" (abre Explorer na pasta do domínio), "Executar"
- Terminal integrado (dark theme, cores):
  - `[CACHE]` → verde-azulado
  - `[ERRO]` → vermelho bold
  - Cabeçalhos `===` / `───` → azul bold
  - `[storage]` → cinza
  - `[auth]` → lilás
  - `Concluído` → verde bold
  - Botão "Limpar"
- Barra de status: "Pronto" + timestamp "Concluído: HH:MM:SS"

**Arquitetura:**
- `gui/runner.py`: `QueueStream` redireciona `sys.stdout` → `queue.Queue`; execução em `threading.Thread` daemon
- `gui/main_window.py`: polling da queue a cada 50ms via `root.after()` (thread-safe)
- `_on_task_done` usa `root.after(0, ...)` para atualizar UI da thread principal

**Validado em execução real:** janela abre, todos controles visíveis, terminal exibe output colorido em tempo real, botão desativa durante execução e reativa ao concluir.

---

## Estrutura atual do projeto

```
gsc-monitor/
  app.py                    ← entry point da GUI
  main.py                   ← CLI: indexação
  posicao.py                ← CLI: posicionamento
  config.py                 ← BASE_DIR centralizado
  requirements.txt          ← dependências Python (versões pinadas)
  requirements-dev.txt      ← deps de desenvolvimento
  setup.ps1 / setup.sh      ← instalação automática do venv
  historico.json            ← snapshots históricos globais (totais)
  core/                     ← lógica de negócio
    auth.py                 ← OAuth2 Google
    cache.py                ← cache JSON por domínio
    storage.py              ← I/O de arquivos (pasta por domínio)
    analytics.py            ← health score, órfãs, canibalização
    classifier.py           ← mapeamento verdict → categoria
    sitemap.py              ← parser de sitemap.xml
  fetchers/                 ← integração com APIs externas
    inspector.py            ← URL Inspection API
    position_fetcher.py     ← Search Analytics API
    knowledge_graph.py      ← Knowledge Graph Search API
    nlp_analyzer.py         ← Cloud Natural Language API
    trends_fetcher.py       ← Google Trends via pytrends
  reporters/                ← geração de saída
    reporter.py             ← relatórios de indexação
    position_reporter.py    ← relatórios de posicionamento
    excel_reporter.py       ← geração de Excel (.xlsx)
    html_reporter.py        ← Dashboard HTML estático
  gui/
    runner.py               ← execução em thread + QueueStream
    main_window.py          ← janela principal Tkinter
  tests/
    test_storage_phase1.py  ← Fase 1 (11 testes — script-based)
    test_cache_phase2.py    ← Fase 2 (9 testes — script-based)
    test_analytics_phase4.py ← Fase 4 (21 testes)
    test_phase5.py          ← Fase 5 (27 testes)
    test_phase6.py          ← Fase 6 (34 testes)
  relatorios/
    {dominio}/              ← arquivos por domínio
      .cache/               ← cache de API
      historico_posicao.json
      YYYY-MM-DD_*.json/csv/xlsx/txt
      dashboard.html
```

---

---

### Fase 4 — Análises novas ✅
**Arquivos criados:** `analytics.py`, `test_analytics_phase4.py`
**Arquivos modificados:** `cache.py`, `storage.py`, `position_fetcher.py`, `excel_reporter.py`, `posicao.py`, `gui/runner.py`, `gui/main_window.py`

**4d — Score de saúde do site:**
- `calculate_health_score(position_report, consolidated=None) -> dict` em `analytics.py`
- Fórmula: `(% indexadas × 0.4) + (score_posição × 0.4) + (ctr_vs_benchmark × 0.2)`
- score_posição: `max(0, 100 − (avg_pos − 1) × 2)` — posição 1 = 100, posição 51+ = 0
- ctr_component: ratio CTR_real / CTR_benchmark por URL na 1ª página (neutro=50 sem 1ª página)
- Se consolidated=None: componente indexação estimado em 50
- Classificação: Crítico (<40) / Regular (40–59) / Bom (60–79) / Excelente (≥80)
- Exibido no terminal (`print_health_score`) e na sheet "Resumo" do Excel
- Indicador visual na barra de status da GUI (colorido por grade)
- Retornado via `result_store` da thread para a GUI

**4a — Detecção de páginas órfãs:**
- `detect_orphan_pages(position_report) -> list[dict]` em `analytics.py`
- URLs com `has_data=False` (zero impressões no período)
- Exibido no terminal (`print_orphan_pages`) e na sheet "Páginas Órfãs" do Excel

**4c — Rastreamento de tendência histórica por URL:**
- `append_historico_posicao(site, date, period, rows)` e `load_historico_posicao(site)` em `storage.py`
- Arquivo `relatorios/{dominio}/historico_posicao.json` — mantém até 30 snapshots
- Estrutura: `{"site", "snapshots": [{"date", "period", "urls": {url: {position, clicks, impressions}}}]}`
- Deduplicação por data; só URLs com `has_data=True` são salvas
- Sheet "Histórico" no Excel com cores por faixa e coluna "Tendência" (↑↓→)
- `load_latest_consolidated(site)` em `storage.py` — carrega indexação mais recente do disco

**4b — Análise de canibalização de keywords:**
- `fetch_query_positions(service, domain, use_cache=True)` em `position_fetcher.py`
  - Dimensões `["query", "page"]` — cache separado: `posicao_queries_{start}_{end}.json` (TTL 72h)
- `detect_cannibalization(query_rows) -> list[dict]` em `analytics.py`
- `get_query_cache / set_query_cache` em `cache.py`
- Flag `--queries` em `posicao.py`; checkbox "Canibalização (queries)" na GUI
- Sheet "Canibalização" no Excel com grupos coloridos por keyword

**Testes:** `test_analytics_phase4.py` — 21/21 testes passaram

---

---

### Fase 5 — Novas APIs Google ✅
**Arquivos criados:** `knowledge_graph.py`, `trends_fetcher.py`, `nlp_analyzer.py`, `test_phase5.py`
**Arquivos modificados:** `excel_reporter.py`, `posicao.py`, `gui/runner.py`, `gui/main_window.py`, `requirements.txt`

**5a — Knowledge Graph Search API:**
- `knowledge_graph.py`: `search_entity(domain, api_key=None, use_cache=True) -> dict | None`
- Extrai marca do domínio (ex: `www.exemplo.com.br` → `Exemplo`) e busca entidade no KG
- Retorna: found, name, types, description, detailed_desc, kg_id, score, url
- Cache: `relatorios/{domain}/.cache/knowledge_graph.json` — TTL 7 dias
- API key: env `GOOGLE_API_KEY` ou arquivo `google_api_key.txt`
- Se API key ausente: skip silencioso com aviso no terminal
- Seção "Knowledge Graph" adicionada ao Excel sheet "Resumo"
- Roda sempre que API key estiver disponível (sem flag explícita)

**5b — pytrends (Google Trends):**
- `trends_fetcher.py`: `fetch_trends(keywords, site, geo="BR", use_cache=True) -> dict`
- Extrai top keywords por `top_keywords_from_queries(query_rows, max_kw=10)` (posição ≤ 10, ordenado por impressões)
- Tendência calculada: média 3 primeiros meses vs. 3 últimos → "rising"/"stable"/"declining"
- Cache por keyword+geo, TTL 24h; delay 1.5s entre keywords (anti-rate-limit)
- `PYTRENDS_AVAILABLE = False` se não instalado → skip com instrução de install
- Flag `--trends` em `posicao.py` (implica busca de queries se não já feita)
- Checkbox "Tendências" na GUI
- Nova sheet "Trends" no Excel com cores (verde/amarelo/vermelho)

**5c — Natural Language API (annotateText):**
- `nlp_analyzer.py`: `analyze_opportunity_urls(rows, site, api_key=None, use_cache=True) -> dict`
- Filtra posição 4–10, ordena por impressões, analisa até 5 URLs mais relevantes
- Fetch de HTML + remoção de tags + truncado a 1000 chars
- Usa `annotateText` com `extractEntities + classifyText` em chamada única — 2 unidades NLP por URL
  - Fallback para `analyzeEntities` apenas se classifyText falhar por texto insuficiente (1 unidade)
- Retorna `{url: {"entities": [...], "categories": [...]}}` com saliência e confidence respectivamente
- Ignora tipos numéricos (NUMBER, PRICE, DATE, ADDRESS, PHONE_NUMBER) nas entidades
- `categories` seguem a taxonomia Google/IAB (ex: `/Business & Industrial/Industrial Materials & Equipment`)
- Cache por URL com prefixo `nlp2_`, TTL 72h
- Flag `--nlp` em `posicao.py` (opt-in para preservar cota)
- Checkbox "NLP entidades" na GUI
- Sheet "Oportunidades CTR": colunas "Entidades Principais" + "Categoria NLP"
- Dashboard HTML: seção "🧠 Análise NLP" com pills de categorias e barras de saliência por URL

**GUI — novos controles:**
- Opções row: checkboxes "Canibalização", "Tendências", "NLP entidades"
- API Key row: campo de texto (lê/salva `google_api_key.txt`)

**Testes:** `test_phase5.py` — 27/27 testes passaram (inclui TestNlpParsers com 6 testes de _parse_entities/_parse_categories)

---

---

### Fase 6 — Dashboard HTML estático ✅
**Arquivo criado:** `html_reporter.py`, `test_phase6.py`
**Arquivos modificados:** `storage.py` (`save_dashboard`), `posicao.py`, `gui/runner.py`, `gui/main_window.py`

**Dashboard:**
- `relatorios/{dominio}/dashboard.html` — autocontido (CSS embutido) com Chart.js via CDN jsDelivr
- Seções dinâmicas: Saúde do Site · Posicionamento · Indexação · Knowledge Graph · Histórico · Trends · Canibalização · Páginas Órfãs
- Gráficos interativos (barras horizontais, doughnut, linhas, barras) via `<canvas>` + Chart.js
- Nav bar sticky com links apenas para seções presentes
- Gerado automaticamente ao final de toda execução de posicionamento (CLI e GUI)
- `save_dashboard(site, html)` em `storage.py` — sempre sobrescreve o arquivo único por domínio

**GUI:**
- Botão "Dashboard" abre `dashboard.html` no navegador padrão via `webbrowser.open()`
- Usa `result_store["dashboard_path"]` (caminho da última execução) ou calcula o caminho a partir do domínio digitado

**Testes:** `test_phase6.py` — 34/34 testes passaram
**Total acumulado:** 11+9 (F1-F2, script) + 21 (F4) + 27 (F5) + 34 (F6) = 102 testes
`py -m unittest discover` → 82 testes (F4 + F5 + F6, unittest-based)

---

## Projeto Completo

## Dependências instaladas
```
google-auth>=2.29.0
google-auth-httplib2>=0.2.0
google-auth-oauthlib>=1.2.0
google-api-python-client>=2.126.0
requests>=2.31.0
openpyxl>=3.1.0
```
`openpyxl` estava no requirements.txt mas não instalado — já instalado via `pip install openpyxl`.

---

## Notas de uso

1. **Testar com `--limit 5`** ao usar `main.py` para não consumir cota da URL Inspection API (2000/dia)
2. **`posicao.py` não tem `--limit`** — usa todos do sitemap (Search Analytics API não tem cota restritiva)
3. **Cache está ativo por padrão** — usar `--no-cache` para forçar dados frescos da API
4. **Domínios de teste disponíveis:** `www.exemplo.com.br`, `www.exemplo.com`, `www.exemplo.com`
5. **`token.json`** está presente — OAuth já autenticado, não precisa login no browser
6. **Flags do `posicao.py`:** `--queries` (canibalização), `--trends` (pytrends), `--nlp` (entidades), `--api-key KEY`
7. **Score de saúde:** aparece no terminal após execução do posicionamento; na GUI fica na barra de status
8. **Sheet "Histórico" no Excel / seção Histórico no Dashboard** só aparece a partir da 2ª execução (≥2 snapshots)
9. **API key Google Cloud:** env `GOOGLE_API_KEY` ou arquivo `google_api_key.txt` ou campo na GUI
10. **pytrends:** requer `pip install pytrends`; sem ela `--trends` imprime instrução e pula
11. **Dashboard HTML:** gerado automaticamente em `relatorios/{dominio}/dashboard.html` a cada execução de posicionamento; botão "Dashboard" na GUI abre no navegador
12. **Rodar todos os testes:** `py -m unittest discover -s tests -t .` (82 tests, F4+F5+F6) ou individualmente: `py tests/test_storage_phase1.py`, `py tests/test_cache_phase2.py`
