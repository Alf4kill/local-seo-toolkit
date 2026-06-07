"""
nlp_report_generator.py — Relatório NLP detalhado (Fase 5c complementar).

Gerado automaticamente quando --nlp é usado em posicao.py.
Salvo em: relatorios/{dominio}/nlp_{date}.html

Seções:
  1. Resumo Executivo    — stats globais + diagnóstico
  2. Pilares Temáticos   — entidades em 2+ páginas (topical authority)
  3. Score de Profundidade por Página — 0-100, componentes, recomendações
  4. Distribuição de Tipos de Entidade — gráfico empilhado + interpretação
  5. Gaps de Conteúdo Semântico — termos das queries GSC ausentes nas entidades NLP
"""

import json
from collections import Counter, defaultdict

# ---------------------------------------------------------------------------
# Paleta de tipos (espelhada do html_reporter para consistência visual)
# ---------------------------------------------------------------------------

_TYPE_COLORS = {
    "PERSON":        ("#E65100", "#fff3e0"),
    "ORGANIZATION":  ("#1565C0", "#e8f0fe"),
    "LOCATION":      ("#2E7D32", "#e8f5e9"),
    "CONSUMER_GOOD": ("#6A1B9A", "#f3e5f5"),
    "WORK_OF_ART":   ("#00695C", "#e0f7fa"),
    "EVENT":         ("#C62828", "#ffebee"),
    "OTHER":         ("#546E7A", "#eceff1"),
    "UNKNOWN":       ("#757575", "#f5f5f5"),
}
_TYPE_PT = {
    "PERSON":        "Pessoa",
    "ORGANIZATION":  "Organização",
    "LOCATION":      "Local",
    "CONSUMER_GOOD": "Produto",
    "WORK_OF_ART":   "Obra",
    "EVENT":         "Evento",
    "OTHER":         "Outro",
    "UNKNOWN":       "Desconhecido",
}
_TYPE_INTERP = {
    "PERSON":        "A API classificou a entidade como humana. Quando isso ocorre para produtos ou raças, indica que o texto carece de contexto específico suficiente.",
    "ORGANIZATION":  "Empresa, instituição ou entidade coletiva. Ideal para menções de marcas e órgãos.",
    "LOCATION":      "Lugar, cidade ou região. Relevante para negócios locais e SEO geográfico.",
    "CONSUMER_GOOD": "Bem ou produto de consumo. Classificação ideal para páginas de produtos e serviços.",
    "WORK_OF_ART":   "Obra, título de artigo ou publicação. Pode indicar que a API leu o título da página como entidade.",
    "EVENT":         "Acontecimento ou ação no tempo. Termos como 'investimento' ou 'compra' podem ser classificados aqui.",
    "OTHER":         "Entidade que não se encaixa nas categorias acima. Normal em conteúdo temático amplo.",
    "UNKNOWN":       "Tipo não identificado pela API.",
}

