"""
ficha.py — FICHA.toml: o que muda de um site para outro.

A ficha é escrita UMA vez (`dossie.py iniciar`) e editada à mão. É lida por todos
os comandos. TOML porque é para gente editar: comentário, sem vírgula sobrando.
"""

import os
import re

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover — só ambientes antigos de teste
    import tomli as tomllib

NOME = "FICHA.toml"

MODELO = """# FICHA.toml — dossiê de {dominio}
# Escrita por `dossie.py iniciar` em {hoje}. Edite à mão; todos os comandos a leem.

[site]
dominio = "{dominio}"
url = "{url}"

[projeto]
# Pasta do projeto ORIGINAL do site (código/conteúdo). Vazio = usar a
# subpasta `projeto_original/` dentro do dossiê, se você copiar o projeto para lá.
caminho = "{projeto}"
# php, nextjs, wordpress, html... — só informativo, para quem lê.
stack = ""
# Extensões tratadas como PÁGINA ao mapear arquivo -> URL.
extensoes_pagina = [".php", ".html", ".md", ".mdx", ".tsx", ".jsx", ".json"]
# Pastas ignoradas no inventário (além de .git).
ignorar = ["node_modules", "vendor", ".next", "dist", "build", "out", ".cache", "cache"]

[taxonomia]
# Regras regex sobre o CAMINHO da URL -> grupo. A primeira que casar vence;
# o que não casar fica como "sem_grupo". É você quem define: nada aqui é inferido.
regras = [
  ["^/$", "home"],
  ["^/images/", "imagem"],
]

[marca]
# Termos que identificam busca de marca (minúsculas, sem acento).
termos = []

[crawl]
pausa = {pausa}          # segundos entre requisições (educado)
max_urls = {max_urls}
incluir_urls_do_acervo = true   # fotografa também URLs que só o GSC conhece
"""


def caminho(pasta_dossie: str) -> str:
    return os.path.join(pasta_dossie, NOME)


def escrever_modelo(
    pasta_dossie: str,
    *,
    dominio: str,
    url: str,
    projeto: str = "",
    hoje: str,
    pausa: float,
    max_urls: int,
) -> str:
    """Escreve a ficha-modelo. Nunca sobrescreve uma ficha existente."""
    destino = caminho(pasta_dossie)
    if os.path.exists(destino):
        return destino
    texto = MODELO.format(
        dominio=dominio,
        url=url,
        projeto=projeto.replace("\\", "\\\\"),
        hoje=hoje,
        pausa=pausa,
        max_urls=max_urls,
    )
    os.makedirs(pasta_dossie, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(texto)
    return destino


def ler(pasta_dossie: str) -> dict:
    """Lê a ficha. Falta de arquivo é erro explícito: sem ficha não há dossiê."""
    destino = caminho(pasta_dossie)
    if not os.path.exists(destino):
        raise FileNotFoundError(
            f"{destino} nao existe. Rode `dossie.py iniciar --site ...` primeiro."
        )
    with open(destino, "rb") as fh:
        return tomllib.load(fh)


def pasta_projeto(ficha: dict, pasta_dossie: str) -> "str | None":
    """Onde está o projeto original: o caminho da ficha ou `projeto_original/`."""
    informado = (ficha.get("projeto") or {}).get("caminho") or ""
    if informado:
        return informado
    local = os.path.join(pasta_dossie, "projeto_original")
    return local if os.path.isdir(local) else None


def grupo_de(caminho_url: str, regras: list) -> str:
    """Primeira regra [regex, grupo] que casar com o caminho; senão 'sem_grupo'."""
    for regra in regras or []:
        if len(regra) != 2:
            continue
        padrao, grupo = regra
        if re.search(padrao, caminho_url):
            return grupo
    return "sem_grupo"
