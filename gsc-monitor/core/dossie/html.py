"""
html.py — sinais de UMA página HTML, extraídos com a stdlib (sem bs4).

Extrai o que o Google lê e o que a análise cruza com o GSC: title, description,
meta robots, canonical, hreflang, H1, idioma, contagem de palavras visíveis,
links (internos/externos/nofollow) e os tipos de schema. Não julga nada: um
title de 120 caracteres sai com 120 caracteres, sem rótulo de "longo demais".

Função pública: `extrair(html, url_base, host)`.
"""

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

# Conteúdo que não é texto visível.
_INVISIVEIS = {"script", "style", "noscript", "template", "svg", "head"}
_ESQUEMAS_IGNORADOS = ("mailto:", "tel:", "javascript:", "data:", "whatsapp:", "sms:")
_PALAVRA = re.compile(r"\w+", re.UNICODE)


def _host_nu(host: str) -> str:
    host = (host or "").lower().split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def _sem_fragmento(url: str) -> str:
    partes = urlsplit(url)
    return urlunsplit((partes.scheme, partes.netloc, partes.path or "/", partes.query, ""))


class _Extrator(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titulo = None
        self._no_titulo = False
        self._buf_titulo = []
        self.metas = {}
        self.canonicals = []
        self.hreflang = []
        self.h1 = []
        self._h1_prof = 0
        self._buf_h1 = []
        self.lang = None
        self.links = []  # (href, rel)
        self.itemtypes = []
        self._invisivel = 0
        self._no_ld = False
        self._buf_ld = []
        self.blocos_ld = []
        self._texto = []

    def handle_starttag(self, tag, attrs):
        a = {(k or "").lower(): (v or "") for k, v in attrs}
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"].strip()
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            self._no_ld = True
            self._buf_ld = []
        if tag in _INVISIVEIS:
            self._invisivel += 1
        if tag == "title" and self.titulo is None:
            self._no_titulo = True
            self._buf_titulo = []
        elif tag == "meta":
            nome = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if nome and nome not in self.metas:
                self.metas[nome] = a.get("content", "").strip()
        elif tag == "link":
            rels = a.get("rel", "").lower().split()
            if "canonical" in rels and a.get("href"):
                self.canonicals.append(a["href"].strip())
            if "alternate" in rels and a.get("hreflang"):
                self.hreflang.append((a["hreflang"].strip(), a.get("href", "").strip()))
        elif tag == "h1":
            self._h1_prof += 1
            if self._h1_prof == 1:
                self._buf_h1 = []
        elif tag == "a" and a.get("href"):
            self.links.append((a["href"].strip(), a.get("rel", "").lower()))
        if a.get("itemtype"):
            self.itemtypes.extend(a["itemtype"].split())

    def handle_endtag(self, tag):
        if tag == "script" and self._no_ld:
            self._no_ld = False
            self.blocos_ld.append("".join(self._buf_ld))
        if tag in _INVISIVEIS and self._invisivel:
            self._invisivel -= 1
        if tag == "title" and self._no_titulo:
            self._no_titulo = False
            self.titulo = " ".join("".join(self._buf_titulo).split())
        elif tag == "h1" and self._h1_prof:
            self._h1_prof -= 1
            if self._h1_prof == 0:
                self.h1.append(" ".join("".join(self._buf_h1).split()))

    def handle_data(self, data):
        if self._no_ld:
            self._buf_ld.append(data)
        if self._no_titulo:
            self._buf_titulo.append(data)
        if self._h1_prof:
            self._buf_h1.append(data)
        if not self._invisivel:
            self._texto.append(data)


def _tipos_ld(no, saida: list) -> None:
    """Coleta todo @type de um JSON-LD (inclui @graph e listas aninhadas)."""
    if isinstance(no, list):
        for item in no:
            _tipos_ld(item, saida)
    elif isinstance(no, dict):
        tipo = no.get("@type")
        if isinstance(tipo, str):
            saida.append(tipo)
        elif isinstance(tipo, list):
            saida.extend(t for t in tipo if isinstance(t, str))
        for valor in no.values():
            if isinstance(valor, (dict, list)):
                _tipos_ld(valor, saida)


def extrair(html: str, url_base: str, host: str) -> dict:
    """Sinais da página. `host` é o do site (www indiferente) — define o que é interno."""
    ex = _Extrator()
    try:
        ex.feed(html)
        ex.close()
    except Exception:  # HTML quebrado: devolve o que deu para ler
        pass

    host_site = _host_nu(host)
    internos, vistos = [], set()
    n_externos = n_nofollow = 0
    for href, rel in ex.links:
        if href.startswith("#") or href.lower().startswith(_ESQUEMAS_IGNORADOS):
            continue
        absoluta = urljoin(url_base, href)
        partes = urlsplit(absoluta)
        if partes.scheme not in ("http", "https"):
            continue
        if "nofollow" in rel.split():
            n_nofollow += 1
        if _host_nu(partes.netloc) == host_site:
            limpa = _sem_fragmento(absoluta)
            if limpa not in vistos:
                vistos.add(limpa)
                internos.append(limpa)
        else:
            n_externos += 1

    tipos, erros_ld = [], 0
    for bloco in ex.blocos_ld:
        try:
            _tipos_ld(json.loads(bloco), tipos)
        except (ValueError, TypeError):
            erros_ld += 1
    tipos.extend(t.rstrip("/").rsplit("/", 1)[-1] for t in ex.itemtypes)

    robots = ", ".join(v for k, v in ex.metas.items() if k in ("robots", "googlebot") and v)
    canonical = urljoin(url_base, ex.canonicals[0]) if ex.canonicals else None
    texto = " ".join(ex._texto)

    return {
        "titulo": ex.titulo,
        "titulo_chars": len(ex.titulo) if ex.titulo else 0,
        "descricao": ex.metas.get("description"),
        "robots_meta": robots or None,
        "canonical": canonical,
        "n_canonicals": len(ex.canonicals),
        "hreflang": [[lingua, urljoin(url_base, h)] for lingua, h in ex.hreflang],
        "h1": ex.h1,
        "lang": ex.lang,
        "n_palavras": len(_PALAVRA.findall(texto)),
        "links_internos": internos,
        "n_links_internos": len(internos),
        "n_links_externos": n_externos,
        "n_links_nofollow": n_nofollow,
        "schema_tipos": sorted(set(tipos)),
        "schema_blocos_invalidos": erros_ld,
    }
