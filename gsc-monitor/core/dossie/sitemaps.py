"""
sitemaps.py — parse de sitemap.xml / sitemapindex COM lastmod (lógica pura).

`core/sitemap.py` já busca o sitemap para o posicionamento, mas descarta o
`lastmod` — e para o dossiê ele importa: é a data que o site DECLARA para cada
página, e a análise compara com a data em que a página apareceu no GSC.
"""

import xml.etree.ElementTree as ET


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse(conteudo: "str | bytes") -> dict:
    """{'tipo': 'urlset'|'sitemapindex'|'invalido', 'entradas': [{'loc','lastmod'}]}."""
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError:
        return {"tipo": "invalido", "entradas": []}
    tipo = _local(raiz.tag)
    filho = "sitemap" if tipo == "sitemapindex" else "url"
    entradas = []
    for el in raiz:
        if _local(el.tag) != filho:
            continue
        item = {"loc": None, "lastmod": None}
        for campo in el:
            nome = _local(campo.tag)
            if nome in item and campo.text:
                item[nome] = campo.text.strip()
        if item["loc"]:
            entradas.append(item)
    if tipo not in ("urlset", "sitemapindex"):
        tipo = "invalido"
    return {"tipo": tipo, "entradas": entradas}


def sitemaps_do_robots(texto_robots: str) -> list:
    """Diretivas `Sitemap:` do robots.txt, na ordem em que aparecem."""
    saida = []
    for linha in (texto_robots or "").splitlines():
        if linha.strip().lower().startswith("sitemap:"):
            url = linha.split(":", 1)[1].strip()
            if url and url not in saida:
                saida.append(url)
    return saida
