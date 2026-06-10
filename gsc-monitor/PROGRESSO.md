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

### P1 — Modo batch headless (snapshots agendados) ✅ (2026-06-09)
**Arquivos criados:** `core/batch.py`, `sites.example.txt`, `tests/test_batch.py`
**Arquivos modificados:** `posicao.py`, `README.md`, `CLAUDE.md`, `.gitignore`

**Mudanças:**
- Pipeline de `posicao.py` extraído para `run_pipeline(site, **opções)` —
  mesmo fluxo do CLI, mas levanta `PipelineError` em vez de `sys.exit` e
  retorna resumo (health, posição média, CTR, canibalização, vereditos de
  conteúdo, nº de snapshots). CLI single-site inalterado.
- `py posicao.py --batch sites.txt`: roda o pipeline padrão (posições +
  queries + qualidade de conteúdo, cache-aware, sem GUI) para cada domínio do
  arquivo, sequencialmente. Erro em um site **não aborta** o lote; linha-resumo
  ASCII por site (health + grade + snapshots) e recap ao final.
- `--batch-report`: CSV consolidado em `relatorios/_batch/YYYY-MM-DD_resumo.csv`
  (site, status, health, grade, posição média, CTR, grupos de canibalização,
  contagem de vereditos ok/atenção/over/raso, snapshots, erro). utf-8-sig.
- `sites.txt` no `.gitignore` (domínios reais); modelo em `sites.example.txt`
  (um domínio/linha, `#` comenta, inline também).
- README: seção batch + one-liner do Windows Task Scheduler para snapshots
  semanais automáticos (alimenta o loop de medição do Move 2 sem runs manuais).

**Por quê:** o loop de medição (Move 2) só responde "PLN ajuda?" se houver
snapshots acumulando consistentemente — o batch agendado remove a dependência
de lembrar de rodar manualmente.

**Testes:** `tests/test_batch.py` — 18/18 (orquestrador puro, pipeline mockado)
`py -m unittest discover` → **122 testes OK**

---

### P2 — Plano de consolidação 301 (executor da recomendação) ✅ (2026-06-09)
**Arquivos criados:** `tests/test_consolidation.py`
**Arquivos modificados:** `core/analytics.py`, `core/storage.py`,
`reporters/excel_reporter.py`, `reporters/html_reporter.py`, `posicao.py`,
`gui/runner.py`, `README.md`, `CLAUDE.md`

**Mudanças:**
- `build_consolidation_plan(cannibalization)` em `core/analytics.py` (puro):
  para cada grupo, escolhe a URL canônica (**cliques desc → posição asc →
  impressões desc**) e lista as demais como origens de redirect 301.
- Resolução de conflitos entre grupos (URL em vários grupos): prioridade por
  severidade; canônica nunca vira origem; origem não recebe segundo destino;
  sem cadeias/ciclos por construção. Conflitos registrados e exibidos.
- Artefatos por execução (quando há canibalização): `YYYY-MM-DD_redirects.csv`
  (from_url, to_url, keyword, severity, clicks_from, clicks_to),
  `*_redirects_apache.txt` (bloco `Redirect 301` p/ .htaccess) e
  `*_redirects_nginx.txt` (bloco `location = ... return 301`). Configs em
  ASCII puro (keywords com acento são normalizadas nos comentários).
- **Regra de honestidade:** todos os outputs (CSV, txt, Excel, dashboard,
  terminal) marcam o plano como SUGESTÃO com aviso de revisão humana.
- Sheet "Plano 301" no Excel + seção 🔀 no dashboard (escapada, degrada bem).
- Parâmetros propagados aos DOIS call sites (`posicao.py` e `gui/runner.py`).

**Por quê:** a recomendação de consolidar a canilmansur (122 grupos) existia
só como diagnóstico. Com o artefato executável, a intervenção do experimento
antes/depois (P12) pode ser aplicada em produção diretamente.

