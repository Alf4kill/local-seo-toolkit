"""
report.py — Relatórios dos clusters semânticos: console + HTML.

Grupos com 2+ páginas = páginas de mesma intenção competindo (candidatas a
consolidação). O "representante" é a página mais central, sugerida como canônica.
"""

import html as H

_LLM_BADGE = {
    "spun": ("#b03030", "#FFE0E0", "SPUN — mesmo texto reescrito"),
    "raso": ("#b06000", "#FFF2CC", "RASO — pouco conteúdo útil"),
    "ok": ("#2d8c5e", "#E6F4EA", "OK — páginas distintas"),
}


def _llm_html(c: dict) -> str:
    """Bloco HTML com o veredito do LLM para um grupo (vazio se não houver)."""
    l = c.get("llm")
    if not l:
        return ""
    fg, bg, lbl = _LLM_BADGE.get(l.get("verdict"), ("#555", "#eee", l.get("verdict", "?")))
    base = H.escape(l.get("base_recomendada") or "")
    resumo = H.escape(l.get("resumo") or "")
    gaps = "".join(f"<li>{H.escape(g)}</li>" for g in (l.get("lacunas") or [])[:5])
    return (
        f'<div style="margin-top:8px;padding:8px 10px;background:{bg};border-radius:6px;font-size:12px">'
        f'<b style="color:{fg}">🤖 {H.escape(lbl)}</b>'
        + (f" · base sugerida: <b>{base}</b>" if base else "")
        + (f'<div style="color:#444;margin-top:3px">{resumo}</div>' if resumo else "")
        + (f'<ul style="margin:4px 0 0 16px;color:#555">{gaps}</ul>' if gaps else "")
        + "</div>"
    )


_PAPEL_BADGE = {
    "cabeca": ("#1F4E79", "#E6EEF7", "CABEÇA"),
    "spoke": ("#2d8c5e", "#E6F4EA", "spoke"),
    "duplicado_real": ("#b03030", "#FFE0E0", "duplicado → canonical"),
}


def _diff_html(c: dict) -> str:
    """Bloco HTML com o plano de DIFERENCIAÇÃO de um grupo (vazio se não houver)."""
    d = c.get("diff")
    if not d or not d.get("paginas"):
        return ""
    rows = ""
    for p in d["paginas"]:
        fg, bg, lbl = _PAPEL_BADGE.get(p.get("papel"), ("#555", "#eee", p.get("papel", "")))
        rows += (
            '<tr style="border-top:1px solid #e3edf9">'
            f'<td style="padding:4px 6px;vertical-align:top"><span style="background:{bg};color:{fg};'
            f'padding:1px 6px;border-radius:4px;font-size:11px;font-weight:700">{H.escape(lbl)}</span></td>'
            f'<td style="padding:4px 6px;font-family:monospace;font-size:11px;vertical-align:top">{H.escape(p.get("slug", ""))}</td>'
            f'<td style="padding:4px 6px;vertical-align:top"><b>{H.escape(p.get("keyword_alvo", ""))}</b>'
            f'<div style="color:#666;font-size:11px">{H.escape(p.get("intencao", ""))}</div></td>'
            f'<td style="padding:4px 6px;font-size:12px;vertical-align:top">{H.escape(p.get("titulo", ""))}'
            f'<div style="color:#777;margin-top:2px;font-size:11px">{H.escape(p.get("foco", ""))}</div></td>'
            "</tr>"
        )
    omit = ""
    if d.get("omitidas"):
        omit = (
            f'<div style="font-size:11px;color:#b06000;margin-top:6px">+{len(d["omitidas"])} '
            f"página(s) sem intenção distinta → candidatas a <b>rel=canonical</b> (não 301): "
            f"{H.escape(', '.join(d['omitidas']))}</div>"
        )
    return (
        '<div style="margin-top:8px;padding:8px 10px;background:#f3f8ff;border:1px solid #d6e4f5;border-radius:6px">'
        '<b style="color:#1F4E79;font-size:12px">🧩 Plano de diferenciação — manter todas, sem 301</b>'
        '<table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">'
        '<thead><tr style="color:#888;text-align:left;font-size:11px">'
        '<th style="padding:0 6px">Papel</th><th style="padding:0 6px">Slug</th>'
        '<th style="padding:0 6px">Nova keyword / intenção</th><th style="padding:0 6px">Título + foco</th>'
        f"</tr></thead><tbody>{rows}</tbody></table>{omit}</div>"
    )


