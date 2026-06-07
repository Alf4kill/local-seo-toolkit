"""
hybrid.py — Camada LLM do pipeline (estratégia HYBRID).

Embeddings/clustering acham OS GRUPOS de duplicatas (barato, local). O LLM julga
SÓ os grupos sinalizados — caro por página, mas roda em poucos grupos.

O prompt é "ancorado" para um modelo pequeno/local dar respostas úteis:
  - rubrica clara de veredito (spun / raso / ok) no system;
  - 2 exemplos (few-shot): um de FUNDIR (spun) e um de NÃO fundir (ok), p/ calibrar
    os dois desfechos — sem o exemplo "ok" o modelo tende a chamar tudo de "spun";
  - sinais REAIS do GSC por página (posição, cliques, impressões) quando houver;
  - contexto opcional do nicho do site;
  - corte de páginas em grupos enormes (manda as N de maior desempenho).
"""

from core.llm import parse_json_block

SYSTEM = (
    "Você é um especialista sênior em SEO de conteúdo. Um agrupador AUTOMÁTICO marcou as "
    "páginas abaixo como SIMILARES — mas isso pode ser FALSO-POSITIVO. Seu trabalho é decidir, "
    "LENDO O CONTEÚDO de cada uma, se elas são REALMENTE redundantes (mesma intenção, texto "
    "intercambiável) ou se apenas parecem parecidas e na verdade atendem intenções DISTINTAS. "
    "Seja cético: NÃO presuma que são duplicatas só porque foram agrupadas.\n\n"
    "Critérios de veredito:\n"
    "- spun: as páginas dizem essencialmente a mesma coisa reescrita; conteúdo intercambiável, "
    "sem valor distinto entre elas.\n"
    "- raso: conteúdo genérico e pobre — sem especificidade, dados, preços, exemplos ou "
    "experiência real; não satisfaz bem a intenção de busca.\n"
    "- ok: as páginas cobrem ângulos/intenções realmente distintos e úteis (NÃO fundir).\n\n"
    "ATENÇÃO: páginas do MESMO tema podem ter intenções DIFERENTES (ex.: comparações com "
    "concorrentes distintos, públicos distintos, fases distintas) — nesses casos o veredito é "
    "'ok' e NÃO se funde. Não marque 'spun' só porque o assunto é parecido; exija que o "
    "conteúdo seja realmente intercambiável.\n\n"
    "Para 'base_recomendada' escolha o slug da página com melhor desempenho real no GSC "
    "(mais cliques/impressões, melhor posição) que também tenha bom conteúdo.\n"
    "Quando o veredito for 'ok', deixe 'base_recomendada' como \"\" e 'lacunas' como [] "
    "(não há consolidação a fazer).\n"
    "Em 'lacunas' liste o que falta para virar UM artigo único, completo e útil — específico "
    "(seções, dados, tabela, FAQ, exemplos), nunca genérico.\n\n"
    "Responda APENAS um objeto JSON válido em português, sem nada fora do JSON."
)

_FEWSHOT = (
    "EXEMPLOS (apenas para ilustrar formato, nível de detalhe e os DOIS desfechos):\n\n"
    "EXEMPLO 1 — FUNDIR (spun):\n"
    "Entrada: 3 páginas — 'preço do produto X', 'valor do produto X', 'quanto custa o produto X' "
    "— textos quase idênticos, sem faixa de preço real, sem fatores que influenciam o custo, sem FAQ.\n"
    "Saída esperada:\n"
    '{"verdict":"spun","base_recomendada":"preco-do-produto-x",'
    '"lacunas":["faixa de preço real (de R$X a R$Y) e o que a faz variar",'
    '"tabela comparativa por tipo","FAQ com as dúvidas de compra mais comuns",'
    '"seção sobre custo de manutenção"],'
    '"resumo":"Três páginas reescritas para a mesma intenção de preço; fundir em uma só com dados concretos e FAQ."}\n\n'
    "EXEMPLO 2 — NÃO FUNDIR (ok):\n"
    "Entrada: 2 páginas — 'produto X vs concorrente A' e 'produto X vs concorrente B' — mesmo tema, "
    "mas cada uma responde a uma COMPARAÇÃO diferente, com prós/contras específicos de concorrentes distintos.\n"
    "Saída esperada:\n"
    '{"verdict":"ok","base_recomendada":"","lacunas":[],'
    '"resumo":"São comparações distintas (X vs A e X vs B); atendem intenções diferentes — manter separadas (ou criar um hub que linke as duas), não fundir."}\n'
)

