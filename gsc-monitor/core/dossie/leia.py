"""
leia.py — LEIA.md: a escrituração do dossiê.

Faz pelo dossiê o que o DADOS.md faz pelo acervo: diz o que existe, DE QUANDO é
cada fonte, o que falta e o que nunca vai estar aqui. É regenerado no fim de
todo comando do `dossie.py` — derivado das pastas, nunca editado à mão.

Sem veredito: contagens e datas. "12 URLs com noindex" é fato da foto;
"o noindex derrubou o tráfego" é análise, e não mora aqui.
"""

import os
import re
import sqlite3
import unicodedata

from core.dossie import saidas

# (chave, rótulo, regex no nome do arquivo, como exportar, essencial)
ITENS_UI = [
    (
        "indexacao-paginas",
        "Indexação › Páginas",
        r"indexa|pagin|coverage|indexing",
        "Exportar o relatório (gráfico + motivos). Em cada motivo de não indexação, "
        "exportar também as URLs de exemplo.",
        True,
    ),
    (
        "sitemaps",
        "Indexação › Sitemaps",
        r"sitemap",
        "Export ou print da lista de sitemaps, com status e URLs descobertas.",
        True,
    ),
    (
        "links",
        "Links",
        r"(^|[_\-\s.])links?([_\-\s.]|$)",
        "Botão Exportar no topo: páginas mais linkadas (internas e externas) e textos âncora.",
        True,
    ),
    (
        "rastreamento",
        "Configurações › Estatísticas de rastreamento",
        r"rastre|crawl",
        "Exportar (90 dias): por resposta, por tipo de arquivo, por finalidade e por "
        "tipo de Googlebot.",
        True,
    ),
    (
        "acoes-manuais",
        "Ações manuais e problemas de segurança",
        r"aco(es)?[_\-]?manua|manual|seguranca|security",
        "Print ou nota de texto: há ação manual? Há problema de segurança? (sim/não, com data).",
        True,
    ),
    (
        "core-web-vitals",
        "Experiência › Core Web Vitals",
        r"vitals|cwv",
        "Exportar mobile e desktop.",
        False,
    ),
    (
        "aparencia",
        "Desempenho › Aparência na pesquisa",
        r"aparen|appearance",
        "Na aba 'Aparência na pesquisa' do relatório de desempenho, período de 16 meses, exportar.",
        False,
    ),
    (
        "ia",
        "Desempenho em recursos de IA",
        r"(^|[_\-\s.])ia([_\-\s.]|$)|generativ",
        "Só se a propriedade mostrar esse relatório: exportar.",
        False,
    ),
    (
        "remocoes",
        "Remoções",
        r"remoc|removal",
        "Export ou print das solicitações de remoção.",
        False,
    ),
]


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def checklist_ui(pasta_ui: str) -> list:
    arquivos = sorted(os.listdir(pasta_ui)) if os.path.isdir(pasta_ui) else []
    saida = []
    for chave_item, rotulo, padrao, como, essencial in ITENS_UI:
        achados = [a for a in arquivos if re.search(padrao, _sem_acento(a.lower()))]
        saida.append(
            {
                "chave": chave_item,
                "rotulo": rotulo,
                "arquivos": achados,
                "como": como,
                "essencial": essencial,
            }
        )
    reconhecidos = {a for item in saida for a in item["arquivos"]}
    outros = [a for a in arquivos if a not in reconhecidos and not a.startswith(".")]
    return saida, outros


def _acervo(pasta_acervo: str) -> dict:
    db = os.path.join(pasta_acervo, "acervo.sqlite3")
    info = {
        "existe": os.path.exists(db),
        "copia": saidas.ler_json(os.path.join(pasta_acervo, "copia.json"), {}),
    }
    if not info["existe"]:
        return info
    info["documentos"] = sorted(
        d
        for d in os.listdir(pasta_acervo)
        if os.path.exists(os.path.join(pasta_acervo, d, "DADOS.md"))
    )
    uri = "file:" + os.path.abspath(db).replace("\\", "/") + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
        try:
            info["tipos"] = con.execute(
                """SELECT tipo, MIN(data), MAX(data), COUNT(DISTINCT data),
                          SUM(data_state <> 'final')
                   FROM ingestao WHERE grao = 'total' GROUP BY tipo ORDER BY tipo"""
            ).fetchall()
            info["eventos"] = con.execute("SELECT COUNT(*) FROM evento").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as exc:
        info["erro"] = str(exc)
    return info


