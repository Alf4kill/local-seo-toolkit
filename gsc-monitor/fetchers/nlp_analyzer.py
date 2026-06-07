"""
nlp_analyzer.py — Análise de entidades e categorias via Cloud Natural Language API.

Analisa páginas de oportunidade (posição 4–10) com annotateText, combinando:
  - extractEntities : entidades semânticas com saliência 0–1
  - classifyText    : categoria de conteúdo na taxonomia Google/IAB (confidence 0–1)

Autenticação: API key do Google Cloud (mesma do Knowledge Graph).
Cota gratuita: 5.000 unidades/mês.
Custo por URL: 2 unidades (extractEntities + classifyText em chamada única).
Se o texto for curto demais para classifyText, usa apenas extractEntities (1 unidade).
Use somente com a flag --nlp para preservar a cota.

Como habilitar:
  console.cloud.google.com → Ativar "Cloud Natural Language API"
"""

import html as html_module
import os
import re
import requests
import time

from config import NLP_DELAY

NLP_ANNOTATE_URL = "https://language.googleapis.com/v1/documents:annotateText"
NLP_ENTITIES_URL = "https://language.googleapis.com/v1/documents:analyzeEntities"
TTL_NLP_HOURS    = 72
MAX_TEXT_CHARS   = 5000   # 3000 → 5000: com limpeza interna, mais chars = melhor classifyText
# Tipos de entidade NLP pouco informativos para SEO
_SKIP_TYPES = frozenset({"NUMBER", "PRICE", "DATE", "ADDRESS", "PHONE_NUMBER"})

# ─── Limpeza interna (dentro de <main>/<article>) ─────────────────────────────
# Elementos estruturais que aparecem DENTRO do bloco de conteúdo principal mas
# não fazem parte do artigo: listas de bairros/cidades, galerias de imagens,
# barras laterais e banners CTA. Sem essa limpeza, a API NLP detecta nomes de
# cidades como entidades LOCATION de alta saliência, deslocando entidades reais.

# Tags que nunca se aninham — remoção por nome de tag é segura.
_NOISE_TAG_NAMES: tuple[str, ...] = ("aside", "nav")

# Pares (tag, substring-de-class) — apenas para elementos que NÃO têm a mesma
# tag aninhada dentro, portanto o regex fecha no </tag> correto.
_NOISE_SECTION_CLASSES: tuple[tuple[str, str], ...] = (
    ("section", "regioesDeAtendimento"),  # lista de cidades/bairros por aba
    ("section", "galeria"),               # carrossel de imagens (Swiper)
    ("section", "cta-division"),          # banner call-to-action
    ("section", "cta-section"),           # variante do banner CTA
)


# ---------------------------------------------------------------------------
# Limpeza interna de ruído (dentro do bloco <main>/<article>)
# ---------------------------------------------------------------------------

def _strip_inner_noise(html: str) -> str:
    """
    Remove blocos estruturais DENTRO do <main>/<article> que poluiriam a
    análise NLP com conteúdo irrelevante (nomes de cidades, títulos de
    artigos relacionados, texto de CTA).

    Padrões tratados:
      - <aside>              → índice lateral + CTA (template Blog)
      - <nav>                → eventual nav interno
      - <section class="regioesDeAtendimento"> → lista de bairros/cidades
      - <section class="galeria">              → carrossel de imagens
      - <section class="cta-*">               → banners de conversão

    Segurança do regex: cada padrão usa apenas tags que não se aninham
    consigo mesmas (ex: não há <aside> dentro de <aside>), portanto o
    regex fecha no </tag> correto sem captura prematura.
    """
    # 1 — Por nome de tag (auto-exclusão de aninhamento)
    for tag in _NOISE_TAG_NAMES:
        html = re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>", " ", html,
            flags=re.DOTALL | re.IGNORECASE,
        )
    # 2 — Por (tag, substring-de-class)
    for tag, cls in _NOISE_SECTION_CLASSES:
        html = re.sub(
            rf'<{tag}\b[^>]*\bclass="[^"]*{re.escape(cls)}[^"]*"[^>]*>.*?</{tag}>',
            " ", html,
            flags=re.DOTALL | re.IGNORECASE,
        )
    return html


