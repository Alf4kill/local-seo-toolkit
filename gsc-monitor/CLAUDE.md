# CLAUDE.md — GSC Monitor

Guia para sessões do Claude Code neste projeto. Leia também `PROGRESSO.md` (log
por fase) e `README.md` (setup do usuário). Código, comentários e relatórios são
em **português**; este guia mistura PT/EN.

---

## 1. O que é o projeto

Ferramenta **desktop local** de análise do Google Search Console para múltiplos
domínios. Cruza o sitemap do site com a Search Analytics API e produz:
- relatório de **posicionamento** por URL (CLI `posicao.py`),
- relatório de **indexação** (CLI `main.py`, URL Inspection API),
- **Excel** (várias abas) + **dashboard HTML** (Chart.js) + CSV/TXT,
- análises: health score, canibalização, páginas sem impressões, Knowledge
  Graph, Google Trends, NLP de entidades e **qualidade de conteúdo**.

Stack: Python 3.13, Tkinter (GUI), openpyxl, google-api-python-client, requests,
pytrends (opcional). Sem framework web — tudo roda local.

### Por que existe (contexto do dono)
O usuário trabalha numa empresa de SEO que cria sites do zero com foco em
artigos por keyword (tem acesso a 100+ sites; testa em poucos). Objetivos:
**crescimento pessoal** + **portfólio/credibilidade de carreira**. **Não é
comercial.** O grande tema é usar **PLN/NLP para diagnosticar over-optimization
e conteúdo raso** ("keyword-heavy") que os core updates recentes do Google
penalizam — e medir empiricamente se otimizar ajuda.

### Restrições que guiam decisões (IMPORTANTES)
- **Local-only, permanente.** Não rodar no servidor da empresa (um projeto PHP
  anterior derrubou o painel Plesk; o Python do servidor é antigo e congelado).
  Como roda local (Python 3.13), o Python do servidor é irrelevante.
- **APIs pagas estão FORA** — inclui a **Claude API**. Só free tiers (GSC,
  Knowledge Graph, Cloud NLP free 5.000 un./mês) ou processamento local. Nada de
  "insights gerados por LLM" — vereditos são **rule-based**.
- O gargalo real **não é RAM** (8 GB sobra): são **cotas de API** (URL Inspection
  2.000/dia, NLP 5.000 un./mês) e o rate-limit do pytrends.
- **Honestidade analítica acima de tudo.** A prioridade nº1 do usuário foi
  corrigir "bugs e confident but wrong assessments". Nunca apresente heurística
  como certeza. A Cloud NLP API ≠ algoritmo de ranking do Google.

---

## 2. Como rodar

```powershell
# Setup (1ª vez) — cria .venv e instala deps
.\setup.ps1                          # Windows  (setup.sh no Linux/Mac)

# GUI
py app.py

# CLI posicionamento (flags combináveis)
py posicao.py --site www.exemplo.com.br --excel --queries --content --nlp
#   --queries   canibalização        --trends   Google Trends (pytrends)
#   --content   qualidade de conteúdo (Move 1)  --nlp  entidades NLP (cota)
#   --csv --txt --no-cache --api-key KEY

# CLI indexação (cuidado com a cota 2.000/dia — use --limit ao testar)
py main.py --site www.exemplo.com.br --limit 10

# Testes  (154 testes; rode da pasta gsc-monitor/)
py -m pytest
```

**Credenciais:** `client_secrets.json` (OAuth desktop) + `token.json` (gerado;
refresh automático silencioso — ver `core/auth.py`). API key Google (KG/NLP) em
`google_api_key.txt` ou env `GOOGLE_API_KEY`. Todos gitignored.

**Domínios de teste:** `www.exemplo.com` (foco atual), `www.exemplo.com.br`,
`www.exemplo.com`.

---

## 3. Arquitetura