# Stopwords PT para extração de termos de query (Seção 5)
_PT_STOPWORDS = frozenset({
    "de", "do", "da", "dos", "das", "e", "em", "um", "uma", "uns", "umas",
    "para", "o", "a", "os", "as", "com", "no", "na", "nos", "nas",
    "que", "ou", "como", "por", "se", "mais", "muito", "mas", "qual",
    "quanto", "quanta", "quais", "quando", "onde", "quem", "pelo", "pela",
    "pelos", "pelas", "ao", "aos", "num", "numa", "dum", "duma",
    "este", "esta", "estes", "estas", "esse", "essa", "esses", "essas",
    "seu", "sua", "seus", "suas", "meu", "minha", "me",
    "eu", "tu", "ele", "ela", "eles", "elas",
    "foi", "ser", "ter", "tem", "vai", "vou", "ver", "são",
})

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """\
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;color:#333;font-size:14px}
a{color:#1F4E79;text-decoration:none}
header{background:linear-gradient(135deg,#1F4E79,#2e6da4);color:#fff;padding:24px 32px}
header h1{font-size:20px;font-weight:700;margin-bottom:4px}
header .meta{opacity:.8;font-size:13px}
nav{background:#fff;border-bottom:1px solid #dde3ea;padding:0 32px;
    position:sticky;top:0;z-index:100;overflow-x:auto;white-space:nowrap}
nav a{display:inline-block;padding:12px 16px;font-size:13px;color:#555;
      border-bottom:3px solid transparent;transition:all .2s}
nav a:hover{color:#1F4E79;border-bottom-color:#1F4E79}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
section{background:#fff;border-radius:10px;padding:24px;margin-bottom:20px;
        box-shadow:0 1px 4px rgba(0,0,0,.08)}
section h2{font-size:16px;font-weight:700;color:#1F4E79;margin-bottom:16px;
           padding-bottom:10px;border-bottom:2px solid #e8f0fe}
section h3{font-size:13px;font-weight:700;color:#333;margin-bottom:10px;margin-top:16px}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
            gap:12px;margin-bottom:20px}
.stat-card{background:#f5f8ff;border-radius:8px;padding:14px;text-align:center;
           border:1px solid #dde3ea}
.stat-val{font-size:26px;font-weight:700;color:#1F4E79}
.stat-label{font-size:11px;color:#666;margin-top:4px;text-transform:uppercase;
            letter-spacing:.5px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#1F4E79;color:#fff;padding:8px 10px;text-align:left;
   font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
td{padding:8px 10px;border-bottom:1px solid #edf0f5;vertical-align:middle}
tr:hover td{background:#f5f8ff}
.badge{display:inline-block;padding:3px 10px;border-radius:10px;
       font-size:12px;font-weight:700}
.type-badge{display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;
            font-weight:700;border-width:1px;border-style:solid}
.url-card{background:#f8faff;border:1px solid #dde3ea;border-radius:8px;
          padding:16px;margin-bottom:14px}
.url-label{font-family:monospace;font-size:11px;color:#555;margin-bottom:12px;
           word-break:break-all}
.score-big{font-size:40px;font-weight:900;line-height:1}
.comp-row{display:flex;align-items:center;gap:10px;margin-bottom:6px;font-size:12px}
.comp-label{width:180px;flex-shrink:0;color:#555}
.comp-bar-bg{flex:1;background:#e8ecf0;border-radius:3px;height:8px;overflow:hidden;
             min-width:80px}
.comp-bar-fg{height:100%;border-radius:3px}
.comp-val{width:48px;text-align:right;font-weight:600;color:#333;font-size:12px}
.ent-inline{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.rec-box{background:#fff8e1;border-left:3px solid #ffc107;padding:10px 12px;
         border-radius:4px;font-size:12px;color:#555;margin-top:12px}
.rec-box strong{color:#b06000;display:block;margin-bottom:6px}
.rec-box li{margin-left:16px;margin-bottom:4px;line-height:1.5}
.chart-wrap{position:relative;height:300px;margin-top:16px}
.interp-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));
             gap:10px;margin-top:16px}
.interp-card{border-radius:6px;padding:10px 12px;font-size:12px;
             border-left:4px solid currentColor;line-height:1.5}
.no-data{color:#999;font-size:13px;font-style:italic;padding:20px;text-align:center}
.diag-row{display:flex;align-items:flex-start;gap:10px;padding:8px 0;
          border-bottom:1px solid #f0f0f0;font-size:13px}
.diag-row:last-child{border-bottom:none}
.diag-icon{font-size:16px;flex-shrink:0;width:24px;text-align:center}
footer{text-align:center;padding:20px;color:#aaa;font-size:11px;margin-top:8px}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _h(s: str) -> str:
    """Escapa HTML básico."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _short_url(url: str) -> str:
    """Extrai a parte final legível de uma URL."""
    clean = url.rstrip("/")
    part  = clean.split("/")[-1] if "/" in clean else clean
    return (part[:45] + "…") if len(part) > 45 else part or clean.split("//")[-1]


def _type_badge(etype: str) -> str:
    fg, bg = _TYPE_COLORS.get(etype, ("#546E7A", "#eceff1"))
    label  = _TYPE_PT.get(etype, etype.title())
    return (
        f'<span class="type-badge" '
        f'style="background:{bg};color:{fg};border-color:{fg}40" '
        f'title="{etype}">{label}</span>'
    )


def _depth_score(url_data: dict) -> int:
    """
    Score de profundidade de conteúdo — 0 a 100.

    Componentes:
      Categoria (0/40)  — tem ao menos uma categoria Google/IAB?
      Saliência  (0/35) — saliência média das entidades; 0.10+ = nota máxima
      Entidades  (0/25) — qtd. de entidades; 8+ = nota máxima
    """
    entities   = url_data.get("entities", [])
    categories = url_data.get("categories", [])

    cat_pts = 40 if categories else 0

    if entities:
        avg_sal = sum(e["salience"] for e in entities) / len(entities)
        sal_pts = min(35, int(avg_sal * 350))
    else:
        avg_sal = 0.0
        sal_pts = 0

    ent_pts = min(25, len(entities) * 3)
    return cat_pts + sal_pts + ent_pts


def _score_grade(score: int) -> tuple:
    """Retorna (label, cor_texto, cor_fundo)."""
    if score >= 70: return ("Rico",       "#2E7D32", "#e8f5e9")
    if score >= 50: return ("Moderado",   "#b06000", "#fff8e1")
    if score >= 30: return ("Raso",       "#E65100", "#fff3e0")
    return              ("Muito raso",  "#C62828", "#ffebee")