# ---------------------------------------------------------------------------
# Cache  (chave nlp2_ distingue do formato antigo — lista simples)
# ---------------------------------------------------------------------------

def _nlp_cache_key(url: str) -> str:
    clean = re.sub(r"[^\w]", "_", url)
    return f"nlp2_{clean[-55:]}"


def _get_nlp_cache(site: str, url: str) -> "dict | None":
    from core.cache import _cache_dir, _read_entry, _is_fresh
    key   = _nlp_cache_key(url)
    path  = os.path.join(_cache_dir(site), f"{key}.json")
    entry = _read_entry(path)
    if entry and _is_fresh(entry, TTL_NLP_HOURS):
        data = entry["data"]
        if isinstance(data, dict):
            return data
    return None


def _set_nlp_cache(site: str, url: str, result: dict) -> None:
    from core.cache import _cache_dir, _write_entry
    key  = _nlp_cache_key(url)
    path = os.path.join(_cache_dir(site), f"{key}.json")
    _write_entry(path, result)


# ---------------------------------------------------------------------------
# Fetch e limpeza de texto
# ---------------------------------------------------------------------------

def _fetch_page_text(url: str, max_chars: int = MAX_TEXT_CHARS) -> "str | None":
    """
    Baixa o HTML da URL e retorna texto puro focado no conteúdo editorial.

    Pipeline de extração:
      1. Isola <main> ou <article> — bloco de conteúdo semântico principal.
         Fallback: remove <nav>/<header>/<footer>/<aside> globais.
      2. Remove ruído INTERNO ao bloco extraído: listas de cidades, galerias
         de imagens, aside de navegação, banners CTA.  ← novo (evita entidades
         LOCATION de bairros que deslocam entidades reais do artigo)
      3. Remove <script>/<style> e todas as demais tags HTML.
      4. Decodifica entidades HTML e normaliza espaços.
      5. Retorna até max_chars caracteres.
    """
    try:
        resp = requests.get(
            url,
            timeout=12,
            headers={"User-Agent": "GSC-Monitor/1.0 (SEO entity analysis)"},
        )
        resp.raise_for_status()
        html = resp.text

        # 1 — Isola bloco semântico principal
        for semantic_tag in ("main", "article"):
            m = re.search(
                rf"<{semantic_tag}[^>]*>(.*?)</{semantic_tag}>",
                html, re.DOTALL | re.IGNORECASE,
            )
            if m:
                html = m.group(1)
                break
        else:
            # Fallback: remove chrome global quando não há <main>/<article>
            for chrome_tag in ("nav", "header", "footer", "aside"):
                html = re.sub(
                    rf"<{chrome_tag}[^>]*>.*?</{chrome_tag}>", " ", html,
                    flags=re.DOTALL | re.IGNORECASE,
                )

        # 2 — Remove ruído interno (galerias, listas de cidades, aside, CTAs)
        html = _strip_inner_noise(html)

        # 3 — Remove scripts, estilos e demais tags HTML
        text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", html,
                      flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        # 4 — Decodifica entidades HTML (ex: &atilde; → ã, &ccedil; → ç)
        text = html_module.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if text else None
    except Exception as exc:
        print(f"[nlp] ERRO ao buscar página {url}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Parsers de resposta
# ---------------------------------------------------------------------------

def _parse_entities(raw: list) -> list:
    entities = [
        {
            "name":     e.get("name", ""),
            "type":     e.get("type", "OTHER"),
            "salience": round(e.get("salience", 0.0), 3),
        }
        for e in raw
        if e.get("type") not in _SKIP_TYPES and e.get("name", "").strip()
    ]
    entities.sort(key=lambda e: -e["salience"])
    return entities[:8]


def _parse_categories(raw: list) -> list:
    categories = [
        {"name": c.get("name", ""), "confidence": round(c.get("confidence", 0.0), 3)}
        for c in raw
    ]
    categories.sort(key=lambda c: -c["confidence"])
    return categories[:3]


# ---------------------------------------------------------------------------
# Análise de página
# ---------------------------------------------------------------------------

def analyze_page_nlp(url: str, api_key: str) -> dict:
    """
    Analisa entidades e categorias de uma URL via Natural Language API.

    Usa annotateText (extractEntities + classifyText) em chamada única — 2 unidades.
    Se classifyText falhar por texto insuficiente, usa apenas analyzeEntities — 1 unidade.

    Retorna: {"entities": [...], "categories": [...]}
    """
    text = _fetch_page_text(url)
    if not text:
        return {"entities": [], "categories": []}

    # Tenta annotateText com ambas as features (2 unidades de cota)
    try:
        resp = requests.post(
            NLP_ANNOTATE_URL,
            params={"key": api_key},
            json={
                "document":     {"type": "PLAIN_TEXT", "content": text},
                "features":     {"extractEntities": True, "classifyText": True},
                "encodingType": "UTF8",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            body = resp.json()
            return {
                "entities":   _parse_entities(body.get("entities", [])),
                "categories": _parse_categories(body.get("categories", [])),
            }
    except requests.RequestException:
        pass

    # Fallback: apenas entidades (texto curto demais para classifyText — 1 unidade)
    try:
        resp = requests.post(
            NLP_ENTITIES_URL,
            params={"key": api_key},
            json={
                "document":     {"type": "PLAIN_TEXT", "content": text},
                "encodingType": "UTF8",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return {"entities": _parse_entities(resp.json().get("entities", [])), "categories": []}
    except requests.RequestException as exc:
        print(f"[nlp] ERRO na API para {url}: {exc}")
        return {"entities": [], "categories": []}


def analyze_opportunity_urls(
    opportunity_rows: list,
    site: str,
    api_key: "str | None" = None,
    use_cache: bool = True,
    max_urls: int = 5,
    delay: float = NLP_DELAY,
) -> dict:
    """
    Analisa entidades e categorias das URLs de oportunidade (posição 4–10).

    Retorna: {url: {"entities": [...], "categories": [...]}}
    """
    from fetchers.knowledge_graph import load_api_key
    if api_key is None:
        api_key = load_api_key()
    if not api_key:
        print("[nlp] API key não configurada — análise NLP ignorada.")
        return {}

    candidates = sorted(
        [r for r in opportunity_rows
         if r.get("has_data") and r.get("position") is not None
         and 4 <= r["position"] <= 10],
        key=lambda r: -r.get("impressions", 0),
    )[:max_urls]

    if not candidates:
        print("[nlp] Nenhuma URL de oportunidade (posição 4–10) encontrada.")
        return {}

    results = {}
    for r in candidates:
        url = r["url"]

        if use_cache:
            cached = _get_nlp_cache(site, url)
            if cached is not None:
                print(f"[nlp] [CACHE] {url}")
                results[url] = cached
                continue

        print(f"[nlp] Analisando: {url}")
        result = analyze_page_nlp(url, api_key)
        results[url] = result
        if use_cache:
            _set_nlp_cache(site, url, result)
        time.sleep(delay)

    return results


def print_nlp_results(nlp_results: dict) -> None:
    """Exibe resultado da análise NLP no terminal."""
    if not nlp_results:
        return
    print(f"\n{'─' * 68}")
    print("  Análise NLP — Entidades & Categorias")
    print(f"{'─' * 68}")
    for url, data in nlp_results.items():
        entities   = data.get("entities", [])   if isinstance(data, dict) else data
        categories = data.get("categories", []) if isinstance(data, dict) else []

        short = url if len(url) <= 58 else url[:55] + "..."
        print(f"\n  {short}")

        if categories:
            for c in categories[:2]:
                cat_short = c["name"].rsplit("/", 1)[-1] if "/" in c["name"] else c["name"]
                print(f"    [categoria      ]  {c['confidence']:.2f}  {cat_short}")

        if entities:
            for e in entities[:5]:
                print(f"    [{e['type'][:14]:<14}]  {e['salience']:.3f}  {e['name']}")
        else:
            print("    (sem entidades detectadas)")
    print(f"{'─' * 68}\n")
