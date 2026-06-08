"""
crawl_reporter.py — Saída do analisador de crawl budget (logs.py).

Dois artefatos:
  - build_crawl_txt_lines(): relatório .txt legível, ASCII, com as listas
    completas (não só amostras como o terminal).
  - generate_crawl_html(): dashboard HTML autocontido (CSS embutido, sem CDN),
    no mesmo idioma visual do dashboard de posição. Todo texto externo (paths,
    URLs, User-Agents) passa por html.escape().

Recebe o dict produzido por core.log_analyzer.analyze_logs/analyze_lines.
Não faz IO: quem salva é core.storage (save_crawl_txt/html/csv/report).
"""

from __future__ import annotations

import html

_esc = html.escape


def _fmt(n) -> str:
    """Inteiro com separador de milhar; passa o resto adiante como str."""
    return f"{n:,}" if isinstance(n, int) else str(n)


def _detection_label(result: dict) -> str:
    return "verificado por DNS" if result.get("resolved") else "por User-Agent (NÃO verificado)"


# ---------------------------------------------------------------------------
# Relatório .txt (ASCII puro, listas completas)
# ---------------------------------------------------------------------------


def build_crawl_txt_lines(result: dict, domain: str, date: str) -> list[str]:
    sep = "=" * 70
    dash = "-" * 70
    gb = result["googlebot"]
    traffic = result["traffic"]
    out: list[str] = []

    out.append(sep)
    out.append(f"  RELATORIO DE CRAWL BUDGET - {domain}  ({date})")
    out.append(sep)
    dr = result["date_range"]
    if dr["start"]:
        out.append(f"  Periodo do log : {dr['start']}  ->  {dr['end']}")
    out.append(
        f"  Linhas         : {_fmt(result['lines_total'])} "
        f"({_fmt(result['lines_parsed'])} ok, {_fmt(result['lines_malformed'])} ignoradas)"
    )
    out.append(f"  Deteccao bot   : {_detection_label(result).replace('NÃO', 'NAO')}")
    if not result["has_user_agent"]:
        out.append("  AVISO: log sem User-Agent ('common') - split bot x humano indisponivel.")
    out.append(dash)
    out.append(f"  Googlebot      : {_fmt(traffic['googlebot'])} hits")
    if result.get("resolved"):
        out.append(f"    - verificados por DNS : {_fmt(traffic.get('googlebot_verified', 0))}")
        out.append(
            f"    - nao verificaveis    : {_fmt(traffic.get('googlebot_unverifiable', 0))}"
            " (sem PTR; provavel CDN)"
        )
    out.append(f"  Outros bots    : {_fmt(traffic['other_bots'])}")
    out.append(f"  Humanos        : {_fmt(traffic['humans'])}")
    if traffic["spoofed_googlebot"]:
        out.append(
            f"  Googlebot FORJADO: {_fmt(traffic['spoofed_googlebot'])}"
            " (PTR resolve p/ host NAO-Google)"
        )
    if result.get("behind_cdn_suspected"):
        out.append("  AVISO: IPs do Googlebot sem PTR - log registra o IP do CDN/proxy")
        out.append("         (ex.: Cloudflare), nao o do bot. Verificacao por IP indisponivel;")
        out.append("         registre o IP real (header CF-Connecting-IP) para verificar.")
    out.append(dash)
    out.append(f"  URLs distintas rastreadas: {_fmt(gb['unique_paths'])}")
    if gb["status_mix"]:
        mix = "  ".join(f"{c}:{n}" for c, n in sorted(gb["status_mix"].items()))
        out.append(f"  Status (Googlebot): {mix}")
    if gb["param_hits"]:
        out.append(f"  Crawl em URLs com parametro (?): {_fmt(gb['param_hits'])} hits")

    out.append("")
    out.append("  CRAWL POR URL (todas, desc por hits):")
    out.append(dash)
    for r in gb["by_path"]:
        last = (r["last_seen"] or "")[:19]
        out.append(f"  {r['hits']:>7}x  {last:<19}  {r['path']}")

    if gb["top_errors"]:
        out.append("")
        out.append("  CRAWL DESPERDICADO EM ERROS (status >= 400):")
        out.append(dash)
        for r in gb["top_errors"]:
            out.append(f"  {r['hits']:>7}x  {r['path']}")

    nc = result.get("never_crawled")
    if nc:
        out.append("")
        out.append(f"  SITEMAP NUNCA RASTREADO: {nc['never']} de {nc['sitemap_total']} URLs")
        out.append(dash)
        for u in nc["urls"]:
            out.append(f"    - {u}")

    um = result.get("undercrawled_money")
    if um:
        out.append("")
        out.append(f"  MONEY PAGES SUBCRAWLADAS (muitas impressoes, ZERO crawl): {len(um)}")
        out.append(dash)
        for r in um:
            pos = f"{r['position']:.1f}" if isinstance(r["position"], (int, float)) else "-"
            out.append(f"  {r['impressions']:>9,} impr  pos {pos:>5}  {r['url']}")

    out.append(sep)
    return out


