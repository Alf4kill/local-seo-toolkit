"""
trends_fetcher.py — Tendências do Google Trends via pytrends (biblioteca não oficial).

Para as keywords da 1ª página do GSC, busca a curva de interesse dos últimos
12 meses e classifica a tendência (crescente / estável / em queda).

Requer: pip install pytrends

Limites:
  - Sem autenticação (scraping unofficial) → pode receber TooManyRequests
  - Delay de 1-2s entre keywords para evitar bloqueio
  - Cache obrigatório: TTL 24h por keyword+geo
"""

import os
import re
import time

from config import TRENDS_GEO

try:
    from pytrends.request import TrendReq

    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False

TTL_TRENDS_HOURS = 24

# Mínimo de semanas com dados não-zero para considerar a tendência confiável.
# Keywords com menos que isso são marcadas como "sparse" (dados esparsos).
_SPARSE_THRESHOLD = 8


# ---------------------------------------------------------------------------
# Helpers de cache  (reutiliza _cache_dir, _read_entry, _write_entry, _is_fresh)
# ---------------------------------------------------------------------------


def _normalize_kw(kw: str) -> str:
    """Normaliza keyword para nome de arquivo seguro."""
    return re.sub(r"[^\w]", "_", kw.lower())[:60]


def _get_trends_cache(site: str, keyword: str, geo: str) -> "dict | None":
    from core.cache import _cache_dir, _is_fresh, _read_entry

    key = f"trends_{_normalize_kw(keyword)}_{geo}"
    path = os.path.join(_cache_dir(site), f"{key}.json")
    entry = _read_entry(path)
    if entry and _is_fresh(entry, TTL_TRENDS_HOURS):
        return entry["data"]
    return None


def _set_trends_cache(site: str, keyword: str, geo: str, data: dict) -> None:
    from core.cache import _cache_dir, _write_entry

    key = f"trends_{_normalize_kw(keyword)}_{geo}"
    path = os.path.join(_cache_dir(site), f"{key}.json")
    _write_entry(path, data)


# ---------------------------------------------------------------------------
# Extração de top keywords a partir de query_rows
# ---------------------------------------------------------------------------


def top_keywords_from_queries(query_rows: list, max_kw: int = 10) -> list:
    """
    Retorna as top keywords com posição ≤ 10, ordenadas por impressões totais.
    Deduplica queries idênticas.
    """
    kw_impr: dict = {}
    for r in query_rows:
        if r.get("position") is not None and r["position"] <= 10:
            q = r["query"]
            kw_impr[q] = kw_impr.get(q, 0) + r.get("impressions", 0)
    return sorted(kw_impr, key=lambda k: -kw_impr[k])[:max_kw]


# ---------------------------------------------------------------------------
# Cálculo de tendência
# ---------------------------------------------------------------------------


def _classify_trend(values: list) -> str:
    """
    Classifica a tendência de uma série de interesse (0–100).

    Remove zeros finais antes de comparar: o Google Trends frequentemente
    retorna 0 para a semana mais recente (ainda incompleta), o que distorceria
    a classificação sem esse tratamento.

    Compara a média dos primeiros 3 períodos vs. últimos 3 períodos.
    """
    # Remove trailing zeros (semana atual geralmente incompleta no Trends)
    vals = list(values)
    while vals and vals[-1] == 0:
        vals.pop()

    if len(vals) < 6:
        return "stable"
    first3 = sum(vals[:3]) / 3
    last3 = sum(vals[-3:]) / 3
    if first3 == 0:
        return "rising" if last3 > 0 else "stable"
    ratio = last3 / first3
    if ratio >= 1.15:
        return "rising"
    if ratio <= 0.85:
        return "declining"
    return "stable"