```
core/        lógica pura (sem rede/IO quando possível)
  auth.py            OAuth2 GSC (refresh silencioso)
  cache.py           cache JSON por domínio em relatorios/{dom}/.cache/
  storage.py         IO de arquivos, historico_posicao.json
  sitemap.py         fetch/parse de sitemap.xml (+ robots fallback)
  classifier.py      verdict da inspeção → categoria
  analytics.py       health score, canibalização, páginas sem impressões
  content_quality.py [Move 1/2] analyzer puro + build_content_tracking
fetchers/    integração com APIs externas (IO)
  position_fetcher.py  Search Analytics (page; query+page)
  inspector.py         URL Inspection
  knowledge_graph.py   KG Search (com guard de falso positivo)
  nlp_analyzer.py      Cloud NL (annotateText) + _fetch_page_text
  trends_fetcher.py    pytrends (FRÁGIL — opcional)
  content_fetcher.py   [Move 1] orquestra qualidade de conteúdo (+ cache de texto)
reporters/   geração de saída
  position_reporter.py / reporter.py   relatórios
  excel_reporter.py    Excel (openpyxl)
  html_reporter.py     dashboard HTML (Chart.js via CDN)
  nlp_report_generator.py
gui/         main_window.py (Tkinter) + runner.py (thread + QueueStream)
```

Fluxo posição: `auth → sitemap → fetch_positions → build_report → analytics →
content_quality → reports (excel/html/csv)`. O **dashboard é regenerado a cada
run**; `historico_posicao.json` acumula até 30 snapshots por domínio.

### Conceitos-chave
- **Health score (0–100)** = `indexação×0.4 + posição×0.4 + ctr×0.2`. A posição é
  **ponderada por impressões** (reflete onde o tráfego ranqueia). Sem indexação,
  os pesos são **re-normalizados** para Posição/CTR (0.667/0.333) — nunca presume
  50. Grades: Excelente ≥80, Bom ≥60, Regular ≥40, Crítico <40. **O valor está na
  decomposição, não no número composto** (ex.: exemplo 70.7 "Bom" mas CTR
  8.7/100 = o problema real).
- **Canibalização** só conta URLs que competem de fato (`impressões≥10`,
  `posição≤30`); campo `severity` alta/média/baixa por impressões em disputa.
- **Qualidade de conteúdo** (`content_quality.py`): sinais LOCAIS sem cota
  (word_count, keyword_density, exact_repetitions, vocab_diversity) + sinais NLP
  opcionais (salience_concentration, entity_count, classified, target_in_salient).
  Veredito conservador: `ok / atencao / over_otimizado / raso`. Keyword-alvo vem
  das queries reais do GSC (`target_keywords_for_url`).
- **Loop de medição (Move 2)**: cada snapshot guarda também as métricas de
  conteúdo; `build_content_tracking` cruza posição × veredito ao longo do tempo
  (Δ desde o baseline). É como se responde "PLN ajuda?".

---

## 4. Convenções e armadilhas

- **stdout UTF-8:** `posicao.py` faz `sys.stdout.reconfigure(utf-8)`; a GUI usa
  `QueueStream(encoding="utf-8")`. Funções `print_*` usam Unicode (─, ✓, ⚠)
  livremente. **MAS** código de biblioteca chamado fora desses entry points pode
  quebrar em console cp1252 — em prints de fluxo use texto ASCII (ex.:
  `content_fetcher` imprime `verdict`, não `verdict_label` com emoji). Emojis só
  nos artefatos (HTML/Excel).
- **HTML sempre escapado:** todo texto externo (entidades, KG, queries, URLs) no
  dashboard passa por `html.escape()`. Mantenha isso ao adicionar seções.
- **Cache por domínio** em `relatorios/{dom}/.cache/`: posição 72h, queries 72h,
  inspect 24h, KG 7d, NLP 72h (`nlp2_`), trends 24h, **texto 72h** (`text_`).
  `--no-cache` força fresco. Erros de API nunca são cacheados.
- **Reports são opcionais e degradam bem:** cada seção só aparece se houver dado.
  Ao adicionar parâmetro a `generate_dashboard`/`generate_excel`, propague em
  `posicao.py` E `gui/runner.py` (dois call sites).
- **Testes que afirmam comportamento antigo** devem ser atualizados junto com a
  mudança (não silenciados). Rode a suíte após cada bloco de edição.
- **pytrends é não-oficial e quebra** — trate sempre como opcional e isolado.

---

## 5. O que foi feito nesta sessão (2026-06-02) e por quê

Auditoria inicial + 3 "Moves". Suíte foi de 82 → **104 testes**, todos passando.

### Move 0 — Correções de "confident but wrong" (POR QUÊ: prioridade nº1; base de credibilidade)
- **"Páginas Órfãs" → "Páginas sem impressões"**: o código nunca detectou órfãs
  reais (sem links internos), e sim URLs com 0 impressões. Nome estava mentindo.
- **`html.escape` no dashboard**: texto externo era injetado cru (render quebrado/
  injeção).