def _site_vivo(pasta: str) -> dict:
    if not os.path.isdir(pasta):
        return {"datas": []}
    datas = sorted(d for d in os.listdir(pasta) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d))
    if not datas:
        return {"datas": []}
    dia = os.path.join(pasta, datas[-1])
    coleta = saidas.ler_json(os.path.join(dia, "coleta.json"), {})
    registros = saidas.ler_jsonl(os.path.join(dia, "crawl.jsonl"))
    origens = {}
    for r in registros:
        origens[r.get("origem")] = origens.get(r.get("origem"), 0) + 1
    return {
        "datas": datas,
        "ultima": datas[-1],
        "coleta": coleta,
        "n": len(registros),
        "status": saidas.contagem_status(registros),
        "origens": origens,
    }


def gerar(pasta_dossie: str, ficha: dict, *, agora: str) -> str:
    """Escreve LEIA.md e devolve o caminho."""
    dominio = ficha["site"]["dominio"]
    ui, outros_ui = checklist_ui(os.path.join(pasta_dossie, "gsc_ui"))
    acervo = _acervo(os.path.join(pasta_dossie, "acervo"))
    vivo = _site_vivo(os.path.join(pasta_dossie, "site_vivo"))
    proj = saidas.ler_json(os.path.join(pasta_dossie, "projeto", "coleta.json"), {})
    comum = os.path.join(
        os.path.dirname(pasta_dossie.rstrip("/\\")), "_comum", "google_updates.csv"
    )
    n_updates = 0
    if os.path.exists(comum):
        with open(comum, encoding="utf-8-sig") as fh:
            n_updates = max(sum(1 for linha in fh if linha.strip()) - 1, 0)

    L = []
    L.append(f"# LEIA.md — dossiê de `{dominio}`\n")
    L.append(
        "Este dossiê é **extração**, não análise: contagens, datas e rótulos de "
        "proveniência. O veredito é a etapa seguinte, numa sessão de análise.\n"
    )
    L.append(f"_Gerado por `dossie.py` em {agora}. Regenerado a cada comando; não edite à mão._\n")

    L.append("## 1. Fontes e datas\n")
    L.append("| Fonte | Estado | De quando |")
    L.append("|---|---|---|")
    if acervo["existe"]:
        tipos = ", ".join(f"`{t}` {a}→{b}" for t, a, b, *_ in acervo.get("tipos", []))
        L.append(
            f"| Acervo GSC (`acervo/`) | {tipos or 'sem ingestão'}; "
            f"{acervo.get('eventos', 0)} evento(s) anotado(s) | "
            f"cópia de {acervo['copia'].get('copiado_em', '?')} |"
        )
    else:
        L.append(
            "| Acervo GSC (`acervo/`) | **ausente** — rode `acervo.py pacote` e "
            "`dossie.py fechar` | — |"
        )
    n_ui = sum(1 for i in ui if i["arquivos"])
    datas_ui = sorted(
        {_data_arquivo(os.path.join(pasta_dossie, "gsc_ui", a)) for i in ui for a in i["arquivos"]}
    )
    L.append(
        f"| UI do GSC (`gsc_ui/`) | {n_ui} de {len(ui)} itens | {', '.join(datas_ui) or '—'} |"
    )
    if vivo["datas"]:
        st = vivo["status"]
        resumo = ", ".join(f"{k} {v}" for k, v in sorted(st.items()))
        L.append(
            f"| Site ao vivo (`site_vivo/{vivo['ultima']}/`) | "
            f"{vivo['n']} URLs fotografadas ({resumo}) | {vivo['ultima']} |"
        )
    else:
        L.append("| Site ao vivo (`site_vivo/`) | **ausente** — rode `dossie.py site` | — |")
    if proj:
        git = "com git" if proj.get("git") else "**sem git** (datas = sistema de arquivos)"
        L.append(
            f"| Projeto original (`projeto/`) | {proj.get('n_arquivos', 0)} arquivos, {git}; "
            f"{proj.get('n_candidatos', 0)} evento(s) candidato(s); "
            f"{proj.get('n_redirects', 0)} redirect(s) declarados | "
            f"{proj.get('coletado_em', '?')} |"
        )
    else:
        L.append("| Projeto original (`projeto/`) | **ausente** — rode `dossie.py projeto` | — |")
    L.append(f"| Updates do Google (`../_comum/google_updates.csv`) | {n_updates} linha(s) | — |")
    L.append("")

    if acervo["existe"] and vivo["datas"]:
        ultimo = max((b for _, _, b, *_ in acervo.get("tipos", [])), default="?")
        L.append(
            f"**Defasagem:** o acervo termina em {ultimo} (dia da Califórnia); a foto do site é de "
            f"{vivo['ultima']}. A foto mostra o site **de hoje**, "
            "não o de quando o tráfego mudou.\n"
        )

    L.append("## 2. UI do GSC — o que já está e o que falta\n")
    L.append(
        "Largue os exports em `gsc_ui/` com nome `AAAA-MM-DD_<chave>.<ext>` "
        "(ex.: `2026-10-18_indexacao-paginas.zip`).\n"
    )
    L.append("| Item | Chave | Situação | Como exportar |")
    L.append("|---|---|---|---|")
    for i in ui:
        sit = (
            ", ".join(f"`{a}`" for a in i["arquivos"])
            if i["arquivos"]
            else ("**falta**" if i["essencial"] else "falta (opcional)")
        )
        L.append(f"| {i['rotulo']} | `{i['chave']}` | {sit} | {i['como']} |")
    if outros_ui:
        L.append(
            "\nArquivos em `gsc_ui/` sem item reconhecido: "
            + ", ".join(f"`{a}`" for a in outros_ui)
            + "."
        )
    L.append("")

    if vivo["datas"]:
        c = vivo["coleta"]
        L.append(f"## 3. Site ao vivo — {vivo['ultima']}\n")
        L.append(
            f"- Alvos: {c.get('n_alvos', '?')} (origem: "
            + ", ".join(
                f"{k} {v}" for k, v in sorted(vivo["origens"].items(), key=lambda kv: str(kv[0]))
            )
            + ")."
        )
        fora = c.get("fora") or {}
        if fora:
            L.append(
                f"- Fora do crawl: {fora.get('nao_pagina', 0)} não-página (imagem/binário), "
                f"{fora.get('fragmento_fundido', 0)} URL(s) com `#` fundidas na URL base, "
                f"{fora.get('cortadas_pelo_maximo', 0)} cortada(s) pelo `max_urls`."
            )
        if not c.get("completo", True):
            L.append(
                "- **Crawl incompleto** — rode `dossie.py site` de novo no mesmo dia para retomar."
            )
        L.append(
            "- Arquivos: `crawl.jsonl` (completo), `resumo.csv` (uma linha por URL), "
            "`links_internos.csv` (arestas), `sitemaps/`, `robots.txt`, `html/` (gzip)."
        )
        L.append(
            "- `canonical_para_outra` compara o canonical com a URL final **exatamente** "
            "(protocolo, www e barra final contam).\n"
        )

    if proj:
        L.append("## 4. Projeto original\n")
        L.append(f"- Pasta lida: `{proj.get('pasta', '?')}`.")
        if not proj.get("git"):
            L.append(
                "- **Sem histórico git.** As datas são do sistema de arquivos (cópia, checkout e "
                "deploy mudam essas datas). Use-as só como pista."
            )
        L.append(
            "- `inventario.csv`: arquivos com datas e o casamento arquivo→URL (`unico`, `ambiguo`, "
            "`sem_par`). O casamento é pelo **nome do arquivo**; "
            "não prova que o arquivo é a página."
        )
        L.append(
            "- `eventos_candidatos.csv` e `eventos/*.txt`: dias com muitos arquivos de página "
            "adicionados, editados ou removidos, e commits em configuração. São **candidatos**: "
            "confirme e anote com o comando abaixo."
        )
        L.append(
            "- `redirects.csv`: regras declaradas no projeto, "
            "com a data em que a linha entrou (git blame).\n"
        )
        L.append("```")
        L.append(f"py acervo.py anotar --site {dominio} --data AAAA-MM-DD --tipo conteudo-novo \\")
        L.append(
            '    --desc "o que foi feito" '
            "--urls-de <dossie>/projeto/eventos/AAAA-MM-DD_conteudo-novo.txt"
        )
        L.append("```\n")

    L.append("## 5. O que NÃO está aqui\n")
    L.append(
        "- GA4, conversões e receita; log de servidor (o `logs.py` existe, mas não roda no dossiê)."
    )
    L.append(
        "- Core Web Vitals por URL (CrUX/PageSpeed). Só o relatório agregado da UI, se exportado."
    )
    L.append(
        "- O site como era no passado. A foto é de hoje; versões antigas, só via Wayback Machine."
    )
    L.append("- Qualquer veredito. Nenhum arquivo deste dossiê pontua, classifica ou sugere causa.")
    L.append("")

    caminho = os.path.join(pasta_dossie, "LEIA.md")
    with open(caminho, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    return caminho


def _data_arquivo(caminho: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", os.path.basename(caminho))
    if m:
        return m.group(1)
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(os.path.getmtime(caminho), tz=timezone.utc).date().isoformat()
    except OSError:
        return "?"
