"""
html_reporter.py — Gera o dashboard HTML estático do GSC Monitor.

O arquivo gerado é autocontido (CSS embutido) e usa Chart.js via CDN jsDelivr.
Salvo em: relatorios/{dominio}/dashboard.html

Seções geradas conforme dados disponíveis:
  Saúde do Site | Posicionamento | Indexação | Knowledge Graph
  Histórico | Tendências | Canibalização | Páginas Órfãs
"""

import html
import json
from collections import Counter

# ---------------------------------------------------------------------------
# Paletas
# ---------------------------------------------------------------------------

_RANGE_HEX = {
    "Top 3": "#92D050",
    "1ª Página": "#C6EFCE",
    "2ª Página": "#FFEB9C",
    "3ª Página": "#FFCC99",
    "4ª+ Página": "#FFC7CE",
    "Sem Dados": "#D9D9D9",
}
_RANGE_ORDER = ["Top 3", "1ª Página", "2ª Página", "3ª Página", "4ª+ Página", "Sem Dados"]

_GRADE_HEX = {
    "Excelente": "#1e7a1e",
    "Bom": "#2d8c5e",
    "Regular": "#b06000",
    "Crítico": "#b03030",
}
_GRADE_BG = {
    "Excelente": "#C6EFCE",
    "Bom": "#d9f0e0",
    "Regular": "#FFF2CC",
    "Crítico": "#FFE0E0",
}

_IDX_HEX = ["#2d7a2d", "#b03030", "#b06000", "#888888"]
_IDX_LABEL = ["Indexado", "Não Indexado", "Aviso", "Desconhecido"]
_IDX_KEYS = ["indexed", "not_indexed", "warning", "unknown"]

_TREND_HEX = {"rising": "#2d7a2d", "stable": "#b06000", "declining": "#b03030"}
_TREND_LBL = {"rising": "↑ Crescente", "stable": "→ Estável", "declining": "↓ Em queda"}

# Severidade de canibalização: (cor do texto, cor de fundo, rótulo)
_SEVERITY_BADGE = {
    "alta": ("#b03030", "#FFE0E0", "ALTA"),
    "média": ("#b06000", "#FFF2CC", "MÉDIA"),
    "baixa": ("#2d7a2d", "#E6F4EA", "BAIXA"),
}

# Qualidade de conteúdo: veredito → (cor do texto, cor de fundo)
_CQ_VERDICT_BADGE = {
    "ok": ("#2d7a2d", "#E6F4EA"),
    "atencao": ("#b06000", "#FFF2CC"),
    "over_otimizado": ("#b03030", "#FFE0E0"),
    "raso": ("#b03030", "#FFE0E0"),
}

# Cores e rótulos em PT para cada tipo de entidade NLP
# (fg=texto/borda, bg=fundo do badge)
_NLP_TYPE_COLORS = {
    "PERSON": ("#E65100", "#fff3e0"),
    "ORGANIZATION": ("#1565C0", "#e8f0fe"),
    "LOCATION": ("#2E7D32", "#e8f5e9"),
    "CONSUMER_GOOD": ("#6A1B9A", "#f3e5f5"),
    "WORK_OF_ART": ("#00695C", "#e0f7fa"),
    "EVENT": ("#C62828", "#ffebee"),
    "OTHER": ("#546E7A", "#eceff1"),
    "UNKNOWN": ("#757575", "#f5f5f5"),
}
_NLP_TYPE_PT = {
    "PERSON": "Pessoa",
    "ORGANIZATION": "Organização",
    "LOCATION": "Local",
    "CONSUMER_GOOD": "Produto",
    "WORK_OF_ART": "Obra",
    "EVENT": "Evento",
    "OTHER": "Outro",
    "UNKNOWN": "Desconhecido",
}


