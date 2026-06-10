"""
analytics.py — Análises derivadas dos dados de posicionamento e indexação.

Fase 4:
  4d — Score de saúde do site (0–100)
  4a — Detecção de páginas órfãs (zero impressões no período)
  4b — Análise de canibalização de keywords (2+ URLs para a mesma query)

P2 (roadmap):
  Plano de consolidação 301 — transforma os grupos de canibalização em uma
  SUGESTÃO executável de redirects (CSV + blocos Apache/nginx).
"""

import sys
from collections import defaultdict
from urllib.parse import urlparse

from config import CANNIBAL_MAX_POSITION, CANNIBAL_MIN_IMPRESSIONS, HEALTH_WEIGHTS

from core.ctr import expected_ctr

# ---------------------------------------------------------------------------
# P4 — Alertas por componente do health score
# ---------------------------------------------------------------------------
#
# O score composto pode MASCARAR um componente crítico (caso real: 70.7 "Bom"
# com CTR 8.7/100). Qualquer componente abaixo do limiar gera um alerta com
# explicação em português claro. O composto NUNCA é suprimido — os dois
# aparecem juntos (regra de honestidade: a decomposição > o número único).

COMPONENT_ALERT_THRESHOLD = 40.0  # componente abaixo disso gera alerta
COMPONENT_CRITICAL_BELOW = 20.0  # abaixo disso a severidade é "critico"

_COMPONENT_LABELS = {
    "indexation": "Indexação",
    "position": "Posicionamento",
    "ctr": "CTR vs benchmark",
}


def _component_alert_message(component: str, value: float) -> str:
    """Explicação em pt-BR, sem jargão, do que o componente baixo significa."""
    if component == "indexation":
        return (
            f"Só {value:.0f}% das páginas estão indexadas — boa parte do "
            f"site nem aparece no Google."
        )
    if component == "position":
        return (
            f"Posicionamento {value:.0f}/100 — as páginas com impressões "
            f"ranqueiam muito longe da 1ª página (ou não há dados de posição)."
        )
    return (
        f"CTR {value:.0f}/100 vs benchmark — o site aparece na busca mas "
        f"quase ninguém clica (títulos/descriptions fracos ou página "
        f"errada para a intenção da busca)."
    )


