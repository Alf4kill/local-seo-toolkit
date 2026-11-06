"""
site_crawler.py — a FOTO do site ao vivo para o dossiê (P8). Sem cota de API.

Para cada URL alvo (sitemap ∪ acervo, ver core/dossie/alvos.py) registra o que um
robô vê HOJE: a cadeia de redirect passo a passo, o status final, os cabeçalhos
que importam para indexação e, se for HTML, os sinais extraídos por
core/dossie/html.py. O HTML vai compactado para o dossiê, para a análise de
conteúdo rodar depois sem baixar de novo.

É uma foto do PRESENTE. A queda que a análise investiga aconteceu meses antes;
o que esta foto mostra é o estado de hoje, e o LEIA.md diz isso.

Educado por padrão: uma requisição por vez, pausa entre elas, User-Agent
identificado. Retoma: rodar de novo no mesmo dia pula as URLs já fotografadas.
"""

import gzip
import hashlib
import json
import os
import time
from urllib.parse import urljoin

import requests
from core.dossie import html as html_extrator
from core.dossie import sitemaps as sm

USER_AGENT = "gsc-monitor-dossie/1.0 (coleta local para analise de SEO)"
STATUS_REDIRECT = (301, 302, 303, 307, 308)
CABECALHOS = ("content-type", "x-robots-tag", "last-modified", "cache-control", "content-length")


def nova_sessao() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    s.headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    return s


def obter(sessao, url: str, *, timeout: float = 20, max_redirects: int = 10) -> dict:
    """GET seguindo redirects À MÃO, para registrar cada salto."""
    cadeia, atual, resp = [], url, None
    t0 = time.monotonic()
    for _ in range(max_redirects + 1):
        try:
            resp = sessao.get(atual, allow_redirects=False, timeout=timeout)
        except requests.RequestException as exc:
            return {
                "cadeia": cadeia,
                "url_final": atual,
                "status_final": None,
                "erro": f"{type(exc).__name__}: {str(exc)[:200]}",
                "resp": None,
                "tempo_ms": int((time.monotonic() - t0) * 1000),
            }
        cadeia.append({"url": atual, "status": resp.status_code})
        destino = resp.headers.get("Location")
        if resp.status_code in STATUS_REDIRECT and destino:
            proximo = urljoin(atual, destino)
            if any(passo["url"] == proximo for passo in cadeia):
                cadeia.append({"url": proximo, "status": None})
                return {
                    "cadeia": cadeia,
                    "url_final": proximo,
                    "status_final": None,
                    "erro": "loop de redirect",
                    "resp": None,
                    "tempo_ms": int((time.monotonic() - t0) * 1000),
                }
            atual = proximo
            continue
        break
    else:
        return {
            "cadeia": cadeia,
            "url_final": atual,
            "status_final": None,
            "erro": f"mais de {max_redirects} redirects",
            "resp": None,
            "tempo_ms": int((time.monotonic() - t0) * 1000),
        }
    return {
        "cadeia": cadeia,
        "url_final": atual,
        "status_final": resp.status_code,
        "erro": None,
        "resp": resp,
        "tempo_ms": int((time.monotonic() - t0) * 1000),
    }