def _recommendations(url_data: dict, score: int) -> list:
    """Gera lista de recomendações baseada nos dados da página."""
    recs       = []
    entities   = url_data.get("entities", [])
    categories = url_data.get("categories", [])

    if not categories:
        recs.append(
            "Expandir para 600+ palavras de texto narrativo contínuo — "
            "mínimo necessário para a API classificar o tema da página."
        )

    if entities:
        type_counts = Counter(e.get("type", "OTHER") for e in entities)
        total       = len(entities)

        if type_counts.get("PERSON", 0) / total > 0.35:
            recs.append(
                "Muitas entidades classificadas como 'Pessoa' — adicionar contexto "
                "específico (produto, raça, local, organização) para que a API "
                "identifique corretamente os temas abordados."
            )

        avg_sal = sum(e["salience"] for e in entities) / total
        if avg_sal < 0.04:
            recs.append(
                "Saliência média muito baixa — focar o conteúdo num tema principal "
                "em vez de dispersar entre muitos termos de passagem."
            )

        if total < 4:
            recs.append(
                "Poucas entidades detectadas — enriquecer o texto com termos mais "
                "específicos ao nicho (ex: origem da raça, características, cuidados)."
            )
    else:
        recs.append(
            "Nenhuma entidade detectada — o conteúdo pode estar muito curto "
            "ou ser majoritariamente não-textual (tabelas, listas sem contexto)."
        )

    if score < 50 and categories:
        recs.append("Aumentar a profundidade — mesmo com categoria, a saliência indica conteúdo superficial.")

    if not recs:
        recs.append("Conteúdo bem estruturado. Monitorar posicionamento após próximas atualizações.")

    return recs


def _topical_pillars(nlp_results: dict) -> list:
    """
    Entidades que aparecem em 2+ páginas = pilares temáticos do site.
    Indica os conceitos que o Google tende a associar ao domínio.
    """
    name_pages = defaultdict(set)
    name_sals  = defaultdict(list)
    name_types = defaultdict(list)

    for url, data in nlp_results.items():
        seen = set()
        for e in data.get("entities", []):
            name = e["name"].strip()
            if name not in seen:
                name_pages[name].add(url)
                name_sals[name].append(e["salience"])
                name_types[name].append(e.get("type", "OTHER"))
                seen.add(name)

    pillars = []
    for name, urls in name_pages.items():
        if len(urls) >= 2:
            main_type = Counter(name_types[name]).most_common(1)[0][0]
            avg_sal   = sum(name_sals[name]) / len(name_sals[name])
            pillars.append({
                "name":    name,
                "type":    main_type,
                "pages":   len(urls),
                "avg_sal": round(avg_sal, 3),
            })

    pillars.sort(key=lambda p: (-p["pages"], -p["avg_sal"]))
    return pillars


def _type_distribution(nlp_results: dict) -> dict:
    """Contagem de tipos de entidade por URL e global."""
    per_url      = {}
    global_count = Counter()

    for url, data in nlp_results.items():
        entities = data.get("entities", [])
        counts   = Counter(e.get("type", "OTHER") for e in entities)
        per_url[url] = dict(counts)
        global_count.update(counts)

    # Ordena tipos pelo mais frequente globalmente
    all_types = [t for t, _ in global_count.most_common()]
    return {"per_url": per_url, "global": dict(global_count), "all_types": all_types}


def _type_dist_chart_json(nlp_results: dict, dist: dict) -> str:
    """Serializa dados para o gráfico Chart.js de distribuição de tipos."""
    all_types = dist["all_types"]
    per_url   = dist["per_url"]
    urls      = list(nlp_results.keys())

    labels   = [_short_url(u) for u in urls]
    datasets = []
    for etype in all_types:
        fg = _TYPE_COLORS.get(etype, ("#546E7A", "#eceff1"))[0]
        datasets.append({
            "label":           _TYPE_PT.get(etype, etype.title()),
            "data":            [per_url.get(u, {}).get(etype, 0) for u in urls],
            "backgroundColor": fg,
        })

    return json.dumps({"labels": labels, "datasets": datasets})


# ---------------------------------------------------------------------------
# Helpers — Gaps de Conteúdo (Seção 5)
# ---------------------------------------------------------------------------

def _extract_query_terms(query: str) -> set:
    """Extrai termos significativos de uma query (sem stopwords PT, mín. 3 chars)."""
    return {
        t for t in query.lower().split()
        if t not in _PT_STOPWORDS and len(t) >= 3
    }