def _collisions_html(collisions: list) -> str:
    """Seção HTML (global) com as colisões de keyword entre grupos. Vazio se não houver."""
    if not collisions:
        return ""
    rows = ""
    for col in collisions:
        mem = ""
        for m in col["members"]:
            keep = m["cluster"] == col["owner"]["cluster"] and m["slug"] == col["owner"]["slug"]
            tag = (
                '<b style="color:#1e7a1e">← mantém</b>'
                if keep
                else '<span style="color:#b03030">→ nova keyword</span>'
            )
            mem += (
                f'<div style="font-family:monospace;font-size:11px">[g{m["cluster"]}] '
                f"{H.escape(m['slug'])} {tag}</div>"
            )
        badge = "#b03030" if col["kind"] == "exata" else "#b06000"
        rows += (
            '<tr style="border-top:1px solid #f0dada">'
            f'<td style="padding:5px 8px;vertical-align:top"><span style="background:{badge};color:#fff;'
            f'padding:1px 6px;border-radius:4px;font-size:11px">{col["kind"]}</span></td>'
            f'<td style="padding:5px 8px;vertical-align:top"><b>{H.escape(col["keyword"])}</b></td>'
            f'<td style="padding:5px 8px;vertical-align:top">{mem}</td>'
            f'<td style="padding:5px 8px;text-align:right;vertical-align:top">{col["impr_total"]:,}</td></tr>'
        )
    return (
        "<section>"
        "<h2>⚠ Colisões de keyword entre grupos</h2>"
        '<p class="note">A diferenciação roda um grupo por vez, então grupos diferentes podem cair na '
        "MESMA keyword (ou em uma quase igual) e voltar a competir. A página de maior tráfego "
        "<b>mantém</b> a keyword; as outras precisam de uma keyword distinta. Resolva antes de entregar.</p>"
        '<table style="width:100%;border-collapse:collapse;font-size:13px">'
        '<thead><tr style="background:#b03030;color:#fff">'
        '<th style="text-align:left;padding:5px 8px">Tipo</th>'
        '<th style="text-align:left;padding:5px 8px">Keyword em conflito</th>'
        '<th style="text-align:left;padding:5px 8px">Páginas</th>'
        '<th style="padding:5px 8px">Impr.</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></section>"
    )


def _link_plan_html(c: dict) -> str:
    """Bloco HTML com o plano de links hub-and-spoke de um grupo (vazio se não houver)."""
    p = c.get("link_plan")
    if not p:
        return ""
    hub = H.escape(p["hub"])
    anchor = H.escape(p.get("hub_keyword") or p["hub"].replace("-", " "))
    if p.get("complete"):
        return (
            '<div style="margin-top:8px;padding:8px 10px;background:#E6F4EA;border-radius:6px;font-size:12px">'
            f'<b style="color:#2d8c5e">🔗 Backbone de links OK</b> — os spokes já linkam a cabeça '
            f"<b>{hub}</b> e vice-versa.</div>"
        )
    items = ""
    if p.get("missing_spoke_to_hub"):
        lis = "".join(
            f"<li><code>{H.escape(s)}</code> → <code>{hub}</code> (âncora: <b>{anchor}</b>)</li>"
            for s in p["missing_spoke_to_hub"]
        )
        items += (
            f'<div style="margin-top:5px"><b style="color:#b03030">Faltam links spoke → cabeça '
            f"({len(p['missing_spoke_to_hub'])})</b> — o essencial p/ a cabeça concentrar autoridade:"
            f'<ul style="margin:3px 0 0 16px">{lis}</ul></div>'
        )
    if p.get("missing_hub_to_spoke"):
        lis = "".join(
            f"<li><code>{hub}</code> → <code>{H.escape(s)}</code></li>"
            for s in p["missing_hub_to_spoke"]
        )
        items += (
            f'<div style="margin-top:5px"><b style="color:#b06000">Faltam links cabeça → spoke '
            f'({len(p["missing_hub_to_spoke"])})</b>:<ul style="margin:3px 0 0 16px">{lis}</ul></div>'
        )
    return (
        '<div style="margin-top:8px;padding:8px 10px;background:#f3f8ff;border:1px solid #d6e4f5;border-radius:6px;font-size:12px">'
        f'<b style="color:#1F4E79">🔗 Plano de links internos (hub-and-spoke) — cabeça: {hub}</b>'
        f"{items}</div>"
    )


def _ul_cols(items: list, empty: str) -> str:
    if not items:
        return f"<li style='list-style:none;margin-left:-16px;color:#2d8c5e'>{empty}</li>"
    return "".join(f"<li>{H.escape(x)}</li>" for x in items)


