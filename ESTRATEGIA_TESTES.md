# Estratégia de Testes — local-seo-toolkit

Documento de avaliação da bateria de testes (`gsc-monitor` e `semantic-analyzer`):
estado atual, lacunas de cobertura, recomendações de estratégia e o que foi
melhorado nesta passagem. Foco em **honestidade analítica** — o objetivo nº1 do
projeto: travar contratos que, se quebrarem, geram "confident but wrong
assessments".

Data: 2026-06-06

---

## 1. Resumo executivo

A bateria já era boa — testes pensados, dados sintéticos realistas, sem rede.
O problema **não era qualidade dos testes existentes, e sim**:

1. **Três estilos de runner no mesmo projeto** (`unittest`, `pytest`,
   runner-print caseiro) — confunde quem roda e impede um comando único.
2. **Lacunas em funções puras críticas** que decidem veredito/indexação e
   estavam sem nenhum teste.
3. **Testes escreviam na pasta real `relatorios/`** e dependiam de limpeza
   manual — frágil e poluía o repositório.

Tudo isso foi corrigido nesta passagem. Resultado:

| Projeto            | Antes            | Agora            |
|--------------------|------------------|------------------|
| gsc-monitor        | 110 testes (+9 erros de limpeza) | **154 testes, 0 erros** |
| semantic-analyzer  | 36 testes        | **80 testes**    |

Comando único agora: `py -m pytest` em cada pasta (config em `pytest.ini`).

---

## 2. Estado atual — mapa de cobertura

### gsc-monitor (Search Console)

| Módulo | Cobertura antes | Status |
|---|---|---|
| `core/storage.py` | parcial (runner-print) | OK |
| `core/cache.py` | bom (pytest) | OK |
| `core/analytics.py` (health score, canibalização, órfãs) | bom | OK |
| `core/content_quality.py` (Move 1 — NLP/over-optimization) | **excelente** | OK |
| `reporters/html_reporter.py` (dashboard) | bom | OK |
| `reporters/excel_reporter.py` | parcial | OK |
| `fetchers/knowledge_graph.py`, `trends_fetcher.py` | bom | OK |
| **`core/classifier.py`** (verdict → categoria) | **ZERO** | ✅ adicionado |
| **`core/sitemap.py`** (parse de sitemap) | **ZERO** | ✅ adicionado (parse) |
| **`fetchers/position_fetcher.py`** (helpers de URL/data) | **ZERO** | ✅ adicionado (puros) |
| `core/auth.py` (OAuth) | ZERO | ainda aberto (ver §5) |
| `fetchers/inspector.py`, `nlp_analyzer.py` | parcial/rede | ainda aberto |
| `gui/*` (Tkinter) | ZERO | fora de escopo (ver §5) |

### semantic-analyzer

| Módulo | Cobertura antes | Status |
|---|---|---|
| `core/clusterer.py`, `dedup.py`, `embedder.py` (cache) | bom | OK |
| `core/gsc_link.py`, `hybrid.py`, `llm.py`, `loaders.py` | bom | OK |
| **`core/report.py`** (365 linhas — gera o HTML do plano) | **ZERO** | ✅ adicionado |

---

## 3. Pirâmide de testes — onde cada coisa deve viver

```
        /   E2E    \      Poucos, lentos: rodar a CLI real contra 1 domínio
       / Integração  \    Alguns: fetch + cache + storage juntos (com mocks de rede)
      /  Unitários     \  Muitos, rápidos: funções puras (parse, score, formatação)
```

Princípio para ESTES projetos (cota de API é o gargalo, não RAM):

- **Nunca** gastar cota de API num teste. Toda chamada de rede é **mockada**.
  Os testes existentes já fazem isso bem (FakeClient, monkeypatch de `_get`,
  `_fetch_page_text`); manter essa disciplina.
- **Funções puras primeiro.** São baratas, rápidas e cobrem a lógica onde os
  bugs de "confident but wrong" nascem (mapeamento de verdict, densidade de
  keyword, faixa de posição, normalização de domínio p/ chave de cache).
- **Integração com mocks** para o caminho fetch → cache → storage (1 nível
  acima do unitário). Já há base disso no `content_quality` (orquestrador
  mockado) e no `cache_phase2`.
