"""
dossie.py — Dossiê de análise de UM site (P8).

Junta numa pasta fora do repositório tudo o que é viável coletar de forma simples
para a sessão de análise. Como o acervo: EXTRAÇÃO, NUNCA VEREDITO.

    E:\\projetos\\dossies\\{dominio}\\
      FICHA.toml   o que muda por site (editada à mão)
      LEIA.md      a escrituração: o que existe, de quando, o que falta
      acervo\\      cópia do pacote do acervo
      gsc_ui\\      exports manuais da UI do GSC
      site_vivo\\AAAA-MM-DD\\   foto do site ao vivo
      projeto\\     inventário, eventos candidatos e redirects do projeto original
      analise\\     saídas da sessão de análise

Uso:
    py dossie.py iniciar --site www.exemplo.com.br [--projeto E:\\caminho\\do\\site]
    py dossie.py site    --site www.exemplo.com.br [--tempo-max 600]
    py dossie.py projeto --site www.exemplo.com.br
    py dossie.py fechar  --site www.exemplo.com.br      # copia o pacote do acervo
    py dossie.py status  --site www.exemplo.com.br      # só regenera e mostra o LEIA

Ordem sugerida: iniciar -> exports da UI em gsc_ui\\ -> site -> projeto ->
anotar eventos no acervo -> `acervo.py pacote --todos-os-tipos` -> fechar.
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import os
import shutil
from datetime import UTC, date, datetime

from config import (
    DOSSIE_CRAWL_MAX_URLS,
    DOSSIE_CRAWL_PAUSA,
    DOSSIE_MIN_ARQUIVOS_LOTE,
    DOSSIES_DIR,
)
from core import storage
from core.dossie import alvos as alvos_mod
from core.dossie import ficha as ficha_mod
from core.dossie import leia, projeto, saidas
from core.urls import build_site_url, normalize_domain


class DossieError(RuntimeError):
    """Falha fatal de um comando do dossiê."""


def _agora() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def pasta_dossie(site: str, raiz: "str | None" = None) -> str:
    return os.path.join(raiz or DOSSIES_DIR, normalize_domain(site))


def pasta_pacote(site: str) -> str:
    return os.path.join(storage.RELATORIOS_DIR, normalize_domain(site), "acervo", "pacote")


def _db_acervo(site: str, pasta: str) -> "str | None":
    """O banco para listar URLs: a cópia do dossiê, senão o acervo vivo."""
    for candidato in (
        os.path.join(pasta, "acervo", "acervo.sqlite3"),
        os.path.join(storage.RELATORIOS_DIR, normalize_domain(site), "acervo", "acervo.sqlite3"),
    ):
        if os.path.exists(candidato):
            return candidato
    return None


def _fechar_leia(pasta: str) -> str:
    return leia.gerar(pasta, ficha_mod.ler(pasta), agora=_agora())


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


def cmd_iniciar(args) -> dict:
    pasta = pasta_dossie(args.site, args.raiz)
    for sub in ("acervo", "gsc_ui", "site_vivo", "projeto", "analise"):
        os.makedirs(os.path.join(pasta, sub), exist_ok=True)
    existia = os.path.exists(ficha_mod.caminho(pasta))
    ficha_mod.escrever_modelo(
        pasta,
        dominio=normalize_domain(args.site),
        url=build_site_url(normalize_domain(args.site)),
        projeto=args.projeto or "",
        hoje=date.today().isoformat(),
        pausa=DOSSIE_CRAWL_PAUSA,
        max_urls=DOSSIE_CRAWL_MAX_URLS,
    )
    comum = os.path.join(os.path.dirname(pasta), "_comum")
    os.makedirs(comum, exist_ok=True)
    updates = os.path.join(comum, "google_updates.csv")
    if not os.path.exists(updates):
        saidas.escrever_csv(updates, [], ["data_inicio", "data_fim", "nome", "tipo", "fonte_url"])
    caminho_leia = _fechar_leia(pasta)
    print(f"[dossie] {'ficha mantida' if existia else 'ficha criada'}: {ficha_mod.caminho(pasta)}")
    print(
        f"[dossie] edite a FICHA (taxonomia, marca, projeto) e veja o que falta em {caminho_leia}"
    )
    return {"pasta": pasta, "ficha_existia": existia}


def cmd_site(args) -> dict:
    from fetchers import site_crawler

    pasta = pasta_dossie(args.site, args.raiz)
    ficha = ficha_mod.ler(pasta)
    conf = ficha.get("crawl") or {}
    dominio = ficha["site"]["dominio"]
    pausa = args.pausa if args.pausa is not None else float(conf.get("pausa", DOSSIE_CRAWL_PAUSA))
    max_urls = args.max_urls or int(conf.get("max_urls", DOSSIE_CRAWL_MAX_URLS))
    dia = date.today().isoformat()
    pasta_dia = os.path.join(pasta, "site_vivo", dia)
    os.makedirs(pasta_dia, exist_ok=True)
    caminho_alvos = os.path.join(pasta_dia, "alvos.json")
    sessao = site_crawler.nova_sessao()

    coleta = saidas.ler_json(os.path.join(pasta_dia, "coleta.json"), {})
    if not os.path.exists(caminho_alvos):
        status_robots, robots = site_crawler.baixar_texto(sessao, f"https://{dominio}/robots.txt")
        if robots is not None:
            with open(os.path.join(pasta_dia, "robots.txt"), "w", encoding="utf-8") as fh:
                fh.write(robots)
        print("[site] lendo sitemaps...")
        mapas = site_crawler.coletar_sitemaps(
            sessao, dominio, robots, os.path.join(pasta_dia, "sitemaps"), pausa=pausa
        )
        do_acervo = []
        if conf.get("incluir_urls_do_acervo", True) and not args.sem_acervo:
            do_acervo = alvos_mod.urls_do_acervo(_db_acervo(args.site, pasta))
        montado = alvos_mod.montar(mapas["entradas"], do_acervo, max_urls=max_urls)
        saidas.escrever_json(caminho_alvos, montado["alvos"])
        coleta = {
            "dia": dia,
            "iniciado_em": _agora(),
            "robots_status": status_robots,
            "sitemaps": mapas["arquivos"],
            "n_entradas_sitemap": len(mapas["entradas"]),
            "n_urls_acervo": len(do_acervo),
            "n_alvos": len(montado["alvos"]),
            "fora": montado["fora"],
            "pausa": pausa,
            "user_agent": site_crawler.USER_AGENT,
        }
        print(
            f"[site] {len(montado['alvos'])} URLs alvo "
            f"({len(mapas['entradas'])} do sitemap, {len(do_acervo)} do acervo)"
        )
    alvos = saidas.ler_json(caminho_alvos, [])

    resultado = site_crawler.rodar(
        sessao, alvos, host=dominio, pasta_dia=pasta_dia, pausa=pausa, tempo_max=args.tempo_max
    )
    registros = saidas.ler_jsonl(os.path.join(pasta_dia, "crawl.jsonl"))
    linhas, arestas = saidas.resumo_crawl(
        registros, regras_taxonomia=(ficha.get("taxonomia") or {}).get("regras")
    )
    saidas.escrever_csv(os.path.join(pasta_dia, "resumo.csv"), linhas, saidas.COLUNAS_RESUMO)
    saidas.escrever_csv(
        os.path.join(pasta_dia, "links_internos.csv"), arestas, ["origem", "destino_caminho"]
    )
    coleta.update(
        {
            "terminado_em": _agora(),
            "completo": resultado["completo"],
            "fotografadas": resultado["fotografadas"],
        }
    )
    saidas.escrever_json(os.path.join(pasta_dia, "coleta.json"), coleta)
    _fechar_leia(pasta)
    if not resultado["completo"]:
        print(
            f"[site] parcial: {resultado['fotografadas']}/{resultado['total_alvos']}. "
            "Rode de novo hoje para retomar."
        )
    else:
        print(f"[site] completo: {resultado['fotografadas']} URLs em {pasta_dia}")
    return resultado


def cmd_projeto(args) -> dict:
    pasta = pasta_dossie(args.site, args.raiz)
    ficha = ficha_mod.ler(pasta)
    origem = ficha_mod.pasta_projeto(ficha, pasta)
    if not origem or not os.path.isdir(origem):
        raise DossieError(
            "projeto original nao encontrado: preencha [projeto].caminho na FICHA.toml "
            "ou copie o projeto para projeto_original/ dentro do dossie."
        )
    conf = ficha.get("projeto") or {}
    exts = conf.get("extensoes_pagina") or [".php", ".html", ".md"]
    itens = projeto.inventario(origem, extensoes_pagina=exts, ignorar=conf.get("ignorar"))
    git = projeto.tem_git(origem)
    commits = projeto.parse_log(projeto.log_git(origem)) if git else []
    if git:
        projeto.aplicar_git(itens, commits)

    urls = [a["url"] for a in alvos_mod.urls_do_acervo(_db_acervo(args.site, pasta))]
    vivo = os.path.join(pasta, "site_vivo")
    if os.path.isdir(vivo):
        for dia in sorted(os.listdir(vivo))[-1:]:
            urls += [a["url"] for a in saidas.ler_json(os.path.join(vivo, dia, "alvos.json"), [])]
    projeto.mapear_urls(itens, sorted(set(urls)))

    destino = os.path.join(pasta, "projeto")
    saidas.escrever_csv(
        os.path.join(destino, "inventario.csv"),
        itens,
        [
            "arquivo",
            "ext",
            "e_pagina",
            "e_config",
            "bytes",
            "mtime",
            "criado_git",
            "alterado_git",
            "n_commits",
            "url_casada",
            "casamento",
        ],
    )

    min_arq = args.min_arquivos or DOSSIE_MIN_ARQUIVOS_LOTE
    candidatos = projeto.eventos_candidatos(commits, extensoes_pagina=exts, min_arquivos=min_arq)
    url_por_arquivo = {
        i["arquivo"]: i.get("url_casada") for i in itens if i.get("casamento") == "unico"
    }
    pasta_ev = os.path.join(destino, "eventos")
    if os.path.isdir(pasta_ev):
        shutil.rmtree(pasta_ev)
    for c in candidatos:
        casadas = [url_por_arquivo[a] for a in c["arquivos"] if a in url_por_arquivo]
        c["n_urls_casadas"] = len(casadas)
        if casadas:
            nome = f"{c['data']}_{c['tipo_sugerido']}.txt"
            os.makedirs(pasta_ev, exist_ok=True)
            with open(os.path.join(pasta_ev, nome), "a", encoding="utf-8") as fh:
                fh.write(
                    f"# CANDIDATO, nao verdade: {c['n_arquivos']} arquivo(s) em {c['data']}"
                    f" ({c['tipo_sugerido']}). Apague o que nao for do evento.\n"
                )
                fh.write("\n".join(casadas) + "\n")
            c["arquivo_urls"] = "eventos/" + nome
    saidas.escrever_csv(
        os.path.join(destino, "eventos_candidatos.csv"),
        candidatos,
        [
            "data",
            "tipo_sugerido",
            "n_arquivos",
            "n_urls_casadas",
            "pasta_dominante",
            "assuntos",
            "arquivo_urls",
            "arquivos",
        ],
    )

    redirects = []
    for item in itens:
        if not item["e_config"]:
            continue
        try:
            with open(
                os.path.join(origem, item["arquivo"]), encoding="utf-8", errors="replace"
            ) as fh:
                texto = fh.read()
        except OSError:
            continue
        regras = projeto.redirects_de_texto(texto, item["arquivo"])
        datas = projeto.datas_blame(origem, item["arquivo"]) if (git and regras) else {}
        for r in regras:
            r.update({"arquivo": item["arquivo"], "data_git": datas.get(r["linha"])})
            redirects.append(r)
    saidas.escrever_csv(
        os.path.join(destino, "redirects.csv"),
        redirects,
        ["arquivo", "linha", "regra", "codigo", "origem", "destino", "data_git"],
    )
    saidas.escrever_json(
        os.path.join(destino, "coleta.json"),
        {
            "coletado_em": _agora(),
            "pasta": origem,
            "git": git,
            "n_commits": len(commits),
            "n_arquivos": len(itens),
            "n_paginas": sum(1 for i in itens if i["e_pagina"]),
            "n_candidatos": len(candidatos),
            "n_redirects": len(redirects),
            "min_arquivos_lote": min_arq,
        },
    )
    _fechar_leia(pasta)
    print(
        f"[projeto] {len(itens)} arquivos, git={'sim' if git else 'nao'}, "
        f"{len(candidatos)} evento(s) candidato(s), {len(redirects)} redirect(s)"
    )
    return {"n_arquivos": len(itens), "git": git, "n_candidatos": len(candidatos)}


def cmd_fechar(args) -> dict:
    pasta = pasta_dossie(args.site, args.raiz)
    ficha_mod.ler(pasta)
    origem = args.pacote or pasta_pacote(args.site)
    copiado = False
    if args.sem_copiar:
        print("[fechar] --sem-copiar: acervo/ mantido como esta")
    elif os.path.isdir(origem):
        destino = os.path.join(pasta, "acervo")
        if os.path.isdir(destino):
            shutil.rmtree(destino)
        shutil.copytree(origem, destino)
        saidas.escrever_json(
            os.path.join(destino, "copia.json"), {"copiado_em": _agora(), "origem": origem}
        )
        copiado = True
        print(f"[fechar] pacote copiado de {origem}")
    else:
        print(
            f"[fechar] AVISO: pacote nao encontrado em {origem}. "
            f"Rode `py acervo.py pacote --site {normalize_domain(args.site)} --todos-os-tipos`."
        )
    caminho = _fechar_leia(pasta)
    print(f"[fechar] {caminho}")
    return {"copiado": copiado}


def cmd_status(args) -> dict:
    pasta = pasta_dossie(args.site, args.raiz)
    caminho = _fechar_leia(pasta)
    with open(caminho, encoding="utf-8") as fh:
        print(fh.read())
    return {}


COMANDOS = {
    "iniciar": cmd_iniciar,
    "site": cmd_site,
    "projeto": cmd_projeto,
    "fechar": cmd_fechar,
    "status": cmd_status,
}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dossie de analise de um site (extracao, nao analise)"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    def comum(p):
        p.add_argument("--site", required=True, help="dominio (ex. www.exemplo.com.br)")
        p.add_argument("--raiz", help=f"pasta dos dossies (padrao: {DOSSIES_DIR})")

    p = sub.add_parser("iniciar", help="cria a pasta, a FICHA.toml e o LEIA.md")
    comum(p)
    p.add_argument("--projeto", help="pasta do projeto original do site")

    p = sub.add_parser("site", help="foto do site ao vivo (sitemap + URLs do acervo); sem cota")
    comum(p)
    p.add_argument("--pausa", type=float, help="segundos entre requisicoes (padrao: FICHA)")
    p.add_argument("--max-urls", dest="max_urls", type=int, help="limite de URLs (padrao: FICHA)")
    p.add_argument(
        "--tempo-max",
        dest="tempo_max",
        type=float,
        help="para depois de N segundos; rodar de novo no mesmo dia retoma",
    )
    p.add_argument(
        "--sem-acervo", dest="sem_acervo", action="store_true", help="fotografa so o sitemap"
    )

    p = sub.add_parser("projeto", help="inventario, eventos candidatos e redirects do projeto")
    comum(p)
    p.add_argument(
        "--min-arquivos",
        dest="min_arquivos",
        type=int,
        help=(
            "arquivos de pagina no mesmo dia para virar candidato "
            f"(padrao: {DOSSIE_MIN_ARQUIVOS_LOTE})"
        ),
    )

    p = sub.add_parser("fechar", help="copia o pacote do acervo e regenera o LEIA.md")
    comum(p)
    p.add_argument("--pacote", help="pasta do pacote (padrao: relatorios/{dominio}/acervo/pacote)")
    p.add_argument(
        "--sem-copiar",
        dest="sem_copiar",
        action="store_true",
        help="nao recopia o acervo (so regenera o LEIA)",
    )

    p = sub.add_parser("status", help="regenera e imprime o LEIA.md")
    comum(p)
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    try:
        COMANDOS[args.comando](args)
    except (DossieError, FileNotFoundError, RuntimeError) as exc:
        print(f"[dossie] ERRO: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