**Testes:** `tests/test_consolidation.py` — 21/21: ordenação da canônica,
conflitos, formatos de arquivo, escape de HTML, sheet Excel.
`py -m unittest discover` → **143 testes OK**

---

### P3 — Densidade vs slug e n-grama dominante ✅ (2026-06-09)
**Arquivos modificados:** `core/content_quality.py`, `fetchers/content_fetcher.py`,
`reporters/excel_reporter.py`, `reporters/html_reporter.py`,
`tests/test_content_quality.py`, `README.md`, `CLAUDE.md`

**Problema (honestidade analítica):** a densidade usava só a query natural do
GSC. Página otimizada para o slug, sem query correspondente, reportava 0% de
densidade e recebia veredito **falsamente limpo** — minando a promessa central
do projeto (detectar over-optimization de verdade).

**Mudanças:**
- `keyword_density` reportada agora é o **máximo entre 3 fontes**:
  (a) queries reais do GSC; (b) `slug_phrase(url)` — slug → frase, split em
  `-`/`_`, remove stopwords pt-BR e números, casa com texto acentuado
  ("preco" ↔ "preço"); (c) `dominant_ngram(text)` — n-grama 2–3 mais repetido,
  piso de 4 ocorrências, bordas não podem ser stopword, acentos agrupados.
- Novo campo `density_source` (`query`/`slug`/`ngram`); empates priorizam
  query > slug > n-grama. As **reasons citam o gatilho**:
  `Gatilho: "cane corso preco" (slug da URL, 12.4%)`.
- `analyze_content_quality` ganhou parâmetro opcional `url` (retrocompatível);
  `content_fetcher` repassa a URL analisada.
- Excel: coluna "Keyword-alvo" → "Keyword gatilho (fonte)". Dashboard: linha de
  densidade mostra keyword + fonte. Terminal idem.
- **Thresholds inalterados** — veredito continua conservador; 1 flag de
  densidade isolada ainda é só "atenção".

**Testes:** +13 novos (slug_phrase, dominant_ngram, fontes de densidade,
caso slug-stuffed sem query GSC ≠ ok, página limpa continua ok, gatilho nas
reasons); 1 teste existente atualizado (`test_sem_keyword_alvo` — o
comportamento antigo de 0% era exatamente o bug corrigido).
`py -m unittest discover` → **156 testes OK**

---

### P4 — Alertas por componente do health score ✅ (2026-06-09)
**Arquivos modificados:** `core/analytics.py`, `reporters/excel_reporter.py`,
`reporters/html_reporter.py`, `gui/main_window.py`,
`tests/test_analytics_phase4.py`, `README.md`, `CLAUDE.md`

**Problema (honestidade analítica):** o score composto mascara componente
crítico — caso real: canilmansur 70.7 "Bom" com CTR 8.7/100. O número único
escondia exatamente o problema que importava.

**Mudanças:**
- `build_component_alerts(components)` em `core/analytics.py`: componente
  < 40 gera alerta `{component, label, value, severity, message}`; severidade
  **critico** (< 20) ou **alto** (20–39.9); mensagem de 1 linha em pt-BR
  explicando o que significa (sem jargão). Componente sem dados (indexação
  None) não alerta. Incluído no retorno de `calculate_health_score` como
  `component_alerts`.
- **O composto NUNCA é suprimido** — score geral e alertas aparecem juntos em
  todas as superfícies: terminal (`print_health_score`, bloco `[ALERTA ...]`),
  GUI (badge vermelho na status bar ao lado do score), Excel (linhas
  destacadas na seção Saúde da sheet "Resumo"; seção KG reposicionada
  dinamicamente) e dashboard (caixa vermelha na seção 🏥 Saúde).

**Testes:** +6 — composto "Excelente" com CTR crítico DEVE alertar (o caso
canilmansur sintético); tudo-bom NÃO alerta; indexação None não vira alerta;
severidades; mensagens citam o valor. `test_estrutura_retorno` atualizado.
`py -m unittest discover` → **162 testes OK**

