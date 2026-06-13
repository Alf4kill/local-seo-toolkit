"""
pruning.py — Plano de Poda: detecção e remoção planejada de URLs antigas.

Premissa (convenção da empresa): o sitemap (+ image-sitemap) lista TODAS as
páginas ativas do site. Logo, qualquer URL que o Google conhece (Search
Analytics) e que NÃO está no sitemap é uma página antiga/morta — candidata a
remoção (410/404) ou, se ainda recebe impressões, a redirect 301 para uma
página ativa relevante.

Fluxo em duas etapas (revisão humana obrigatória entre elas):
  1. build_pruning_plan  → CSV editável com ação sugerida por URL antiga
     (410 por padrão; "revisar" quando ainda há tráfego — o analista decide)
  2. parse_plan_csv + build_poda_htaccess/nginx → blocos de servidor finais
     a partir do CSV revisado pelo analista

IMPORTANTE (regra de honestidade): o plano é uma SUGESTÃO. URLs com tráfego
nunca recebem diretiva automática — ficam como "revisar" até o analista
definir a ação. Redirects em massa para a home são detectados e avisados
(o Google trata isso como soft-404).

Módulo de lógica pura: sem rede e sem IO de arquivos (CSV entra/sai como
linhas de texto — a persistência fica em core/storage.py).
"""

import csv
import re
from urllib.parse import unquote, urlparse

from core.content_quality import _normalize_accents, slug_phrase

# Ação sugerida vira "revisar" (em vez de 410) quando a URL antiga ainda tem
# cliques > 0 ou impressões >= este piso no período analisado.
PODA_MIN_IMPRESSIONS = 10

# Acima deste nº de redirects 301 apontando para a home, o plano ganha um
# aviso destacado (padrão de soft-404 aos olhos do Google).
HOMEPAGE_WARN_THRESHOLD = 3

# Similaridade mínima (Jaccard de tokens de slug) para sugerir destino por slug.
SLUG_MIN_JACCARD = 0.5

# Nº de queries exibidas por URL no plano (contexto para o analista).
TOP_QUERIES_PER_URL = 3

_PODA_DISCLAIMER = (
    "SUGESTAO gerada automaticamente pelo GSC Monitor: URLs conhecidas pelo "
    "Google que estao FORA do sitemap (paginas antigas, na convencao de "
    "sitemap completo). NAO aplique sem revisao humana. URLs com trafego "
    "ficam como 'revisar' ate o analista definir 410/404/301 e o destino. "
    "Evite redirecionar tudo para a home (soft-404)."
)

_VALID_ACTIONS = {"410", "404", "301", "manter", "revisar"}


# ---------------------------------------------------------------------------
# Normalização de URL para comparação sitemap × GSC
# ---------------------------------------------------------------------------


