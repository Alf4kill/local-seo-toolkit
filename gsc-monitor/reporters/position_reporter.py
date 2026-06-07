"""
position_reporter.py — Formata e exibe o relatório de posicionamento por URL.
"""


def build_position_report(domain: str, today: str, data: dict) -> dict:
    """
    Monta o dicionário do relatório de posicionamento para salvar em JSON.

    data: resultado de position_fetcher.fetch_positions()
    """
    rows       = data["rows"]
    with_data  = [r for r in rows if r["has_data"]]
    no_data    = [r for r in rows if not r["has_data"]]

    avg_position = (
        round(sum(r["position"] for r in with_data) / len(with_data), 1)
        if with_data else None
    )
    total_clicks      = sum(r["clicks"]      for r in rows)
    total_impressions = sum(r["impressions"] for r in rows)
    avg_ctr           = (
        round(sum(r["ctr"] for r in with_data) / len(with_data), 2)
        if with_data else 0.0
    )

    return {
        "site": domain,
        "date": today,
        "period": {
            "start":   data["start_date"],
            "end":     data["end_date"],
            "country": data["country"],
        },
        "summary": {
            "total_urls_sitemap":  len(rows),
            "urls_with_data":      len(with_data),
            "urls_no_impressions": len(no_data),
            "avg_position_site":   avg_position,
            "total_clicks":        total_clicks,
            "total_impressions":   total_impressions,
            "avg_ctr_percent":     avg_ctr,
        },
        "urls": rows,
    }


def print_position_report(domain: str, today: str, data: dict) -> None:
    """Imprime o relatório de posicionamento no terminal."""
    rows      = data["rows"]
    with_data = [r for r in rows if r["has_data"]]
    no_data   = [r for r in rows if not r["has_data"]]

    avg_position = (
        round(sum(r["position"] for r in with_data) / len(with_data), 1)
        if with_data else None
    )
    total_clicks      = sum(r["clicks"]      for r in rows)
    total_impressions = sum(r["impressions"] for r in rows)

    sep  = "=" * 82
    dash = "-" * 82

    print("\n" + sep)
    print(f"  Relatorio de Posicionamento — {domain}  ({today})")
    print(f"  Periodo : {data['start_date']}  a  {data['end_date']}")
    print(f"  Pais    : Global (sem filtro de pais)")
    print(sep)
    print(f"  URLs no sitemap      : {len(rows):>5}")
    print(f"  URLs com dados GSC   : {len(with_data):>5}")
    print(f"  URLs sem impressoes  : {len(no_data):>5}")
    print(dash)
    print(f"  Posicao media geral  : {avg_position if avg_position else 's/d':>5}")
    print(f"  Total de cliques     : {total_clicks:>5,}")
    print(f"  Total de impressoes  : {total_impressions:>5,}")
    print(dash)

    # Cabeçalho da tabela
    print(f"  {'Pos.':>5}  {'Cliques':>8}  {'Impressoes':>11}  {'CTR':>7}  URL")
    print(dash)

    for r in rows:
        if r["has_data"]:
            pos         = f"{r['position']:>5.1f}"
            clicks      = f"{r['clicks']:>8,}"
            impressions = f"{r['impressions']:>11,}"
            ctr         = f"{r['ctr']:>6.2f}%"
        else:
            pos         = "  s/d"
            clicks      = f"{'0':>8}"
            impressions = f"{'0':>11}"
            ctr         = "   s/d "

        url_display = r["url"]
        if len(url_display) > 52:
            url_display = url_display[:49] + "..."

        print(f"  {pos}  {clicks}  {impressions}  {ctr}  {url_display}")

    print(sep + "\n")


def build_position_txt_lines(domain: str, today: str, data: dict, report: dict) -> list[str]:
    """
    Gera as linhas do relatório de posicionamento em formato texto legível.
    Usado por storage.save_position_txt().
    """
    rows      = data["rows"]
    with_data = [r for r in rows if r["has_data"]]
    no_data   = [r for r in rows if not r["has_data"]]
    summary   = report["summary"]

    sep  = "=" * 82
    dash = "-" * 82
    lines = []

    lines.append(sep)
    lines.append(f"  RELATORIO DE POSICIONAMENTO — {domain}  ({today})")
    lines.append(f"  Periodo : {data['start_date']}  a  {data['end_date']}")
    lines.append(f"  Pais    : Global (sem filtro de pais)")
    lines.append(sep)
    lines.append(f"  URLs no sitemap      : {len(rows):>5}")
    lines.append(f"  URLs com dados GSC   : {len(with_data):>5}")
    lines.append(f"  URLs sem impressoes  : {len(no_data):>5}")
    lines.append(dash)
    lines.append(f"  Posicao media geral  : {summary['avg_position_site'] if summary['avg_position_site'] else 's/d':>5}")
    lines.append(f"  Total de cliques     : {summary['total_clicks']:>5,}")
    lines.append(f"  Total de impressoes  : {summary['total_impressions']:>5,}")
    lines.append(dash)
    lines.append(f"  {'Pos.':>5}  {'Cliques':>8}  {'Impressoes':>11}  {'CTR':>7}  URL")
    lines.append(dash)

    for r in rows:
        if r["has_data"]:
            pos         = f"{r['position']:>5.1f}"
            clicks      = f"{r['clicks']:>8,}"
            impressions = f"{r['impressions']:>11,}"
            ctr         = f"{r['ctr']:>6.2f}%"
        else:
            pos         = "  s/d"
            clicks      = f"{'0':>8}"
            impressions = f"{'0':>11}"
            ctr         = "   s/d "

        lines.append(f"  {pos}  {clicks}  {impressions}  {ctr}  {r['url']}")

    lines.append(sep)
    return lines