def nome_html(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".html.gz"


def fotografar(sessao, alvo: dict, *, host: str, pasta_html: str, timeout: float = 20) -> dict:
    """Um registro do crawl.jsonl para uma URL alvo."""
    r = obter(sessao, alvo["url"], timeout=timeout)
    resp = r.pop("resp")
    registro = dict(alvo)
    registro.update(
        {
            "status_inicial": r["cadeia"][0]["status"] if r["cadeia"] else None,
            "n_redirects": max(len(r["cadeia"]) - 1, 0),
            "cadeia": r["cadeia"],
            "url_final": r["url_final"],
            "status_final": r["status_final"],
            "erro": r["erro"],
            "tempo_ms": r["tempo_ms"],
        }
    )
    if resp is None:
        return registro
    cab = {k: resp.headers.get(k) for k in CABECALHOS if resp.headers.get(k)}
    registro["cabecalhos"] = cab
    registro["x_robots_tag"] = cab.get("x-robots-tag")
    registro["bytes"] = len(resp.content or b"")
    tipo = (cab.get("content-type") or "").lower()
    if resp.status_code == 200 and "html" in tipo:
        texto = resp.text
        registro.update(html_extrator.extrair(texto, r["url_final"], host))
        arquivo = nome_html(alvo["url"])
        os.makedirs(pasta_html, exist_ok=True)
        with gzip.open(os.path.join(pasta_html, arquivo), "wt", encoding="utf-8") as fh:
            fh.write(texto)
        registro["arquivo_html"] = "html/" + arquivo
    return registro


def baixar_texto(sessao, url: str, *, timeout: float = 20) -> "tuple[int | None, str | None]":
    try:
        resp = sessao.get(url, timeout=timeout)
    except requests.RequestException:
        return None, None
    return resp.status_code, resp.text if resp.status_code == 200 else None


def coletar_sitemaps(
    sessao,
    dominio: str,
    robots_txt: "str | None",
    pasta: str,
    *,
    pausa: float = 0.5,
    max_arquivos: int = 200,
) -> dict:
    """Busca robots -> sitemaps (recursivo em sitemapindex) e salva cada XML cru.

    Devolve {'arquivos': [{url, status, tipo, n_entradas, salvo_em}], 'entradas': [...]}
    """
    fila = sm.sitemaps_do_robots(robots_txt or "") or [
        f"https://{dominio}/sitemap.xml",
        f"https://{dominio}/sitemap_index.xml",
    ]
    vistos, arquivos, entradas = set(), [], []
    os.makedirs(pasta, exist_ok=True)
    while fila and len(vistos) < max_arquivos:
        url = fila.pop(0)
        if url in vistos:
            continue
        vistos.add(url)
        status, texto = baixar_texto(sessao, url)
        info = {"url": url, "status": status, "tipo": None, "n_entradas": 0, "salvo_em": None}
        if texto:
            nome = f"{len(arquivos) + 1:03d}_" + (url.rstrip("/").rsplit("/", 1)[-1] or "sitemap")
            nome = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in nome)[:120]
            with open(os.path.join(pasta, nome), "w", encoding="utf-8") as fh:
                fh.write(texto)
            info["salvo_em"] = "sitemaps/" + nome
            lido = sm.parse(texto)
            info["tipo"], info["n_entradas"] = lido["tipo"], len(lido["entradas"])
            if lido["tipo"] == "sitemapindex":
                fila.extend(e["loc"] for e in lido["entradas"])
            elif lido["tipo"] == "urlset":
                for e in lido["entradas"]:
                    entradas.append(dict(e, sitemap=url))
        arquivos.append(info)
        time.sleep(pausa)
    return {"arquivos": arquivos, "entradas": entradas}


def ja_fotografadas(caminho_jsonl: str) -> set:
    feitas = set()
    if os.path.exists(caminho_jsonl):
        with open(caminho_jsonl, encoding="utf-8") as fh:
            for linha in fh:
                try:
                    feitas.add(json.loads(linha)["url"])
                except (ValueError, KeyError):
                    continue
    return feitas


def rodar(
    sessao,
    alvos: list,
    *,
    host: str,
    pasta_dia: str,
    pausa: float,
    tempo_max: "float | None" = None,
    timeout: float = 20,
    progresso=print,
) -> dict:
    """Fotografa os alvos que faltam, anexando ao crawl.jsonl. Retomável."""
    caminho = os.path.join(pasta_dia, "crawl.jsonl")
    feitas = ja_fotografadas(caminho)
    pendentes = [a for a in alvos if a["url"] not in feitas]
    t0, feitas_agora = time.monotonic(), 0
    with open(caminho, "a", encoding="utf-8") as fh:
        for i, alvo in enumerate(pendentes, start=1):
            if tempo_max and time.monotonic() - t0 > tempo_max:
                break
            reg = fotografar(
                sessao, alvo, host=host, pasta_html=os.path.join(pasta_dia, "html"), timeout=timeout
            )
            fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
            fh.flush()
            feitas_agora += 1
            if i % 25 == 0 or i == len(pendentes):
                progresso(f"[site] {len(feitas) + i}/{len(alvos)} URLs fotografadas")
            time.sleep(pausa)
    total = len(feitas) + feitas_agora
    return {
        "total_alvos": len(alvos),
        "fotografadas": total,
        "nesta_rodada": feitas_agora,
        "completo": total >= len(alvos),
    }
