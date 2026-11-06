"""
saidas.py — gravação dos arquivos do dossiê (CSV/JSON), num formato só.

CSV em UTF-8 com BOM e vírgula: abre certo no Excel pt-BR e é lido sem
surpresa por SQL/pandas na sessão de análise. Listas viram texto separado por
" | " — o CSV é o resumo; o dado completo fica no .jsonl.
"""

import csv
import json
import os
import re
from collections import Counter

from core.urls import canonical_path


def escrever_csv(caminho: str, linhas: list, colunas: list) -> None:
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=colunas, extrasaction="ignore")
        w.writeheader()
        for linha in linhas:
            w.writerow({c: _celula(linha.get(c)) for c in colunas})


def _celula(valor):
    if isinstance(valor, (list, tuple)):
        return " | ".join(_celula(v) for v in valor)
    if isinstance(valor, bool):
        return "1" if valor else "0"
    return "" if valor is None else valor


def escrever_json(caminho: str, dado) -> None:
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(dado, fh, ensure_ascii=False, indent=2)


def ler_json(caminho: str, padrao=None):
    if not os.path.exists(caminho):
        return padrao
    with open(caminho, encoding="utf-8") as fh:
        return json.load(fh)


def ler_jsonl(caminho: str) -> list:
    if not os.path.exists(caminho):
        return []
    saida = []
    with open(caminho, encoding="utf-8") as fh:
        for linha in fh:
            try:
                saida.append(json.loads(linha))
            except ValueError:
                continue
    return saida


# ---------------------------------------------------------------------------
# Crawl: resumo plano + arestas de link interno
# ---------------------------------------------------------------------------

COLUNAS_RESUMO = [
    "url",
    "origem",
    "grupo",
    "lastmod",
    "acervo_impressoes",
    "acervo_cliques",
    "acervo_primeiro",
    "acervo_ultimo",
    "status_inicial",
    "n_redirects",
    "url_final",
    "status_final",
    "erro",
    "x_robots_tag",
    "robots_meta",
    "canonical",
    "canonical_e_outra",
    "titulo",
    "titulo_chars",
    "descricao",
    "h1",
    "n_h1",
    "lang",
    "n_palavras",
    "n_links_internos",
    "n_links_externos",
    "n_links_nofollow",
    "n_inlinks",
    "schema_tipos",
    "hreflang",
    "arquivo_html",
    "tempo_ms",
]


def chave(url: str) -> str:
    """Chave de cruzamento de links: caminho canônico, sem host/query/barra final."""
    return canonical_path(url or "")


def resumo_crawl(registros: list, *, regras_taxonomia=None) -> "tuple[list, list]":
    """(linhas_do_resumo, arestas). `n_inlinks` = páginas fotografadas distintas
    que linkam para a URL (pela chave de caminho). É contagem, não juízo."""
    from core.dossie.ficha import grupo_de

    arestas, entrada = [], Counter()
    for r in registros:
        origem = chave(r.get("url_final") or r["url"])
        destinos = {chave(d) for d in r.get("links_internos") or []} - {origem}
        for d in sorted(destinos):
            arestas.append({"origem": r["url"], "destino_caminho": d})
            entrada[d] += 1

    linhas = []
    for r in registros:
        linha = dict(r)
        linha["grupo"] = grupo_de(chave(r["url"]), regras_taxonomia or [])
        linha["n_h1"] = len(r.get("h1") or [])
        linha["n_inlinks"] = entrada.get(chave(r["url"]), 0)
        can = r.get("canonical")
        if can:
            linha["canonical_e_outra"] = _sem_frag(can) != _sem_frag(r.get("url_final") or r["url"])
        linha["hreflang"] = [f"{a}={b}" for a, b in r.get("hreflang") or []]
        linhas.append(linha)
    return linhas, arestas


def _sem_frag(url: str) -> str:
    return re.sub(r"#.*$", "", url or "")


def contagem_status(registros: list) -> dict:
    """Distribuição do status FINAL por classe, mais redirects e erros."""
    c = Counter()
    for r in registros:
        st = r.get("status_final")
        c["erro" if st is None else f"{str(st)[0]}xx"] += 1
        if (r.get("n_redirects") or 0) > 0:
            c["com_redirect"] += 1
        sinais = " ".join(filter(None, [r.get("robots_meta"), r.get("x_robots_tag")])).lower()
        if "noindex" in sinais:
            c["noindex"] += 1
        can = r.get("canonical")
        if can and _sem_frag(can) != _sem_frag(r.get("url_final") or r["url"]):
            c["canonical_para_outra"] += 1
    return dict(c)
