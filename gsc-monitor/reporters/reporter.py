"""
reporter.py — Gera relatório detalhado (por URL) e relatório consolidado (totais).
"""

from collections import Counter

CATEGORIES = ("indexed", "not_indexed", "warning", "unknown")


def build_detailed(site: str, date: str, url_results: list[dict]) -> dict:
    """
    Monta o dicionário do relatório detalhado no formato:
    {
        "site": "...",
        "date": "...",
        "urls": [ { url, category, verdict, coverageState, lastCrawlTime }, ... ]
    }
    """
    urls_payload = [
        {
            "url": r["url"],
            "category": r["category"],
            "verdict": r["verdict"],
            "coverageState": r["coverageState"],
            "lastCrawlTime": r["lastCrawlTime"],
        }
        for r in url_results
    ]
    return {"site": site, "date": date, "urls": urls_payload}


def build_consolidated(site: str, date: str, url_results: list[dict]) -> dict:
    """
    Monta o dicionário do relatório consolidado com totais e % por categoria.
    """
    counts = Counter(r["category"] for r in url_results)
    total = len(url_results)

    summary = {}
    for cat in CATEGORIES:
        n = counts.get(cat, 0)
        summary[cat] = {
            "total": n,
            "percent": round((n / total * 100) if total else 0, 1),
        }

    return {
        "site": site,
        "date": date,
        "total_urls": total,
        "summary": summary,
    }


def print_consolidated(report: dict) -> None:
    """Imprime o relatório consolidado no terminal."""
    print("\n" + "=" * 60)
    print(f"  Relatório Consolidado — {report['site']}  ({report['date']})")
    print("=" * 60)
    print(f"  Total de URLs: {report['total_urls']}")
    print("-" * 60)
    for cat in CATEGORIES:
        data = report["summary"].get(cat, {"total": 0, "percent": 0.0})
        label = cat.replace("_", " ").capitalize()
        bar_len = int(data["percent"] / 5)  # barra de até 20 chars (100%/5)
        bar = "#" * bar_len
        print(f"  {label:<15} {data['total']:>5}  ({data['percent']:>5.1f}%)  [{bar:<20}]")
    print("=" * 60 + "\n")


def print_detailed(report: dict) -> None:
    """Imprime relatório detalhado por URL no terminal."""
    STATUS_LABEL = {
        "indexed":     "  INDEXADO     ",
        "not_indexed": "  NAO INDEXADO ",
        "warning":     "  AVISO        ",
        "unknown":     "  DESCONHECIDO ",
    }
    STATUS_MARK = {
        "indexed":     "[+]",
        "not_indexed": "[X]",
        "warning":     "[!]",
        "unknown":     "[?]",
    }

    print("\n" + "=" * 70)
    print(f"  Relatório Detalhado — {report['site']}  ({report['date']})")
    print("=" * 70)

    for entry in report["urls"]:
        cat = entry["category"]
        mark = STATUS_MARK.get(cat, "[?]")
        label = STATUS_LABEL.get(cat, "  DESCONHECIDO ")
        print(f"{mark}{label} {entry['url']}")
        if entry.get("coverageState"):
            print(f"          Estado      : {entry['coverageState']}")
        if entry.get("lastCrawlTime"):
            print(f"          Ultimo crawl: {entry['lastCrawlTime']}")

    print("=" * 70 + "\n")