def _classify_range(pos) -> str:
    if pos is None:
        return "Sem Dados"
    if pos <= 3:
        return "Top 3"
    if pos <= 10:
        return "1ª Página"
    if pos <= 20:
        return "2ª Página"
    if pos <= 50:
        return "3ª Página"
    return "4ª+ Página"


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;color:#333;font-size:14px}
a{color:#1F4E79;text-decoration:none}
header{background:linear-gradient(135deg,#1F4E79,#2e6da4);color:#fff;padding:24px 32px}
header h1{font-size:22px;font-weight:700;margin-bottom:4px}
header .meta{opacity:.8;font-size:13px}
nav{background:#fff;border-bottom:1px solid #dde3ea;padding:0 32px;position:sticky;top:0;z-index:100;overflow-x:auto;white-space:nowrap}
nav a{display:inline-block;padding:12px 16px;font-size:13px;color:#555;border-bottom:3px solid transparent;transition:all .2s}
nav a:hover,nav a.active{color:#1F4E79;border-bottom-color:#1F4E79}
main{max-width:1200px;margin:0 auto;padding:24px 16px}
section{background:#fff;border-radius:10px;padding:24px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
section h2{font-size:16px;font-weight:700;color:#1F4E79;margin-bottom:16px;padding-bottom:10px;border-bottom:2px solid #e8f0fe}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.stat-card{background:#f5f8ff;border-radius:8px;padding:14px;text-align:center;border:1px solid #dde3ea}
.stat-val{font-size:22px;font-weight:700;color:#1F4E79}
.stat-label{font-size:11px;color:#666;margin-top:3px;text-transform:uppercase;letter-spacing:.5px}
.chart-wrap{position:relative;height:260px;margin-bottom:20px}
.score-row{display:flex;align-items:center;gap:24px;margin-bottom:20px;flex-wrap:wrap}
.score-big{font-size:64px;font-weight:900;line-height:1}
.score-denom{font-size:24px;color:#888;align-self:flex-end;margin-bottom:8px}
.grade-badge{display:inline-block;padding:6px 18px;border-radius:20px;font-size:15px;font-weight:700;color:#fff}
.comp-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:13px}
.comp-label{width:220px;flex-shrink:0;color:#555}
.comp-bar-bg{flex:1;background:#eee;border-radius:4px;height:10px;overflow:hidden;min-width:100px}
.comp-bar-fg{height:100%;border-radius:4px;background:#1F4E79;transition:width .6s}
.comp-val{width:60px;text-align:right;font-weight:600;color:#333}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#1F4E79;color:#fff;padding:8px 10px;text-align:left;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
td{padding:7px 10px;border-bottom:1px solid #edf0f5;vertical-align:top}
tr:hover td{background:#f5f8ff}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.kg-card{background:#f5f8ff;border-radius:8px;padding:16px;border-left:4px solid #1F4E79}
.kg-card h3{font-size:17px;font-weight:700;color:#1F4E79;margin-bottom:6px}
.kg-card .kg-types{color:#555;font-size:12px;margin-bottom:8px}
.kg-card .kg-desc{color:#333;line-height:1.5;margin-bottom:8px}
.kg-card .kg-score{font-size:12px;color:#888}
.canib-group{margin-bottom:16px;border:1px solid #e0e8f5;border-radius:8px;overflow:hidden}
.canib-header{background:#EBF3FB;padding:8px 12px;font-weight:700;font-size:13px;color:#1F4E79}
.orphan-url{padding:6px 10px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#444;font-family:monospace}
.orphan-url:last-child{border-bottom:none}
.note{background:#fff8e1;border-left:3px solid #ffc107;padding:8px 12px;border-radius:4px;font-size:12px;color:#666;margin-top:12px}
.no-data{color:#999;font-size:13px;font-style:italic;text-align:center;padding:20px}
footer{text-align:center;padding:20px;color:#aaa;font-size:11px;margin-top:10px}
@media(max-width:640px){.stats-grid{grid-template-columns:repeat(2,1fr)}.score-big{font-size:48px}}
"""

# ---------------------------------------------------------------------------
# JS Charts (sem f-string — usa variáveis globais injetadas antes)
# ---------------------------------------------------------------------------

_JS = """
function safeChart(id, cfg) {
    const el = document.getElementById(id);
    if (!el) return;
    new Chart(el, cfg);
}

// NOTA (bugfix): as constantes são declaradas com `const` no escopo global,
// e `const` NÃO cria propriedade em `window` — `window.POS_DATA` era sempre
// undefined e NENHUM gráfico renderizava. Os guards referenciam as
// constantes diretamente (sempre declaradas; valem null quando sem dados).

// Posicionamento — barras horizontais
if (POS_DATA) {
    safeChart('chart-pos', {
        type: 'bar',
        data: {
            labels: POS_DATA.labels,
            datasets: [{
                label: 'URLs',
                data: POS_DATA.counts,
                backgroundColor: POS_DATA.colors,
                borderColor: POS_DATA.colors.map(c => c),
                borderWidth: 1,
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { x: { beginAtZero: true, ticks: { precision: 0 } } }
        }
    });
}

// Indexação — doughnut
if (IDX_DATA) {
    safeChart('chart-idx', {
        type: 'doughnut',
        data: {
            labels: IDX_DATA.labels,
            datasets: [{
                data: IDX_DATA.counts,
                backgroundColor: IDX_DATA.colors,
                hoverOffset: 8,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'right' } }
        }
    });
}

// Histórico — linhas
if (HIST_DATA && HIST_DATA.datasets.length > 0) {
    safeChart('chart-hist', {
        type: 'line',
        data: HIST_DATA,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom', labels: { font: { size: 11 } } } },
            scales: {
                y: {
                    reverse: true,
                    title: { display: true, text: 'Posição' },
                    min: 1,
                    ticks: { precision: 0 }
                }
            }
        }
    });
}

// Trends — linha (fonte GSC, P5: impressões/dia) ou barras (pytrends, legado)
if (TRENDS_DATA && TRENDS_DATA.mode === 'line' && TRENDS_DATA.series.length > 0) {
    safeChart('chart-trends', {
        type: 'line',
        data: {
            labels: TRENDS_DATA.dates,
            datasets: TRENDS_DATA.series.map(s => ({
                label: s.label,
                data: s.values,
                borderColor: s.color,
                backgroundColor: 'transparent',
                borderWidth: s.site ? 2.5 : 1.2,
                pointRadius: 0,
                tension: 0.25,
            }))
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: true, labels: { boxWidth: 14, font: { size: 10 } } } },
            scales: {
                y: { beginAtZero: true, title: { display: true, text: 'Impressões/dia' } },
                x: { ticks: { maxTicksLimit: 12, font: { size: 9 } } }
            }
        }
    });
} else if (TRENDS_DATA && TRENDS_DATA.labels && TRENDS_DATA.labels.length > 0) {
    safeChart('chart-trends', {
        type: 'bar',
        data: {
            labels: TRENDS_DATA.labels,
            datasets: [{
                label: 'Interesse atual (0-100)',
                data: TRENDS_DATA.latest,
                backgroundColor: TRENDS_DATA.colors,
                borderWidth: 0,
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { x: { beginAtZero: true, max: 100 } }
        }
    });
}
"""


# ---------------------------------------------------------------------------
# Helpers de serialização para Chart.js
# ---------------------------------------------------------------------------


def _pos_chart_data(report: dict) -> dict:
    counts = Counter(_classify_range(r["position"]) for r in report["urls"])
    labels = [r for r in _RANGE_ORDER if counts.get(r, 0) > 0]
    return {
        "labels": labels,
        "counts": [counts[l] for l in labels],
        "colors": [_RANGE_HEX[l] for l in labels],
    }


def _idx_chart_data(consolidated: dict) -> dict:
    summary = consolidated.get("summary", {})
    counts = [summary.get(k, {}).get("total", 0) for k in _IDX_KEYS]
    # Filtra categorias com 0 para não poluir o doughnut
    pairs = [(l, c, h) for l, c, h in zip(_IDX_LABEL, counts, _IDX_HEX) if c > 0]
    return {
        "labels": [p[0] for p in pairs],
        "counts": [p[1] for p in pairs],
        "colors": [p[2] for p in pairs],
    }


def _hist_chart_data(historico: dict) -> dict:
    snapshots = historico.get("snapshots", [])[-8:]
    dates = [s["date"] for s in snapshots]

    # Pega as top 8 URLs por total de impressões acumuladas
    url_impr: dict = {}
    for s in snapshots:
        for url, v in s["urls"].items():
            url_impr[url] = url_impr.get(url, 0) + v.get("impressions", 0)
    top_urls = sorted(url_impr, key=lambda u: -url_impr[u])[:8]

    palette = [
        "#1F4E79",
        "#E65100",
        "#1B5E20",
        "#4A148C",
        "#B71C1C",
        "#006064",
        "#F57F17",
        "#37474F",
    ]
    datasets = []
    for i, url in enumerate(top_urls):
        label = url.rstrip("/").split("/")[-1] or url.split("/")[2]
        data = [s["urls"].get(url, {}).get("position") for s in snapshots]
        datasets.append(
            {
                "label": label[:40],
                "data": data,
                "borderColor": palette[i % len(palette)],
                "backgroundColor": palette[i % len(palette)] + "22",
                "tension": 0.3,
                "spanGaps": True,
            }
        )
    return {"labels": dates, "datasets": datasets}


def _trends_chart_data(trends_data: dict) -> dict:
    # P5 — fonte GSC: gráfico de LINHA com as séries diárias (site + top queries)
    is_gsc = any(isinstance(td, dict) and td.get("source") == "gsc" for td in trends_data.values())
    if is_gsc:
        from core.analytics import SITE_TREND_KEY

        dates = (
            next((td.get("dates") for td in trends_data.values() if td.get("dates")), None) or []
        )
        palette = ["#1F4E79", "#e07b39", "#2d8c5e", "#b03030", "#7b5cb8", "#3a9fbf"]
        series = [
            {
                "label": kw[:35],
                "values": td.get("values", []),
                "color": palette[i % len(palette)],
                "site": kw == SITE_TREND_KEY,
            }
            for i, (kw, td) in enumerate(list(trends_data.items())[:6])
        ]
        return {"mode": "line", "dates": dates, "series": series}

    # pytrends (legado) — barras horizontais do interesse atual 0–100
    labels, latest, colors = [], [], []
    for kw, td in trends_data.items():
        labels.append(kw[:35])
        latest.append(td.get("latest", 0))
        colors.append(_TREND_HEX.get(td.get("trend", "stable"), "#888"))
    return {"mode": "bar", "labels": labels, "latest": latest, "colors": colors}


# ---------------------------------------------------------------------------
# Builders de seções HTML
# ---------------------------------------------------------------------------


def _sec_saude(health: dict) -> str:
    if not health:
        return ""
    score = health["score"]
    grade = health["grade"]
    comp = health["components"]
    color = _GRADE_HEX.get(grade, "#333")

    idx_val = f"{comp['indexation']:.1f}" if comp["indexation"] is not None else "s/d"
    idx_pct = comp["indexation"] if comp["indexation"] is not None else 0
    pos_pct = comp["position"]
    ctr_pct = comp["ctr"]
    note = (
        ""
        if health["has_indexation_data"]
        else '<p class="note">* Indexação não executada — score baseado só em Posição + CTR (pesos re-normalizados).</p>'
    )

    # P4 — alertas por componente: o composto pode mascarar um componente
    # crítico (caso real: 70.7 "Bom" com CTR 8.7/100). Caixa destacada,
    # SEM esconder o composto — os dois aparecem juntos.
    alerts_html = ""
    alerts = health.get("component_alerts") or []
    if alerts:
        items = "".join(
            f'<div style="margin:4px 0"><strong>{html.escape(a["label"])} '
            f"{a['value']:.1f}/100</strong> "
            f'<span style="background:{"#842029" if a["severity"] == "critico" else "#b06000"};'
            f'color:#fff;border-radius:8px;padding:1px 8px;font-size:10px;font-weight:700">'
            f"{html.escape(a['severity'].upper())}</span><br>"
            f'<span style="font-size:12px">{html.escape(a["message"])}</span></div>'
            for a in alerts
        )
        alerts_html = f"""
  <div style="background:#fdecea;border:1px solid #f5c2c7;border-left:4px solid #dc3545;border-radius:6px;padding:10px 14px;margin-top:12px;color:#842029">
    <strong>⚠ Componente(s) crítico(s) abaixo do score geral</strong> — o número composto não conta a história toda:
    {items}
  </div>"""

    return f"""
<section id="saude">
  <h2>🏥 Saúde do Site</h2>
  <div class="score-row">
    <div class="score-big" style="color:{color}">{score:.0f}</div>
    <div class="score-denom">/100</div>
    <div class="grade-badge" style="background:{color}">{grade}</div>
  </div>
  <div>
    <div class="comp-row">
      <span class="comp-label">Indexação (peso 40%)</span>
      <div class="comp-bar-bg"><div class="comp-bar-fg" style="width:{idx_pct:.0f}%"></div></div>
      <span class="comp-val">{idx_val}</span>
    </div>
    <div class="comp-row">
      <span class="comp-label">Posicionamento (peso 40%)</span>
      <div class="comp-bar-bg"><div class="comp-bar-fg" style="width:{pos_pct:.0f}%"></div></div>
      <span class="comp-val">{pos_pct:.1f}</span>
    </div>
    <div class="comp-row">
      <span class="comp-label">CTR vs benchmark (peso 20%)</span>
      <div class="comp-bar-bg"><div class="comp-bar-fg" style="width:{ctr_pct:.0f}%"></div></div>
      <span class="comp-val">{ctr_pct:.1f}</span>
    </div>
  </div>
  {alerts_html}
  {note}
</section>"""


def _sec_posicionamento(report: dict, data: dict) -> str:
    summary = report["summary"]
    avg_pos = summary.get("avg_position_site") or "–"
    avg_pos_str = f"{avg_pos:.1f}" if isinstance(avg_pos, float) else avg_pos

    rows_sorted = sorted(
        [r for r in report["urls"] if r["has_data"]],
        key=lambda r: r["position"] or 9999,
    )[:15]

    rows_html = ""
    for r in rows_sorted:
        faixa = _classify_range(r["position"])
        badge_bg = _RANGE_HEX.get(faixa, "#ddd")
        short_url = html.escape(r["url"].replace("https://", "").replace("http://", ""))
        rows_html += f"""
      <tr>
        <td><span class="badge" style="background:{badge_bg}">{r["position"]:.1f}</span></td>
        <td style="font-family:monospace;font-size:12px">{short_url}</td>
        <td style="text-align:right">{r["clicks"]:,}</td>
        <td style="text-align:right">{r["impressions"]:,}</td>
        <td style="text-align:right">{r["ctr"]:.1f}%</td>
      </tr>"""

    return f"""
<section id="posicionamento">
  <h2>📈 Posicionamento</h2>
  <div class="stats-grid">
    <div class="stat-card"><div class="stat-val">{summary["total_urls_sitemap"]}</div><div class="stat-label">URLs no Sitemap</div></div>
    <div class="stat-card"><div class="stat-val">{summary["urls_with_data"]}</div><div class="stat-label">Com dados GSC</div></div>
    <div class="stat-card"><div class="stat-val">{avg_pos_str}</div><div class="stat-label">Posição Média</div></div>
    <div class="stat-card"><div class="stat-val">{summary["total_clicks"]:,}</div><div class="stat-label">Cliques (período)</div></div>
    <div class="stat-card"><div class="stat-val">{summary["total_impressions"]:,}</div><div class="stat-label">Impressões</div></div>
    <div class="stat-card"><div class="stat-val">{data["start_date"]} → {data["end_date"]}</div><div class="stat-label">Período</div></div>
  </div>
  <div class="chart-wrap"><canvas id="chart-pos"></canvas></div>
  <table>
    <thead><tr><th>Pos.</th><th>URL</th><th>Cliques</th><th>Impressões</th><th>CTR</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</section>"""


def _sec_indexacao(consolidated: dict) -> str:
    if not consolidated:
        return ""
    total = consolidated.get("total_urls", 0)
    summary = consolidated.get("summary", {})
    idx = summary.get("indexed", {})
    rows_html = "".join(
        f"<tr><td>{label}</td>"
        f'<td style="text-align:right">{summary.get(key, {}).get("total", 0)}</td>'
        f'<td style="text-align:right">{summary.get(key, {}).get("percent", 0):.1f}%</td></tr>'
        for key, label in zip(_IDX_KEYS, _IDX_LABEL)
    )
    return f"""
<section id="indexacao">
  <h2>🔍 Indexação</h2>
  <div class="stats-grid">
    <div class="stat-card"><div class="stat-val">{total}</div><div class="stat-label">Total URLs</div></div>
    <div class="stat-card"><div class="stat-val">{idx.get("total", 0)}</div><div class="stat-label">Indexadas</div></div>
    <div class="stat-card"><div class="stat-val">{idx.get("percent", 0):.1f}%</div><div class="stat-label">% Indexadas</div></div>
  </div>
  <div class="chart-wrap" style="max-width:420px;height:220px"><canvas id="chart-idx"></canvas></div>
  <table style="margin-top:16px">
    <thead><tr><th>Status</th><th>Qtd.</th><th>%</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</section>"""


def _sec_kg(kg_result: dict) -> str:
    if not kg_result:
        return ""
    if not kg_result.get("found"):
        brand = html.escape(kg_result.get("brand", ""))
        return f"""
<section id="kg">
  <h2>🌐 Knowledge Graph</h2>
  <div class="no-data">Marca "{brand}" não encontrada no Knowledge Graph do Google.</div>
</section>"""
    name = html.escape(kg_result.get("name", ""))
    types = html.escape(", ".join(t for t in kg_result.get("types", []) if t != "Thing") or "–")
    desc = html.escape(kg_result.get("description", ""))
    detail = kg_result.get("detailed_desc", "")
    if detail and len(detail) > 300:
        detail = detail[:297] + "..."
    detail = html.escape(detail)
    url = html.escape(kg_result.get("url", ""))
    detail_html = (
        f'<p class="kg-desc" style="color:#555;font-size:12px">{detail}</p>' if detail else ""
    )
    url_html = (
        f'<a href="{url}" target="_blank" style="font-size:12px">{url}</a>'
        if kg_result.get("url")
        else ""
    )
    return f"""
<section id="kg">
  <h2>🌐 Knowledge Graph</h2>
  <div class="kg-card">
    <h3>{name}</h3>
    <div class="kg-types">{types}</div>
    {"<p class='kg-desc'>" + desc + "</p>" if desc else ""}
    {detail_html}
    {url_html}
    <div class="kg-score">Score KG: {kg_result.get("score", 0):.1f}</div>
  </div>
</section>"""


def _sec_historico(historico: dict) -> str:
    snaps = historico.get("snapshots", [])
    if len(snaps) < 2:
        return ""
    return f"""
<section id="historico">
  <h2>📅 Histórico de Posicionamento</h2>
  <p style="color:#666;font-size:12px;margin-bottom:12px">{len(snaps)} snapshots disponíveis. Exibindo até 8 URLs com mais impressões.</p>
  <div class="chart-wrap" style="height:320px"><canvas id="chart-hist"></canvas></div>
</section>"""


def _sec_trends(trends_data: dict) -> str:
    if not trends_data:
        return ""

    # P5 — fonte GSC (padrão) vs pytrends (legado): rótulos honestos por fonte
    is_gsc = any(isinstance(td, dict) and td.get("source") == "gsc" for td in trends_data.values())
    if is_gsc:
        days = len(next(iter(trends_data.values())).get("values", []))
        title = f"📊 Tendências de demanda — GSC ({days} dias)"
        note = (
            '<p style="color:#666;font-size:12px;margin-bottom:10px">'
            "Impressões/dia do <strong>próprio site</strong> na busca "
            "(dimensão <code>date</code> da Search Analytics API). Tendência = "
            "média do 1º terço vs último terço do período. Não é o índice "
            "global 0–100 do Google Trends.</p>"
        )
        hdr_peak, hdr_latest = "Pico (impr./dia)", "Média recente"
    else:
        title = "📊 Tendências Google Trends (12 meses)"
        note = ""
        hdr_peak, hdr_latest = "Pico", "Atual"

    rows = "".join(
        f"<tr><td>{html.escape(kw)}</td>"
        f'<td style="color:{_TREND_HEX.get(td["trend"], "#888")};font-weight:700">'
        f"{_TREND_LBL.get(td['trend'], '→ Estável')}</td>"
        f'<td style="text-align:right">{td.get("peak", 0)}</td>'
        f'<td style="text-align:right">{td.get("latest", 0)}</td></tr>'
        for kw, td in trends_data.items()
    )
    return f"""
<section id="trends">
  <h2>{title}</h2>
  {note}
  <div class="chart-wrap"><canvas id="chart-trends"></canvas></div>
  <table style="margin-top:16px">
    <thead><tr><th>Keyword</th><th>Tendência</th><th>{hdr_peak}</th><th>{hdr_latest}</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""


def _sec_canibalizacao(cannibalization: list) -> str:
    if not cannibalization:
        return ""
    groups_html = ""
    for g in cannibalization[:20]:
        urls_html = "".join(
            f'<tr><td style="font-family:monospace;font-size:11px">{html.escape(u["url"])}</td>'
            f'<td style="text-align:right">{u["position"]:.1f}</td>'
            f'<td style="text-align:right">{u["impressions"]:,}</td></tr>'
            for u in g["urls"]
        )
        sfg, sbg, slbl = _SEVERITY_BADGE.get(g.get("severity", "baixa"), ("#555", "#eee", "—"))
        sev_badge = (
            f'<span style="background:{sbg};color:{sfg};border-radius:10px;'
            f'padding:1px 8px;font-size:10px;font-weight:700;margin-left:8px">{slbl}</span>'
        )
        groups_html += f"""
    <div class="canib-group">
      <div class="canib-header">🔑 {html.escape(g["query"])} <span style="font-size:11px;font-weight:400">({g["url_count"]} URLs)</span>{sev_badge}</div>
      <table>
        <thead><tr><th>URL</th><th>Posição</th><th>Impressões</th></tr></thead>
        <tbody>{urls_html}</tbody>
      </table>
    </div>"""
    total = len(cannibalization)
    note = f'<p class="note">Exibindo 20 de {total} grupos.</p>' if total > 20 else ""
    return f"""
<section id="canibalizacao">
  <h2>⚡ Canibalização de Keywords</h2>
  <p style="color:#666;font-size:12px;margin-bottom:14px">{total} keyword(s) com 2+ páginas competindo. Consolidar ou diferenciar o conteúdo.</p>
  {groups_html}
  {note}
</section>"""


def _sec_plano_301(plan: dict) -> str:
    """Seção do plano de consolidação 301 (P2). Sempre marcada como SUGESTÃO."""
    if not plan or not plan.get("redirects"):
        return ""

    groups_html = ""
    for g in plan["groups"][:20]:
        can = g["canonical"]
        rows = (
            f'<tr style="background:#eef7ee">'
            f'<td style="font-weight:700;color:#1e7e34;width:90px">MANTER</td>'
            f'<td style="font-family:monospace;font-size:11px">{html.escape(can["url"])}</td>'
            f'<td style="text-align:right">{can.get("clicks", 0):,}</td>'
            f'<td style="text-align:right">{can["position"]:.1f}</td></tr>'
        )
        for s in g["sources"]:
            rows += (
                f'<tr><td style="color:#b02a37;font-weight:700">301 →</td>'
                f'<td style="font-family:monospace;font-size:11px">{html.escape(s["url"])}</td>'
                f'<td style="text-align:right">{s.get("clicks", 0):,}</td>'
                f'<td style="text-align:right">{s["position"]:.1f}</td></tr>'
            )
        sfg, sbg, slbl = _SEVERITY_BADGE.get(g.get("severity", "baixa"), ("#555", "#eee", "—"))
        sev_badge = (
            f'<span style="background:{sbg};color:{sfg};border-radius:10px;'
            f'padding:1px 8px;font-size:10px;font-weight:700;margin-left:8px">{slbl}</span>'
        )
        groups_html += f"""
    <div class="canib-group">
      <div class="canib-header">🔀 {html.escape(g["query"])}{sev_badge}</div>
      <table>
        <thead><tr><th>Ação</th><th>URL</th><th>Cliques</th><th>Posição</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

    total_g = plan["total_groups"]
    note = f'<p class="note">Exibindo 20 de {total_g} grupos.</p>' if total_g > 20 else ""

    conflicts_html = ""
    if plan.get("conflicts"):
        items = "".join(f"<li>{html.escape(c)}</li>" for c in plan["conflicts"][:30])
        more = (
            f'<p class="note">+{len(plan["conflicts"]) - 30} conflitos no CSV.</p>'
            if len(plan["conflicts"]) > 30
            else ""
        )
        conflicts_html = f"""
  <details style="margin-top:12px">
    <summary style="cursor:pointer;font-size:12px;color:#9c5700">
      Conflitos entre grupos resolvidos automaticamente ({len(plan["conflicts"])})
    </summary>
    <ul style="font-size:11px;color:#666;margin:8px 0 0 18px">{items}</ul>
    {more}
  </details>"""

    return f"""
<section id="plano301">
  <h2>🔀 Plano de Consolidação 301 <span style="font-size:13px;background:#fff3cd;color:#9c5700;border-radius:10px;padding:2px 10px;vertical-align:middle">SUGESTÃO</span></h2>
  <div style="background:#fff3cd;border:1px solid #ffe69c;border-left:4px solid #ffc107;border-radius:6px;padding:10px 14px;font-size:12px;color:#664d03;margin-bottom:14px">
    ⚠ <strong>Sugestão automática — não aplicar sem revisão humana.</strong>
    {html.escape(plan.get("disclaimer", ""))}
  </div>
  <p style="color:#666;font-size:12px;margin-bottom:14px">
    {plan["total_redirects"]} redirect(s) sugerido(s) em {total_g} grupo(s).
    Canônica escolhida por: cliques (desc) → posição (asc) → impressões (desc).
    Arquivos prontos: <code>*_redirects.csv</code>, <code>*_redirects_apache.txt</code>, <code>*_redirects_nginx.txt</code> na pasta do domínio.
  </p>
  {groups_html}
  {note}
  {conflicts_html}
</section>"""


def _sec_nlp(nlp_results: dict) -> str:
    if not nlp_results:
        return ""

    cards_html = ""
    for url, data in nlp_results.items():
        entities = data.get("entities", []) if isinstance(data, dict) else []
        categories = data.get("categories", []) if isinstance(data, dict) else []
        short_url = html.escape(url.replace("https://", "").replace("http://", ""))

        cat_pills = "".join(
            f'<span style="display:inline-block;background:#E8F0FE;color:#1F4E79;'
            f"border-radius:12px;padding:2px 10px;font-size:11px;margin:2px 4px 2px 0;"
            f'border:1px solid #c5d8f8">'
            f"{html.escape(c['name'].rsplit('/', 1)[-1])} {int(c['confidence'] * 100)}%</span>"
            for c in categories[:2]
        )

        # Normaliza barras pelo maior salience da página (visual mais legível)
        max_sal = max((e["salience"] for e in entities[:6]), default=1) or 1

        ent_rows = ""
        for e in entities[:6]:
            etype = e.get("type", "OTHER")
            fg, bg = _NLP_TYPE_COLORS.get(etype, ("#546E7A", "#eceff1"))
            label_pt = _NLP_TYPE_PT.get(etype, etype.title())
            bar_pct = int(e["salience"] / max_sal * 100)
            ename = html.escape(e["name"])
            ent_rows += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:12px">'
                f'<span style="width:80px;flex-shrink:0;background:{bg};color:{fg};border-radius:4px;'
                f"padding:2px 6px;font-size:10px;font-weight:700;text-align:center;"
                f'border:1px solid {fg}40" title="{html.escape(etype)}">{label_pt}</span>'
                f'<span style="width:120px;flex-shrink:0;color:#333;overflow:hidden;'
                f'text-overflow:ellipsis;white-space:nowrap;font-weight:500" title="{ename}">'
                f"{ename}</span>"
                f'<div style="flex:1;background:#e8ecf0;border-radius:3px;height:8px">'
                f'<div style="width:{bar_pct}%;background:{fg};height:100%;border-radius:3px;'
                f'opacity:0.8"></div></div>'
                f'<span style="width:40px;text-align:right;color:#888;font-size:11px">'
                f"{e['salience']:.3f}</span>"
                f"</div>"
            )
        if not ent_rows:
            ent_rows = '<div style="color:#999;font-size:12px">Sem entidades detectadas</div>'

        no_cat_note = (
            (
                '<div style="font-size:11px;color:#b06000;background:#fff8e1;border-radius:4px;'
                'padding:4px 8px;margin-bottom:8px;border-left:3px solid #ffc107">'
                "⚠ Sem categoria — conteúdo insuficiente para classificação (menos de ~20 tokens informativos)</div>"
            )
            if not categories
            else ""
        )

        cards_html += f"""
    <div style="background:#f8faff;border:1px solid #dde3ea;border-radius:8px;padding:14px;margin-bottom:12px">
      <div style="font-family:monospace;font-size:11px;color:#555;margin-bottom:10px;word-break:break-all">{short_url}</div>
      {no_cat_note}
      {f'<div style="margin-bottom:10px">{cat_pills}</div>' if cat_pills else ""}
      <div style="background:#fff;border-radius:6px;padding:10px;border:1px solid #e8ecf0">
        {ent_rows}
      </div>
    </div>"""

    n = len(nlp_results)
    legend_items = [
        ("Pessoa", _NLP_TYPE_COLORS["PERSON"][0]),
        ("Organização", _NLP_TYPE_COLORS["ORGANIZATION"][0]),
        ("Local", _NLP_TYPE_COLORS["LOCATION"][0]),
        ("Produto", _NLP_TYPE_COLORS["CONSUMER_GOOD"][0]),
        ("Obra", _NLP_TYPE_COLORS["WORK_OF_ART"][0]),
        ("Evento", _NLP_TYPE_COLORS["EVENT"][0]),
        ("Outro", _NLP_TYPE_COLORS["OTHER"][0]),
    ]
    legend_html = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:3px;'
        f'margin:0 10px 4px 0;font-size:11px;color:#555">'
        f'<span style="width:10px;height:10px;border-radius:2px;background:{color};'
        f'display:inline-block;flex-shrink:0"></span>{label}</span>'
        for label, color in legend_items
    )

    return f"""
<section id="nlp">
  <h2>🧠 Análise NLP — Entidades &amp; Categorias</h2>
  <p style="color:#666;font-size:12px;margin-bottom:10px">{n} página(s) de oportunidade analisadas (posição 4–10). Entidades ordenadas por saliência — barra normalizada pelo maior valor da página.</p>
  <div style="margin-bottom:16px;padding:8px 12px;background:#f5f8ff;border-radius:6px;border:1px solid #dde3ea;flex-wrap:wrap">
    <span style="font-size:11px;font-weight:700;color:#555;margin-right:8px">Tipos:</span>{legend_html}
  </div>
  {cards_html}
</section>"""


def _sec_orfas(orphans: list) -> str:
    if not orphans:
        return ""
    urls_html = "".join(
        f'<div class="orphan-url">🔗 {html.escape(o["url"])}</div>' for o in orphans[:100]
    )
    note = f'<p class="note">Exibindo 100 de {len(orphans)}.</p>' if len(orphans) > 100 else ""
    return f"""
<section id="orfas">
  <h2>📭 Páginas sem impressões ({len(orphans)})</h2>
  <p style="color:#666;font-size:12px;margin-bottom:12px">URLs sem nenhuma impressão de busca no período. Revisar conteúdo, intenção de busca ou consolidar.</p>
  <div style="border:1px solid #eee;border-radius:6px;overflow:hidden;max-height:360px;overflow-y:auto">
    {urls_html}
  </div>
  {note}
</section>"""


def _sec_content_quality(content_results: dict) -> str:
    if not content_results:
        return ""
    cards = ""
    for url, cq in content_results.items():
        fg, bg = _CQ_VERDICT_BADGE.get(cq.get("verdict", "ok"), ("#555", "#eee"))
        short = html.escape(url.replace("https://", "").replace("http://", ""))
        reasons = "".join(f"<li>{html.escape(r)}</li>" for r in cq.get("reasons", []))
        if not reasons:
            reasons = "<li>Sem alertas relevantes.</li>"
        # P3 — keyword gatilho da densidade + fonte (query GSC / slug / n-grama)
        _src_labels = {"query": "query GSC", "slug": "slug da URL", "ngram": "n-grama dominante"}
        dens_kw = html.escape(cq.get("densest_keyword") or "—")
        src = _src_labels.get(cq.get("density_source"))
        if src and cq.get("densest_keyword"):
            dens_kw += f" · {src}"
        ent = cq.get("entity_count")
        ent_str = f" · {ent} entidades" if ent is not None else ""
        cards += f"""
    <div style="background:#f8faff;border:1px solid #dde3ea;border-radius:8px;padding:14px;margin-bottom:12px">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
        <span style="background:{bg};color:{fg};border-radius:10px;padding:2px 12px;font-size:12px;font-weight:700">{html.escape(cq.get("verdict_label", ""))}</span>
        <span style="font-family:monospace;font-size:11px;color:#555;word-break:break-all">{short}</span>
      </div>
      <div style="font-size:12px;color:#444;margin-bottom:6px">
        {cq.get("word_count", 0)} palavras · densidade {cq.get("keyword_density", 0):.1f}% ({dens_kw}) · diversidade {cq.get("vocab_diversity", 0):.2f}{ent_str}
      </div>
      <ul style="font-size:12px;color:#666;margin:6px 0 0 18px;padding:0">{reasons}</ul>
    </div>"""
    return f"""
<section id="conteudo">
  <h2>🧪 Qualidade de Conteúdo</h2>
  <p style="color:#666;font-size:12px;margin-bottom:12px">Diagnóstico de over-optimization / conteúdo raso nas páginas de oportunidade (posição 4–10). <strong>Heurística</strong> correlacionada com o que os core updates do Google valorizam — não é o algoritmo de ranking.</p>
  {cards}
</section>"""


def _sec_tracking(tracking: dict) -> str:
    rows = tracking.get("rows", [])
    if not rows:
        return ""
    n = tracking.get("n_content_snapshots", 0)
    note = (
        '<p class="note">Baseline registrado. Otimize/consolide o conteúdo e rode novamente '
        "em outra data para medir se a posição acompanha a melhora.</p>"
        if n < 2
        else ""
    )
    body = ""
    for r in rows:
        fg, bg = _CQ_VERDICT_BADGE.get(r.get("last_verdict", "ok"), ("#555", "#eee"))
        d = r["position_delta"]
        if d is None:
            delta = '<span style="color:#888">baseline</span>'
        elif d > 0:
            delta = f'<span style="color:#2d7a2d;font-weight:700">▲ +{d:.1f}</span>'
        elif d < 0:
            delta = f'<span style="color:#b03030;font-weight:700">▼ {d:.1f}</span>'
        else:
            delta = '<span style="color:#888">→ 0</span>'
        short = html.escape(r["url"].replace("https://", "").replace("http://", ""))
        pos = f"{r['last_position']:.1f}" if r["last_position"] is not None else "—"
        dens = r.get("last_density")
        dens_s = f"{dens:.1f}%" if dens is not None else "—"
        body += f"""
      <tr>
        <td><span class="badge" style="background:{bg};color:{fg}">{html.escape(r.get("last_verdict", ""))}</span></td>
        <td style="font-family:monospace;font-size:11px">{short}</td>
        <td style="text-align:center">{pos}</td>
        <td style="text-align:center">{dens_s}</td>
        <td style="text-align:center">{delta}</td>
        <td style="text-align:center">{r["snapshots"]}</td>
      </tr>"""
    return f"""
<section id="acompanhamento">
  <h2>📓 Acompanhamento — Conteúdo × Posição</h2>
  <p style="color:#666;font-size:12px;margin-bottom:10px">Evolução das páginas analisadas: veredito de conteúdo vs. posição ao longo dos snapshots. Δ positivo = posição melhorou desde o baseline. É o loop de medição — otimize o conteúdo e veja se a posição acompanha.</p>
  <table>
    <thead><tr><th>Veredito</th><th>URL</th><th>Posição</th><th>Densidade</th><th>Δ Posição</th><th>Snapshots</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
  {note}
</section>"""


# ---------------------------------------------------------------------------
# Montagem final
# ---------------------------------------------------------------------------


def generate_dashboard(
    domain: str,
    today: str,
    data: dict,
    report: dict,
    health: "dict | None" = None,
    orphans: "list | None" = None,
    historico_posicao: "dict | None" = None,
    cannibalization: "list | None" = None,
    kg_result: "dict | None" = None,
    trends_data: "dict | None" = None,
    consolidated: "dict | None" = None,
    nlp_results: "dict | None" = None,
    content_results: "dict | None" = None,
    consolidation_plan: "dict | None" = None,
) -> str:
    """
    Gera o HTML do dashboard como string.
    Salvar com storage.save_dashboard(site, html).
    """

    # Serializa dados para Chart.js
    pos_json = json.dumps(_pos_chart_data(report))
    idx_json = json.dumps(_idx_chart_data(consolidated)) if consolidated else "null"
    hist_data = (
        _hist_chart_data(historico_posicao)
        if historico_posicao and len(historico_posicao.get("snapshots", [])) >= 2
        else None
    )
    hist_json = json.dumps(hist_data) if hist_data else "null"
    trend_json = json.dumps(_trends_chart_data(trends_data)) if trends_data else "null"

    # Move 2 — acompanhamento conteúdo × posição (derivado do próprio histórico)
    from core.content_quality import build_content_tracking

    tracking = (
        build_content_tracking(historico_posicao)
        if historico_posicao
        else {"rows": [], "n_content_snapshots": 0}
    )

    # Seções
    body = ""
    body += _sec_saude(health)
    body += _sec_posicionamento(report, data)
    if consolidated:
        body += _sec_indexacao(consolidated)
    if kg_result:
        body += _sec_kg(kg_result)
    if hist_data:
        body += _sec_historico(historico_posicao)
    if trends_data:
        body += _sec_trends(trends_data)
    if cannibalization:
        body += _sec_canibalizacao(cannibalization)
    if consolidation_plan and consolidation_plan.get("redirects"):
        body += _sec_plano_301(consolidation_plan)
    if nlp_results:
        body += _sec_nlp(nlp_results)
    if content_results:
        body += _sec_content_quality(content_results)
    if tracking["rows"]:
        body += _sec_tracking(tracking)
    if orphans:
        body += _sec_orfas(orphans)

    # Nav links (apenas seções presentes)
    nav_items = [("posicionamento", "📈 Posicionamento")]
    if health:
        nav_items.insert(0, ("saude", "🏥 Saúde"))
    if consolidated:
        nav_items.append(("indexacao", "🔍 Indexação"))
    if kg_result:
        nav_items.append(("kg", "🌐 KG"))
    if hist_data:
        nav_items.append(("historico", "📅 Histórico"))
    if trends_data:
        nav_items.append(("trends", "📊 Trends"))
    if cannibalization:
        nav_items.append(("canibalizacao", "⚡ Canibalização"))
    if consolidation_plan and consolidation_plan.get("redirects"):
        nav_items.append(("plano301", "🔀 Plano 301"))
    if nlp_results:
        nav_items.append(("nlp", "🧠 NLP"))
    if content_results:
        nav_items.append(("conteudo", "🧪 Conteúdo"))
    if tracking["rows"]:
        nav_items.append(("acompanhamento", "📓 Acompanhamento"))
    if orphans:
        nav_items.append(("orfas", "📭 Sem impressões"))
    nav_html = "".join(f'<a href="#{i}">{l}</a>' for i, l in nav_items)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard GSC — {domain}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>📊 GSC Monitor — {domain}</h1>
  <div class="meta">Gerado em {today} &nbsp;·&nbsp; Período: {data["start_date"]} a {data["end_date"]}</div>
</header>
<nav>{nav_html}</nav>
<main>
{body}
</main>
<footer>Gerado por GSC Monitor · {today}</footer>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
const POS_DATA    = {pos_json};
const IDX_DATA    = {idx_json};
const HIST_DATA   = {hist_json};
const TRENDS_DATA = {trend_json};
{_JS}
</script>
</body>
</html>"""