def normalize_for_match(url: str) -> str:
    """
    Normaliza uma URL para comparação entre sitemap e GSC, tolerando as
    variações que NÃO distinguem páginas na prática (e que gerariam falsos
    "fantasmas" — perigoso, pois a sugestão padrão é 410):
      - esquema http/https ignorado
      - host minúsculo e sem prefixo www.
      - barra final do path ignorada
      - percent-encoding decodificado
      - fragmento (#...) descartado
    A query string é PRESERVADA — ela distingue páginas reais.
    """
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    host = host.removeprefix("www.")
    path = unquote(parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    norm = f"{host}{path or '/'}"
    if parsed.query:
        norm += f"?{parsed.query}"
    return norm


def _url_path(url: str) -> str:
    """Caminho (sem query) de uma URL absoluta. '/' se vazio."""
    return urlparse(url).path or "/"


def _is_homepage(url: str) -> bool:
    return _url_path(url).rstrip("/") == ""


def _homepage_url(sitemap_urls: list) -> "str | None":
    """
    URL da página inicial (home) do site, a partir do sitemap. Usada como
    destino de ÚLTIMO RECURSO no plano de poda (ver build_pruning_plan).
    Prefere a home explicitamente listada no sitemap; se ausente, constrói a
    raiz a partir do host da primeira URL.
    """
    for url in sitemap_urls or []:
        if _is_homepage(url):
            return url
    if sitemap_urls:
        parsed = urlparse(sitemap_urls[0])
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/"
    return None


def _brand_compact(sitemap_urls: list) -> str:
    """Host do site sem www/pontos/hífens — base p/ detectar query de marca."""
    for url in sitemap_urls:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if host:
            return re.sub(r"[^a-z0-9]", "", _normalize_accents(host.split(".")[0]))
    return ""


def _is_brand_query(query: str, brand_compact: str) -> bool:
    """
    True se a query é navegacional/de marca (ex: "exemplo kits" num site
    exemplokits.com.br). Queries de marca casam com QUALQUER página do site
    e geram sugestões de destino 301 sem relação real — são excluídas do
    scoring (mas continuam visíveis em top_queries, como contexto).
    """
    if not brand_compact or len(brand_compact) < 4:
        return False
    compact = re.sub(r"[^a-z0-9]", "", _normalize_accents(query.lower()))
    if len(compact) < 4:
        return False
    return compact in brand_compact or brand_compact in compact


# ---------------------------------------------------------------------------
# Etapa 1 — detecção de URLs antigas (fantasmas) e plano sugerido
# ---------------------------------------------------------------------------


def find_ghost_urls(api_pages: dict, sitemap_urls: list) -> list:
    """
    Diferença de conjuntos: URLs com dados no GSC que não estão no sitemap.

    Parâmetros:
        api_pages    — dict url -> {"clicks", "impressions", "ctr", "position"}
                       (formato do cache de fetch_positions)
        sitemap_urls — lista de URLs ativas (whitelist)

    Retorna lista de dicts {"url", "clicks", "impressions", "ctr", "position"}
    ordenada por impressões desc. A comparação usa normalize_for_match para
    não marcar como fantasma variações triviais (barra final, www, http/https).
    """
    whitelist = {normalize_for_match(u) for u in sitemap_urls}
    ghosts = []
    for url, metrics in (api_pages or {}).items():
        if normalize_for_match(url) in whitelist:
            continue
        ghosts.append(
            {
                "url": url,
                "clicks": int(metrics.get("clicks", 0)),
                "impressions": int(metrics.get("impressions", 0)),
                "ctr": metrics.get("ctr", 0.0),
                "position": metrics.get("position"),
            }
        )
    ghosts.sort(key=lambda g: (-g["impressions"], -g["clicks"], g["url"]))
    return ghosts


def _queries_by_ghost(ghost_norms: set, query_rows: list) -> dict:
    """Agrupa as linhas query×page dos fantasmas: norm_url -> [rows]."""
    out: dict = {}
    for row in query_rows or []:
        norm = normalize_for_match(row.get("url", ""))
        if norm in ghost_norms:
            out.setdefault(norm, []).append(row)
    return out


def _suggest_target_by_query(
    ghost_rows: list,
    active_by_query: dict,
    brand_compact: str = "",
) -> "tuple[str, str] | None":
    """
    Sugere destino 301 por query compartilhada: a URL ativa que mais disputa
    as mesmas queries do fantasma (peso = impressões do fantasma na query).
    A home nunca é sugerida (casa queries de forma ampla demais) e queries de
    marca não pontuam (casam com qualquer página — sugestão sem relação real).
    Retorna (url_destino, "query compartilhada") ou None.
    """
    scores: dict = {}
    clicks_of: dict = {}
    for row in ghost_rows:
        query = row.get("query", "")
        if _is_brand_query(query, brand_compact):
            continue
        weight = row.get("impressions", 0) + 1  # +1: query com 0 impr. ainda conta
        for cand in active_by_query.get(query, []):
            url = cand["url"]
            if _is_homepage(url):
                continue
            scores[url] = scores.get(url, 0) + weight
            clicks_of[url] = clicks_of.get(url, 0) + cand.get("clicks", 0)
    if not scores:
        return None
    best = sorted(scores, key=lambda u: (-scores[u], -clicks_of.get(u, 0), u))[0]
    return best, "query compartilhada"


def _suggest_target_by_slug(
    ghost_url: str,
    active_slug_tokens: list,
) -> "tuple[str, str] | None":
    """
    Fallback: destino pela similaridade de slug (Jaccard de tokens, sem
    stopwords — reusa slug_phrase do P3). Exige Jaccard >= SLUG_MIN_JACCARD.
    Retorna (url_destino, "slug semelhante") ou None.
    """
    phrase = slug_phrase(ghost_url)
    if not phrase:
        return None
    ghost_tokens = set(phrase.split())
    best_url, best_score = None, 0.0
    for url, tokens in active_slug_tokens:
        union = ghost_tokens | tokens
        if not union:
            continue
        jaccard = len(ghost_tokens & tokens) / len(union)
        if jaccard > best_score:
            best_url, best_score = url, jaccard
    if best_url is None or best_score < SLUG_MIN_JACCARD:
        return None
    return best_url, "slug semelhante"


def build_pruning_plan(
    api_pages: dict,
    sitemap_urls: list,
    query_rows: "list | None" = None,
    min_impressions: int = PODA_MIN_IMPRESSIONS,
    extra_urls: "list | None" = None,
    home_fallback: bool = True,
) -> dict:
    """
    Monta o Plano de Poda (SUGESTÃO) a partir do diff GSC × sitemap.

    Ação sugerida por URL antiga:
      - "revisar" — ainda tem cliques > 0 ou impressões >= min_impressions:
        oportunidade de 301; quem decide é o analista (nunca o código)
      - "410"     — sem tráfego relevante: remoção limpa

    Para toda URL antiga tenta-se um destino 301 sugerido (query compartilhada
    com página ativa > slug semelhante). Sem candidato confiável, URLs COM
    tráfego ("revisar") caem no fallback da home (ver `home_fallback`); URLs
    sem tráfego (410) ficam com destino vazio (410 não redireciona).

    Parâmetros extras:
        extra_urls — URLs vindas do export do relatório "Páginas" do GSC
                     (sem dados de busca; a API não expõe esse relatório).
                     As que estiverem fora do sitemap e ainda não detectadas
                     entram no plano com métricas 0 e origem "export-gsc".
        home_fallback — quando True (padrão), uma URL "revisar" sem destino
                     por query/slug recebe a HOME do site como sugestão de
                     último recurso (marcada `target_source="home (fallback)"`),
                     para não deixar a célula de destino em branco na revisão.
                     É uma sugestão FRACA: o Google trata redirect em massa
                     para a home como soft-404 — por isso a ação continua
                     "revisar" (nunca diretiva automática) e parse_plan_csv
                     avisa se muitos virarem 301. Passe False para manter o
                     destino vazio quando não houver candidato relevante.

    Retorna:
    {
        "disclaimer": str,
        "entries": [
            {"url", "clicks", "impressions", "ctr", "position", "action",
             "origem" ("busca" | "export-gsc"), "top_queries": [str],
             "suggested_target": str|None, "target_source": str|None},
            ...                          # revisar primeiro, depois 410
        ],
        "total": int, "total_review": int, "total_410": int,
    }
    """
    ghosts = find_ghost_urls(api_pages, sitemap_urls)
    for g in ghosts:
        g["origem"] = "busca"

    whitelist = {normalize_for_match(u): u for u in sitemap_urls}

    # URLs do export do GSC: só as fora do sitemap e ainda não vistas na busca
    seen = {normalize_for_match(g["url"]) for g in ghosts}
    for url in extra_urls or []:
        norm = normalize_for_match(url)
        if norm in whitelist or norm in seen:
            continue
        seen.add(norm)
        ghosts.append(
            {
                "url": url,
                "clicks": 0,
                "impressions": 0,
                "ctr": 0.0,
                "position": None,
                "origem": "export-gsc",
            }
        )

    ghost_norms = {normalize_for_match(g["url"]) for g in ghosts}

    # Índices auxiliares a partir das queries (se disponíveis)
    ghost_queries = _queries_by_ghost(ghost_norms, query_rows or [])
    active_by_query: dict = {}
    for row in query_rows or []:
        if normalize_for_match(row.get("url", "")) in whitelist:
            active_by_query.setdefault(row.get("query", ""), []).append(row)

    active_slug_tokens = []
    for url in sitemap_urls:
        phrase = slug_phrase(url)
        if phrase:
            active_slug_tokens.append((url, set(phrase.split())))

    brand = _brand_compact(sitemap_urls)
    home_url = _homepage_url(sitemap_urls) if home_fallback else None

    entries = []
    for ghost in ghosts:
        norm = normalize_for_match(ghost["url"])
        rows = sorted(
            ghost_queries.get(norm, []),
            key=lambda r: -r.get("impressions", 0),
        )
        top_queries = [r["query"] for r in rows[:TOP_QUERIES_PER_URL]]

        suggestion = _suggest_target_by_query(rows, active_by_query, brand_compact=brand)
        if suggestion is None:
            suggestion = _suggest_target_by_slug(ghost["url"], active_slug_tokens)

        # O destino sugerido tem de ser uma URL do sitemap ATUAL (whitelist):
        # a sugestão por query devolve a forma vista no GSC (que pode diferir
        # da URL canônica do sitemap em barra final/www/esquema). Mapeia de
        # volta para a string exata do sitemap — é ela que será aplicada no
        # redirect, então tem de existir como página ativa.
        if suggestion is not None:
            canonical = whitelist.get(normalize_for_match(suggestion[0]))
            if canonical is not None:
                suggestion = (canonical, suggestion[1])

        has_traffic = ghost["clicks"] > 0 or ghost["impressions"] >= min_impressions

        # Fallback de ÚLTIMO RECURSO: URL com tráfego ("revisar") que não achou
        # destino por query/slug recebe a home como sugestão — evita célula de
        # destino em branco na revisão. Sugestão FRACA (Google trata redirect
        # em massa p/ home como soft-404): a ação continua "revisar" e a
        # compilação avisa se muitos virarem 301. Não se aplica a 410 (sem
        # tráfego não há o que redirecionar).
        if suggestion is None and has_traffic and home_url:
            suggestion = (home_url, "home (fallback)")

        entries.append(
            {
                **ghost,
                "action": "revisar" if has_traffic else "410",
                "top_queries": top_queries,
                "suggested_target": suggestion[0] if suggestion else None,
                "target_source": suggestion[1] if suggestion else None,
            }
        )

    entries.sort(key=lambda e: (e["action"] != "revisar", -e["impressions"], e["url"]))
    total_review = sum(1 for e in entries if e["action"] == "revisar")
    return {
        "disclaimer": _PODA_DISCLAIMER,
        "entries": entries,
        "total": len(entries),
        "total_review": total_review,
        "total_410": len(entries) - total_review,
    }


# ---------------------------------------------------------------------------
# Import do export do GSC (relatório "Páginas" — sem API; download manual)
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s\"'<>,;]+")


