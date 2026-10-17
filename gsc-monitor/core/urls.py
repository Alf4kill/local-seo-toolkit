"""
urls.py — Helpers de URL/domínio compartilhados (lógica pura, sem rede/IO).

Centraliza a normalização de domínio e a montagem do siteUrl no formato exigido
pela Search Console API. Antes ambos estavam copiados (idênticos) em posicao.py,
main.py, gui/runner.py, fetchers/position_fetcher.py e fetchers/inspector.py —
uma cópia única evita que as formas divirjam, o que quebraria a chave de cache
(que depende de normalize_domain produzir a MESMA string para o mesmo site).

Também centraliza a extração de CAMINHO de uma URL. Existem três variantes
porque os usos são de fato diferentes — e é justamente por isso que elas moram
aqui juntas, onde a diferença fica explícita, em vez de espalhadas como cópias
quase iguais em cada módulo:

    url_path            — caminho só, preservando a barra final
    url_path_with_query — caminho + query (redirects: a query importa)
    canonical_path      — a CHAVE DE CRUZAMENTO: sem query/fragmento, barra
                          inicial garantida, barra final removida

`canonical_path` é a que o cruzamento sitemap × access log × GSC usa. Esse
cruzamento só funciona se as três fontes produzirem a MESMA chave para a mesma
página, então ela precisa ter uma implementação única — pelo mesmo motivo que
normalize_domain tem.
"""

from urllib.parse import urlparse, urlsplit


def normalize_domain(site: str) -> str:
    """Extrai o domínio limpo (sem esquema, prefixo sc-domain: ou barra final).

    Usado para nomes de arquivo/pasta e como chave de cache — por isso
    'https://exemplo.com/' e 'sc-domain:exemplo.com' precisam normalizar para a
    MESMA string.
    """
    if site.startswith("sc-domain:"):
        return site[len("sc-domain:") :]
    return site.removeprefix("https://").removeprefix("http://").rstrip("/")


def build_site_url(domain: str) -> str:
    """Monta o siteUrl no formato exigido pela GSC API (propriedade URL Prefix).

    O GSC exige o valor exatamente como cadastrado (protocolo + barra final);
    domínios sc-domain: já estão no formato correto e passam intactos.
    """
    if domain.startswith("sc-domain:"):
        return domain
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain.rstrip("/") + "/"
    return f"https://{domain.rstrip('/')}/"


# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------


def url_path(url: str) -> str:
    """Caminho (sem query) de uma URL absoluta. '/' se vazio.

    PRESERVA a barra final: '/a/' e '/a' são caminhos distintos aqui. Usado pela
    poda, onde a forma exata importa (o destino do redirect tem de bater com a
    URL do sitemap). Para cruzar fontes diferentes use `canonical_path`.
    """
    return urlparse(url).path or "/"


def url_path_with_query(url: str) -> str:
    """Caminho + query de uma URL absoluta. '/' se vazio.

    A query entra porque esta variante alimenta a geração de redirects, onde
    '/p?id=1' e '/p?id=2' são alvos diferentes.
    """
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    return path


def canonical_path(path_or_url: str) -> str:
    """Chave canônica de cruzamento entre sitemap, access log e GSC.

    Remove query e fragmento, garante a barra inicial e tira a barra final
    redundante (exceto na raiz). Aceita tanto um caminho cru vindo do log quanto
    uma URL absoluta.

    É a única forma de '/a/', '/a?x=1' e 'https://ex.com/a' virarem a mesma
    chave — e sem isso o cruzamento das três fontes compara maçã com laranja.
    """
    if "//" in path_or_url and ":" in path_or_url.split("//", 1)[0]:
        path_or_url = urlsplit(path_or_url).path
    path = path_or_url.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return path