def _compute_trend_data(vals: list) -> dict:
    """
    Computa trend, peak, latest e sparse a partir dos valores brutos do Trends.

    Centraliza a lógica de derivação para que seja usada tanto ao buscar dados
    frescos quanto ao ler do cache (garantindo que melhorias no algoritmo sejam
    aplicadas mesmo em runs que acertam o cache).

    Campos retornados:
      trend   — "rising" | "stable" | "declining"
      peak    — valor máximo no período (0–100)
      latest  — último valor não-zero (ignora semana atual incompleta)
      values  — série completa como lista de ints
      sparse  — True se < _SPARSE_THRESHOLD semanas com dados não-zero
    """
    if not vals:
        return {"trend": "stable", "peak": 0, "latest": 0, "values": [], "sparse": False}

    int_vals = [int(v) for v in vals]

    # Último valor não-zero: ignora a semana atual se ainda incompleta (valor=0)
    latest = next((v for v in reversed(int_vals) if v > 0), 0)

    non_zero_count = sum(1 for v in int_vals if v > 0)

    return {
        "trend": _classify_trend(int_vals),
        "peak": max(int_vals),
        "latest": latest,
        "values": int_vals,
        "sparse": non_zero_count < _SPARSE_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# Consulta principal
# ---------------------------------------------------------------------------


def fetch_trends(
    keywords: list,
    site: str,
    geo: str = TRENDS_GEO,
    use_cache: bool = True,
    delay: float = 1.5,
) -> dict:
    """
    Busca a tendência do Google Trends para cada keyword.

    Parâmetros:
        keywords  — lista de strings (até ~10 para performance)
        site      — domínio para cache (ex: www.exemplo.com.br)
        geo       — código de país ISO (default "BR")
        use_cache — usa cache de 24h
        delay     — segundos de espera entre keywords (anti-rate-limit)

    Retorna:
    {
        "keyword": {
            "trend":  "rising" | "declining" | "stable",
            "peak":   int,     # 0–100 — valor máximo no período
            "latest": int,     # 0–100 — último valor não-zero (semana incompleta ignorada)
            "values": list,    # série temporal completa
            "sparse": bool,    # True se dados insuficientes para tendência confiável
        },
        ...
    }
    Keywords sem dados retornam {"trend": "stable", "peak": 0, "latest": 0,
                                  "values": [], "sparse": False}.
    """
    if not PYTRENDS_AVAILABLE:
        print("[trends] pytrends não instalado. Execute: pip install pytrends")
        return {}

    if not keywords:
        return {}

    results = {}
    # Nota: não passamos retries= para evitar incompatibilidade do pytrends
    # com urllib3 v2.x (method_whitelist → allowed_methods). O except já lida
    # com falhas de rede.
    pytrends = TrendReq(hl="pt-BR", tz=180, timeout=(10, 30))

    for kw in keywords:
        if use_cache:
            cached = _get_trends_cache(site, kw, geo)
            if cached is not None:
                print(f"[trends] [CACHE] '{kw}'")
                # Recomputa trend/latest a partir dos valores brutos — garante que
                # melhorias no algoritmo se apliquem sem precisar limpar o cache.
                vals = cached.get("values")
                results[kw] = _compute_trend_data(vals) if vals else cached
                continue

        print(f"[trends] Buscando tendência: '{kw}'...")
        try:
            pytrends.build_payload(
                [kw],
                cat=0,
                timeframe="today 12-m",
                geo=geo,
                gprop="",
            )
            df = pytrends.interest_over_time()

            if df.empty or kw not in df.columns:
                print(
                    f"[trends] Sem dados no Google Trends para '{kw}' (volume muito baixo para essa região)"
                )
                data = {"trend": "stable", "peak": 0, "latest": 0, "values": [], "sparse": False}
            else:
                data = _compute_trend_data(df[kw].tolist())

            results[kw] = data
            if use_cache:
                _set_trends_cache(site, kw, geo, data)

        except Exception as exc:
            print(f"[trends] ERRO para '{kw}': {exc}")
            results[kw] = {"trend": "stable", "peak": 0, "latest": 0, "values": [], "sparse": False}

        time.sleep(delay)

    return results


def print_trends(trends_data: dict) -> None:
    """Exibe resumo de tendências no terminal."""
    if not trends_data:
        return
    ARROW = {"rising": "↑", "declining": "↓", "stable": "→"}
    LABEL = {"rising": "Crescente", "declining": "Em queda", "stable": "Estável"}
    print(f"\n{'─' * 72}")
    print("  Tendências Google Trends (últimos 12 meses)")
    print(f"{'─' * 72}")
    for kw, data in trends_data.items():
        arrow = ARROW.get(data["trend"], "→")
        trend_lbl = LABEL.get(data["trend"], "Estável")

        if data.get("peak") == 0:
            note = "  ⚠ sem dados no Trends"
        elif data.get("sparse"):
            note = "  ⚠ dados esparsos"
        else:
            note = ""

        print(
            f"  {arrow} {kw:<38}  {trend_lbl:<12}  pico:{data['peak']:>3}  atual:{data['latest']:>3}{note}"
        )
    print(f"{'─' * 72}\n")