def _linkgraph_html(lg: dict) -> str:
    """Seção HTML (global) com o audit do grafo de links internos. Vazio se não houver."""
    if not lg:
        return ""
    orphans = lg.get("orphans") or []
    template_only = lg.get("template_only") or []
    money = lg.get("money") or []
    anchors = lg.get("anchors") or []
    cls = lg.get("classification")

    # Resumo em 3 níveis (quando temos a classificação template-aware).
    summary = ""
    if cls is not None:
        n_ctx = sum(1 for c in cls.values() if c["tier"] == "contextual")
        chip = (
            '<span style="padding:3px 9px;border-radius:12px;font-size:12px;font-weight:700;'
            'background:{bg};color:{fg}">{n} {lbl}</span>'
        )
        summary = (
            '<div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 4px">'
            + chip.format(bg="#E6F4EA", fg="#2d8c5e", n=n_ctx, lbl="com link contextual")
            + chip.format(bg="#FFF2CC", fg="#b06000", n=len(template_only), lbl="só índice/widget")
            + chip.format(bg="#FFE0E0", fg="#b03030", n=len(orphans), lbl="órfãs de fato")
            + "</div>"
        )

    tmpl_block = ""
    if template_only:
        tmpl_block = (
            f'<h3 style="font-size:13px;color:#b06000;margin:16px 0 6px">🔸 Sem link contextual '
            f"({len(template_only)}) — alcançadas só pelo índice (blog.php) e/ou pelo widget de "
            f"“relacionados”</h3>"
            '<p class="note">Não são órfãs (o índice/array as linka), mas não recebem nenhum link '
            "<b>editorial/contextual</b> de dentro de outro artigo — que é o link que de fato passa "
            "autoridade. É aqui que o plano hub-and-spoke atua.</p>"
            f'<ul style="columns:2;font-family:monospace;font-size:12px;line-height:1.7;margin:0 0 0 18px">'
            f"{_ul_cols(template_only[:40], '')}</ul>"
            + (
                f'<div style="font-size:11px;color:#888">+{len(template_only) - 40} outras</div>'
                if len(template_only) > 40
                else ""
            )
        )

    money_block = ""
    if money:

        def tier_tag(slug):
            t = (cls or {}).get(slug, {}).get("tier")
            if t == "orphan":
                return '<span style="color:#b03030">órfã</span>'
            if t == "template_only":
                return '<span style="color:#b06000">índice/widget</span>'
            return ""

        rows = "".join(
            f'<tr><td style="font-family:monospace;font-size:12px">{H.escape(m["slug"])}</td>'
            f'<td style="text-align:center;color:#b03030;font-weight:700">{m["inlinks"]}</td>'
            f'<td style="text-align:center;font-size:11px">{tier_tag(m["slug"])}</td>'
            f'<td style="text-align:right">{m["clicks"]:,}</td>'
            f'<td style="text-align:right">{m["impressions"]:,}</td></tr>'
            for m in money[:20]
        )
        money_block = (
            '<h3 style="font-size:13px;color:#1F4E79;margin:16px 0 6px">💰 Money-pages sem link contextual '
            "(tráfego real no GSC, 0 link editorial de entrada)</h3>"
            '<table style="width:100%;border-collapse:collapse;font-size:13px">'
            '<thead><tr style="color:#888;text-align:left;font-size:11px">'
            '<th style="padding:0 6px">Página</th><th style="padding:0 6px;text-align:center">Contextual in</th>'
            '<th style="padding:0 6px;text-align:center">Alcance</th>'
            '<th style="padding:0 6px;text-align:right">Cliques</th>'
            '<th style="padding:0 6px;text-align:right">Impressões</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )

    anchor_block = ""
    if anchors:
        rows = "".join(
            f'<tr><td style="padding:4px 6px"><b>{H.escape(a["anchor"])}</b></td>'
            f'<td style="padding:4px 6px;font-family:monospace;font-size:11px">{H.escape(", ".join(a["targets"]))}</td>'
            f'<td style="padding:4px 6px;text-align:center">{a["n"]}</td></tr>'
            for a in anchors[:20]
        )
        anchor_block = (
            '<h3 style="font-size:13px;color:#1F4E79;margin:16px 0 6px">⚓ Canibalização de âncora '
            "(mesmo texto-âncora → páginas diferentes)</h3>"
            '<table style="width:100%;border-collapse:collapse;font-size:13px">'
            '<thead><tr style="color:#888;text-align:left;font-size:11px">'
            '<th style="padding:0 6px">Âncora</th><th style="padding:0 6px">Aponta para</th>'
            '<th style="padding:0 6px;text-align:center">Nº destinos</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )

    orphan_block = (
        f'<h3 style="font-size:13px;color:#b03030;margin:16px 0 6px">🕳️ Órfãs de fato ({len(orphans)}) '
        "— nenhum link, nem de índice/widget</h3>"
        f'<ul style="columns:2;font-family:monospace;font-size:12px;line-height:1.7;margin:0 0 0 18px">'
        f"{_ul_cols(orphans, 'nenhuma 🎉')}</ul>"
    )

    return (
        "<section>"
        "<h2>🔗 Links internos</h2>"
        f'<p class="note">Grafo de {lg.get("n_edges", 0):,} links <b>contextuais (de corpo)</b> entre '
        f"{lg.get('n_sources', 0)} páginas. Links gerados por template/array do primeWeb — o índice "
        "<code>blog.php</code> (<code>foreach&nbsp;$blog</code> → linka todos os artigos) e o widget de "
        "“relacionados” (<code>array_rand</code>) — são contados à parte como <b>índice/widget</b>, "
        "porque passam pouca autoridade. O que falta nesses artigos é link <b>contextual</b>. "
        "(Para o grafo já renderizado, com o menu, rode com <code>--urls</code> no site no ar.)</p>"
        f"{summary}{tmpl_block}{money_block}{anchor_block}{orphan_block}"
        "</section>"
    )


def print_clusters(clusters: list, backend: str, threshold: float) -> None:
    multi = [c for c in clusters if c["size"] >= 2]
    singles = [c for c in clusters if c["size"] == 1]
    total_pages = sum(c["size"] for c in clusters)

    print("\n" + "=" * 72)
    print(f"  CLUSTERS SEMÂNTICOS  ({backend}, limiar {threshold})")
    print(
        f"  {total_pages} páginas → {len(clusters)} grupos "
        f"({len(multi)} com 2+ páginas, {len(singles)} únicas)"
    )
    print("=" * 72)

    for i, c in enumerate(multi, 1):
        print(f"\n  [{i}] {c['size']} páginas · coesão {c['cohesion']:.2f}")
        print(f"      canônica sugerida: {c['representative']}")
        for m in c["members"]:
            mark = "  ◀ manter" if m == c["representative"] else ""
            print(f"        - {m}{mark}")

    print(f"\n  + {len(singles)} páginas sem grupo (conteúdo único — ok).")
    print("=" * 72 + "\n")


def print_nearest(pairs: list) -> None:
    print("  Pares mais similares (inspeção de duplicatas):")
    for sim, a, b in pairs:
        print(f"    {sim:.3f}   {a}")
        print(f"            {b}")
    print()


def _intro_html(
    clusters: list, has_gsc: bool, linkgraph: dict = None, collisions: list = None
) -> str:
    """Bloco amigável (não-técnico): o que é o relatório, como foi feito e glossário.
    Adapta os passos e os termos ao que o relatório realmente contém."""
    has_diff = any((c.get("diff") or {}).get("paginas") for c in clusters)
    has_llm = any(c.get("llm") for c in clusters)
    has_links = bool(linkgraph)
    has_coll = bool(collisions)

    steps = [
        "Lemos o <b>texto de todas as páginas</b> do site — nada é enviado para fora, roda tudo no computador, sem custo.",
        "Agrupamos as páginas <b>por significado</b>, com inteligência artificial, para achar as que falam do mesmo assunto e <b>competem entre si</b> no Google (mesmo quando usam palavras diferentes).",
    ]
    if has_gsc:
        steps.append(
            "Cruzamos com o <b>Google Search Console</b> (cliques, impressões e posição reais) para ver qual página de cada grupo já tem o melhor desempenho."
        )
    if has_diff:
        steps.append(
            "Uma IA local sugeriu, para cada grupo, um <b>assunto, título e palavra-chave únicos por página</b> — assim elas param de competir <b>sem precisar apagar nenhuma</b>."
        )
    elif has_llm:
        steps.append(
            "Uma IA local <b>leu cada grupo</b> e deu um diagnóstico (se as páginas são mesmo repetidas e o que falta nelas)."
        )
    if has_links:
        steps.append(
            "Mapeamos os <b>links internos</b> do site para mostrar quais páginas estão “soltas” e quais links conviria criar."
        )
    steps_html = "".join(f"<li>{s}</li>" for s in steps)

    gloss = [
        (
            "Canibalização",
            "Quando várias páginas do mesmo site disputam a mesma busca no Google. Elas dividem a força entre si e nenhuma fica bem posicionada.",
        ),
        (
            "Grupo de mesma intenção",
            "Conjunto de páginas que o sistema entendeu que falam da mesma coisa — as candidatas a competir entre si.",
        ),
        (
            "Coesão",
            "O quanto as páginas de um grupo são parecidas (de 0 a 1). Quanto mais alta, mais parecidas.",
        ),
    ]
    if has_gsc:
        gloss.append(
            (
                "Impressões, cliques e posição",
                "Dados reais do Google: quantas vezes a página apareceu nas buscas, quantos cliques recebeu e em que posição média ficou.",
            )
        )
        gloss.append(
            (
                "MANTER / página canônica",
                "A página mais forte do grupo (a que o Google já prefere). É a candidata natural a “cabeça” do tema.",
            )
        )
    if has_diff:
        gloss.append(
            (
                "Diferenciação: cabeça e spokes",
                "Em vez de apagar páginas, damos a cada uma um ângulo único. A <b>cabeça</b> é a página principal do tema; os <b>spokes</b> são páginas-satélite com recortes específicos que apontam para a cabeça.",
            )
        )
    if has_gsc:
        if has_diff:
            gloss.append(
                (
                    "301 — e por que NÃO usamos aqui",
                    "“301” é redirecionar (apagar) uma página para outra. Como o objetivo é <b>não perder páginas</b>, usamos a Diferenciação no lugar. A tabela de desempenho serve só para escolher a “cabeça” de cada grupo.",
                )
            )
        else:
            gloss.append(
                (
                    "301 (redirecionamento)",
                    "Redirecionar uma página para outra: a antiga deixa de existir e a força vai para a que fica. É a forma clássica de resolver páginas duplicadas — só faça se puder perder aquela URL.",
                )
            )
    if has_links:
        gloss.append(
            (
                "Link contextual × link de índice/widget",
                "Contextual = link dentro do <b>texto</b> de um artigo apontando para outro (vale muito para o Google). Índice/widget = link automático de listas, menus ou “veja também” (vale pouco).",
            )
        )
        gloss.append(
            (
                "Sem link contextual",
                "A página é alcançável (pelo índice/menu), mas <b>nenhum artigo a cita no corpo do texto</b> — então recebe pouca força interna.",
            )
        )
        gloss.append(
            (
                "Plano de links (hub-and-spoke)",
                "Os links que faltam criar: cada página-satélite (spoke) deve linkar para a página principal (cabeça), usando a palavra-chave dela como texto do link.",
            )
        )
        gloss.append(
            (
                "Money-page",
                "Página que já recebe tráfego real do Google — vale a pena priorizar o reforço dela.",
            )
        )
    if has_coll:
        gloss.append(
            (
                "Colisão de palavra-chave",
                "Quando o plano acaba sugerindo a MESMA palavra-chave para duas páginas — precisa de um ajuste para elas não voltarem a competir.",
            )
        )
    gloss_html = "".join(f"<li><b>{t}</b> — {d}</li>" for t, d in gloss)

    return f"""
  <section style="border-left:5px solid #2e6da4;background:#f7fbff">
    <h2>📖 Como ler este relatório</h2>
    <p style="font-size:14px;color:#333;margin:0 0 4px">
      Este relatório aponta <b>páginas do site que competem entre si no Google</b> (tratam do mesmo
      assunto) e o que fazer para resolver isso — de preferência <b>sem perder nenhuma página</b>.
    </p>
    <h3 style="font-size:14px;color:#1F4E79;margin:14px 0 6px">Como foi feito</h3>
    <ol style="font-size:13px;color:#444;line-height:1.6;margin:0 0 6px 18px">{steps_html}</ol>
    <h3 style="font-size:14px;color:#1F4E79;margin:14px 0 6px">O que cada termo significa</h3>
    <ul style="font-size:13px;color:#444;line-height:1.7;margin:0 0 0 18px">{gloss_html}</ul>
  </section>"""


def generate_html(
    clusters: list,
    title: str,
    backend: str,
    threshold: float,
    collisions: list = None,
    linkgraph: dict = None,
) -> str:
    multi = [c for c in clusters if c["size"] >= 2]
    singles = [c for c in clusters if c["size"] == 1]
    total = sum(c["size"] for c in clusters)

    def color(size):
        if size >= 5:
            return "#b03030"  # vermelho — duplicação grave
        if size >= 3:
            return "#b06000"  # laranja
        return "#2d8c5e"  # verde — par

    cards = ""
    for i, c in enumerate(multi, 1):
        col = color(c["size"])
        members = "".join(
            f'<li style="{"font-weight:700;color:#1F4E79" if m == c["representative"] else ""}">'
            f"{H.escape(m)}{' — manter (canônica sugerida)' if m == c['representative'] else ''}</li>"
            for m in c["members"]
        )
        cards += f"""
    <div style="border:1px solid #e0e6ee;border-left:5px solid {col};border-radius:8px;padding:14px;margin-bottom:12px">
      <div style="font-weight:700;color:{col}">Grupo {i} — {c["size"]} páginas · coesão {c["cohesion"]:.2f}</div>
      <ul style="margin:8px 0 0 18px;font-family:monospace;font-size:13px;line-height:1.6">{members}</ul>
      {_llm_html(c)}
      {_diff_html(c)}
      {_link_plan_html(c)}
    </div>"""

    singles_html = "".join(f"<li>{H.escape(c['members'][0])}</li>" for c in singles)

    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clusters Semânticos — {H.escape(title)}</title>
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;color:#333;margin:0;font-size:14px}}
header{{background:linear-gradient(135deg,#1F4E79,#2e6da4);color:#fff;padding:24px 32px}}
header h1{{font-size:21px;margin:0 0 4px}} header .meta{{opacity:.85;font-size:13px}}
main{{max-width:1000px;margin:0 auto;padding:24px 16px}}
section{{background:#fff;border-radius:10px;padding:22px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
h2{{font-size:16px;color:#1F4E79;margin:0 0 14px;border-bottom:2px solid #e8f0fe;padding-bottom:8px}}
.note{{background:#fff8e1;border-left:3px solid #ffc107;padding:8px 12px;border-radius:4px;font-size:12px;color:#666}}
</style></head><body>
<header>
  <h1>🧭 Clusters Semânticos — {H.escape(title)}</h1>
  <div class="meta">{backend} · limiar {threshold} · {total} páginas · {len(multi)} grupos de duplicação · {len(singles)} únicas</div>
</header>
<main>
  {_intro_html(clusters, False, linkgraph, collisions)}
  {_collisions_html(collisions)}
  {_linkgraph_html(linkgraph)}
  <section>
    <h2>⚡ Grupos de mesma intenção ({len(multi)})</h2>
    <p class="note">Páginas que o modelo considera semanticamente equivalentes — competem entre si (canibalização / doorway pages). Consolidar cada grupo em uma página forte e redirecionar (301) as demais para a “canônica sugerida”.</p>
    {cards if cards else "<p>Nenhum grupo de duplicação no limiar atual.</p>"}
  </section>
  <section>
    <h2>✅ Páginas únicas ({len(singles)})</h2>
    <ul style="columns:2;font-family:monospace;font-size:12px;line-height:1.7">{singles_html}</ul>
  </section>
</main></body></html>"""


# ---------------------------------------------------------------------------
# Relatórios cruzados com GSC (canônica por performance real)
# ---------------------------------------------------------------------------


def print_clusters_gsc(clusters: list, backend: str, threshold: float) -> None:
    multi = [c for c in clusters if c["size"] >= 2]
    multi.sort(key=lambda c: -c.get("group_impressions", 0))
    print("\n" + "=" * 80)
    print(f"  CLUSTERS + GSC  ({backend}, limiar {threshold})")
    print(f"  {len(multi)} grupos de duplicação — ordenados por impressões em disputa")
    print("=" * 80)
    for i, c in enumerate(multi, 1):
        diff = "   ⚠ difere da página central do cluster" if c.get("canonical_differs") else ""
        print(
            f"\n[{i}] {c['size']} págs · coesão {c['cohesion']:.2f} · "
            f"{c['group_clicks']} cliques / {c['group_impressions']:,} impressões no grupo"
        )
        print(f"     MANTER (melhor performance): {c['canonical_by_performance']}{diff}")
        for m in c["members_gsc"]:
            keep = m["slug"] == c["canonical_by_performance"]
            pos = f"{m['position']:.1f}" if m.get("position") is not None else "s/d"
            tag = "KEEP " if keep else "301->"
            print(
                f"       {tag} pos {pos:>5} | {m['clicks']:>4} cli | {m['impressions']:>7,} impr  {m['slug']}"
            )
    print("=" * 80 + "\n")


def generate_html_gsc(
    clusters: list,
    title: str,
    backend: str,
    threshold: float,
    gsc_name: str,
    collisions: list = None,
    linkgraph: dict = None,
) -> str:
    multi = [c for c in clusters if c["size"] >= 2]
    multi.sort(key=lambda c: -c.get("group_impressions", 0))
    tot_clicks = sum(c.get("group_clicks", 0) for c in multi)
    tot_impr = sum(c.get("group_impressions", 0) for c in multi)

    # Quando há plano de diferenciação, o "301" não é a recomendação (não se apaga
    # página): a tabela serve para escolher a "cabeça". Ajusta título/nota p/ não confundir.
    has_diff = any((c.get("diff") or {}).get("paginas") for c in multi)
    if has_diff:
        cons_title = (
            f"⚡ Grupos que competem ({len(multi)}) — a tabela mostra a página "
            "mais forte (a “cabeça”)"
        )
        cons_note = (
            "Em cada grupo, a página <b>✅ MANTER</b> é a de melhor desempenho real no GSC — "
            "use-a como <b>cabeça</b> do tema. Como o objetivo é <b>não apagar páginas</b>, siga o "
            "<b>🧩 Plano de diferenciação</b> dentro de cada grupo (dá um assunto único a cada "
            "página) em vez do 301. As marcas “301 →” abaixo são só referência — não execute o 301."
        )
    else:
        cons_title = f"⚡ Grupos de duplicação ({len(multi)}) — manter a melhor, 301 o resto"
        cons_note = (
            "Em cada grupo, a página marcada <b>✅ MANTER</b> é a de melhor performance real no GSC "
            "(cliques → impressões → posição). Redirecione (301) as demais para ela. Quando a "
            "“manter” difere da página central do cluster, é porque o conteúdo mais representativo "
            "não é o que melhor ranqueia."
        )

    blocks = ""
    for i, c in enumerate(multi, 1):
        rows = ""
        for m in c["members_gsc"]:
            keep = m["slug"] == c["canonical_by_performance"]
            pos = f"{m['position']:.1f}" if m.get("position") is not None else "—"
            rows += (
                f'<tr style="background:{"#e6f4ea" if keep else "#fff"}">'
                f'<td style="font-weight:{"700" if keep else "400"};color:{"#1e7a1e" if keep else "#b03030"}">'
                f"{'✅ MANTER' if keep else '301 →'}</td>"
                f'<td style="font-family:monospace;font-size:12px">{H.escape(m["slug"])}</td>'
                f'<td style="text-align:center">{pos}</td>'
                f'<td style="text-align:right">{m["clicks"]:,}</td>'
                f'<td style="text-align:right">{m["impressions"]:,}</td></tr>'
            )
        diff = (
            ' <span style="color:#b06000">(≠ página central do cluster)</span>'
            if c.get("canonical_differs")
            else ""
        )
        blocks += f"""
    <div style="border:1px solid #e0e6ee;border-radius:8px;padding:14px;margin-bottom:14px">
      <div style="font-weight:700;color:#1F4E79;font-size:14px">Grupo {i} — {c["size"]} páginas · coesão {c["cohesion"]:.2f}</div>
      <div style="font-size:12px;color:#555;margin:3px 0 8px">{c["group_clicks"]} cliques / {c["group_impressions"]:,} impressões em disputa · manter: <b>{H.escape(c["canonical_by_performance"])}</b>{diff}</div>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:#1F4E79;color:#fff">
          <th style="text-align:left;padding:5px 8px">Ação</th><th style="text-align:left;padding:5px 8px">URL (slug)</th>
          <th style="padding:5px">Posição</th><th style="padding:5px">Cliques</th><th style="padding:5px">Impressões</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      {_llm_html(c)}
      {_diff_html(c)}
      {_link_plan_html(c)}
    </div>"""

    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Consolidação (Clusters + GSC) — {H.escape(title)}</title>
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;color:#333;margin:0;font-size:14px}}
header{{background:linear-gradient(135deg,#1F4E79,#2e6da4);color:#fff;padding:24px 32px}}
header h1{{font-size:21px;margin:0 0 4px}} header .meta{{opacity:.85;font-size:13px}}
main{{max-width:1000px;margin:0 auto;padding:24px 16px}}
section{{background:#fff;border-radius:10px;padding:22px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
h2{{font-size:16px;color:#1F4E79;margin:0 0 14px;border-bottom:2px solid #e8f0fe;padding-bottom:8px}}
th{{font-weight:600}} td{{padding:5px 8px;border-bottom:1px solid #eef2f7}}
.note{{background:#fff8e1;border-left:3px solid #ffc107;padding:8px 12px;border-radius:4px;font-size:12px;color:#666}}
</style></head><body>
<header>
  <h1>🧭 Plano de Consolidação — {H.escape(title)}</h1>
  <div class="meta">{backend} · limiar {threshold} · cruzado com {H.escape(gsc_name)} · {len(multi)} grupos · {tot_clicks:,} cliques / {tot_impr:,} impressões fragmentados</div>
</header>
<main>
  {_intro_html(clusters, True, linkgraph, collisions)}
  {_collisions_html(collisions)}
  {_linkgraph_html(linkgraph)}
  <section>
    <h2>{cons_title}</h2>
    <p class="note">{cons_note}</p>
    {blocks if blocks else "<p>Nenhum grupo no limiar atual.</p>"}
  </section>
</main></body></html>"""


# ---------------------------------------------------------------------------
# Julgamento LLM (camada hybrid)
# ---------------------------------------------------------------------------


def print_llm_judgments(judged: list) -> None:
    if not judged:
        return
    VERD = {
        "spun": "⚠ SPUN (mesmo texto reescrito)",
        "raso": "⚠ RASO (pouco conteúdo útil)",
        "ok": "✓ OK (páginas distintas)",
    }
    print("\n" + "=" * 78)
    print(f"  JULGAMENTO LLM — {len(judged)} grupo(s)")
    print("=" * 78)
    for i, c in enumerate(judged, 1):
        l = c["llm"]
        print(
            f"\n[{i}] {c['size']} págs · coesão {c['cohesion']:.2f} · {VERD.get(l['verdict'], l['verdict'])}"
        )
        if l.get("base_recomendada"):
            print(f"     base p/ consolidar: {l['base_recomendada']}")
        if l.get("resumo"):
            print(f"     {l['resumo']}")
        for g in (l.get("lacunas") or [])[:5]:
            print(f"       • falta: {g}")
        if not l.get("raw_ok"):
            print("     (⚠ modelo não retornou JSON limpo — veja 'resumo')")
    print("=" * 78 + "\n")


def print_differentiation(diffed: list) -> None:
    if not diffed:
        return
    PAPEL = {"cabeca": "CABEÇA", "spoke": "spoke", "duplicado_real": "DUPLICADO→canonical"}
    print("\n" + "=" * 78)
    print(f"  PLANO DE DIFERENCIAÇÃO — {len(diffed)} grupo(s)  (mantém todas as páginas, sem 301)")
    print("=" * 78)
    for i, c in enumerate(diffed, 1):
        d = c["diff"]
        print(
            f"\n[{i}] {c['size']} págs · coesão {c['cohesion']:.2f} · cabeça: {d.get('cabeca', '?')}"
        )
        if not d.get("raw_ok"):
            print("     (⚠ modelo não retornou JSON limpo — veja 'resumo')")
            if d.get("resumo"):
                print(f"     {d['resumo']}")
        for p in d.get("paginas", []):
            print(f"     [{PAPEL.get(p['papel'], p['papel'])}] {p['slug']}")
            print(f"        keyword: {p['keyword_alvo']}  |  intenção: {p['intencao']}")
            print(f"        título : {p['titulo']}")
            if p.get("foco"):
                print(f"        foco   : {p['foco']}")
        if d.get("omitidas"):
            print(
                f"     +{len(d['omitidas'])} sem intenção distinta → rel=canonical (não 301): "
                f"{', '.join(d['omitidas'])}"
            )
    print("=" * 78 + "\n")


def print_keyword_collisions(collisions: list) -> None:
    if not collisions:
        return
    print("\n" + "=" * 78)
    print(f"  COLISÕES DE KEYWORD ENTRE GRUPOS — {len(collisions)}")
    print("  (a diferenciação roda por grupo; a de maior tráfego mantém a keyword)")
    print("=" * 78)
    for i, col in enumerate(collisions, 1):
        scope = "cross-cluster" if col.get("cross") else "mesmo grupo"
        print(
            f'\n[{i}] {col["kind"].upper()} ({scope}) · "{col["keyword"]}" · '
            f"{col['impr_total']:,} impr em disputa"
        )
        for m in col["members"]:
            keep = m["cluster"] == col["owner"]["cluster"] and m["slug"] == col["owner"]["slug"]
            tag = "MANTÉM" if keep else "NOVA  "
            print(f"     {tag} [g{m['cluster']}] {m['slug']}  ({m['keyword_alvo']})")
    print("=" * 78 + "\n")


def print_link_audit(lg: dict) -> None:
    """Audit do grafo de links internos: órfãs, money-pages sub-linkadas, âncora."""
    if not lg:
        return
    orphans = lg.get("orphans") or []
    template_only = lg.get("template_only") or []
    money = lg.get("money") or []
    anchors = lg.get("anchors") or []
    cls = lg.get("classification")
    print("\n" + "=" * 78)
    print(
        f"  LINKS INTERNOS — {lg.get('n_edges', 0):,} links CONTEXTUAIS (de corpo) entre {lg.get('n_sources', 0)} páginas"
    )
    print(
        "  (links de índice blog.php/widget array_rand contam à parte; menu via include não entra)"
    )
    print("=" * 78)

    if cls is not None:
        n_ctx = sum(1 for c in cls.values() if c["tier"] == "contextual")
        print(f"\n  Classificação das {len(cls)} páginas analisadas:")
        print(f"     {n_ctx:>4}  com link CONTEXTUAL (editorial, de dentro de outro artigo)")
        print(
            f"     {len(template_only):>4}  SÓ índice/widget (não-órfãs, mas sem link editorial) <- foco do hub-and-spoke"
        )
        print(f"     {len(orphans):>4}  órfãs de fato (nenhum link, nem de índice/widget)")
        for o in orphans[:40]:
            print(f"          - {o}")
        if len(orphans) > 40:
            print(f"          (+{len(orphans) - 40} outras)")
    else:
        print(f"\n  Órfãs (nenhuma página as linka): {len(orphans)}")
        for o in orphans[:40]:
            print(f"     - {o}")
        if len(orphans) > 40:
            print(f"     (+{len(orphans) - 40} outras)")

    if money:
        print(
            f"\n  Money-pages SEM link contextual (tráfego real, 0 link editorial de entrada): {len(money)}"
        )
        print(f"     {'ctx':>4} {'cliques':>8} {'impr':>9}  página")
        for m in money[:20]:
            print(f"     {m['inlinks']:>4} {m['clicks']:>8,} {m['impressions']:>9,}  {m['slug']}")

    if anchors:
        print(f"\n  Canibalização de âncora (mesmo texto → páginas diferentes): {len(anchors)}")
        for a in anchors[:15]:
            print(f'     "{a["anchor"]}" → {a["n"]} destinos: {", ".join(a["targets"])}')
    print("=" * 78 + "\n")


def print_link_plan(planned: list) -> None:
    """Plano de links hub-and-spoke por grupo (o que falta linkar)."""
    if not planned:
        return
    gaps = [c for c in planned if not c["link_plan"].get("complete")]
    print("\n" + "=" * 78)
    print(
        f"  PLANO DE LINKS (hub-and-spoke) — {len(planned)} grupo(s), "
        f"{len(gaps)} com links faltando"
    )
    print("=" * 78)
    for i, c in enumerate(planned, 1):
        p = c["link_plan"]
        anchor = p.get("hub_keyword") or p["hub"].replace("-", " ")
        print(f"\n[{i}] cabeça: {p['hub']}  ({p['spokes_total']} spokes)")
        if p.get("complete"):
            print("     ✓ backbone completo — spokes já linkam a cabeça e vice-versa")
            continue
        for s in p.get("missing_spoke_to_hub", []):
            print(f'     + LINK  {s} → {p["hub"]}   (âncora: "{anchor}")')
        for s in p.get("missing_hub_to_spoke", []):
            print(f"     . link  {p['hub']} → {s}")
    print("=" * 78 + "\n")
