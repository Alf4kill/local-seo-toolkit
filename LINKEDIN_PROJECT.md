# LinkedIn — Project entry: local-seo-toolkit

Drop-in copy for the LinkedIn profile **Projects** section, in English and
Portuguese. Written to be skimmed by a recruiter / headhunter in ~10 seconds, and
kept **under LinkedIn's 2,000-character** description limit. Swap the
`<your-handle>` placeholder for your real GitHub username — and confirm no client
data is committed before making the repo public (reports live in the git-ignored
`relatorios/`).

---

## 🇬🇧 English

**Project name**
local-seo-toolkit — NLP-powered SEO diagnostics, 100% local

**One-line headline**
NLP-driven SEO diagnostics: embeddings + semantic clustering + a local LLM detect content cannibalization across 100+ sites. Free-tier and 100% local.

**Description** (1,064 characters)
Python suite that diagnoses content cannibalization and over-optimization across 100+ sites with NLP — not keyword tools.

semantic-analyzer embeds every page (sentence-transformers) and clusters them by meaning (cosine similarity + agglomerative clustering) to surface duplicate and doorway content; an optional local LLM (Ollama / LM Studio, GPU) judges each group and proposes fixes.

gsc-monitor adds a rule-based content-quality verdict — keyword density across 3 sources, entity salience (Cloud Natural Language), and an impression-weighted health score with component alerts — plus auto-generated 301-consolidation and page-pruning plans.

Built for analytical honesty: every verdict is rule-based or from a local model, never overstated. Runs on one machine, free API quotas only, no paid LLM.

Engineered, not scripted: clean core/fetchers/reporters layering, 390 offline tests, CI coverage gate, secret scanning.

Stack: Python · sentence-transformers · scikit-learn · NumPy · local LLMs · Google Search Console API · Cloud NLP · pytest / GitHub Actions.

**Project URL**
https://github.com/<your-handle>/local-seo-toolkit

---

## 🇧🇷 Português

**Nome do projeto**
local-seo-toolkit — diagnóstico de SEO com NLP, 100% local

**Chamada de uma linha**
Diagnóstico de SEO com NLP: embeddings + clustering semântico + LLM local detectam canibalização de conteúdo em 100+ sites. Grátis e 100% local.

**Descrição** (1.172 caracteres)
Suíte em Python que diagnostica canibalização de conteúdo e over-optimization em 100+ sites com NLP — não ferramentas de keyword.

semantic-analyzer transforma cada página em embedding (sentence-transformers) e agrupa por significado (similaridade do cosseno + clustering aglomerativo), revelando conteúdo duplicado e doorway pages; uma LLM local opcional (Ollama / LM Studio, GPU) julga cada grupo e propõe correções.

gsc-monitor adiciona um veredito de qualidade de conteúdo baseado em regras — densidade de keyword em 3 fontes, saliência de entidades (Cloud Natural Language) e health score ponderado por impressões com alertas por componente — além de planos de consolidação 301 e de poda gerados automaticamente.

Feito com honestidade analítica: todo veredito é baseado em regras ou vem de um modelo local, nunca superestimado. Roda em uma máquina, só com cotas gratuitas de API, sem LLM paga.

Engenharia, não improviso: camadas core/fetchers/reporters, 390 testes offline, gate de cobertura na CI, varredura de segredos.

Stack: Python · sentence-transformers · scikit-learn · NumPy · LLMs locais · Google Search Console API · Cloud NLP · pytest / GitHub Actions.

**URL do projeto**
https://github.com/<seu-usuario>/local-seo-toolkit

---

## Skills (LinkedIn tags)

LinkedIn pins **5 skills max per project** — lead with the NLP/ML core.

**Pin these 5:** Natural Language Processing (NLP) · Sentence Embeddings · Machine Learning · Python · Large Language Models (LLMs)

**Add the rest to your profile Skills:** Semantic Search · Text Clustering · scikit-learn · NumPy · Data Analysis · SEO · Google Search Console API · Cloud Natural Language API · Local LLM deployment (Ollama / LM Studio) · pytest (TDD) · CI/CD (GitHub Actions) · Software Architecture · Data Visualization · Tkinter

---

## Media — attach for "more info"

Ranked by impact. Use placeholder `exemplo.com.br` data or blur every screenshot —
reports embed real client domains and Search Console metrics.

1. **GitHub repo** — `github.com/<your-handle>/local-seo-toolkit`. README + ARCHITECTURE + PROJECT_STATUS make a strong landing page. Verify credentials and `relatorios/` are git-ignored first.
2. **Dashboard screenshot** — the generated `dashboard.html` (Chart.js: health score, cannibalization, content quality). Most visual proof it works.
3. **Architecture diagram** — export the diagram from `docs/ARCHITECTURE.md` as an image; reads as "designs systems," not "writes scripts."
4. **Cluster report** — a `semantic-analyzer` HTML report: grouped pages + LLM verdict (placeholder `exemplo` site).
5. **Case study (optional)** — 1-page PDF or article: "detected → planned the fix → measured," anonymized.