_SCHEMA = (
    "{\n"
    '  "verdict": "spun" | "raso" | "ok",\n'
    '  "base_recomendada": "<slug da melhor página para ser a base da consolidação>",\n'
    '  "lacunas": ["o que falta para virar UM artigo completo e útil (específico)", "..."],\n'
    '  "resumo": "1-2 frases explicando o veredito"\n'
    "}"
)


def build_prompt(
    cluster: dict,
    pages: dict,
    max_chars: int = 1500,
    max_pages: int = 6,
    site_context: "str | None" = None,
) -> str:
    # Usa a ordem do GSC (já por desempenho) quando disponível; senão, os membros.
    members = cluster.get("members_gsc")
    if members:
        ordered = [m["slug"] for m in members]
        metrics = {m["slug"]: m for m in members}
    else:
        ordered = list(cluster["members"])
        metrics = {}

    shown = ordered[:max_pages]
    extra = len(ordered) - len(shown)

    parts = []
    if site_context:
        parts.append(f"Contexto do site: {site_context}")
    parts.append(
        f"{cluster['size']} página(s) que o agrupador marcou como SIMILARES "
        f"(pode haver falso-positivo — avalie pelo conteúdo).\n"
    )
    parts.append(_FEWSHOT)
    parts.append("=== PÁGINAS A AVALIAR ===")
    for i, slug in enumerate(shown, 1):
        m = metrics.get(slug)
        if m:
            pos = f"{m['position']:.1f}" if m.get("position") is not None else "s/d"
            gsc = f"  [GSC: posição {pos}, {m.get('clicks', 0)} cliques, {m.get('impressions', 0)} impressões]"
        else:
            gsc = ""
        txt = (pages.get(slug, "") or "")[:max_chars]
        parts.append(f"\n--- PÁGINA {i} (slug: {slug}){gsc} ---\n{txt}")
    if extra > 0:
        parts.append(
            f"\n(+{extra} página(s) quase idêntica(s) com sinais semelhantes, omitidas para encurtar.)"
        )
    parts.append("\nResponda com APENAS este JSON:\n" + _SCHEMA)
    return "\n".join(parts)


def judge_clusters(
    clusters: list,
    pages: dict,
    client,
    max_clusters: int = 8,
    min_size: int = 2,
    max_chars: int = 1500,
    max_pages: int = 6,
    site_context: "str | None" = None,
) -> list:
    """
    Julga os maiores grupos de duplicação com o LLM. Prioriza por impressões em
    disputa (se houver cruzamento GSC), senão por tamanho. Anexa c["llm"] a cada
    grupo julgado e retorna a lista dos julgados.
    """
    multi = [c for c in clusters if c["size"] >= min_size]
    multi.sort(key=lambda c: (-c.get("group_impressions", 0), -c["size"]))

    judged = []
    for c in multi[:max_clusters]:
        raw = client.chat(SYSTEM, build_prompt(c, pages, max_chars, max_pages, site_context))
        v = parse_json_block(raw)
        c["llm"] = {
            "verdict": v.get("verdict", "?"),
            "base_recomendada": v.get("base_recomendada", ""),
            "lacunas": v.get("lacunas", []) if isinstance(v.get("lacunas"), list) else [],
            "resumo": v.get("resumo", "") or (raw[:200] if not v else ""),
            "raw_ok": bool(v),
        }
        judged.append(c)
    return judged