# ---------------------------------------------------------------------------
# Dashboard HTML autocontido
# ---------------------------------------------------------------------------

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;color:#333;font-size:14px}
header{background:linear-gradient(135deg,#1F4E79,#2e6da4);color:#fff;padding:24px 32px}
header h1{font-size:21px;margin-bottom:4px}
header .meta{opacity:.85;font-size:13px}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
section{background:#fff;border-radius:10px;padding:22px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
section h2{font-size:16px;color:#1F4E79;margin-bottom:14px;padding-bottom:9px;border-bottom:2px solid #e8f0fe}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-bottom:6px}
.card{background:#f5f8ff;border-radius:8px;padding:14px;text-align:center;border:1px solid #dde3ea}
.val{font-size:22px;font-weight:700;color:#1F4E79}
.lbl{font-size:11px;color:#666;margin-top:3px;text-transform:uppercase;letter-spacing:.5px}
.banner{padding:12px 16px;border-radius:8px;font-size:13px;margin-bottom:16px}
.banner.warn{background:#FFF2CC;border:1px solid #e0c97a;color:#7a5b00}
.banner.info{background:#e8f0fe;border:1px solid #b9d0f5;color:#1F4E79}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{padding:7px 9px;border-bottom:1px solid #eef2f7;text-align:left}
th{background:#f5f8ff;color:#1F4E79;font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.path{font-family:monospace;font-size:12px;word-break:break-all}
.chip{display:inline-block;padding:3px 10px;border-radius:14px;font-size:12px;font-weight:600;margin:2px 4px 2px 0;background:#eef2f7;color:#33506f}
.chip.err{background:#FFE0E0;color:#b03030}
.muted{color:#888;font-size:12px}
.danger{color:#b03030;font-weight:600}
"""


def _stat(val, label) -> str:
    return f'<div class="card"><div class="val">{_esc(_fmt(val))}</div><div class="lbl">{_esc(label)}</div></div>'


def _sec_resumo(result: dict) -> str:
    t = result["traffic"]
    gb = result["googlebot"]
    cards = [
        _stat(t["googlebot"], "Googlebot hits"),
        _stat(gb["unique_paths"], "URLs rastreadas"),
        _stat(t["humans"], "Humanos"),
        _stat(t["other_bots"], "Outros bots"),
        _stat(result["lines_malformed"], "Linhas ignoradas"),
    ]
    if result.get("resolved"):
        cards.insert(1, _stat(t.get("googlebot_verified", 0), "Verificados DNS"))
        cards.insert(2, _stat(t.get("googlebot_unverifiable", 0), "Nao verificaveis"))
    if t["spoofed_googlebot"]:
        cards.append(_stat(t["spoofed_googlebot"], "Googlebot forjado"))

    dr = result["date_range"]
    periodo = (
        f'<p class="muted">Período do log: {_esc(dr["start"])} → {_esc(dr["end"])}</p>'
        if dr["start"]
        else ""
    )

    detect = _detection_label(result)
    banner_cls = "info" if result["resolved"] else "warn"
    banner = (
        f'<div class="banner {banner_cls}">Detecção do Googlebot: <b>{_esc(detect)}</b>. '
        "O User-Agent é falsificável; a verificação confiável é por DNS reverso+direto "
        "(<code>--verify-googlebot</code>).</div>"
    )
    if result.get("behind_cdn_suspected"):
        banner += (
            '<div class="banner warn">A maioria dos IPs do Googlebot não tem DNS reverso — '
            "o log provavelmente registra o IP do <b>CDN/proxy</b> (ex.: Cloudflare), não o "
            "do bot. A verificação por IP fica <b>indisponível</b> (isto <b>não</b> é fraude). "
            "Para verificar, registre o IP real do visitante no log "
            "(header <code>CF-Connecting-IP</code>).</div>"
        )
    if not result["has_user_agent"]:
        banner += (
            '<div class="banner warn">Log sem User-Agent (formato <code>common</code>): '
            "não é possível separar bot de humano.</div>"
        )

    chips = ""
    if gb["status_mix"]:
        chips = (
            "<div>"
            + "".join(
                f'<span class="chip{" err" if code[:1] in "45" else ""}">{_esc(code)}: {_fmt(n)}</span>'
                for code, n in sorted(gb["status_mix"].items())
            )
            + "</div>"
        )

    return f"""
<section>
  <h2>Resumo do crawl</h2>
  {banner}
  <div class="grid">{"".join(cards)}</div>
  {periodo}
  {chips}
</section>"""


def _sec_top_paths(result: dict) -> str:
    rows = result["googlebot"]["top_paths"]
    if not rows:
        return ""
    body = ""
    for r in rows:
        last = _esc((r["last_seen"] or "")[:19])
        mix = " ".join(f"{c}:{n}" for c, n in sorted(r["status_mix"].items()))
        body += (
            f'<tr><td class="num">{_fmt(r["hits"])}</td>'
            f'<td class="path">{_esc(r["path"])}</td>'
            f"<td>{last}</td><td>{_esc(mix)}</td></tr>"
        )
    return f"""
<section>
  <h2>URLs mais rastreadas pelo Googlebot</h2>
  <table>
    <thead><tr><th class="num">Hits</th><th>URL</th><th>Último acesso</th><th>Status</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
</section>"""


def _sec_waste(result: dict) -> str:
    gb = result["googlebot"]
    errors, params = gb["top_errors"], gb["top_param"]
    if not errors and not params:
        return ""
    blocks = ""
    if errors:
        rows = "".join(
            f'<tr><td class="num danger">{_fmt(r["hits"])}</td><td class="path">{_esc(r["path"])}</td></tr>'
            for r in errors
        )
        blocks += (
            "<h2>Crawl desperdiçado em erros (status ≥ 400)</h2>"
            f'<table><thead><tr><th class="num">Hits</th><th>URL</th></tr></thead><tbody>{rows}</tbody></table>'
        )
    if params:
        rows = "".join(
            f'<tr><td class="num">{_fmt(r["hits"])}</td><td class="path">{_esc(r["path"])}</td></tr>'
            for r in params
        )
        blocks += (
            '<h2 style="margin-top:18px">Crawl em URLs com parâmetro (possível duplicata)</h2>'
            f'<table><thead><tr><th class="num">Hits</th><th>URL</th></tr></thead><tbody>{rows}</tbody></table>'
        )
    return f"<section>{blocks}</section>"


def _sec_never(result: dict) -> str:
    nc = result.get("never_crawled")
    if not nc:
        return ""
    items = "".join(f'<li class="path">{_esc(u)}</li>' for u in nc["urls"][:200])
    extra = (
        f'<p class="muted">... (+{nc["never"] - 200} URLs no .txt/.csv)</p>'
        if nc["never"] > 200
        else ""
    )
    return f"""
<section>
  <h2>Sitemap nunca rastreado no período</h2>
  <p class="muted"><b class="danger">{_fmt(nc["never"])}</b> de {_fmt(nc["sitemap_total"])} URLs do sitemap não receberam nenhum hit do Googlebot.</p>
  <ul style="margin-top:8px;padding-left:20px;line-height:1.7">{items}</ul>
  {extra}
</section>"""


def _sec_money(result: dict) -> str:
    um = result.get("undercrawled_money")
    if not um:
        return ""
    body = ""
    for r in um:
        pos = f"{r['position']:.1f}" if isinstance(r["position"], (int, float)) else "–"
        body += (
            f'<tr><td class="num">{_fmt(r["impressions"])}</td><td class="num">{_esc(pos)}</td>'
            f'<td class="num danger">{_fmt(r["crawl_hits"])}</td>'
            f'<td class="path">{_esc(r["url"])}</td></tr>'
        )
    return f"""
<section>
  <h2>Money pages subcrawladas</h2>
  <p class="muted">URLs com muitas impressões no GSC mas <b class="danger">zero</b> crawl do Googlebot no período — candidatas prioritárias a investigar.</p>
  <table>
    <thead><tr><th class="num">Impressões</th><th class="num">Posição</th><th class="num">Crawl</th><th>URL</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
</section>"""


def generate_crawl_html(result: dict, domain: str, date: str) -> str:
    body = (
        _sec_resumo(result)
        + _sec_top_paths(result)
        + _sec_waste(result)
        + _sec_money(result)
        + _sec_never(result)
    )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crawl Budget — {_esc(domain)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>🕷️ Crawl Budget — {_esc(domain)}</h1>
  <div class="meta">Gerado em {_esc(date)} · análise local do access log · sem cota de API</div>
</header>
<main>{body}</main>
</body>
</html>"""