def extract_urls_from_lines(lines, domain: str) -> list:
    """
    Extrai URLs absolutas de linhas de texto (CSV/TXT exportado do relatório
    de indexação do GSC), filtrando pelo domínio do site (www. ignorado).
    Deduplica preservando a ordem.
    """
    host = domain.lower().removeprefix("sc-domain:").removeprefix("www.").rstrip("/")
    seen = set()
    urls = []
    for line in lines:
        for match in _URL_RE.findall(line):
            url_host = urlparse(match).netloc.lower().removeprefix("www.")
            if url_host != host:
                continue
            norm = normalize_for_match(match)
            if norm in seen:
                continue
            seen.add(norm)
            urls.append(match)
    return urls


# ---------------------------------------------------------------------------
# Etapa 2 — parse do CSV revisado pelo analista
# ---------------------------------------------------------------------------

# Colunas do CSV editável ({data}_poda.csv). O analista edita acao_final e
# destino_final (logo após a url, já pré-preenchidas com a sugestão); as
# demais são contexto somente-leitura.
PLAN_CSV_COLUMNS = [
    "url",
    "acao_final",
    "destino_final",
    "origem",
    "impressoes",
    "cliques",
    "posicao",
    "fonte_sugestao",
    "top_queries",
]


def parse_plan_csv(lines) -> dict:
    """
    Lê o CSV do plano (revisado ou não pelo analista) e valida as decisões.

    Parâmetros:
        lines — iterável de linhas de texto (linhas iniciadas em '#' são
                comentário e são ignoradas). O delimitador é detectado pelo
                cabeçalho (';' — padrão atual, amigável ao Excel pt-BR — ou
                ',' — formato antigo), então CSVs antigos seguem compiláveis.

    Regras:
      - acao_final aceita: 410, 404, 301, manter, revisar (vazio = revisar)
      - 301 exige destino_final absoluto (http/https) e diferente da origem
      - "manter" e "revisar" não geram diretiva (revisar fica pendente)
      - aviso destacado se mais de HOMEPAGE_WARN_THRESHOLD redirects apontam
        para a home (padrão de soft-404)

    Retorna:
    {
        "entries":  [{"url", "action" (410|404|301), "target": str|None}],
        "pending":  [url],   # acao_final = revisar/vazio
        "kept":     [url],   # acao_final = manter
        "errors":   [str],   # linhas inválidas (não entram em entries)
        "warnings": [str],
    }
    """
    content = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    delimiter = ","
    if content and content[0].count(";") > content[0].count(","):
        delimiter = ";"
    reader = csv.DictReader(content, delimiter=delimiter)

    entries, pending, kept, errors, warnings = [], [], [], [], []
    homepage_targets = 0

    for i, row in enumerate(reader, start=2):  # 2 = primeira linha de dados
        url = (row.get("url") or "").strip()
        if not url:
            errors.append(f"linha {i}: coluna 'url' vazia — ignorada")
            continue

        action = (row.get("acao_final") or "").strip().lower() or "revisar"
        if action not in _VALID_ACTIONS:
            errors.append(f"linha {i}: acao_final invalida '{action}' ({url}) — ignorada")
            continue

        if action == "revisar":
            pending.append(url)
            continue
        if action == "manter":
            kept.append(url)
            continue

        target = (row.get("destino_final") or "").strip() or None
        if action == "301":
            if not target or not target.lower().startswith(("http://", "https://")):
                errors.append(
                    f"linha {i}: 301 sem destino_final absoluto valido ({url}) — ignorada"
                )
                continue
            if normalize_for_match(target) == normalize_for_match(url):
                errors.append(f"linha {i}: 301 com destino igual a origem ({url}) — ignorada")
                continue
            if _is_homepage(target):
                homepage_targets += 1
        else:
            target = None  # 410/404 não têm destino

        entries.append({"url": url, "action": action, "target": target})

    if homepage_targets > HOMEPAGE_WARN_THRESHOLD:
        warnings.append(
            f"{homepage_targets} redirects 301 apontam para a home — o Google "
            f"costuma tratar redirect em massa para a home como soft-404 "
            f"(nao passa valor). Prefira destinos relevantes ou 410."
        )

    return {
        "entries": entries,
        "pending": pending,
        "kept": kept,
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Etapa 2 — blocos de servidor (Apache / nginx)
# ---------------------------------------------------------------------------


def _ascii_safe(text: str) -> str:
    """Remove acentos/não-ASCII (comentários de arquivos de config)."""
    import unicodedata

    norm = unicodedata.normalize("NFKD", str(text))
    return norm.encode("ascii", "ignore").decode("ascii")


def _wrap_ascii(text: str, width: int) -> list:
    import textwrap

    return textwrap.wrap(_ascii_safe(text), width=width)


def _split_path_query(url: str) -> "tuple[str, str]":
    parsed = urlparse(url)
    return parsed.path or "/", parsed.query


def _block_header(title: str, date: str, extra: str) -> list:
    lines = [
        "# " + "=" * 68,
        f"# {title} - GSC Monitor (Plano de Poda) - {date}",
        "# " + "-" * 68,
    ]
    lines += [f"# {ln}" for ln in _wrap_ascii(_PODA_DISCLAIMER, 66)]
    lines += [f"# {extra}", "# " + "=" * 68, ""]
    return lines


def build_poda_htaccess(entries: list, date: str) -> str:
    """
    Bloco Apache (.htaccess) com as remoções/redirects do plano revisado.

    - Caminho sem query string: RedirectMatch com regex ancorada (^...$) e
      barra final opcional — diferente do Redirect do mod_alias, NÃO faz
      prefix-match (um 410 em /blog não pode derrubar /blog/post-ativo).
    - Caminho com query string: mod_alias não enxerga query; usa-se
      RewriteCond %{QUERY_STRING} + RewriteRule ([G] = 410).
    """
    lines = _block_header(
        "Remocao de paginas antigas (410/404/301)",
        date,
        "Requer mod_alias (e mod_rewrite p/ URLs com query). .htaccess da raiz.",
    )

    rewrite_rules = []
    for e in entries:
        path, query = _split_path_query(e["url"])
        comment = f"# {_ascii_safe(e['url'])}"
        if query:
            # .htaccess (contexto por diretório): pattern sem barra inicial;
            # strip("/") também na direita p/ não gerar "8//?$" em path com
            # barra final — o "/?$" já cobre a barra opcional
            pattern = "^" + re.escape(path.strip("/")) + "/?$"
            cond = f"RewriteCond %{{QUERY_STRING}} ^{re.escape(query)}$"
            if e["action"] == "301":
                # `?` final descarta a query original no destino
                rule = f"RewriteRule {pattern} {e['target']}? [R=301,L]"
            elif e["action"] == "404":
                rule = f"RewriteRule {pattern} - [R=404,L]"
            else:
                rule = f"RewriteRule {pattern} - [G,L]"
            rewrite_rules += [comment, cond, rule, ""]
        else:
            anchored = "^" + re.escape(path.rstrip("/") or "/") + "/?$"
            if e["action"] == "301":
                directive = f"RedirectMatch 301 {anchored} {e['target']}"
            else:
                directive = f"RedirectMatch {e['action']} {anchored}"
            lines += [comment, directive, ""]

    if rewrite_rules:
        lines += ["# --- URLs com query string (mod_rewrite) ---", "RewriteEngine On", ""]
        lines += rewrite_rules

    return "\n".join(lines)


def build_poda_nginx(entries: list, date: str) -> str:
    """
    Bloco nginx (dentro de server {}) com as remoções/redirects do plano.
    `location =` é exact-match por construção; URLs com query usam if ($args).
    """
    lines = _block_header(
        "Remocao de paginas antigas (410/404/301)",
        date,
        "Adicione dentro do bloco server {} do site.",
    )

    for e in entries:
        path, query = _split_path_query(e["url"])
        if e["action"] == "301":
            ret = f"return 301 {e['target']};"
        else:
            ret = f"return {e['action']};"
        lines.append(f"# {_ascii_safe(e['url'])}")
        if query:
            lines.append(f'location = {path} {{ if ($args = "{query}") {{ {ret} }} }}')
        else:
            lines.append(f"location = {path} {{ {ret} }}")
        lines.append("")

    return "\n".join(lines)


def build_poda_redirect(entries: list, date: str) -> str:
    """
    Bloco Apache no estilo clássico do mod_alias `Redirect` (diretiva simples),
    alternativa ao RedirectMatch ancorado de build_poda_htaccess:

        Redirect 301 /caminho-antigo/ https://site.com/caminho-novo/
        Redirect 410 /caminho-removido/

    Formato pedido por quem prefere a diretiva direta (e que vários painéis de
    hospedagem, ex. cPanel, geram). Preserva o caminho original (inclusive a
    barra final), como o `Redirect` espera.

    ATENÇÃO: `Redirect` faz PREFIX-MATCH — `Redirect 410 /blog` também derruba
    /blog/post-ativo. Por isso o build_poda_htaccess (RedirectMatch ancorado)
    continua sendo o padrão seguro; este arquivo é uma alternativa para quem
    entende o trade-off.

    URLs com query string não são representáveis por `Redirect` (mod_alias
    ignora a query) — ficam listadas como comentário, apontando para o arquivo
    Apache com RewriteRule, que as trata corretamente.
    """
    lines = _block_header(
        "Remocao de paginas antigas (estilo Redirect do mod_alias)",
        date,
        "Requer mod_alias. ATENCAO: Redirect faz prefix-match (pega subpaths).",
    )

    skipped = []
    for e in entries:
        path, query = _split_path_query(e["url"])
        if query:
            skipped.append(e["url"])
            continue
        lines.append(f"# {_ascii_safe(e['url'])}")
        if e["action"] == "301":
            lines.append(f"Redirect 301 {path} {e['target']}")
        else:
            lines.append(f"Redirect {e['action']} {path}")
        lines.append("")

    if skipped:
        lines.append("# --- URLs com query string nao cabem no Redirect simples ---")
        lines.append("# (use o *_poda_apache.txt, que as trata com RewriteRule):")
        lines += [f"#   {_ascii_safe(u)}" for u in skipped]
        lines.append("")

    return "\n".join(lines)


def _php_str(value: str) -> str:
    """String PHP single-quoted (escapa \\ e ')."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def build_poda_php(entries: list, date: str, filename: str = "poda.php") -> str:
    """
    Versão PHP do plano compilado — para hospedagens onde não dá para editar
    .htaccess/nginx (Plesk, shared hosting) ou onde o CMS sobrescreve o
    .htaccess. Um único arquivo: copie para a raiz do site e faça
    `require` no topo do index.php (em WordPress, prefira o início do
    wp-config.php — o index.php é sobrescrito em updates do core).

    Mesma semântica dos blocos de servidor: caminho exato (barra final
    tolerada), regra com query string exige query exata, regra sem query
    casa qualquer query. Compatível com PHP 5.4+ (http_response_code).
    """
    lines = [
        "<?php",
        "// " + "=" * 68,
        f"// Remocao de paginas antigas (410/404/301) - GSC Monitor (Plano de Poda) - {date}",
        "// " + "-" * 68,
    ]
    lines += [f"// {ln}" for ln in _wrap_ascii(_PODA_DISCLAIMER, 66)]
    lines += [
        "//",
        "// COMO USAR: copie este arquivo para a raiz do site e adicione",
        f"//     require __DIR__ . '/{filename}';",
        "// no TOPO do index.php, antes do CMS carregar.",
        "// WordPress: prefira o inicio do wp-config.php - o index.php e",
        "// sobrescrito em updates do core.",
        "// Requer PHP 5.4+ (http_response_code).",
        "// " + "=" * 68,
        "",
        "function gsc_monitor_poda()",
        "{",
        "    // caminho (sem barra final) => regras: array(query|null, status, destino|null)",
        "    $rules = array(",
    ]

    # Agrupa por caminho normalizado: o mesmo path pode ter regra com query
    # (ex: /oculos?slug=...) e sem query — as com query são testadas primeiro.
    grouped: dict = {}
    order: list = []
    for e in entries:
        path, query = _split_path_query(e["url"])
        path = unquote(path)
        if path != "/":
            path = path.rstrip("/")
        if path not in grouped:
            grouped[path] = []
            order.append(path)
        grouped[path].append((query or None, int(e["action"]), e.get("target"), e["url"]))

    for path in order:
        rules = sorted(grouped[path], key=lambda r: r[0] is None)  # query exata primeiro
        lines.append(f"        {_php_str(path)} => array(")
        for query, status, target, url in rules:
            lines.append(f"            // {_ascii_safe(url)}")
            q = _php_str(query) if query is not None else "null"
            t = _php_str(target) if target else "null"
            lines.append(f"            array({q}, {status}, {t}),")
        lines.append("        ),")

    lines += [
        "    );",
        "",
        "    $uri = isset($_SERVER['REQUEST_URI']) ? $_SERVER['REQUEST_URI'] : '/';",
        "    $parts = explode('?', $uri, 2);",
        "    $path = rawurldecode($parts[0]);",
        "    $query = isset($parts[1]) ? $parts[1] : '';",
        "    if ($path !== '/') {",
        "        $path = rtrim($path, '/');",
        "    }",
        "",
        "    if (!isset($rules[$path])) {",
        "        return;",
        "    }",
        "",
        "    foreach ($rules[$path] as $rule) {",
        "        if ($rule[0] !== null && $rule[0] !== $query) {",
        "            continue; // regra exige query exata e nao casou",
        "        }",
        "        if ($rule[1] === 301 && $rule[2] !== null) {",
        "            header('Location: ' . $rule[2], true, 301);",
        "        } else {",
        "            http_response_code($rule[1]);",
        "            header('Content-Type: text/plain; charset=utf-8');",
        "            echo $rule[1] === 404 ? '404 Not Found' : '410 Gone';",
        "        }",
        "        exit;",
        "    }",
        "}",
        "",
        "gsc_monitor_poda();",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Saída de terminal (ASCII-safe, padrão dos print_* do projeto)
# ---------------------------------------------------------------------------


def print_pruning_plan(plan: dict, max_display: int = 10) -> None:
    """Resumo do Plano de Poda no terminal."""
    total = plan.get("total", 0)
    if total == 0:
        print("\n[poda] Nenhuma URL fora do sitemap com dados no GSC — nada a podar.")
        return

    print("\n" + "-" * 70)
    print(
        f"  Plano de Poda (SUGESTAO) — {total} URL(s) antigas: "
        f"{plan['total_review']} para revisar (trafego), {plan['total_410']} sem trafego (410)"
    )
    n_export = sum(1 for e in plan["entries"] if e.get("origem") == "export-gsc")
    if n_export:
        print(f"  Origem: {total - n_export} via busca (GSC) + {n_export} via export importado")
    print("-" * 70)
    print("  ATENCAO: sugestao automatica — o analista decide a acao final no CSV.")

    review = [e for e in plan["entries"] if e["action"] == "revisar"]
    for e in review[:max_display]:
        print(f"\n  Revisar: {e['url']}")
        print(f"    {e['impressions']} impressoes / {e['clicks']} cliques no periodo")
        if e["top_queries"]:
            print(f"    queries: {', '.join(e['top_queries'])}")
        if e["suggested_target"]:
            print(f"    destino sugerido ({e['target_source']}): {e['suggested_target']}")

    rest = len(review) - max_display
    if rest > 0:
        print(f"\n  ... +{rest} URLs com trafego (veja o CSV)")
    print("-" * 70 + "\n")


def print_compile_result(parsed: dict) -> None:
    """Resumo da compilação do CSV revisado no terminal."""
    n = len(parsed["entries"])
    print(f"\n[poda] {n} diretiva(s) compiladas no bloco de servidor.")
    if parsed["kept"]:
        print(f"[poda] {len(parsed['kept'])} URL(s) marcadas 'manter' — fora do bloco.")
    if parsed["pending"]:
        print(
            f"[poda] {len(parsed['pending'])} URL(s) ainda 'revisar' — pendentes de "
            f"decisao do analista (fora do bloco)."
        )
    for w in parsed["warnings"]:
        print(f"[poda] AVISO: {w}")
    for err in parsed["errors"]:
        print(f"[poda] ERRO: {err}")
