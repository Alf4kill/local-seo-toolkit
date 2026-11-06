"""
projeto.py — o que o projeto ORIGINAL do site diz sobre quando cada coisa mudou.

Três saídas, todas extração:
  - inventário: cada arquivo, com data de criação/edição (git quando houver,
    data do sistema de arquivos quando não houver — e a fonte vai na linha);
  - eventos CANDIDATOS: dias em que muitos arquivos de página entraram, mudaram
    ou saíram, e commits que mexeram em configuração (.htaccess, robots,
    sitemap...). São candidatos: um humano confirma antes de `acervo.py anotar`;
  - redirects declarados no projeto, com a data em que cada regra entrou
    (`git blame` da linha).

O mapeamento arquivo -> URL é HEURÍSTICO (nome do arquivo = último segmento da
URL) e vem rotulado `unico` / `ambiguo` / `sem_par`. Nada aqui afirma que um
arquivo É uma URL; afirma que o nome casa.
"""

import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

ARQUIVOS_CONFIG = (
    ".htaccess",
    "robots.txt",
    "web.config",
    "vercel.json",
    "_redirects",
    "netlify.toml",
)
PREFIXOS_CONFIG = ("sitemap", "next.config", "nginx")

TIPO_POR_STATUS = {"A": "conteudo-novo", "M": "conteudo-editado", "D": "poda"}


# ---------------------------------------------------------------------------
# Inventário
# ---------------------------------------------------------------------------


def inventario(pasta: str, *, extensoes_pagina, ignorar) -> list:
    """Todos os arquivos (exceto pastas ignoradas e .git), com tamanho e mtime."""
    ignorar = set(ignorar or ()) | {".git"}
    exts = tuple(e.lower() for e in extensoes_pagina or ())
    saida = []
    for raiz, dirs, arquivos in os.walk(pasta):
        dirs[:] = sorted(d for d in dirs if d not in ignorar)
        for nome in sorted(arquivos):
            completo = os.path.join(raiz, nome)
            rel = os.path.relpath(completo, pasta).replace(os.sep, "/")
            try:
                st = os.stat(completo)
            except OSError:
                continue
            saida.append(
                {
                    "arquivo": rel,
                    "ext": os.path.splitext(nome)[1].lower(),
                    "e_pagina": nome.lower().endswith(exts),
                    "e_config": e_config(rel),
                    "bytes": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                    .date()
                    .isoformat(),
                }
            )
    return saida


def e_config(caminho_rel: str) -> bool:
    nome = caminho_rel.rsplit("/", 1)[-1].lower()
    return nome in ARQUIVOS_CONFIG or nome.startswith(PREFIXOS_CONFIG)


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

_SEP_COMMIT = "\x1e"
_SEP_CAMPO = "\x1f"