- **1 teste E2E manual** documentado (não automatizado, pois consome cota):
  rodar `posicao.py --site <dominio-de-teste> --content` e conferir que o
  dashboard sai. Está nas notas do `PROGRESSO.md`; vale formalizar como
  checklist de release.

---

## 4. O que foi adicionado nesta passagem

### Infraestrutura (ambos os projetos)
- **`pytest.ini`** — um comando para tudo: `py -m pytest`.
- **`conftest.py`** — coloca a raiz no `sys.path` (elimina o bloco
  `sys.path.insert(...)` repetido em todo teste) e, no gsc-monitor, **isola
  `RELATORIOS_DIR` num diretório temporário** durante a sessão. Isso resolve
  os 9 erros de limpeza e garante que os testes nunca tocam a pasta real
  `relatorios/`.

### gsc-monitor — novos testes
- `tests/test_classifier.py` — mapeamento verdict→categoria, fallback seguro
  para valores desconhecidos da API, case-sensitivity, e guarda que o
  vocabulário interno não vaze.
- `tests/test_sitemap.py` — parse de `urlset` vs `sitemapindex`, namespace,
  `<loc>` com espaços, XML quebrado (não crasha), e extração de `Sitemap:` do
  robots.txt — tudo offline.
- `tests/test_position_fetcher.py` — `_build_site_url`, `_normalize_domain`
  (incluindo a invariante crítica: `https://x/` e `sc-domain:x` geram a MESMA
  chave de cache) e `_build_date_range` (janela e delay de 3 dias do GSC).

### semantic-analyzer — novos testes
- `tests/test_report.py` — geradores de HTML (`_llm_html`, `_diff_html`,
  `_collisions_html`, `generate_html`): **escape de HTML/XSS**, blocos opcionais
  que somem quando vazios, marcação da página canônica, limite de 5 lacunas,
  formatação de milhar nas impressões.

---

## 5. Lacunas que permanecem (prioridade decrescente)

1. **`fetchers/nlp_analyzer.py` e `inspector.py`** — têm lógica de parsing da
   resposta da API (entidades, salience, categorias) que pode ser testada com
   payloads-fixture mockados, sem gastar cota. **Alto valor**, pois alimentam
   o veredito de qualidade de conteúdo. Recomendado próximo.
2. **`core/auth.py`** — OAuth é chato mas o caminho de erro (token expirado,
   arquivo ausente) merece 2-3 testes com mock de `Credentials`.
3. **`reporters/position_reporter.py` / `nlp_report_generator.py`** — se
   geram texto/Excel, vale um teste de smoke como o do `excel_reporter`.
4. **GUI (`gui/*`, Tkinter)** — baixo ROI para testes automatizados; manter
   como verificação manual no checklist de release.
5. **Teste de propriedade (opcional)** — `keyword_density` e
   `salience_concentration` são ótimos candidatos a `hypothesis`
   (ex.: densidade sempre entre 0 e 100; nunca lança em texto arbitrário).

---

## 6. Conteúdo a melhorar nos testes existentes

- **Padronizar em pytest.** `test_storage_phase1.py` ainda usa o runner-print
  caseiro com `check()`. Funciona via pytest (as funções `test_*` são
  coletadas), mas o `if __name__ == "__main__"` e o `raise AssertionError`
  manual são ruído. Migrar para `assert` puro quando tocar no arquivo.
- **Nomear por domínio, não por fase.** `test_phase4/5/6` foi útil durante o
  desenvolvimento, mas `test_analytics`, `test_knowledge_graph`,
  `test_dashboard` dizem o que cobrem sem precisar abrir. Renomear aos poucos.
- **Asserções de veredito conservador.** O `content_quality` já testa o caso
  "sinais mistos → atenção, não confiante" — esse é exatamente o tipo de teste
  que protege a honestidade analítica. Vale replicar a mesma disciplina ao
  cobrir o `nlp_analyzer`.

---

## 7. Como rodar

```bash
# gsc-monitor
cd gsc-monitor && py -m pytest            # 303 testes

# semantic-analyzer
cd semantic-analyzer && py -m pytest      # 81 testes

# um arquivo só, verboso
py -m pytest tests/test_classifier.py -v
```

Dependências de teste: só `pytest` (núcleo já cobre `unittest`). Os fetchers do
gsc-monitor importam `googleapiclient` no topo do módulo, então a suíte completa
exige as deps de `requirements.txt` instaladas — o que já é o caso no ambiente
de uso.