- **Canibalização com threshold + `severity`**: antes qualquer query com 2+ URLs
  virava "canibalização" (muito falso positivo).
- **Health score ponderado por impressões** + fim do "50 fixo" quando não há
  indexação (re-normalização honesta).

### Move 1 — Analyzer de Qualidade de Conteúdo (POR QUÊ: o objetivo central — PLN p/ over-optimization/conteúdo raso)
- `core/content_quality.py` (puro, testado) + `fetchers/content_fetcher.py`
  (orquestra: baixa texto com cache próprio, sem cota; reusa
  `nlp_analyzer._fetch_page_text`). Detecta stuffing e thin content.
- Integrado: flag `--content`, checkbox "Qualidade conteúdo" na GUI, seção 🧪 no
  dashboard, aba "Qualidade Conteúdo" no Excel.
- Validado em páginas reais (exemplo): pegou densidade 4–7% e veredito
  correto. NLP **enriquece** (com `--nlp`, vários ok→atencao).

### Move 2 — Loop de medição (POR QUÊ: responder empiricamente "PLN ajuda?" + virar história de portfólio)
- `historico_posicao` agora grava as métricas de conteúdo por snapshot;
  `build_content_tracking` cruza conteúdo × posição (Δ desde baseline). Seção 📓
  "Acompanhamento" no dashboard + `print_content_tracking` no terminal.

### Caso real — exemplo (foco do usuário)
Site é **doorway pages**: 295 URLs, **122 grupos de canibalização** (até 8 URLs
pela mesma keyword, ex.: "cane corso preço"). Indexa e ranqueia, mas **CTR
catastrófico** (páginas de preço: 11k impressões → 10 cliques). Queda de tráfego
no fim de março = provável core update. **Recomendação: consolidar as dezenas de
páginas-permutação em poucas páginas fortes (301)** e medir a recuperação via o
loop do Move 2. Baseline de 8 URLs gravado em 2026-06-02.

---

## 6. Opções de refino e upgrade (próximos passos)

### Quick wins (baixo esforço, alto valor)
- **Densidade vs keyword do slug / n-grama mais repetido.** Hoje a densidade usa
  a query natural do GSC, então páginas otimizadas para o slug aparecem com 0%
  (falsa sensação de "limpo"). Medir também contra o slug e o n-grama dominante.
- **Alertas por componente do health score.** O composto "Bom" mascarou o CTR
  8.7/100 da exemplo. Emitir alerta quando 1 componente é crítico mesmo com
  score geral ok.
- **`severity`/tracking no Excel.** O acompanhamento (Move 2) só está no dashboard
  e terminal; falta uma aba no Excel.

### Médio
- **Trend first-party via dimensão `date` do GSC** (substituir pytrends): oficial,
  free, sem rate-limit, mais relevante que o Trends global. Recomendado.
- **Limpeza de NLP agnóstica a template.** `nlp_analyzer._NOISE_SECTION_CLASSES`
  é hardcoded para o template de OUTRA empresa (site em `E:\projetos\site-exemplo`);
  não generaliza para os 100+ sites. Mover para config por-site + fallback
  genérico de extração por legibilidade.
- **Opção spaCy local** (pt_core_news) como alternativa 100% offline ao Cloud NLP
  (sem cota) — manter a camada de entidades plugável.
- **Sugestão automática de consolidação** na canibalização (escolher a URL
  canônica por cliques/posição e listar as a redirecionar).
- **Testes para caminhos de IO** (OAuth, sitemap aninhado/robots, render de
  Excel/HTML) — hoje os testes cobrem só lógica pura.

### Maior / estratégico (só se mudar de direção)
- **Detecção de órfãs REAL** (crawl de links internos × sitemap) — a feature de
  verdade por trás do nome antigo.
- **Logging estruturado** em vez de `print` scrapeado por string na GUI.
- **GUI: barra de progresso + cancelar** (o `(idx/total)` já é emitido).
- **Config central** para constantes hardcoded (DAYS_BACK, geo="BR", benchmarks
  de CTR, thresholds de canibalização/conteúdo).
- **Batch multi-domínio / modo headless** — só se um dia for escalar (Direction B
  do plano estratégico). Hoje a direção é **A: aprofundar a ferramenta local**.

> Regra ao evoluir: corrigir correção/honestidade antes de adicionar features;
> manter tudo em free tier / local; rodar `py -m pytest`
> após cada mudança.