def tem_git(pasta: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", pasta, "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def log_git(pasta: str) -> str:
    """Saída crua do `git log` (nomes relativos à pasta, sem detecção de rename)."""
    r = subprocess.run(
        [
            "git",
            "-C",
            pasta,
            "log",
            "--relative",
            "--no-renames",
            "--name-status",
            "--date=short",
            f"--format={_SEP_COMMIT}%H{_SEP_CAMPO}%ad{_SEP_CAMPO}%s",
            "--",
            ".",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git log falhou: {r.stderr.strip()[:300]}")
    return r.stdout


def parse_log(texto: str) -> list:
    """[{hash, data, assunto, arquivos: [(status, caminho)]}], mais novo primeiro."""
    commits = []
    for bloco in texto.split(_SEP_COMMIT):
        bloco = bloco.strip("\n")
        if not bloco:
            continue
        cabecalho, *linhas = bloco.split("\n")
        partes = cabecalho.split(_SEP_CAMPO)
        if len(partes) < 3:
            continue
        arquivos = []
        for linha in linhas:
            if "\t" not in linha:
                continue
            status, caminho = linha.split("\t", 1)
            arquivos.append((status.strip()[:1], caminho.strip()))
        commits.append(
            {"hash": partes[0], "data": partes[1], "assunto": partes[2], "arquivos": arquivos}
        )
    return commits


def aplicar_git(itens: list, commits: list) -> None:
    """Acrescenta criado_git / alterado_git / n_commits a cada item do inventário."""
    por_arquivo = defaultdict(list)
    for c in commits:
        for status, caminho in c["arquivos"]:
            por_arquivo[caminho].append((c["data"], status))
    for item in itens:
        hist = por_arquivo.get(item["arquivo"], [])
        datas = sorted(d for d, _ in hist)
        adicoes = sorted(d for d, s in hist if s == "A")
        item["criado_git"] = adicoes[0] if adicoes else (datas[0] if datas else None)
        item["alterado_git"] = datas[-1] if datas else None
        item["n_commits"] = len(hist)


def eventos_candidatos(commits: list, *, extensoes_pagina, min_arquivos: int) -> list:
    """Dias com >= min_arquivos de PÁGINA adicionados/editados/removidos, e todo
    commit que tocou arquivo de configuração. Ordenado por data."""
    exts = tuple(e.lower() for e in extensoes_pagina or ())
    por_dia = defaultdict(lambda: {"arquivos": [], "assuntos": []})
    tecnicos = []
    for c in commits:
        config = [p for _, p in c["arquivos"] if e_config(p)]
        if config:
            tecnicos.append(
                {
                    "data": c["data"],
                    "tipo_sugerido": "tecnico",
                    "n_arquivos": len(config),
                    "pasta_dominante": _pasta_dominante(config),
                    "assuntos": [c["assunto"]],
                    "arquivos": config,
                }
            )
        for status, caminho in c["arquivos"]:
            if status in TIPO_POR_STATUS and caminho.lower().endswith(exts):
                chave = (c["data"], TIPO_POR_STATUS[status])
                por_dia[chave]["arquivos"].append(caminho)
                if c["assunto"] not in por_dia[chave]["assuntos"]:
                    por_dia[chave]["assuntos"].append(c["assunto"])

    saida = []
    for (data, tipo), acc in por_dia.items():
        arquivos = sorted(set(acc["arquivos"]))
        if len(arquivos) < min_arquivos:
            continue
        saida.append(
            {
                "data": data,
                "tipo_sugerido": tipo,
                "n_arquivos": len(arquivos),
                "pasta_dominante": _pasta_dominante(arquivos),
                "assuntos": acc["assuntos"][:5],
                "arquivos": arquivos,
            }
        )
    saida.extend(tecnicos)
    saida.sort(key=lambda e: (e["data"], e["tipo_sugerido"]))
    return saida


def _pasta_dominante(caminhos: list) -> str:
    pastas = Counter(c.rsplit("/", 1)[0] if "/" in c else "." for c in caminhos)
    return pastas.most_common(1)[0][0] if pastas else ""


# ---------------------------------------------------------------------------
# Arquivo -> URL (heurístico, rotulado)
# ---------------------------------------------------------------------------

_INDICES = {"index", "page", "default", "route"}


def slug_do_arquivo(caminho_rel: str) -> str:
    """'artigos/cane-corso.php' -> 'cane-corso'; 'blog/x/index.md' -> 'x'; raiz -> ''."""
    partes = caminho_rel.split("/")
    base = os.path.splitext(partes[-1])[0]
    if base.lower() in _INDICES:
        base = partes[-2] if len(partes) > 1 else ""
    return base.strip().lower()


def ultimo_segmento(url: str) -> str:
    caminho = unquote(urlsplit(url).path).rstrip("/")
    return caminho.rsplit("/", 1)[-1].lower() if caminho else ""


def mapear_urls(itens: list, urls_conhecidas: list) -> None:
    """Acrescenta url_casada / casamento ('unico'|'ambiguo'|'sem_par') às páginas."""
    por_slug = defaultdict(list)
    for url in urls_conhecidas:
        por_slug[ultimo_segmento(url)].append(url)
    for item in itens:
        if not item.get("e_pagina"):
            item["url_casada"], item["casamento"] = None, None
            continue
        candidatas = sorted(set(por_slug.get(slug_do_arquivo(item["arquivo"]), [])))
        if len(candidatas) == 1:
            item["url_casada"], item["casamento"] = candidatas[0], "unico"
        elif candidatas:
            item["url_casada"], item["casamento"] = " | ".join(candidatas), "ambiguo"
        else:
            item["url_casada"], item["casamento"] = None, "sem_par"


# ---------------------------------------------------------------------------
# Redirects declarados no projeto
# ---------------------------------------------------------------------------

_RE_REDIRECT = re.compile(
    r"^\s*Redirect(?:Permanent)?\s+(?:(\d{3}|permanent)\s+)?(\S+)\s+(\S+)", re.I
)
_RE_REDIRECTMATCH = re.compile(r"^\s*RedirectMatch\s+(?:(\d{3}|permanent)\s+)?(\S+)\s+(\S+)", re.I)
_RE_REWRITE = re.compile(r"^\s*RewriteRule\s+(\S+)\s+(\S+)\s+\[([^\]]*)\]", re.I)
_RE_NGINX = re.compile(r"^\s*rewrite\s+(\S+)\s+(\S+)\s+(permanent|redirect)\s*;", re.I)
_RE_NEXT = re.compile(
    r"source\s*:\s*['\"]([^'\"]+)['\"][^}]*?destination\s*:\s*['\"]([^'\"]+)['\"]", re.S
)


def redirects_de_texto(texto: str, nome_arquivo: str) -> list:
    """[{linha, regra, origem, destino, codigo}] de um arquivo de configuração."""
    nome = nome_arquivo.rsplit("/", 1)[-1].lower()
    saida = []
    if nome.startswith("next.config") or nome == "vercel.json":
        for m in _RE_NEXT.finditer(texto):
            linha = texto.count("\n", 0, m.start()) + 1
            fim = texto.find("}", m.end())
            trecho = texto[m.start() : fim if fim != -1 else len(texto)]
            codigo = "308" if re.search(r"permanent\s*:\s*true", trecho) else "307"
            saida.append(
                {
                    "linha": linha,
                    "regra": "next",
                    "origem": m.group(1),
                    "destino": m.group(2),
                    "codigo": codigo,
                }
            )
        return saida
    for n, linha in enumerate(texto.splitlines(), start=1):
        if linha.strip().startswith("#"):
            continue
        if nome == "_redirects":
            partes = linha.split()
            if len(partes) >= 2 and partes[0].startswith("/"):
                saida.append(
                    {
                        "linha": n,
                        "regra": "_redirects",
                        "origem": partes[0],
                        "destino": partes[1],
                        "codigo": partes[2] if len(partes) > 2 else "301",
                    }
                )
            continue
        for regex, regra in ((_RE_REDIRECTMATCH, "RedirectMatch"), (_RE_REDIRECT, "Redirect")):
            m = regex.match(linha)
            if m:
                codigo = m.group(1) or "302"
                codigo = "301" if codigo.lower() == "permanent" else codigo
                saida.append(
                    {
                        "linha": n,
                        "regra": regra,
                        "origem": m.group(2),
                        "destino": m.group(3),
                        "codigo": codigo,
                    }
                )
                break
        else:
            m = _RE_REWRITE.match(linha)
            if m and re.search(r"(^|,)\s*R(=\d{3})?\s*(,|$)", m.group(3)):
                cod = re.search(r"R=(\d{3})", m.group(3))
                saida.append(
                    {
                        "linha": n,
                        "regra": "RewriteRule",
                        "origem": m.group(1),
                        "destino": m.group(2),
                        "codigo": cod.group(1) if cod else "302",
                    }
                )
                continue
            m = _RE_NGINX.match(linha)
            if m:
                saida.append(
                    {
                        "linha": n,
                        "regra": "nginx",
                        "origem": m.group(1),
                        "destino": m.group(2),
                        "codigo": "301" if m.group(3).lower() == "permanent" else "302",
                    }
                )
    return saida


def datas_blame(pasta: str, arquivo_rel: str) -> dict:
    """{numero_da_linha: 'AAAA-MM-DD'} via `git blame` (data do autor da linha)."""
    try:
        r = subprocess.run(
            ["git", "-C", pasta, "blame", "--line-porcelain", "--", arquivo_rel],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if r.returncode != 0:
        return {}
    return parse_blame(r.stdout)


def parse_blame(texto: str) -> dict:
    datas, linha_atual = {}, None
    for linha in texto.splitlines():
        m = re.match(r"^[0-9a-f]{40} \d+ (\d+)", linha)
        if m:
            linha_atual = int(m.group(1))
        elif linha.startswith("author-time ") and linha_atual is not None:
            ts = int(linha.split()[1])
            datas[linha_atual] = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    return datas
