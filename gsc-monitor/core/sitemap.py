"""
sitemap.py — Fetch e parse do sitemap.xml do domínio informado.
Suporta sitemapindex (sitemaps aninhados) e fallback via robots.txt.
"""

import xml.etree.ElementTree as ET
import requests

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
TIMEOUT = 15  # segundos


def _get(url: str) -> requests.Response | None:
    """Faz GET na URL e retorna a Response, ou None em caso de falha."""
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp
    except requests.RequestException:
        return None


def _parse_sitemap(content: str) -> list[str]:
    """
    Recebe o conteúdo XML de um sitemap e retorna lista de URLs de páginas.
    Se for um sitemapindex, retorna lista de URLs de sub-sitemaps.
    Retorna (urls_de_pagina, urls_de_sitemap).
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return [], []

    tag = root.tag.lower()

    if "sitemapindex" in tag:
        sitemap_urls = [
            loc.text.strip()
            for loc in root.findall(f".//{{{SITEMAP_NS}}}loc")
            if loc.text
        ]
        return [], sitemap_urls

    page_urls = [
        loc.text.strip()
        for loc in root.findall(f".//{{{SITEMAP_NS}}}loc")
        if loc.text
    ]
    return page_urls, []


def _sitemap_from_robots(domain: str) -> str | None:
    """Lê robots.txt e extrai a primeira diretiva Sitemap: encontrada."""
    for scheme in ("https", "http"):
        resp = _get(f"{scheme}://{domain}/robots.txt")
        if resp is None:
            continue
        for line in resp.text.splitlines():
            if line.lower().startswith("sitemap:"):
                url = line.split(":", 1)[1].strip()
                return url
    return None


def fetch_urls(domain: str) -> list[str]:
    """
    Ponto de entrada: recebe o domínio (ex: 'exemplo.com.br') e retorna
    a lista completa de URLs de páginas encontradas nos sitemaps.
    """
    candidates = [
        f"https://{domain}/sitemap.xml",
        f"https://{domain}/sitemap_index.xml",
        f"http://{domain}/sitemap.xml",
        f"http://{domain}/sitemap_index.xml",
    ]

    root_sitemap_url = None
    root_content = None

    for url in candidates:
        resp = _get(url)
        if resp is not None:
            root_sitemap_url = url
            root_content = resp.text
            break

    if root_content is None:
        # Última tentativa: robots.txt
        robots_sitemap = _sitemap_from_robots(domain)
        if robots_sitemap:
            resp = _get(robots_sitemap)
            if resp:
                root_sitemap_url = robots_sitemap
                root_content = resp.text

    if root_content is None:
        raise RuntimeError(
            f"Nenhum sitemap encontrado para '{domain}'.\n"
            "Verifique se o domínio está correto e se o sitemap é público."
        )

    print(f"[sitemap] Sitemap raiz: {root_sitemap_url}")

    page_urls, sub_sitemap_urls = _parse_sitemap(root_content)

    # Resolve sitemaps aninhados (até 1 nível de profundidade)
    for sub_url in sub_sitemap_urls:
        print(f"[sitemap] Sub-sitemap: {sub_url}")
        resp = _get(sub_url)
        if resp is None:
            print(f"[sitemap] AVISO — não foi possível obter: {sub_url}")
            continue
        urls, _ = _parse_sitemap(resp.text)
        page_urls.extend(urls)

    # Remove duplicatas mantendo ordem
    seen = set()
    unique_urls = []
    for url in page_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    print(f"[sitemap] Total de URLs únicas encontradas: {len(unique_urls)}")
    return unique_urls
