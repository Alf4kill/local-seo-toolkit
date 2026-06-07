"""
linkgraph.py — Grafo de LINKS INTERNOS do site (100% local, sem API/custo).

`loaders.extract_text` joga fora as tags <a> (só quer o texto). Aqui fazemos o
oposto: lemos o MARKUP cru das páginas e extraímos os links internos para montar
um grafo página→página. Disso saem 4 diagnósticos que a camada semântica não dá:

  1. ÓRFÃS de verdade — páginas que NENHUMA outra linka (o gsc-monitor chama de
     "órfã" a página com 0 impressões, que é outra coisa; esta é a definição certa).
  2. MONEY-PAGES sub-linkadas — páginas com tráfego real (GSC) mas poucos links
     internos apontando p/ elas (autoridade interna desperdiçada).
  3. Canibalização de ÂNCORA — o MESMO texto-âncora apontando p/ páginas DIFERENTES
     (confunde o Google sobre qual página deve rankear pra aquele termo).
  4. PLANO DE LINKS por grupo (hub-and-spoke) — completa o modo --differentiate:
     a estrutura cabeça/spoke só funciona se os spokes LINKAREM para a cabeça;
     aqui apontamos exatamente quais links spoke→cabeça (e cabeça→spoke) FALTAM.

Núcleo PURO (só stdlib + reuso de dedup.normalize_kw). A leitura de arquivos fica
nos loaders; aqui só processamos strings/dicts — fácil de testar sem servidor/ML.

ESCOPO HONESTO: em modo backup/pasta lemos o .php FONTE, então só vemos os links
ESTÁTICOS do corpo. O menu/rodapé/breadcrumb do primeWeb são montados por include
PHP (server-side) e por concatenação dinâmica — NÃO aparecem no arquivo fonte e
NÃO entram no grafo. Logo "órfã" = sem link CONTEXTUAL de outro artigo (a página
pode estar no menu). Para o grafo COMPLETO (com navegação renderizada), use as
fontes via --urls (HTML do site no ar), que já vem com tudo resolvido.
"""

import html as H
import os
import re

from core.dedup import normalize_kw
from core.loaders import slugify

# Âncoras genéricas que legitimamente apontam p/ muitos lugares — NÃO são
# canibalização de âncora (são, no máximo, um problema separado de "âncora pobre").
_GENERIC_ANCHORS = {
    "clique aqui",
    "clique",
    "aqui",
    "saiba mais",
    "saiba",
    "leia mais",
    "leia",
    "veja mais",
    "veja",
    "ver mais",
    "ver",
    "mais",
    "continue lendo",
    "confira",
    "link",
    "este link",
    "acesse",
    "acesse aqui",
    "voltar",
    "home",
    "pagina inicial",
}