def _content_gaps(nlp_results: dict, query_rows: list) -> dict:
    """
    Compara termos das queries GSC com entidades NLP de cada URL.

    Para cada URL em nlp_results identifica:
      - queries    : top queries GSC que trazem tráfego à página
      - covered    : termos das queries presentes nas entidades NLP
      - gaps       : termos das queries ausentes nas entidades NLP
      - term_impr  : impressões acumuladas por cada termo (para priorização)

    Retorna: {url: {"queries", "covered", "gaps", "term_impressions"}}
    """
    # Agrupa query_rows por URL normalizada (sem trailing slash, lowercase)
    url_qs: dict = defaultdict(list)
    for row in query_rows:
        key = row.get("url", "").rstrip("/").lower()
        url_qs[key].append(row)

    result = {}
    for url, nlp_data in nlp_results.items():
        key   = url.rstrip("/").lower()
        qs    = sorted(url_qs.get(key, []), key=lambda r: -r.get("impressions", 0))
        top_q = qs[:8]

        # Termos das queries + acumulador de impressões por termo
        query_terms: set      = set()
        term_impr: dict       = defaultdict(int)
        for q in top_q:
            terms = _extract_query_terms(q.get("query", ""))
            for t in terms:
                term_impr[t] += q.get("impressions", 0)
            query_terms.update(terms)

        # Termos das entidades — apenas entidades com nome ≤ 5 palavras
        # (filtra artefatos de navegação que geram entidades-frase longas)
        entity_terms: set = set()
        for e in nlp_data.get("entities", []):
            words = e["name"].strip().split()
            if len(words) <= 5:
                for t in (w.lower() for w in words):
                    if len(t) >= 3 and t not in _PT_STOPWORDS:
                        entity_terms.add(t)

        covered = query_terms & entity_terms
        gaps    = query_terms - entity_terms

        result[url] = {
            "queries":          top_q,
            "covered":          covered,
            "gaps":             gaps,
            "term_impressions": dict(term_impr),
        }

    return result


# ---------------------------------------------------------------------------
# Seção 1 — Resumo Executivo
# ---------------------------------------------------------------------------

def _sec_executive_summary(nlp_results: dict, pillars: list) -> str:
    n          = len(nlp_results)
    n_cat      = sum(1 for d in nlp_results.values() if d.get("categories"))
    n_no_cat   = n - n_cat
    all_ents   = [e for d in nlp_results.values() for e in d.get("entities", [])]
    n_ents     = len(all_ents)
    scores     = [_depth_score(d) for d in nlp_results.values()]
    avg_score  = round(sum(scores) / len(scores), 1) if scores else 0
    n_rich     = sum(1 for s in scores if s >= 50)
    _, sc, sbg = _score_grade(int(avg_score))

    # Diagnóstico
    diag = []

    # Profundidade
    rich_pct = int(n_rich / n * 100) if n else 0
    if rich_pct >= 60:
        diag.append(("✅", f"Profundidade: {rich_pct}% das páginas com score ≥ 50 — conteúdo moderado a rico."))
    else:
        diag.append(("⚠️", f"Profundidade: apenas {rich_pct}% das páginas com score ≥ 50 — maioria tem conteúdo raso."))

    # Categorias
    if n_no_cat > 0:
        diag.append(("⚠️", f"{n_no_cat} página(s) sem categoria — conteúdo insuficiente para classificação temática pelo Google."))
    else:
        diag.append(("✅", "Todas as páginas classificadas por categoria — bom sinal de profundidade."))

    # Pilar dominante
    if pillars:
        top = pillars[0]
        diag.append(("📌", f'Pilar temático dominante: "{_h(top["name"])}" — presente em {top["pages"]} de {n} páginas.'))
    else:
        diag.append(("ℹ️", "Sem pilares temáticos transversais — nenhuma entidade aparece em 2+ páginas."))

    # Tipo mais comum
    if all_ents:
        top_type, top_cnt = Counter(e.get("type", "OTHER") for e in all_ents).most_common(1)[0]
        type_pct = int(top_cnt / n_ents * 100)
        type_pt  = _TYPE_PT.get(top_type, top_type)
        if top_type == "PERSON" and type_pct > 30:
            diag.append(("⚠️", f"Tipo mais comum: '{type_pt}' ({type_pct}%) — muitas entidades classificadas como Pessoa indicam falta de contexto específico."))
        else:
            diag.append(("ℹ️", f"Tipo mais comum: '{type_pt}' ({type_pct}% das entidades)."))

    diag_html = "".join(
        f'<div class="diag-row"><span class="diag-icon">{icon}</span><span>{text}</span></div>'
        for icon, text in diag
    )

    return f"""
<section id="resumo">
  <h2>📋 Resumo Executivo</h2>
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-val">{n}</div>
      <div class="stat-label">Páginas analisadas</div>
    </div>
    <div class="stat-card">
      <div class="stat-val" style="color:#2E7D32">{n_cat}</div>
      <div class="stat-label">Com categoria</div>
    </div>
    <div class="stat-card">
      <div class="stat-val" style="color:#C62828">{n_no_cat}</div>
      <div class="stat-label">Sem categoria</div>
    </div>
    <div class="stat-card">
      <div class="stat-val">{n_ents}</div>
      <div class="stat-label">Entidades totais</div>
    </div>
    <div class="stat-card">
      <div class="stat-val" style="color:{sc}">{avg_score:.0f}</div>
      <div class="stat-label">Score médio /100</div>
    </div>
  </div>
  <h3>Diagnóstico Global</h3>
  <div style="border:1px solid #e8ecf0;border-radius:8px;padding:4px 12px">
    {diag_html}
  </div>
</section>"""


# ---------------------------------------------------------------------------
# Seção 2 — Pilares Temáticos
# ---------------------------------------------------------------------------