---

### P5 — Tendências first-party via dimensão `date` do GSC ✅ (2026-06-10)
**Arquivos criados:** `tests/test_date_trends.py`
**Arquivos modificados:** `core/cache.py`, `core/analytics.py`,
`fetchers/position_fetcher.py`, `posicao.py`, `gui/runner.py`,
`reporters/html_reporter.py`, `reporters/excel_reporter.py`, `README.md`,
`CLAUDE.md`

**Por quê:** o pytrends é não-oficial, frágil (rate-limit, quebras de API) e
mede o índice GLOBAL 0–100 do Google Trends — não a demanda do próprio site.
A dimensão `date` da Search Analytics é oficial, free, sem rate-limit e
específica do site.

**Mudanças:**
- `fetch_date_trends` (`position_fetcher.py`): 2 consultas — dimensões
  `[date]` (site inteiro) e `[date, query]` — últimos 90 dias, dataState
  final. Cache `date_trends_{start}_{end}.json`, **TTL 24h** (`core/cache.py`).
- `compute_date_trends` (`core/analytics.py`, pura): tendência por
  **1º terço vs último terço** das impressões/dia (≥115% rising, ≤85%
  declining, senão stable; < 6 dias = stable; < 14 dias com dados = sparse).
  Primeira entrada é sempre `SITE_TREND_KEY` (domínio inteiro); demais são as
  top-10 queries por impressões. Dias sem linha na API contam como 0. Shape
  compatível com as superfícies existentes de Trends (`trend/peak/latest/
  values/sparse`) + campos `source/metric/first_avg/last_avg`.
- `--trends` agora usa GSC **por padrão**; `--trends-source pytrends` mantém o
  caminho legado. Propagado aos dois call sites (`posicao.py`, `gui/runner.py`).
- Dashboard: gráfico de **linha** com as séries diárias (site + top 5 queries)
  quando a fonte é GSC; barras 0–100 continuam para o legado. Rótulos honestos
  por fonte na seção, no Excel ("Tendências de demanda — GSC (90 dias)",
  "Pico (impr./dia)", "Média recente") e no terminal (`print_date_trends`).

**Testes:** `tests/test_date_trends.py` — 19/19: classificação por terços,
top_n, datas faltantes = 0, sparse, eixo de datas, parsing com service
mockado, corpos das 2 chamadas, cache hit evita API, chart line vs bar.
`py -m unittest discover` → **181 testes OK**

---

### Bugfix — NENHUM gráfico do dashboard renderizava no navegador ✅ (2026-06-10)
**Arquivo modificado:** `reporters/html_reporter.py` (+2 testes em `tests/test_date_trends.py`)

**Sintoma (reportado no dashboard real da canilmansur):** seções "Histórico de
Posicionamento" e "Tendências" com a área do gráfico vazia — na verdade,
**todos** os 4 gráficos (posição, indexação, histórico, trends) nunca
renderizaram em nenhum navegador, desde a Fase 6.

**Causa:** as constantes do Chart.js são declaradas com `const` no escopo
global do script, e `const` **não cria propriedade em `window`** — então
guards como `if (window.HIST_DATA && ...)` eram sempre `undefined`/falsos e
nenhum `new Chart()` executava. Os testes da Fase 6 validavam o HTML como
string em Python; o JS nunca tinha sido executado de fato.

**Correção:** guards passam a referenciar as constantes diretamente
(`if (POS_DATA)`, `if (HIST_DATA && ...)` etc. — sempre declaradas, valem
`null` sem dados). Validado executando o script do dashboard real no Node com
stub do Chart.js: os 4 gráficos instanciam (histórico com 8 séries, trends
com 6 linhas). Regressão: testes garantem que `_JS` não contém `window.X`.
`py -m unittest discover` → **183 testes OK**

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
