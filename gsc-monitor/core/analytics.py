"""
analytics.py — Análises derivadas dos dados de posicionamento e indexação.

Fase 4:
  4d — Score de saúde do site (0–100)
  4a — Detecção de páginas órfãs (zero impressões no período)
  4b — Análise de canibalização de keywords (2+ URLs para a mesma query)
"""

import sys
from collections import defaultdict

from config import CANNIBAL_MAX_POSITION, CANNIBAL_MIN_IMPRESSIONS, HEALTH_WEIGHTS

from core.ctr import expected_ctr

# ---------------------------------------------------------------------------
# 4d — Score de saúde do site
# ---------------------------------------------------------------------------


def _pos_component(position_report: dict) -> float:
    """
    Componente posicionamento: 0–100 baseado na posição das URLs com dados,
    ponderada por impressões.

    A ponderação por impressões faz o score refletir onde o TRÁFEGO do site
    ranqueia — não onde a cauda longa de páginas sem volume ranqueia. Sem isso,
    muitas páginas profundas de baixa demanda derrubam o score mesmo quando as
    páginas que recebem impressões estão bem posicionadas.
    """
    with_data = [
        r for r in position_report.get("urls", []) if r["has_data"] and r["position"] is not None
    ]
    if not with_data:
        return 0.0
    total_impr = sum(r["impressions"] for r in with_data)
    if total_impr > 0:
        avg = sum(r["position"] * r["impressions"] for r in with_data) / total_impr
    else:
        # Sem impressões em nenhuma URL: cai para média simples (evita div/0)
        avg = sum(r["position"] for r in with_data) / len(with_data)
    # pos=1 → 100, pos=51+ → 0 (decresce 2 pts por posição acima de 1)
    return max(0.0, round(100.0 - (avg - 1.0) * 2.0, 1))


def _ctr_component(position_report: dict) -> float:
    """
    Componente CTR: 0–100 vs. benchmark por posição (só URLs na 1ª página).
    Retorna 50 (neutro) quando não há URLs na 1ª página para avaliar.
    """
    page1 = [
        r
        for r in position_report.get("urls", [])
        if r["has_data"] and r["position"] is not None and r["position"] <= 10
    ]
    if not page1:
        return 50.0

    total, count = 0.0, 0
    for r in page1:
        exp = expected_ctr(r["position"])
        if exp and exp > 0:
            total += min(1.0, r["ctr"] / exp)
            count += 1
    return round(total / count * 100.0, 1) if count else 50.0


def calculate_health_score(
    position_report: dict,
    consolidated: "dict | None" = None,
) -> dict:
    """
    Calcula o score de saúde do site (0–100).

    Fórmula: (% indexadas × 0.4) + (score_posição × 0.4) + (ctr_vs_benchmark × 0.2)

    Se consolidated=None (indexação não executada), NÃO inventa um valor de
    indexação: re-normaliza os pesos para Posição + CTR (0.667 / 0.333) e marca
    has_indexation_data=False. Assim o número nunca embute um palpite de 50.

    Retorna:
    {
        "score":               float,        # 0–100, 1 casa decimal
        "grade":               str,          # "Crítico" / "Regular" / "Bom" / "Excelente"
        "has_indexation_data": bool,
        "components": {
            "indexation": float | None,      # 0–100  (None se sem dados)
            "position":   float,             # 0–100
            "ctr":        float,             # 0–100
        }
    }
    """
    pos = _pos_component(position_report)
    ctr = _ctr_component(position_report)

    W_IDX = HEALTH_WEIGHTS["indexation"]
    W_POS = HEALTH_WEIGHTS["position"]
    W_CTR = HEALTH_WEIGHTS["ctr"]

    if consolidated is not None:
        total = consolidated.get("total_urls", 0)
        idx_pct = (
            consolidated.get("summary", {}).get("indexed", {}).get("percent", 0.0)
            if total > 0
            else 0.0
        )
        score = round(idx_pct * W_IDX + pos * W_POS + ctr * W_CTR, 1)
        has_idx = True
    else:
        idx_pct = None
        # Sem indexação: re-normaliza pesos para Posição + CTR (não inventa 50).
        denom = W_POS + W_CTR  # 0.6
        score = round(pos * (W_POS / denom) + ctr * (W_CTR / denom), 1)
        has_idx = False

    grade = (
        "Excelente"
        if score >= 80
        else "Bom"
        if score >= 60
        else "Regular"
        if score >= 40
        else "Crítico"
    )

    return {
        "score": score,
        "grade": grade,
        "has_indexation_data": has_idx,
        "components": {
            "indexation": idx_pct,
            "position": pos,
            "ctr": ctr,
        },
    }