def _sec_topical_pillars(pillars: list, n_total: int) -> str:
    if not pillars:
        return """
<section id="pilares">
  <h2>🏛 Pilares Temáticos</h2>
  <div class="no-data">Nenhuma entidade aparece em 2 ou mais páginas — sem pilares temáticos identificados.<br>
  Isso pode indicar conteúdo sem fio condutor temático entre as páginas do site.</div>
</section>"""

    rows = ""
    for p in pillars:
        bar_pct = int(p["avg_sal"] / 0.15 * 100)  # 0.15+ = barra cheia
        bar_pct = min(bar_pct, 100)
        fg, bg  = _TYPE_COLORS.get(p["type"], ("#546E7A", "#eceff1"))
        rows += f"""
      <tr>
        <td style="font-weight:600;max-width:200px">{_h(p["name"])}</td>
        <td>{_type_badge(p["type"])}</td>
        <td style="text-align:center">
          <span class="badge" style="background:#e8f0fe;color:#1F4E79">{p["pages"]}/{n_total}</span>
        </td>
        <td>
          <div style="display:flex;align-items:center;gap:8px">
            <div class="comp-bar-bg" style="min-width:120px">
              <div class="comp-bar-fg" style="width:{bar_pct}%;background:{fg}"></div>
            </div>
            <span style="font-size:12px;color:#888;width:40px">{p["avg_sal"]:.3f}</span>
          </div>
        </td>
      </tr>"""

    note = (
        '<p class="note" style="margin-top:12px;background:#e8f5e9;border-color:#4caf50;color:#1B5E20">'
        '💡 <strong>Topical Authority:</strong> entidades recorrentes sinalizam ao Google quais temas '
        'o site domina. Quanto mais páginas tratam de um mesmo conceito de forma aprofundada, '
        'maior a autoridade temática percebida.</p>'
    ) if len(pillars) >= 3 else ""

    return f"""
<section id="pilares">
  <h2>🏛 Pilares Temáticos</h2>
  <p style="color:#666;font-size:12px;margin-bottom:14px">Entidades presentes em 2 ou mais páginas.
  Representam os temas que o Google tende a associar ao domínio como um todo.</p>
  <table>
    <thead>
      <tr>
        <th>Entidade</th>
        <th>Tipo</th>
        <th style="text-align:center">Páginas</th>
        <th>Saliência média</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  {note}
</section>"""


# ---------------------------------------------------------------------------
# Seção 3 — Score de Profundidade por Página
# ---------------------------------------------------------------------------