_A_TAG = re.compile(r"<a\b([^>]*?)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_HREF = re.compile(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_PHP = re.compile(r"<\?.*?\?>", re.DOTALL)
_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</(script|style)>", re.DOTALL | re.IGNORECASE)
_SCHEME_HOST = re.compile(r"^[a-z][a-z0-9+.\-]*://[^/]+", re.IGNORECASE)
_EXT = re.compile(r"\.(php\d?|html?|aspx?|jsp|cgi)$", re.IGNORECASE)


def _clean_anchor(inner: str) -> str:
    """Texto de âncora a partir do HTML interno do <a> (sem tags, sem entidades)."""
    return re.sub(r"\s+", " ", H.unescape(_TAG.sub(" ", inner))).strip()


def extract_links(markup: str) -> list:
    """
    Extrai (href, texto_ancora) de cada <a href> do markup.

    Remove blocos PHP/script/style ANTES — assim hrefs dinâmicos (href="<?= ... ?>")
    viram vazio e são descartados (não dá p/ resolvê-los estaticamente mesmo).
    """
    if not markup:
        return []
    markup = _PHP.sub(" ", markup)
    markup = _SCRIPT_STYLE.sub(" ", markup)
    out = []
    for m in _A_TAG.finditer(markup):
        attrs, inner = m.group(1), m.group(2)
        hm = _HREF.search(attrs)
        if not hm:
            continue
        href = hm.group(1) or hm.group(2) or hm.group(3) or ""
        out.append((href, _clean_anchor(inner)))
    return out


def normalize_href(href: str) -> "str | None":
    """
    Reduz um href ao SLUG da página de destino (último segmento, sem extensão),
    ou None se for externo/não-página (mailto, tel, âncora pura, vazio).

    A resolução é "best-effort": externos sobrevivem como um slug candidato, mas
    o grafo só mantém a aresta se esse slug existir entre as páginas conhecidas
    (`known`) — então links externos caem fora naturalmente.
    """
    if not href:
        return None
    h = href.strip()
    low = h.lower()
    if not h or low.startswith(("mailto:", "tel:", "javascript:", "data:", "#", "//")):
        return None
    h = h.split("#", 1)[0].split("?", 1)[0]  # tira fragmento e query
    h = _SCHEME_HOST.sub("", h).strip("/")  # tira esquema+host
    if not h:
        return None  # era a home ("/" ou "https://host/")
    seg = h.split("/")[-1]
    seg = _EXT.sub("", seg).lower()
    return seg or None


def build_link_graph(sources: dict, known: "set | None" = None) -> dict:
    """
    Monta o grafo de links internos a partir de {slug: markup_cru}.

    `known` = slugs válidos como DESTINO (padrão: as próprias chaves de `sources`).
    Mantém só arestas para destinos conhecidos e descarta auto-links.

    Retorna um dict:
      out["src"][dst]  -> lista de âncoras (src linka dst)
      in["dst"]["src"] -> lista de âncoras (dst é linkado por src)
      edges            -> [(src, dst, ancora), ...]
      anchor_index[na] -> {dst: contagem}   (na = âncora normalizada)
      known, sources   -> conjuntos
    """
    known = set(known) if known is not None else set(sources)
    # Mapa slug-normalizado -> chave original. Faz o grafo funcionar tanto quando as
    # chaves são SLUGS (modo pasta/primeweb) quanto URLs completas (modo --urls):
    # resolvemos o href a um slug e voltamos à chave original. (1ª chave vence em
    # caso de slugs repetidos em hierarquias profundas — raro em URLs amigáveis.)
    slug_of = {}
    for k in known:
        slug_of.setdefault(normalize_href(k) or k, k)
    out, inn, edges, anchor_index = {}, {}, [], {}
    for src, markup in sources.items():
        tgts = out.setdefault(src, {})
        for href, anchor in extract_links(markup):
            dst_slug = normalize_href(href)
            dst = slug_of.get(dst_slug) if dst_slug else None
            if not dst or dst == src:
                continue
            tgts.setdefault(dst, []).append(anchor)
            inn.setdefault(dst, {}).setdefault(src, []).append(anchor)
            edges.append((src, dst, anchor))
            na = normalize_kw(anchor)
            if na:
                tcount = anchor_index.setdefault(na, {})
                tcount[dst] = tcount.get(dst, 0) + 1
    return {
        "out": out,
        "in": inn,
        "edges": edges,
        "anchor_index": anchor_index,
        "known": known,
        "sources": set(sources),
    }


# ---------------------------------------------------------------------------
# Diagnósticos (puros, sobre o grafo + GSC opcional)
# ---------------------------------------------------------------------------


def find_orphans(graph: dict, targets: "set | None" = None) -> list:
    """Páginas (entre `targets`, padrão `known`) que NENHUMA outra linka."""
    targets = set(targets) if targets is not None else set(graph["known"])
    inn = graph["in"]
    return sorted(t for t in targets if not inn.get(t))


def inlink_report(graph: dict, targets: "set | None" = None, gsc: "dict | None" = None) -> list:
    """Linha por página: nº de links de entrada/saída + métricas GSC (se houver)."""
    targets = sorted(targets) if targets is not None else sorted(graph["known"])
    gsc = gsc or {}
    rows = []
    for t in targets:
        g = gsc.get(t) or {}
        rows.append(
            {
                "slug": t,
                "inlinks": len(graph["in"].get(t, {})),
                "outlinks": len(graph["out"].get(t, {})),
                "impressions": g.get("impressions", 0),
                "clicks": g.get("clicks", 0),
                "position": g.get("position"),
            }
        )
    return rows


def underlinked_money_pages(rows: list, max_inlinks: int = 1, min_impressions: int = 1) -> list:
    """Páginas com tráfego real (GSC) mas <= max_inlinks links internos de entrada."""
    pages = [r for r in rows if r["inlinks"] <= max_inlinks and r["impressions"] >= min_impressions]
    pages.sort(key=lambda r: (-r["impressions"], r["inlinks"]))
    return pages


def anchor_collisions(graph: dict, min_targets: int = 2) -> list:
    """
    Mesma âncora (normalizada) apontando p/ páginas DIFERENTES = sinal ambíguo
    sobre qual página deve rankear pra aquele termo. Ignora âncoras genéricas.
    """
    out = []
    for anchor, targets in graph["anchor_index"].items():
        if anchor in _GENERIC_ANCHORS or len(targets) < min_targets:
            continue
        ordered = dict(sorted(targets.items(), key=lambda kv: -kv[1]))
        out.append({"anchor": anchor, "targets": ordered, "n": len(ordered)})
    out.sort(key=lambda d: (-d["n"], d["anchor"]))
    return out


# ---------------------------------------------------------------------------
# Links gerados por ARRAY/template (primeWeb) — não aparecem na extração estática
# porque o template os monta com PHP (foreach/array_rand sobre $blog/$artigos...).
# Ex.: blog.php faz `foreach ($blog as $link) <a href=...formatStringToURL($link)>`
# → linka TODOS os artigos (página de índice). more-articles.php faz
# `array_rand($artigos,4)` → 4 ALEATÓRIOS (widget de "relacionados").
# Modelamos esses links como tipo 'index' (foreach do array inteiro) ou 'widget'
# (array_rand/array_slice = subconjunto), SEPARADOS dos links 'contextual' (corpo),
# porque o Google valoriza muito mais o link contextual que o de template.
# ---------------------------------------------------------------------------

_ARRAY_DECL = re.compile(r"\$(\w+)\s*=\s*array\((.*?)\n\);", re.DOTALL)
_INCLUDE = re.compile(r"""(?:include|require)(?:_once)?\s*\(?\s*["']([^"']+)["']""", re.IGNORECASE)
_ALIAS = re.compile(r"\$(\w+)\s*=\s*\$(\w+)\s*;")
_FOREACH = re.compile(r"foreach\s*\(\s*(?:array_slice\s*\(\s*)?\$(\w+)", re.IGNORECASE)
_ARRAY_RAND = re.compile(r"array_rand\s*\(\s*\$(\w+)", re.IGNORECASE)
_ARRAY_SLICE = re.compile(r"array_slice\s*\(\s*\$(\w+)", re.IGNORECASE)


def parse_primeweb_arrays(base_path: str) -> dict:
    """Lê include/parametros.php e devolve {nome_array: set(slugs)} (blog, artigos…)."""
    path = os.path.join(base_path, "include", "parametros.php")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return {}
    out = {}
    for m in _ARRAY_DECL.finditer(src):
        items = re.findall(r'"([^"]*)"', m.group(2))
        slugs = {slugify(x) for x in items if x.strip()}
        if slugs:
            out[m.group(1)] = slugs
    return out


def detect_array_emitters(php_source: str, array_names: set) -> list:
    """
    Acha os links gerados por array num trecho PHP. Retorna [(array, modo)] com
    modo 'index' (foreach do array inteiro) ou 'widget' (array_rand/array_slice =
    subconjunto). Só conta se houver geração de slug de link (formatStringToURL).
    """
    if not php_source or "formatStringToURL" not in php_source:
        return []
    alias = {
        m.group(1): m.group(2) for m in _ALIAS.finditer(php_source) if m.group(2) in array_names
    }

    def real(v):
        return v if v in array_names else alias.get(v)

    emit = {}
    for m in _FOREACH.finditer(php_source):
        arr = real(m.group(1))
        if not arr:
            continue
        sliced = bool(re.search(r"array_slice\s*\(\s*\$" + re.escape(m.group(1)), php_source))
        emit[arr] = "widget" if sliced else "index"  # index = array inteiro
    for m in _ARRAY_RAND.finditer(php_source):
        arr = real(m.group(1))
        if arr:
            emit.setdefault(arr, "widget")
    for m in _ARRAY_SLICE.finditer(php_source):
        arr = real(m.group(1))
        if arr:
            emit.setdefault(arr, "widget")
    return list(emit.items())


def _emitters_for_page(markup: str, base_path: str, array_names: set, cache: dict) -> dict:
    """Emissores do próprio markup + dos arquivos que ele inclui (1 nível)."""
    emit = dict(detect_array_emitters(markup, array_names))
    for inc in _INCLUDE.findall(markup):
        incpath = os.path.normpath(os.path.join(base_path, inc))
        if incpath not in cache:
            try:
                with open(incpath, encoding="utf-8", errors="replace") as f:
                    cache[incpath] = dict(detect_array_emitters(f.read(), array_names))
            except OSError:
                cache[incpath] = {}
        for arr, mode in cache[incpath].items():
            emit.setdefault(arr, mode)
    return emit


def build_template_inbound(
    sources: dict, base_path: str, arrays: dict, known: "set | None" = None
) -> dict:
    """
    {dst: set(tipos)} dos links de array/template (tipos: 'index', 'widget').
    `sources` = {slug: markup}; `arrays` = {nome: set(slugs)} de parse_primeweb_arrays.
    """
    if not arrays:
        return {}
    known = set(known) if known is not None else set(sources)
    names = set(arrays)
    cache, inbound = {}, {}
    for src_slug, markup in sources.items():
        for arr, mode in _emitters_for_page(markup, base_path, names, cache).items():
            for dst in arrays.get(arr, ()):
                if dst in known and dst != src_slug:
                    inbound.setdefault(dst, set()).add(mode)
    return inbound


def classify_pages(targets, graph: dict, template_inbound: dict) -> dict:
    """
    Classifica cada página em 3 níveis honestos:
      'contextual'    — recebe >=1 link CONTEXTUAL (de corpo) de outro artigo.
      'template_only' — 0 contextual, mas alcançável por índice/widget (array).
      'orphan'        — não recebe NENHUM link (nem contextual, nem de template).
    """
    out = {}
    for t in targets:
        ctx = len(graph["in"].get(t, {}))
        types = template_inbound.get(t, set())
        tier = "contextual" if ctx else ("template_only" if types else "orphan")
        out[t] = {"contextual": ctx, "template": sorted(types), "tier": tier}
    return out


# ---------------------------------------------------------------------------
# Plano de links por grupo (completa o --differentiate: hub-and-spoke)
# ---------------------------------------------------------------------------


def _hub_and_spokes(c: dict):
    """(hub, keyword_da_cabeça, [(spoke_slug, keyword), ...]) a partir do cluster.

    Usa o plano de diferenciação (cabeça/spokes) se existir; senão cai p/ a
    canônica por performance (GSC) ou a representante do embedding.
    """
    d = c.get("diff")
    if d and d.get("paginas"):
        paginas = [p for p in d["paginas"] if p.get("slug")]
        hub = d.get("cabeca") or (paginas[0]["slug"] if paginas else None)
        hub_kw = next((p.get("keyword_alvo", "") for p in paginas if p.get("slug") == hub), "")
        spokes = [(p["slug"], p.get("keyword_alvo", "")) for p in paginas if p["slug"] != hub]
        return hub, hub_kw, spokes
    hub = c.get("canonical_by_performance") or c.get("representative")
    spokes = [(m, "") for m in c.get("members", []) if m != hub]
    return hub, "", spokes


def cluster_link_plan(clusters: list, graph: dict, min_size: int = 2) -> list:
    """
    Para cada grupo (>= min_size), checa o backbone hub-and-spoke no grafo e anexa
    c["link_plan"] com os links que FALTAM. Retorna os grupos que receberam plano.
    """
    out = []
    for c in clusters:
        if c.get("size", len(c.get("members", []))) < min_size:
            continue
        hub, hub_kw, spokes = _hub_and_spokes(c)
        if not hub:
            continue
        hub_out = graph["out"].get(hub, {})
        missing_up, have_up, missing_down = [], [], []
        for slug, _kw in spokes:
            if graph["out"].get(slug, {}).get(hub):
                have_up.append(slug)
            else:
                missing_up.append(slug)
            if not hub_out.get(slug):
                missing_down.append(slug)
        plan = {
            "hub": hub,
            "hub_keyword": hub_kw,
            "spokes_total": len(spokes),
            "missing_spoke_to_hub": missing_up,
            "have_spoke_to_hub": have_up,
            "missing_hub_to_spoke": missing_down,
            "complete": not missing_up and not missing_down,
        }
        c["link_plan"] = plan
        out.append(c)
    return out