# ---------------------------------------------------------------------------
# Modo DIFERENCIAÇÃO (contract-safe): em vez de fundir/301, dá a CADA página uma
# intenção/keyword distinta para parar a canibalização SEM apagar nenhum artigo.
# (O contrato do usuário paga por nº de artigos → 301 é perigoso.)
# ---------------------------------------------------------------------------

DIFF_SYSTEM = (
    "Você é um especialista sênior em SEO de conteúdo. Recebe um GRUPO de páginas de um MESMO "
    "site que hoje COMPETEM pela mesma intenção de busca (canibalização).\n\n"
    "RESTRIÇÃO CRÍTICA: NÃO é permitido apagar nem redirecionar (301) nenhuma página — todas "
    "devem continuar existindo e ranqueando (o cliente paga por NÚMERO de artigos). Portanto "
    "NÃO sugira fundir/consolidar. Seu trabalho é DIFERENCIAR.\n\n"
    "Como diferenciar:\n"
    "- Escolha UMA página como CABEÇA (hub) para o termo principal — de preferência a de melhor "
    "desempenho no GSC. As demais viram SPOKES, cada uma cobrindo um ÂNGULO/long-tail diferente.\n"
    "- Dê a cada página: uma intenção única, uma keyword-alvo única, um título (title tag) e um "
    "foco de conteúdo específico. NUNCA repita a mesma keyword-alvo em duas páginas.\n"
    "- Os ângulos têm de ser REAIS e úteis para o tema (ex.: visão geral de preço; o que define o "
    "valor; preço por fonte/criador; custo de manutenção mensal; com vs sem pedigree; como comprar "
    "com segurança). Não invente intenções que não façam sentido.\n"
    "- Se DUAS páginas forem realmente idênticas e não houver intenção distinta possível, marque "
    "papel='duplicado_real' — essas são candidatas a rel=canonical (NUNCA a 301).\n\n"
    "Responda APENAS um objeto JSON válido em português, sem nada fora do JSON."
)

_DIFF_FEWSHOT = (
    "EXEMPLO (formato e nível de detalhe esperados):\n"
    "Entrada: 3 páginas que competem por 'preço de cane corso' — 'cane-corso-preco' (melhor no "
    "GSC), 'filhote-de-cane-corso-valor', 'venda-de-cane-corso'.\n"
    "Saída esperada:\n"
    '{"cabeca":"cane-corso-preco","paginas":['
    '{"slug":"cane-corso-preco","papel":"cabeca","intencao":"quanto custa um cane corso (visão geral)",'
    '"keyword_alvo":"cane corso preço","titulo":"Quanto Custa um Cane Corso? Faixa de Preço de Filhote",'
    '"foco":"faixa de preço real + fatores que influenciam; linka para as páginas-spoke"},'
    '{"slug":"filhote-de-cane-corso-valor","papel":"spoke","intencao":"o que determina o VALOR de um filhote",'
    '"keyword_alvo":"o que define o valor do cane corso","titulo":"O Que Define o Valor de um Filhote de Cane Corso",'
    '"foco":"pedigree, linhagem, idade; tirar o termo genérico \'preço\' do H1"},'
    '{"slug":"venda-de-cane-corso","papel":"spoke","intencao":"como comprar com segurança",'
    '"keyword_alvo":"cane corso à venda","titulo":"Cane Corso à Venda: Como Comprar com Segurança",'
    '"foco":"processo de compra, contrato, garantias; CTA transacional"}]}\n'
)

_DIFF_SCHEMA = (
    "{\n"
    '  "cabeca": "<slug da página hub para o termo principal>",\n'
    '  "paginas": [\n'
    "    {\n"
    '      "slug": "<slug exatamente como dado>",\n'
    '      "papel": "cabeca" | "spoke" | "duplicado_real",\n'
    '      "intencao": "<a intenção de busca distinta que esta página passa a atender>",\n'
    '      "keyword_alvo": "<keyword única desta página>",\n'
    '      "titulo": "<title tag sugerido>",\n'
    '      "foco": "<o que mudar no conteúdo p/ atender a intenção e parar de competir>"\n'
    "    }\n"
    "  ]\n"
    "}"
)