def _sec_depth_scores(nlp_results: dict) -> str:
    cards = ""
    for url, data in nlp_results.items():
        score      = _depth_score(data)
        label, sc, sbg = _score_grade(score)
        entities   = data.get("entities", [])
        categories = data.get("categories", [])

        # Componentes do score
        cat_pts = 40 if categories else 0
        if entities:
            avg_sal = sum(e["salience"] for e in entities) / len(entities)
            sal_pts = min(35, int(avg_sal * 350))
        else:
            avg_sal = 0.0
            sal_pts = 0
        ent_pts = min(25, len(entities) * 3)

        # Barras de componentes (width relativo ao máximo possível de cada componente)
        cat_bar = int(cat_pts / 40 * 100)
        sal_bar = int(sal_pts / 35 * 100)
        ent_bar = int(ent_pts / 25 * 100)

        bar_color = sc

        # Categoria obtida
        cat_label = (
            categories[0]["name"].rsplit("/", 1)[-1] + f' ({int(categories[0]["confidence"]*100)}%)'
            if categories else "—"
        )

        # Entidades principais (inline badges)
        ent_items = "".join(
            f'<span style="display:inline-flex;align-items:center;gap:4px;'
            f'background:#f0f4f8;border:1px solid #dde3ea;border-radius:14px;'
            f'padding:3px 8px;font-size:11px">'
            f'{_type_badge(e.get("type","OTHER"))} '
            f'<span style="color:#333;font-weight:500">{_h(e["name"])}</span>'
            f'<span style="color:#aaa;font-size:10px">{e["salience"]:.3f}</span>'
            f'</span>'
            for e in entities[:5]
        ) or '<span style="color:#999;font-size:12px">Sem entidades detectadas</span>'

        # Recomendações
        recs      = _recommendations(data, score)
        recs_html = "".join(f"<li>{_h(r)}</li>" for r in recs)

        cards += f"""
    <div class="url-card">
      <div class="url-label">{_h(url)}</div>
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:14px;flex-wrap:wrap">
        <div>
          <span class="score-big" style="color:{sc}">{score}</span>
          <span style="font-size:13px;color:#888">/100</span>
        </div>
        <span class="badge" style="background:{sbg};color:{sc}">{label}</span>
        <span style="font-size:12px;color:#888">Categoria: <strong>{_h(cat_label)}</strong></span>
      </div>

      <div class="comp-row">
        <span class="comp-label">Categoria (0/40)</span>
        <div class="comp-bar-bg">
          <div class="comp-bar-fg" style="width:{cat_bar}%;background:{bar_color}"></div>
        </div>
        <span class="comp-val">{cat_pts}/40</span>
      </div>
      <div class="comp-row">
        <span class="comp-label">Saliência média (0/35)</span>
        <div class="comp-bar-bg">
          <div class="comp-bar-fg" style="width:{sal_bar}%;background:{bar_color}"></div>
        </div>
        <span class="comp-val">{sal_pts}/35</span>
      </div>
      <div class="comp-row">
        <span class="comp-label">Nº de entidades (0/25)</span>
        <div class="comp-bar-bg">
          <div class="comp-bar-fg" style="width:{ent_bar}%;background:{bar_color}"></div>
        </div>
        <span class="comp-val">{ent_pts}/25</span>
      </div>

      <div style="margin-top:12px">
        <div style="font-size:11px;font-weight:700;color:#555;margin-bottom:6px;
                    text-transform:uppercase;letter-spacing:.4px">Entidades detectadas</div>
        <div class="ent-inline">{ent_items}</div>
      </div>

      <div class="rec-box">
        <strong>💡 Recomendações</strong>
        <ul style="padding:0">{recs_html}</ul>
      </div>
    </div>"""

    return f"""
<section id="profundidade">
  <h2>📏 Score de Profundidade por Página</h2>
  <p style="color:#666;font-size:12px;margin-bottom:6px">
    Score 0–100 calculado por três componentes: presença de categoria (40 pts),
    saliência média das entidades (35 pts) e quantidade de entidades (25 pts).
  </p>
  <table style="margin-bottom:16px;font-size:12px">
    <thead><tr><th>Faixa</th><th>Score</th><th>Significado</th></tr></thead>
    <tbody>
      <tr><td><span class="badge" style="background:#e8f5e9;color:#2E7D32">Rico</span></td>
          <td>70–100</td><td>Conteúdo bem estruturado e informativamente denso</td></tr>
      <tr><td><span class="badge" style="background:#fff8e1;color:#b06000">Moderado</span></td>
          <td>50–69</td><td>Conteúdo razoável, com espaço para melhoria</td></tr>
      <tr><td><span class="badge" style="background:#fff3e0;color:#E65100">Raso</span></td>
          <td>30–49</td><td>Conteúdo insuficiente — revisão recomendada</td></tr>
      <tr><td><span class="badge" style="background:#ffebee;color:#C62828">Muito raso</span></td>
          <td>0–29</td><td>Conteúdo muito fino — reescrita prioritária</td></tr>
    </tbody>
  </table>
  {cards}
</section>"""


# ---------------------------------------------------------------------------
# Seção 4 — Distribuição de Tipos
# ---------------------------------------------------------------------------

def _sec_type_distribution(nlp_results: dict, dist: dict) -> str:
    all_types    = dist["all_types"]
    global_count = dist["global"]
    total_ents   = sum(global_count.values())

    if not all_types:
        return """
<section id="tipos">
  <h2>🏷 Distribuição de Tipos de Entidade</h2>
  <div class="no-data">Sem entidades para exibir.</div>
</section>"""

    # Tabela global
    global_rows = ""
    for etype in all_types:
        cnt  = global_count.get(etype, 0)
        pct  = cnt / total_ents * 100 if total_ents else 0
        fg, bg = _TYPE_COLORS.get(etype, ("#546E7A", "#eceff1"))
        global_rows += (
            f'<tr>'
            f'<td>{_type_badge(etype)}</td>'
            f'<td style="text-align:right;font-weight:600">{cnt}</td>'
            f'<td style="text-align:right">{pct:.1f}%</td>'
            f'<td>'
            f'<div class="comp-bar-bg">'
            f'<div class="comp-bar-fg" style="width:{int(pct)}%;background:{fg}"></div>'
            f'</div>'
            f'</td>'
            f'</tr>'
        )

    # Cards de interpretação (apenas para tipos presentes)
    interp_cards = ""
    for etype in all_types:
        fg, bg = _TYPE_COLORS.get(etype, ("#546E7A", "#eceff1"))
        label  = _TYPE_PT.get(etype, etype.title())
        interp = _TYPE_INTERP.get(etype, "")
        if interp:
            interp_cards += (
                f'<div class="interp-card" '
                f'style="background:{bg};color:#333;border-color:{fg}">'
                f'<strong style="color:{fg}">{label}</strong><br>{interp}'
                f'</div>'
            )

    return f"""
<section id="tipos">
  <h2>🏷 Distribuição de Tipos de Entidade</h2>
  <p style="color:#666;font-size:12px;margin-bottom:14px">
    Como a API Google NLP classificou as entidades encontradas nas páginas.
    A distribuição revela se o conteúdo é percebido como focado em produtos,
    organizações, pessoas, ou termos genéricos.
  </p>

  <div style="display:grid;grid-template-columns:1fr 2fr;gap:24px;align-items:start;flex-wrap:wrap">
    <div>
      <h3>Distribuição Global</h3>
      <table>
        <thead><tr><th>Tipo</th><th>Qtd.</th><th>%</th><th style="min-width:80px">Barra</th></tr></thead>
        <tbody>{global_rows}</tbody>
      </table>
    </div>
    <div>
      <h3>Por Página — gráfico empilhado</h3>
      <div class="chart-wrap"><canvas id="chart-type-dist"></canvas></div>
    </div>
  </div>

  <h3 style="margin-top:20px">Interpretação dos Tipos</h3>
  <div class="interp-grid">{interp_cards}</div>
</section>"""


