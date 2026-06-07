"""
loaders.py — Obtém os textos das páginas a analisar.

Fontes:
  - load_from_folder(path)     : arquivos .php/.html locais (ex.: backup do site).
  - load_from_primeweb(path)   : lê include/parametros.php (CMS primeWeb usado pela
                                 empresa) e carrega as páginas dos arrays $blog e
                                 $palavras_chave pelos slugs.
  - load_from_urls(urls)       : baixa cada URL e extrai o texto editorial.

Extração de texto: remove blocos PHP, <script>/<style> e tags HTML, decodifica
entidades e normaliza espaços — aproxima o texto que um motor semântico veria.
"""

import html as H
import os
import re
import unicodedata


def slugify(s: str) -> str:
    """Converte um nome em slug (minúsculo, sem acento, hífens) — padrão primeWeb."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def extract_text(markup: str) -> str:
    """Texto puro a partir de HTML/PHP."""
    markup = re.sub(r"<\?.*?\?>", " ", markup, flags=re.DOTALL)                       # blocos PHP
    markup = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", markup,
                    flags=re.DOTALL | re.IGNORECASE)                                  # script/style
    markup = re.sub(r"<[^>]+>", " ", markup)                                          # demais tags
    return re.sub(r"\s+", " ", H.unescape(markup)).strip()


def load_from_folder(
    path: str,
    extensions: tuple = (".php", ".html", ".htm"),
    min_chars: int = 300,
    exclude: "set | None" = None,
) -> dict:
    """Lê todos os arquivos de conteúdo de uma pasta. Retorna {slug: texto}."""
    exclude = set(exclude or [])
    out = {}
    for fn in sorted(os.listdir(path)):
        if not fn.lower().endswith(extensions):
            continue
        slug = os.path.splitext(fn)[0]
        if slug in exclude:
            continue
        with open(os.path.join(path, fn), encoding="utf-8", errors="replace") as f:
            txt = extract_text(f.read())
        if len(txt) >= min_chars:
            out[slug] = txt
    return out


def _parse_php_array(name: str, src: str) -> list:
    m = re.search(r"\$" + name + r"\s*=\s*array\((.*?)\n\);", src, re.DOTALL)
    return re.findall(r'"([^"]*)"', m.group(1)) if m else []


def load_from_primeweb(base_path: str, min_chars: int = 300) -> dict:
    """
    Carrega as páginas listadas em $blog + $palavras_chave de
    {base_path}/include/parametros.php. Retorna {slug: texto}.
    """
    params = os.path.join(base_path, "include", "parametros.php")
    with open(params, encoding="utf-8", errors="replace") as f:
        src = f.read()
    names = _parse_php_array("palavras_chave", src) + _parse_php_array("blog", src)

    out = {}
    for name in names:
        slug = slugify(name)
        fpath = os.path.join(base_path, slug + ".php")
        if slug in out or not os.path.exists(fpath):
            continue
        with open(fpath, encoding="utf-8", errors="replace") as f:
            txt = extract_text(f.read())
        if len(txt) >= min_chars:
            out[slug] = txt
    return out


def load_from_urls(urls: list, min_chars: int = 300, timeout: int = 12) -> dict:
    """Baixa cada URL e extrai o texto. Retorna {url: texto}. Requer 'requests'."""
    import requests
    out = {}
    for url in urls:
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": "semantic-analyzer/1.0"})
            r.raise_for_status()
            txt = extract_text(r.text)
            if len(txt) >= min_chars:
                out[url] = txt
        except Exception as exc:
            print(f"[loader] falha em {url}: {exc}")
    return out


# ---------------------------------------------------------------------------
# Markup CRU (sem extrair texto) — usado pelo grafo de links internos, que
# precisa das tags <a href>. Retorna {slug: markup}. Carrega TODAS as páginas
# (sem filtro de min_chars) p/ que links vindos de páginas curtas também contem.
# ---------------------------------------------------------------------------

def load_sources_from_folder(
    path: str,
    extensions: tuple = (".php", ".html", ".htm"),
    exclude: "set | None" = None,
) -> dict:
    """Markup cru de todos os arquivos de conteúdo de uma pasta. {slug: markup}."""
    exclude = set(exclude or [])
    out = {}
    for fn in sorted(os.listdir(path)):
        if not fn.lower().endswith(extensions):
            continue
        slug = os.path.splitext(fn)[0]
        if slug in exclude:
            continue
        with open(os.path.join(path, fn), encoding="utf-8", errors="replace") as f:
            out[slug] = f.read()
    return out


def load_sources_from_primeweb(base_path: str) -> dict:
    """Markup cru das páginas de $blog + $palavras_chave (CMS primeWeb). {slug: markup}."""
    params = os.path.join(base_path, "include", "parametros.php")
    with open(params, encoding="utf-8", errors="replace") as f:
        src = f.read()
    names = _parse_php_array("palavras_chave", src) + _parse_php_array("blog", src)
    out = {}
    for name in names:
        slug = slugify(name)
        fpath = os.path.join(base_path, slug + ".php")
        if slug in out or not os.path.exists(fpath):
            continue
        with open(fpath, encoding="utf-8", errors="replace") as f:
            out[slug] = f.read()
    return out


def load_sources_from_urls(urls: list, timeout: int = 12) -> dict:
    """Baixa cada URL e retorna o markup CRU (p/ extrair links). {url: markup}."""
    import requests
    out = {}
    for url in urls:
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": "semantic-analyzer/1.0"})
            r.raise_for_status()
            out[url] = r.text
        except Exception as exc:
            print(f"[loader] falha em {url}: {exc}")
    return out
