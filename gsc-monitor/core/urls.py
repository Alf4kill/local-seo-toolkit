"""
urls.py — Helpers de URL/domínio compartilhados (lógica pura, sem rede/IO).

Centraliza a normalização de domínio e a montagem do siteUrl no formato exigido
pela Search Console API. Antes ambos estavam copiados (idênticos) em posicao.py,
main.py, gui/runner.py, fetchers/position_fetcher.py e fetchers/inspector.py —
uma cópia única evita que as formas divirjam, o que quebraria a chave de cache
(que depende de normalize_domain produzir a MESMA string para o mesmo site).
"""


def normalize_domain(site: str) -> str:
    """Extrai o domínio limpo (sem esquema, prefixo sc-domain: ou barra final).

    Usado para nomes de arquivo/pasta e como chave de cache — por isso
    'https://exemplo.com/' e 'sc-domain:exemplo.com' precisam normalizar para a
    MESMA string.
    """
    if site.startswith("sc-domain:"):
        return site[len("sc-domain:"):]
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