# ---------------------------------------------------------------------------
# Seção 5 — Gaps de Conteúdo Semântico
# ---------------------------------------------------------------------------

def _sec_content_gaps(nlp_results: dict, query_rows: "list | None") -> str:
    if not query_rows:
        return """
<section id="gaps">
  <h2>🔍 Gaps de Conteúdo Semântico</h2>
  <div class="no-data">Dados de queries não disponíveis —
  use <code style="background:#f0f0f0;padding:1px 4px;border-radius:3px">--queries</code>
  junto com <code style="background:#f0f0f0;padding:1px 4px;border-radius:3px">--nlp</code>
  para ativar esta seção.</div>
</section>"""

    gaps_data = _content_gaps(nlp_results, query_rows)
    has_any   = any(g["queries"] for g in gaps_data.values())

    if not has_any:
        return """
<section id="gaps">
  <h2>🔍 Gaps de Conteúdo Semântico</h2>
  <div class="no-data">Nenhuma URL de oportunidade encontrada nas queries GSC.</div>
</section>"""

    cards = ""
    for url, g in gaps_data.items():
        queries   = g["queries"]
        covered   = g["covered"]
        gaps      = g["gaps"]
        term_impr = g["term_impressions"]

        if not queries:
            continue

        # --- Lista de queries ---
        q_list = ""
        for q in queries[:5]:
            pos_str  = f"{q.get('position', 0):.1f}"
            impr_str = f"{q.get('impressions', 0):,}"
            q_list += (
                f'<div style="display:flex;align-items:center;gap:10px;'
                f'padding:5px 0;border-bottom:1px solid #f0f4f8;font-size:12px">'
                f'<span style="color:#888;width:52px;flex-shrink:0">pos {pos_str}</span>'
                f'<span style="flex:1;color:#333">{_h(q.get("query", ""))}</span>'
                f'<span style="color:#888;width:76px;text-align:right;flex-shrink:0">'
                f'{impr_str} impr.</span>'
                f'</div>'
            )

        # --- Pills cobertos (verde) ---
        covered_pills = (
            "".join(
                f'<span style="display:inline-block;background:#e8f5e9;color:#2E7D32;'
                f'border:1px solid #a5d6a7;border-radius:12px;padding:3px 10px;'
                f'font-size:11px;margin:2px;font-weight:600">{_h(t)}</span>'
                for t in sorted(covered)
            )
            or '<span style="color:#999;font-size:12px">nenhum</span>'
        )

        # --- Pills de gap (vermelho, ordenados por impacto) ---
        gaps_sorted = sorted(gaps, key=lambda t: -term_impr.get(t, 0))
        total_gap_impr = sum(term_impr.get(t, 0) for t in gaps)

        gap_pills = (
            "".join(
                f'<span style="display:inline-flex;align-items:center;gap:5px;'
                f'background:#ffebee;color:#C62828;border:1px solid #ef9a9a;'
                f'border-radius:12px;padding:3px 10px 3px 10px;font-size:11px;'
                f'margin:2px;font-weight:600" '
                f'title="{term_impr.get(t, 0):,} impressões afetadas">'
                f'{_h(t)}'
                f'<span style="background:#C62828;color:#fff;border-radius:8px;'
                f'padding:1px 5px;font-size:10px;font-weight:700;line-height:1.4">'
                f'{term_impr.get(t, 0):,}</span>'
                f'</span>'
                for t in gaps_sorted[:12]
            )
            or '<span style="color:#2E7D32;font-size:12px;font-weight:600">✅ Sem gaps identificados</span>'
        )

        # --- Nota de impacto ---
        impact_note = ""
        if gaps and total_gap_impr > 0:
            impact_note = (
                f'<div style="margin-top:12px;padding:10px 14px;background:#fff3e0;'
                f'border-left:3px solid #E65100;border-radius:4px;font-size:12px;color:#555">'
                f'<strong style="color:#E65100">📊 Impacto estimado:</strong> '
                f'abordar {len(gaps)} gap(s) pode melhorar o ranqueamento para queries com '
                f'<strong>{total_gap_impr:,} impressões</strong> combinadas. '
                f'Priorize os termos com maior número em vermelho — eles representam '
                f'maior volume de buscas relacionadas.</div>'
            )

        cards += f"""
    <div class="url-card">
      <div class="url-label">{_h(url)}</div>

      <div style="margin-bottom:14px">
        <div style="font-size:11px;font-weight:700;color:#555;margin-bottom:6px;
                    text-transform:uppercase;letter-spacing:.4px">Queries GSC — tráfego para esta página</div>
        <div style="border:1px solid #e8ecf0;border-radius:6px;overflow:hidden;padding:0 10px">
          {q_list}
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
        <div>
          <div style="font-size:11px;font-weight:700;color:#2E7D32;margin-bottom:8px;
                      text-transform:uppercase;letter-spacing:.4px">✅ Termos cobertos pelas entidades</div>
          <div style="line-height:2.2">{covered_pills}</div>
        </div>
        <div>
          <div style="font-size:11px;font-weight:700;color:#C62828;margin-bottom:8px;
                      text-transform:uppercase;letter-spacing:.4px">⚠ Gaps — nas queries, ausentes nas entidades</div>
          <div style="line-height:2.2">{gap_pills}</div>
        </div>
      </div>

      {impact_note}
    </div>"""

    return f"""
<section id="gaps">
  <h2>🔍 Gaps de Conteúdo Semântico</h2>
  <p style="color:#666;font-size:12px;margin-bottom:14px">
    Comparação entre os termos das queries do Google Search Console e as entidades
    detectadas pela NLP nas páginas correspondentes.
    <strong style="color:#C62828">Termos em vermelho</strong> aparecem nas buscas mas
    não são cobertos como entidades na página — são oportunidades de conteúdo.
    O número em cada pill indica o total de impressões das queries que contêm aquele termo.
  </p>
  {cards}
</section>"""


