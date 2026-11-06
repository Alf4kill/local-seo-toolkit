"""
alvos.py — a lista de URLs que o crawl do dossiê vai fotografar.

União de duas fontes, com a origem anotada em cada URL:
  - o SITEMAP de hoje (o que o site diz que existe);
  - o ACERVO (o que o Google já mostrou na busca nos ~16 meses).

A diferença entre as duas é o ponto: URL que só o acervo conhece pode estar
redirecionada, em 404, ou viva e fora do sitemap; variante com maiúscula ou barra
final que o Google indexou precisa ser fotografada como está. Por isso a forma
EXATA da URL é preservada — só o fragmento (#...) é retirado.

Arquivos de imagem e outros binários ficam de fora (não são página); a contagem
do que ficou de fora vai para o LEIA.md.
"""

import os
import sqlite3
from urllib.parse import urlsplit, urlunsplit

EXTENSOES_NAO_PAGINA = (
    ".webp",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".avif",
    ".ico",
    ".bmp",
    ".pdf",
    ".mp4",
    ".webm",
    ".mp3",
    ".zip",
    ".css",
    ".js",
    ".xml",
    ".txt",
    ".json",
)


def sem_fragmento(url: str) -> str:
    partes = urlsplit(url.strip())
    return urlunsplit((partes.scheme, partes.netloc, partes.path, partes.query, ""))


def e_pagina(url: str) -> bool:
    caminho = urlsplit(url).path.lower()
    return not caminho.endswith(EXTENSOES_NAO_PAGINA)


def urls_do_acervo(caminho_db: str, tipo: str = "web") -> list:
    """[{url, impressoes, cliques, primeiro, ultimo}] de `fato_pagina`, só leitura.

    Abre o banco em modo read-only: o dossiê nunca escreve no acervo.
    """
    if not caminho_db or not os.path.exists(caminho_db):
        return []
    uri = "file:" + os.path.abspath(caminho_db).replace("\\", "/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        linhas = con.execute(
            """SELECT d.url, SUM(f.impressions), SUM(f.clicks), MIN(f.data), MAX(f.data)
               FROM fato_pagina f JOIN dim_pagina d ON d.id = f.pagina_id
               WHERE f.tipo = ?
               GROUP BY d.url""",
            (tipo,),
        ).fetchall()
    finally:
        con.close()
    return [
        {"url": u, "impressoes": i or 0, "cliques": c or 0, "primeiro": p, "ultimo": ul}
        for u, i, c, p, ul in linhas
    ]


def montar(entradas_sitemap: list, urls_acervo: list, *, max_urls: int) -> dict:
    """Une as duas fontes. Devolve {'alvos': [...], 'fora': {...contagens}}.

    Ordem: primeiro o sitemap (na ordem dele), depois as URLs só do acervo por
    impressões decrescentes — se `max_urls` cortar, corta a cauda de menor volume.
    """
    alvos, indice = [], {}
    fora = {"nao_pagina": 0, "fragmento_fundido": 0, "cortadas_pelo_maximo": 0}

    for e in entradas_sitemap:
        url = sem_fragmento(e["loc"])
        if not e_pagina(url):
            fora["nao_pagina"] += 1
            continue
        if url in indice:
            continue
        item = {
            "url": url,
            "origem": "sitemap",
            "lastmod": e.get("lastmod"),
            "acervo_impressoes": None,
            "acervo_cliques": None,
            "acervo_primeiro": None,
            "acervo_ultimo": None,
        }
        indice[url] = item
        alvos.append(item)

    agregadas = {}
    for linha in urls_acervo:
        url = sem_fragmento(linha["url"])
        if not e_pagina(url):
            fora["nao_pagina"] += 1
            continue
        if url != linha["url"]:
            fora["fragmento_fundido"] += 1
        acc = agregadas.setdefault(
            url, {"impressoes": 0, "cliques": 0, "primeiro": None, "ultimo": None}
        )
        acc["impressoes"] += linha["impressoes"]
        acc["cliques"] += linha["cliques"]
        for campo, escolha in (("primeiro", min), ("ultimo", max)):
            if linha[campo]:
                acc[campo] = (
                    linha[campo] if acc[campo] is None else escolha(acc[campo], linha[campo])
                )

    so_acervo = []
    for url, acc in agregadas.items():
        if url in indice:
            item = indice[url]
            item["origem"] = "ambos"
        else:
            item = {"url": url, "origem": "acervo", "lastmod": None}
            so_acervo.append(item)
        item["acervo_impressoes"] = acc["impressoes"]
        item["acervo_cliques"] = acc["cliques"]
        item["acervo_primeiro"] = acc["primeiro"]
        item["acervo_ultimo"] = acc["ultimo"]

    so_acervo.sort(key=lambda i: (-(i["acervo_impressoes"] or 0), i["url"]))
    alvos.extend(so_acervo)

    if max_urls and len(alvos) > max_urls:
        fora["cortadas_pelo_maximo"] = len(alvos) - max_urls
        alvos = alvos[:max_urls]
    return {"alvos": alvos, "fora": fora}
