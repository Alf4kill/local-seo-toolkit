"""
content_fetcher.py — Orquestra o diagnóstico de qualidade de conteúdo (Move 1).

Busca o texto editorial das URLs de oportunidade (com cache em disco próprio,
para não refazer downloads nem depender de cota de API) e roda o analisador puro
core.content_quality.

Sinais LOCAIS (densidade, repetição, diversidade, tamanho) funcionam sem nenhuma
API. Se nlp_results for fornecido (--nlp), o diagnóstico é enriquecido com os
sinais semânticos do Google (saliência, amplitude temática, categoria).
"""

import os
import re

from core.content_quality import analyze_content_quality, target_keywords_for_url

from fetchers.nlp_analyzer import _fetch_page_text

TTL_TEXT_HOURS = 72  # texto editorial muda pouco; cache evita re-download


# ---------------------------------------------------------------------------
# Cache de texto (chave text_ — separada dos caches de NLP/posição)
# ---------------------------------------------------------------------------


def _text_cache_key(url: str) -> str:
    clean = re.sub(r"[^\w]", "_", url)
    return f"text_{clean[-55:]}"


def _get_text_cache(site: str, url: str) -> "str | None":
    from core.cache import _cache_dir, _is_fresh, _read_entry

    path = os.path.join(_cache_dir(site), f"{_text_cache_key(url)}.json")
    entry = _read_entry(path)
    if entry and _is_fresh(entry, TTL_TEXT_HOURS):
        data = entry["data"]
        if isinstance(data, str):
            return data
    return None


def _set_text_cache(site: str, url: str, text: str) -> None:
    from core.cache import _cache_dir, _write_entry

    path = os.path.join(_cache_dir(site), f"{_text_cache_key(url)}.json")
    _write_entry(path, text)


def fetch_page_text_cached(site: str, url: str, use_cache: bool = True) -> "str | None":
    """Baixa (ou lê do cache) o texto editorial de uma URL."""
    if use_cache:
        cached = _get_text_cache(site, url)
        if cached is not None:
            return cached
    text = _fetch_page_text(url)
    if text and use_cache:
        _set_text_cache(site, url, text)
    return text


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------


def analyze_opportunity_content_quality(
    opportunity_rows: list,
    site: str,
    query_rows: "list | None" = None,
    nlp_results: "dict | None" = None,
    use_cache: bool = True,
    max_urls: int = 8,
) -> dict:
    """
    Roda o diagnóstico de qualidade nas URLs de oportunidade (posição 4–10,
    ordenadas por impressões). A keyword-alvo de cada URL vem das queries reais
    do GSC (query_rows). Retorna {url: cq_dict}.
    """
    candidates = sorted(
        [
            r
            for r in opportunity_rows
            if r.get("has_data") and r.get("position") is not None and 4 <= r["position"] <= 10
        ],
        key=lambda r: -r.get("impressions", 0),
    )[:max_urls]

    if not candidates:
        print("[content] Nenhuma URL de oportunidade (posição 4–10) encontrada.")
        return {}

    print(f"[content] Analisando qualidade de conteúdo de {len(candidates)} URL(s)...")
    results = {}
    for r in candidates:
        url = r["url"]
        text = fetch_page_text_cached(site, url, use_cache=use_cache)
        if not text:
            print(f"[content] [sem texto] {url}")
            continue
        kws = target_keywords_for_url(query_rows or [], url)
        nlp_res = (nlp_results or {}).get(url)
        cq = analyze_content_quality(text, kws, nlp_res, url=url)
        results[url] = cq
        # Usa a chave 'verdict' (ASCII) e não 'verdict_label' (emoji) para não
        # depender da codificação do console — os emojis ficam só nos relatórios.
        print(
            f"[content] [{cq['verdict']}] "
            f"{cq['word_count']} palavras, densidade {cq['keyword_density']:.1f}%  {url}"
        )
    return results