def print_health_score(health: dict) -> None:
    """Exibe o score de saúde no terminal."""
    score = health["score"]
    grade = health["grade"]
    comp = health["components"]

    filled = int(score / 5)
    # Tenta caracteres Unicode; cai para ASCII se o terminal não suportar (ex: cp1252)
    try:
        bar = "█" * filled + "░" * (20 - filled)
        _enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        bar.encode(_enc)
    except (UnicodeEncodeError, LookupError):
        bar = "#" * filled + "-" * (20 - filled)

    print("\n" + "=" * 62)
    print("  Score de Saude do Site")
    print("=" * 62)
    print(f"  {score:>5.1f} / 100   [{bar}]   {grade}")
    print("-" * 62)

    idx_str = f"{comp['indexation']:.1f}" if comp["indexation"] is not None else "s/d"
    print(f"  Indexação            : {idx_str:>6} / 100   (peso 40%)")
    print(f"  Posicionamento       : {comp['position']:>6.1f} / 100   (peso 40%)")
    print(f"  CTR vs benchmark     : {comp['ctr']:>6.1f} / 100   (peso 20%)")

    if not health["has_indexation_data"]:
        print("  * Indexação não executada — score baseado apenas em Posição + CTR")
        print("    (pesos re-normalizados; nenhum valor de indexação foi presumido)")

    print("=" * 62 + "\n")


# ---------------------------------------------------------------------------
# 4a — Páginas órfãs
# ---------------------------------------------------------------------------


def detect_orphan_pages(position_report: dict) -> list:
    """
    Retorna URLs do sitemap com zero impressões no período analisado.
    Cada entrada: {"url": str, "suggestion": str}
    """
    return [
        {"url": r["url"], "suggestion": "Revisar conteúdo ou consolidar"}
        for r in position_report.get("urls", [])
        if not r["has_data"]
    ]


def print_orphan_pages(orphans: list, max_display: int = 20) -> None:
    """Exibe resumo das páginas sem impressões no terminal."""
    total = len(orphans)
    if total == 0:
        print("\n[analytics] Nenhuma página sem impressões detectada.")
        return

    print(f"\n{'─' * 62}")
    print(f"  Páginas sem impressões — {total} URL(s) sem tráfego de busca no período")
    print(f"{'─' * 62}")
    for entry in orphans[:max_display]:
        print(f"  [!] {entry['url']}")
        print(f"       → {entry['suggestion']}")
    if total > max_display:
        print(f"  ... +{total - max_display} (veja a sheet 'Páginas Órfãs' no Excel)")
    print(f"{'─' * 62}\n")


# ---------------------------------------------------------------------------
# 4b — Canibalização de keywords
# ---------------------------------------------------------------------------


def detect_cannibalization(query_rows: list) -> list:
    """
    Detecta queries onde 2+ URLs do site REALMENTE competem no Search Console.

    Uma URL só conta como concorrente se tiver volume e posição relevantes
    (impressões ≥ CANNIBAL_MIN_IMPRESSIONS e posição ≤ CANNIBAL_MAX_POSITION).
    Queries que não atingem 2 concorrentes qualificados são descartadas.

    query_rows: lista de dicts {"query", "url", "clicks", "impressions", "ctr", "position"}
    Retorna lista de grupos ordenados por severidade (impressões em disputa) desc:
    [
        {
            "query":          str,
            "url_count":      int,        # nº de URLs concorrentes qualificadas
            "urls":           [{"url", "position", "clicks", "impressions", "ctr"}, ...],
            "severity":       str,        # "alta" / "média" / "baixa"
            "severity_score": int,        # impressões das URLs secundárias (overlap real)
        },
        ...
    ]
    """
    groups: dict = defaultdict(list)
    for r in query_rows:
        groups[r["query"]].append(r)

    result = []
    for query, urls in groups.items():
        competing = [
            u
            for u in urls
            if u.get("impressions", 0) >= CANNIBAL_MIN_IMPRESSIONS
            and u.get("position")
            and u["position"] <= CANNIBAL_MAX_POSITION
        ]
        if len(competing) < 2:
            continue

        competing.sort(key=lambda u: u["position"])

        # Severidade: impressões "divididas" entre as URLs secundárias — quanto
        # de tráfego potencial está sendo fragmentado entre páginas concorrentes.
        secondary_impr = sum(u["impressions"] for u in competing[1:])
        if competing[0]["position"] <= 10 and competing[1]["position"] <= 10:
            severity = "alta"  # 2+ disputando a 1ª página
        elif competing[1]["position"] <= 20:
            severity = "média"
        else:
            severity = "baixa"

        result.append(
            {
                "query": query,
                "url_count": len(competing),
                "urls": competing,
                "severity": severity,
                "severity_score": secondary_impr,
            }
        )

    result.sort(key=lambda g: (-g["severity_score"], -g["url_count"]))
    return result


def print_cannibalization(cannibalization: list, max_display: int = 10) -> None:
    """Exibe resumo de canibalização no terminal."""
    total = len(cannibalization)
    if total == 0:
        print("\n[analytics] Nenhuma canibalização de keywords detectada.")
        return

    print(f"\n{'─' * 70}")
    print(f"  Canibalização — {total} keyword(s) com URLs concorrentes")
    print(f"{'─' * 70}")

    for group in cannibalization[:max_display]:
        sev = group.get("severity", "?")
        print(f'\n  Keyword: "{group["query"]}"  ({group["url_count"]} URLs · severidade {sev})')
        for u in group["urls"]:
            pos_str = f"{u['position']:.1f}" if u["position"] else "s/d"
            print(f"    Pos {pos_str:>6}  {u['impressions']:>6} impr.  {u['url']}")

    if total > max_display:
        print(f"\n  ... +{total - max_display} grupos (veja a sheet 'Canibalização' no Excel)")
    print(f"{'─' * 70}\n")