def build_component_alerts(components: dict) -> list:
    """
    Gera alertas para componentes do health score abaixo de
    COMPONENT_ALERT_THRESHOLD. Componentes sem dados (None) não alertam.

    Retorna lista (possivelmente vazia) de:
    {
        "component": "indexation" | "position" | "ctr",
        "label":     str,    # rótulo legível
        "value":     float,  # valor 0–100 do componente
        "severity":  "critico" (< 20) | "alto" (< 40),
        "message":   str,    # 1 linha em pt-BR sobre o que significa
    }
    """
    alerts = []
    for comp in ("indexation", "position", "ctr"):
        value = components.get(comp)
        if value is None or value >= COMPONENT_ALERT_THRESHOLD:
            continue
        severity = "critico" if value < COMPONENT_CRITICAL_BELOW else "alto"
        alerts.append(
            {
                "component": comp,
                "label": _COMPONENT_LABELS[comp],
                "value": value,
                "severity": severity,
                "message": _component_alert_message(comp, value),
            }
        )
    return alerts


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
        },
        "component_alerts": [...],           # P4 — componentes < 40 (ver
                                             # build_component_alerts); o
                                             # composto nunca é suprimido
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

    components = {
        "indexation": idx_pct,
        "position": pos,
        "ctr": ctr,
    }

    return {
        "score": score,
        "grade": grade,
        "has_indexation_data": has_idx,
        "components": components,
        "component_alerts": build_component_alerts(components),
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

    # P4 — alertas por componente: o composto pode estar "Bom" com um
    # componente crítico escondido. Mostra os dois, nunca só o composto.
    alerts = health.get("component_alerts") or []
    if alerts:
        print("-" * 62)
        for a in alerts:
            print(f"  [ALERTA {a['severity'].upper()}] {a['label']}: {a['value']:.1f}/100")
            print(f"    {a['message']}")

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


# ---------------------------------------------------------------------------
# P5 — Tendências first-party (dimensão `date` do GSC)
# ---------------------------------------------------------------------------
#
# Classifica a tendência de demanda do site e das top queries comparando a
# média do PRIMEIRO terço do período com a do ÚLTIMO terço (impressões/dia).
# Honestidade: isto é a demanda REAL do próprio site na busca do Google —
# não o índice global 0–100 do Google Trends. Lógica pura (sem rede).

SITE_TREND_KEY = "Site (todo o domínio)"
TREND_RISING_RATIO = 1.15  # último terço ≥ 115% do primeiro → rising
TREND_DECLINING_RATIO = 0.85  # último terço ≤ 85% do primeiro  → declining
TREND_MIN_DAYS = 6  # mínimo de dias p/ classificar (2 por terço)
TREND_SPARSE_DAYS = 14  # menos dias com dados que isso → "sparse"


def _classify_thirds(values: list) -> tuple:
    """
    (trend, first_avg, last_avg) comparando o 1º terço vs o último terço.
    Série curta demais (< TREND_MIN_DAYS) → "stable" com médias globais.
    """
    n = len(values)
    if n < TREND_MIN_DAYS:
        avg = sum(values) / n if n else 0.0
        return "stable", avg, avg

    third = n // 3
    first_avg = sum(values[:third]) / third
    last_avg = sum(values[-third:]) / third

    if first_avg == 0:
        trend = "rising" if last_avg > 0 else "stable"
    else:
        ratio = last_avg / first_avg
        if ratio >= TREND_RISING_RATIO:
            trend = "rising"
        elif ratio <= TREND_DECLINING_RATIO:
            trend = "declining"
        else:
            trend = "stable"
    return trend, first_avg, last_avg


def compute_date_trends(date_data: dict, top_n: int = 10, metric: str = "impressions") -> dict:
    """
    Transforma o bruto de fetch_date_trends em tendências classificadas.

    Retorna no MESMO shape consumido pelas superfícies de Trends
    (print/chart/Excel): {nome: {"trend", "peak", "latest", "values",
    "sparse"}} — com campos extras ("source": "gsc", "metric", "first_avg",
    "last_avg") que permitem aos reporters ajustar os rótulos.

    A primeira entrada é sempre SITE_TREND_KEY (série do domínio inteiro);
    as demais são as top_n queries por impressões totais no período.
    Dias sem linha na API contam como 0 (sem dados = sem demanda).
    """
    site_rows = (date_data or {}).get("site_rows") or []
    if not site_rows:
        return {}

    axis = sorted({r["date"] for r in site_rows})

    def _entry(by_date: dict) -> dict:
        values = [int(by_date.get(d, 0)) for d in axis]
        trend, first_avg, last_avg = _classify_thirds(values)
        days_with_data = sum(1 for v in values if v > 0)
        return {
            "trend": trend,
            "peak": max(values) if values else 0,
            "latest": int(round(last_avg)),
            "values": values,
            "sparse": days_with_data < TREND_SPARSE_DAYS,
            "source": "gsc",
            "metric": metric,
            "first_avg": round(first_avg, 1),
            "last_avg": round(last_avg, 1),
        }

    out = {SITE_TREND_KEY: _entry({r["date"]: r.get(metric, 0) for r in site_rows})}
    out[SITE_TREND_KEY]["dates"] = axis  # eixo p/ o gráfico de linha (P5)

    totals: dict = {}
    per_query: dict = {}
    for r in date_data.get("query_rows") or []:
        q = r["query"]
        totals[q] = totals.get(q, 0) + r.get("impressions", 0)
        per_query.setdefault(q, {})[r["date"]] = r.get(metric, 0)

    for q in sorted(totals, key=lambda k: -totals[k])[:top_n]:
        out[q] = _entry(per_query[q])

    return out


def print_date_trends(trends_data: dict) -> None:
    """Exibe as tendências first-party (GSC) no terminal."""
    if not trends_data:
        print("\n[trends] Sem dados de tendência no período (site sem impressões?).")
        return
    ARROW = {"rising": "+", "declining": "-", "stable": "="}
    LABEL = {"rising": "Crescente", "declining": "Em queda", "stable": "Estavel"}
    days = len(next(iter(trends_data.values())).get("values", []))
    print("\n" + "-" * 72)
    print(f"  Tendencias de demanda — GSC, impressoes/dia ({days} dias)")
    print("  (1o terco vs ultimo terco do periodo; dados do proprio site)")
    print("-" * 72)
    for kw, td in trends_data.items():
        arrow = ARROW.get(td["trend"], "=")
        label = LABEL.get(td["trend"], "Estavel")
        note = "  (dados esparsos)" if td.get("sparse") else ""
        print(
            f"  [{arrow}] {kw:<40} {label:<10} "
            f"{td.get('first_avg', 0):>8.1f} -> {td.get('last_avg', 0):<8.1f}{note}"
        )
    print("-" * 72 + "\n")


# ---------------------------------------------------------------------------
# P2 — Plano de consolidação 301 (SUGESTÃO)
# ---------------------------------------------------------------------------
#
# Transforma os grupos de canibalização em um plano executável de redirects.
# IMPORTANTE (regra de honestidade): o plano é uma SUGESTÃO derivada de
# heurística sobre dados do GSC — nunca uma recomendação definitiva. Todos os
# artefatos gerados carregam esse aviso. Revisão humana é obrigatória antes
# de aplicar em produção (301 é difícil de reverter).

_PLAN_DISCLAIMER = (
    "SUGESTAO gerada automaticamente pelo GSC Monitor a partir dos grupos de "
    "canibalizacao. NAO aplique sem revisao humana: confira se as paginas sao "
    "de fato redundantes (e nao intencionalmente distintas) antes de criar "
    "redirects 301, que sao dificeis de reverter."
)


def _canonical_sort_key(u: dict) -> tuple:
    """
    Ordenação para escolha da URL canônica de um grupo:
    cliques desc → posição asc → impressões desc.
    """
    return (-u.get("clicks", 0), u.get("position", 9999), -u.get("impressions", 0))


def build_consolidation_plan(cannibalization: list) -> dict:
    """
    Constrói o plano de consolidação 301 a partir dos grupos de canibalização
    (saída de detect_cannibalization, já ordenada por severidade desc).

    Para cada grupo, a URL canônica é a melhor por _canonical_sort_key; as
    demais viram fontes de redirect para ela.

    Resolução de conflitos entre grupos (uma URL pode aparecer em vários):
      - Grupos são processados em ordem (maior severidade primeiro = prioridade).
      - URL que já é canônica em um grupo anterior NUNCA vira fonte de
        redirect em grupo posterior (registrado em "conflicts").
      - URL que já tem redirect planejado não recebe um segundo destino
        (mantém o do grupo de maior severidade; divergência registrada).
      - URLs já redirecionadas são excluídas da candidatura a canônica.
    Por construção, nenhum destino (to_url) é também origem (from_url) —
    o plano não gera cadeias nem ciclos de redirect.

    Retorna:
    {
        "disclaimer":      str,    # aviso de SUGESTÃO (regra de honestidade)
        "groups": [
            {"query", "severity", "canonical": dict, "sources": [dict, ...]},
            ...                    # só grupos que geraram ao menos 1 redirect
        ],
        "redirects": [             # lista achatada, na ordem dos grupos
            {"from_url", "to_url", "keyword", "severity",
             "clicks_from", "clicks_to"},
            ...
        ],
        "conflicts":       [str],  # decisões de desempate entre grupos
        "total_groups":    int,    # grupos com redirect no plano
        "total_redirects": int,
    }
    """
    canonical_urls: set = set()
    redirect_target: dict = {}  # from_url -> to_url já planejado
    groups_out: list = []
    redirects: list = []
    conflicts: list = []

    for group in cannibalization or []:
        query = group.get("query", "")
        severity = group.get("severity", "baixa")

        # Candidatas a canônica: excluem URLs já marcadas para redirect
        candidates = [u for u in group["urls"] if u["url"] not in redirect_target]
        if len(candidates) == 0:
            conflicts.append(
                f'grupo "{query}": todas as URLs ja possuem redirect planejado '
                f"em grupos de maior severidade — grupo ignorado"
            )
            continue

        canonical = sorted(candidates, key=_canonical_sort_key)[0]
        sources_out = []

        for u in group["urls"]:
            if u["url"] == canonical["url"]:
                continue
            if u["url"] in canonical_urls:
                conflicts.append(
                    f'grupo "{query}": {u["url"]} e canonica de outro grupo '
                    f"— nao sera redirecionada"
                )
                continue
            if u["url"] in redirect_target:
                if redirect_target[u["url"]] != canonical["url"]:
                    conflicts.append(
                        f'grupo "{query}": {u["url"]} ja redireciona para '
                        f"{redirect_target[u['url']]} (grupo de maior severidade) "
                        f"— destino mantido"
                    )
                continue

            redirect_target[u["url"]] = canonical["url"]
            entry = {
                "from_url": u["url"],
                "to_url": canonical["url"],
                "keyword": query,
                "severity": severity,
                "clicks_from": u.get("clicks", 0),
                "clicks_to": canonical.get("clicks", 0),
            }
            redirects.append(entry)
            sources_out.append(u)

        if sources_out:
            canonical_urls.add(canonical["url"])
            groups_out.append(
                {
                    "query": query,
                    "severity": severity,
                    "canonical": canonical,
                    "sources": sources_out,
                }
            )

    return {
        "disclaimer": _PLAN_DISCLAIMER,
        "groups": groups_out,
        "redirects": redirects,
        "conflicts": conflicts,
        "total_groups": len(groups_out),
        "total_redirects": len(redirects),
    }


def _url_path(url: str) -> str:
    """Extrai o caminho (path + query) de uma URL absoluta. '/' se vazio."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    return path


def build_htaccess_block(plan: dict, date: str) -> str:
    """
    Gera o bloco Apache (.htaccess) com os redirects 301 do plano.
    Comentários em ASCII (arquivos de config de servidor).
    """
    lines = [
        "# " + "=" * 68,
        f"# SUGESTAO de consolidacao 301 - GSC Monitor - {date}",
        "# " + "-" * 68,
    ]
    lines += [f"# {l}" for l in _wrap_ascii(_PLAN_DISCLAIMER, 66)]
    lines += [
        "# Requer: mod_alias habilitado. Adicione ao .htaccess da raiz do site.",
        "# " + "=" * 68,
        "",
    ]
    for r in plan.get("redirects", []):
        lines.append(
            f"# keyword: {_ascii_safe(r['keyword'])}  (severidade {_ascii_safe(r['severity'])})"
        )
        lines.append(f"Redirect 301 {_url_path(r['from_url'])} {r['to_url']}")
        lines.append("")
    return "\n".join(lines)


def build_nginx_block(plan: dict, date: str) -> str:
    """
    Gera o bloco nginx (server {}) com os redirects 301 do plano.
    Comentários em ASCII (arquivos de config de servidor).
    """
    lines = [
        "# " + "=" * 68,
        f"# SUGESTAO de consolidacao 301 - GSC Monitor - {date}",
        "# " + "-" * 68,
    ]
    lines += [f"# {l}" for l in _wrap_ascii(_PLAN_DISCLAIMER, 66)]
    lines += [
        "# Adicione dentro do bloco server {} do site.",
        "# " + "=" * 68,
        "",
    ]
    for r in plan.get("redirects", []):
        lines.append(
            f"# keyword: {_ascii_safe(r['keyword'])}  (severidade {_ascii_safe(r['severity'])})"
        )
        lines.append(f"location = {_url_path(r['from_url'])} {{ return 301 {r['to_url']}; }}")
        lines.append("")
    return "\n".join(lines)


def _ascii_safe(text: str) -> str:
    """Remove acentos/não-ASCII para comentários de arquivos de config."""
    import unicodedata

    norm = unicodedata.normalize("NFKD", str(text))
    return norm.encode("ascii", "ignore").decode("ascii")


def _wrap_ascii(text: str, width: int) -> list:
    """Quebra texto em linhas de até `width` chars (para comentários)."""
    import textwrap

    return textwrap.wrap(_ascii_safe(text), width=width)


def print_consolidation_plan(plan: dict, max_display: int = 10) -> None:
    """Exibe resumo do plano de consolidação no terminal (ASCII-safe)."""
    total = plan.get("total_redirects", 0)
    if total == 0:
        print("\n[analytics] Nenhum redirect sugerido (sem grupos consolidaveis).")
        return

    print("\n" + "-" * 70)
    print(
        f"  Plano de consolidacao 301 (SUGESTAO) — {total} redirect(s) "
        f"em {plan['total_groups']} grupo(s)"
    )
    print("-" * 70)
    print("  ATENCAO: sugestao automatica — revise antes de aplicar.")
    print("  Artefatos: *_redirects.csv, *_redirects_apache.txt, *_redirects_nginx.txt")

    for g in plan["groups"][:max_display]:
        print(f'\n  Keyword: "{g["query"]}"  (severidade {g["severity"]})')
        print(f"    Manter : {g['canonical']['url']}  ({g['canonical'].get('clicks', 0)} cliques)")
        for s in g["sources"]:
            print(f"    301 de : {s['url']}  ({s.get('clicks', 0)} cliques)")

    rest = plan["total_groups"] - max_display
    if rest > 0:
        print(f"\n  ... +{rest} grupos (veja a sheet 'Plano 301' no Excel)")

    if plan.get("conflicts"):
        print(
            f"\n  Conflitos resolvidos automaticamente: {len(plan['conflicts'])} "
            f"(detalhes no CSV/Excel)"
        )
    print("-" * 70 + "\n")