def build_diff_prompt(
    cluster: dict,
    pages: dict,
    max_chars: int = 1200,
    max_pages: int = 6,
    site_context: "str | None" = None,
) -> str:
    members = cluster.get("members_gsc")
    if members:
        ordered = [m["slug"] for m in members]
        metrics = {m["slug"]: m for m in members}
    else:
        ordered = list(cluster["members"])
        metrics = {}

    shown = ordered[:max_pages]
    extra = ordered[max_pages:]

    parts = []
    if site_context:
        parts.append(f"Contexto do site: {site_context}")
    parts.append(
        f"{len(ordered)} página(s) que hoje COMPETEM pela mesma intenção (canibalização). "
        f"Diferencie-as — mantenha TODAS, sem apagar nem redirecionar.\n"
    )
    if shown:
        parts.append(f"Melhor desempenho no GSC (sugestão de CABEÇA): {shown[0]}\n")
    parts.append(_DIFF_FEWSHOT)
    parts.append("=== PÁGINAS A DIFERENCIAR ===")
    for i, slug in enumerate(shown, 1):
        m = metrics.get(slug)
        if m:
            pos = f"{m['position']:.1f}" if m.get("position") is not None else "s/d"
            gsc = f"  [GSC: posição {pos}, {m.get('clicks', 0)} cliques, {m.get('impressions', 0)} impressões]"
        else:
            gsc = ""
        txt = (pages.get(slug, "") or "")[:max_chars]
        parts.append(f"\n--- PÁGINA {i} (slug: {slug}){gsc} ---\n{txt}")
    if extra:
        parts.append(
            f"\n(+{len(extra)} página(s) quase idêntica(s) omitidas; se não houver intenção "
            f"distinta para elas, são candidatas a rel=canonical.)"
        )
    parts.append(
        "\nDê um plano para CADA página mostrada. Responda com APENAS este JSON:\n" + _DIFF_SCHEMA
    )
    return "\n".join(parts)


def differentiate_clusters(
    clusters: list,
    pages: dict,
    client,
    max_clusters: int = 8,
    min_size: int = 2,
    max_chars: int = 1200,
    max_pages: int = 6,
    site_context: "str | None" = None,
) -> list:
    """
    Para cada grupo de canibalização, pede ao LLM um plano de DIFERENCIAÇÃO: uma
    intenção/keyword/título distintos por página (mantém TODAS — sem 301). Prioriza
    por impressões em disputa. Anexa c["diff"] e retorna a lista dos grupos com plano.
    """
    multi = [c for c in clusters if c["size"] >= min_size]
    multi.sort(key=lambda c: (-c.get("group_impressions", 0), -c["size"]))

    out = []
    for c in multi[:max_clusters]:
        members = c.get("members_gsc")
        ordered = [m["slug"] for m in members] if members else list(c["members"])
        extra = ordered[max_pages:]

        # max_tokens generoso: o 14B é verboso e grupos de várias páginas geram
        # JSON longo — com 1200 o JSON truncava no meio (parse falhava). 2200 dá folga.
        raw = client.chat(
            DIFF_SYSTEM,
            build_diff_prompt(c, pages, max_chars, max_pages, site_context),
            max_tokens=2200,
        )
        v = parse_json_block(raw)
        paginas_raw = v.get("paginas") if isinstance(v.get("paginas"), list) else []
        paginas = []
        for p in paginas_raw:
            if not isinstance(p, dict):
                continue
            paginas.append(
                {
                    "slug": p.get("slug", ""),
                    "papel": p.get("papel", "spoke"),
                    "intencao": p.get("intencao", ""),
                    "keyword_alvo": p.get("keyword_alvo", ""),
                    "titulo": p.get("titulo", ""),
                    "foco": p.get("foco", ""),
                }
            )
        c["diff"] = {
            "cabeca": v.get("cabeca", "") or (ordered[0] if ordered else ""),
            "paginas": paginas,
            "omitidas": extra,
            "raw_ok": bool(paginas),
            "resumo": "" if paginas else (raw[:200] if not v else ""),
        }
        out.append(c)
    return out