# ---------------------------------------------------------------------------
# JavaScript (Chart.js)
# ---------------------------------------------------------------------------

_JS_CHART = """\
(function() {
  var el = document.getElementById('chart-type-dist');
  if (!el || !window.TYPE_DIST_DATA) return;
  new Chart(el, {
    type: 'bar',
    data: TYPE_DIST_DATA,
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { font: { size: 11 }, boxWidth: 12 } }
      },
      scales: {
        x: { stacked: true, ticks: { precision: 0 },
             title: { display: true, text: 'Número de entidades', font: { size: 11 } } },
        y: { stacked: true }
      }
    }
  });
})();
"""


# ---------------------------------------------------------------------------
# Montagem final
# ---------------------------------------------------------------------------

def generate_nlp_report(
    domain: str,
    today: str,
    nlp_results: dict,
    query_rows: "list | None" = None,
) -> str:
    """
    Gera o HTML do relatório NLP detalhado como string.
    Salvar com storage.save_nlp_report(site, today, html).

    Args:
        domain      : domínio analisado (ex: www.site.com.br)
        today       : data no formato YYYY-MM-DD
        nlp_results : {url: {"entities": [...], "categories": [...]}}
        query_rows  : lista de dicts GSC query+URL (de fetch_query_positions).
                      Se None, a Seção 5 exibe aviso de dados indisponíveis.
    """
    if not nlp_results:
        return f"""<!DOCTYPE html><html lang="pt-BR">
<head><meta charset="UTF-8"><title>NLP — {domain}</title></head>
<body><p style="padding:40px;font-family:sans-serif">
Nenhum resultado NLP disponível para {domain}.</p></body></html>"""

    pillars = _topical_pillars(nlp_results)
    dist    = _type_distribution(nlp_results)
    n       = len(nlp_results)

    chart_json = _type_dist_chart_json(nlp_results, dist)

    sec1 = _sec_executive_summary(nlp_results, pillars)
    sec2 = _sec_topical_pillars(pillars, n)
    sec3 = _sec_depth_scores(nlp_results)
    sec4 = _sec_type_distribution(nlp_results, dist)
    sec5 = _sec_content_gaps(nlp_results, query_rows)

    gaps_nav = '<a href="#gaps">🔍 Gaps</a>' if query_rows else \
               '<a href="#gaps" style="opacity:.5" title="Use --queries para ativar">🔍 Gaps</a>'

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Análise NLP Detalhada — {domain}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>🧠 Análise NLP Detalhada — {domain}</h1>
  <div class="meta">
    Gerado em {today} &nbsp;·&nbsp; {n} página(s) analisada(s) &nbsp;·&nbsp;
    <a href="dashboard.html" style="color:#fff;opacity:.8;text-decoration:underline">← Dashboard</a>
  </div>
</header>
<nav>
  <a href="#resumo">📋 Resumo</a>
  <a href="#pilares">🏛 Pilares Temáticos</a>
  <a href="#profundidade">📏 Profundidade</a>
  <a href="#tipos">🏷 Tipos</a>
  {gaps_nav}
</nav>
<main>
{sec1}
{sec2}
{sec3}
{sec4}
{sec5}
</main>
<footer>Gerado por GSC Monitor · {today}</footer>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
const TYPE_DIST_DATA = {chart_json};
{_JS_CHART}
</script>
</body>
</html>"""
