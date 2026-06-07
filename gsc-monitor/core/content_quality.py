"""
content_quality.py — Diagnóstico de qualidade de conteúdo para SEO.

Objetivo: detectar artigos "keyword-heavy"/over-optimization e conteúdo raso
("lack of content") — os padrões que os core updates recentes do Google tendem
a penalizar — e mostrar como o conteúdo se distribui semanticamente.

⚠ IMPORTANTE — isto é uma HEURÍSTICA, não o algoritmo de ranking do Google.
Os sinais aqui são proxies correlacionados com o que o "helpful content system"
valoriza, úteis para PRIORIZAR revisões editoriais e MEDIR o efeito ao longo do
tempo (via histórico de posição). Nunca trate o veredito como certeza de
punição ou de ranqueamento. A Cloud Natural Language API ≠ algoritmo de busca.

Sinais LOCAIS (sem cota de API — calculados só a partir do texto):
  - word_count        : tamanho do texto editorial
  - keyword_density   : % de ocorrências da keyword-alvo no texto
  - exact_repetitions : nº de repetições exatas da keyword-alvo principal
  - vocab_diversity   : razão tipo/token (vocabulário variado vs. repetitivo)

Sinais do NLP do Google (OPCIONAIS — só se nlp_result for fornecido):
  - entity_count           : nº de entidades distintas (amplitude temática)
  - salience_concentration : saliência da entidade dominante / soma do topo
  - target_in_salient      : a keyword-alvo está entre as entidades salientes?
  - classified             : o classifyText conseguiu categorizar (texto suficiente)?

A keyword-alvo de cada URL vem das próprias queries do GSC (o que a página
realmente ranqueia) — ver target_keywords_for_url().
"""

import re

# ---------------------------------------------------------------------------
# Limiares (ajustáveis — centralizados para facilitar calibração futura)
# ---------------------------------------------------------------------------
MIN_WORDS = 300  # abaixo disso = conteúdo provavelmente raso
THIN_HARD_WORDS = 180  # abaixo disso = raso quase certo (MIN_WORDS × 0.6)
KW_DENSITY_HIGH = 3.0  # % de densidade acima disso = sinal de stuffing
KW_DENSITY_VERY_HIGH = 5.0  # % claramente excessivo
EXACT_REPEAT_HIGH = 8  # repetições exatas da head keyword
VOCAB_DIVERSITY_LOW = 0.35  # type/token abaixo disso = texto repetitivo
SALIENCE_CONC_HIGH = 0.55  # 1 entidade concentra > metade da saliência do topo
MIN_ENTITIES_BREADTH = 4  # menos entidades distintas que isso = amplitude pobre


# Rótulos legíveis por flag
_FLAG_REASONS = {
    "conteudo_curto": "Texto curto para um artigo (pouca profundidade).",
    "densidade_alta": "Densidade da keyword-alvo elevada (sinal de over-optimization).",
    "densidade_muito_alta": "Densidade da keyword-alvo excessiva (keyword stuffing provável).",
    "repeticao_exata_alta": "Keyword-alvo repetida de forma exata muitas vezes.",
    "vocabulario_repetitivo": "Vocabulário pouco variado (texto repetitivo).",
    "saliencia_concentrada": "Uma única entidade concentra a relevância — artigo gira só em torno do termo.",
    "amplitude_pobre": "Poucas entidades distintas — cobertura temática rasa.",
    "nao_classificavel": "Google não conseguiu categorizar o conteúdo (informação insuficiente).",
    "keyword_nao_saliente": "A keyword-alvo NÃO aparece entre as entidades salientes (diluição de tema).",
}

# Flags que indicam over-optimization vs. conteúdo raso
_OVER_FLAGS = frozenset(
    {
        "densidade_alta",
        "densidade_muito_alta",
        "repeticao_exata_alta",
        "vocabulario_repetitivo",
        "saliencia_concentrada",
        "keyword_nao_saliente",
    }
)
_THIN_FLAGS = frozenset(
    {
        "conteudo_curto",
        "amplitude_pobre",
        "nao_classificavel",
    }
)

_VERDICT_LABELS = {
    "ok": "✓ Conteúdo equilibrado",
    "atencao": "⚠ Pontos de atenção",
    "over_otimizado": "⚠ Possível over-optimization",
    "raso": "⚠ Conteúdo raso",
}


# ---------------------------------------------------------------------------
# Tokenização e contagens (locais)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list:
    """Lista de palavras em minúsculas (suporta acentuação portuguesa via \\w unicode)."""
    return re.findall(r"\w+", text.lower())


def _count_phrase(text_low: str, phrase: str) -> int:
    """Conta ocorrências da phrase (case-insensitive) respeitando limites de palavra."""
    p = phrase.lower().strip()
    if not p:
        return 0
    return len(re.findall(r"\b" + re.escape(p) + r"\b", text_low))


def keyword_density(text: str, keyword: str) -> tuple:
    """
    Densidade da keyword no texto, em %.
    Para keywords multi-palavra usa (ocorrências × nº de palavras da keyword) / total.
    Retorna (densidade_%, ocorrências).
    """
    tokens = _tokenize(text)
    total = len(tokens)
    if total == 0:
        return 0.0, 0
    occ = _count_phrase(text.lower(), keyword)
    kw_size = max(1, len(keyword.split()))
    density = (occ * kw_size) / total * 100.0
    return round(density, 2), occ


def vocab_diversity(text: str) -> float:
    """Razão tipo/token: palavras únicas / total. 1.0 = nada se repete; baixo = repetitivo."""
    tokens = _tokenize(text)
    if not tokens:
        return 0.0
    return round(len(set(tokens)) / len(tokens), 3)


# ---------------------------------------------------------------------------
# Sinais derivados do resultado NLP do Google (opcionais)
# ---------------------------------------------------------------------------


def salience_concentration(nlp_result: dict) -> "float | None":
    """Saliência da entidade dominante / soma das saliências. None se sem entidades."""
    ents = (nlp_result or {}).get("entities", []) or []
    total = sum(e.get("salience", 0.0) for e in ents)
    if not ents or total <= 0:
        return None
    return round(max(e.get("salience", 0.0) for e in ents) / total, 3)


def _target_in_salient(nlp_result: dict, keywords: list, top_n: int = 5) -> "bool | None":
    """A keyword-alvo aparece entre as top_n entidades salientes? None se sem entidades."""
    ents = (nlp_result or {}).get("entities", []) or []
    if not ents:
        return None
    names = [e.get("name", "").lower() for e in ents[:top_n]]
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        if any(k in n or n in k for n in names if n):
            return True
    return False


# ---------------------------------------------------------------------------
# Keywords-alvo a partir das queries reais do GSC
# ---------------------------------------------------------------------------


def target_keywords_for_url(
    query_rows: list,
    url: str,
    max_kw: int = 3,
    min_impressions: int = 1,
) -> list:
    """
    Top queries (por impressões) que a URL realmente ranqueia no GSC — ou seja,
    as keywords-alvo de fato da página. Deduplica e limita a max_kw.
    """
    if not query_rows:
        return []
    candidates = [
        (r["query"], r.get("impressions", 0))
        for r in query_rows
        if r.get("url") == url and r.get("impressions", 0) >= min_impressions
    ]
    candidates.sort(key=lambda x: -x[1])
    out, seen = [], set()
    for q, _ in candidates:
        if q not in seen:
            seen.add(q)
            out.append(q)
        if len(out) >= max_kw:
            break
    return out


# ---------------------------------------------------------------------------
# Análise principal (pura — sem rede, sem I/O)
# ---------------------------------------------------------------------------


def analyze_content_quality(
    text: str,
    target_keywords: "list | None" = None,
    nlp_result: "dict | None" = None,
) -> dict:
    """
    Diagnostica a qualidade de conteúdo de um texto à luz de SEO.

    text            — texto editorial já extraído da página.
    target_keywords — keywords-alvo da página (ex.: de target_keywords_for_url).
                      A 1ª é tratada como a head keyword.
    nlp_result      — opcional: {"entities": [...], "categories": [...]} do
                      nlp_analyzer. Habilita os sinais semânticos do Google.

    Retorna um dict com métricas, flags, verdict e reasons (ver docstring do módulo).
    """
    target_keywords = [k for k in (target_keywords or []) if k and k.strip()]
    head_kw = target_keywords[0] if target_keywords else None

    tokens = _tokenize(text)
    word_count = len(tokens)
    diversity = vocab_diversity(text)

    # Densidade: pega a maior entre as keywords-alvo
    densest_kw, max_density, occ_at_max = None, 0.0, 0
    for kw in target_keywords:
        d, occ = keyword_density(text, kw)
        if d > max_density:
            densest_kw, max_density, occ_at_max = kw, d, occ

    exact_reps = _count_phrase(text.lower(), head_kw) if head_kw else 0

    # ── Sinais NLP (se disponíveis) ─────────────────────────────────────────
    has_nlp = nlp_result is not None
    entities = (nlp_result or {}).get("entities", []) or []
    categories = (nlp_result or {}).get("categories", []) or []
    entity_cnt = (
        len({e.get("name", "").lower() for e in entities if e.get("name")}) if has_nlp else None
    )
    sal_conc = salience_concentration(nlp_result) if has_nlp else None
    in_salient = (
        _target_in_salient(nlp_result, target_keywords) if (has_nlp and target_keywords) else None
    )
    classified = bool(categories) if has_nlp else None

    # ── Flags ───────────────────────────────────────────────────────────────
    flags = []
    if word_count < MIN_WORDS:
        flags.append("conteudo_curto")
    if max_density >= KW_DENSITY_VERY_HIGH:
        flags.append("densidade_muito_alta")
    elif max_density >= KW_DENSITY_HIGH:
        flags.append("densidade_alta")
    if exact_reps >= EXACT_REPEAT_HIGH:
        flags.append("repeticao_exata_alta")
    if word_count > 0 and diversity < VOCAB_DIVERSITY_LOW:
        flags.append("vocabulario_repetitivo")
    if has_nlp:
        if sal_conc is not None and sal_conc >= SALIENCE_CONC_HIGH:
            flags.append("saliencia_concentrada")
        if entity_cnt is not None and entity_cnt < MIN_ENTITIES_BREADTH and entities:
            flags.append("amplitude_pobre")
        if classified is False:
            flags.append("nao_classificavel")
        if in_salient is False:
            flags.append("keyword_nao_saliente")

    over_score = sum(1 for f in flags if f in _OVER_FLAGS)
    thin_score = sum(1 for f in flags if f in _THIN_FLAGS)

    # ── Veredito ────────────────────────────────────────────────────────────
    if word_count < THIN_HARD_WORDS or thin_score >= 2:
        verdict = "raso"
    elif over_score >= 2:
        verdict = "over_otimizado"
    elif over_score >= 1 or thin_score >= 1:
        verdict = "atencao"
    else:
        verdict = "ok"

    reasons = [_FLAG_REASONS[f] for f in flags if f in _FLAG_REASONS]

    return {
        "word_count": word_count,
        "keyword_density": max_density,
        "densest_keyword": densest_kw,
        "keyword_occurrences": occ_at_max,
        "exact_repetitions": exact_reps,
        "vocab_diversity": diversity,
        "entity_count": entity_cnt,
        "salience_concentration": sal_conc,
        "target_in_salient": in_salient,
        "classified": classified,
        "flags": flags,
        "verdict": verdict,
        "verdict_label": _VERDICT_LABELS[verdict],
        "reasons": reasons,
    }


def print_content_quality(url: str, cq: dict) -> None:
    """Exibe o diagnóstico de qualidade de conteúdo de uma URL no terminal."""
    short = url if len(url) <= 60 else url[:57] + "..."
    print(f"\n  {short}")
    print(f"    {cq['verdict_label']}")
    dens_kw = f" ('{cq['densest_keyword']}')" if cq["densest_keyword"] else ""
    print(
        f"    palavras: {cq['word_count']:>5}   "
        f"densidade: {cq['keyword_density']:.1f}%{dens_kw}   "
        f"diversidade: {cq['vocab_diversity']:.2f}"
    )
    if cq["entity_count"] is not None:
        sc = cq["salience_concentration"]
        sc_str = f"{sc:.2f}" if sc is not None else "s/d"
        print(
            f"    entidades: {cq['entity_count']:>3}   concentração: {sc_str}   "
            f"classificado: {'sim' if cq['classified'] else 'não'}"
        )
    for reason in cq["reasons"]:
        print(f"      • {reason}")


# ---------------------------------------------------------------------------
# Move 2 — Acompanhamento conteúdo × posição ao longo do tempo
# ---------------------------------------------------------------------------


def build_content_tracking(historico: dict) -> dict:
    """
    Cruza posição × qualidade de conteúdo nos snapshots do historico_posicao.

    Para cada URL com dados de conteúdo em ≥1 snapshot, compara o primeiro
    snapshot COM conteúdo (baseline) ao mais recente (atual): posição, veredito
    e densidade. É a base do "loop de medição" — permite ver, ao longo do tempo,
    se otimizar o conteúdo de uma página acompanhou melhora de posição.

    Retorna {"n_content_snapshots": int, "rows": [...]}, ordenado por pior
    veredito atual primeiro. position_delta > 0 = posição melhorou (caiu) desde
    o baseline; None quando há só 1 snapshot com conteúdo para a URL.
    """
    snaps = historico.get("snapshots", []) if historico else []

    per_url: dict = {}
    content_dates = set()
    for s in snaps:
        date = s.get("date")
        for url, v in s.get("urls", {}).items():
            cq = v.get("content")
            if not cq:
                continue
            content_dates.add(date)
            per_url.setdefault(url, []).append((date, v.get("position"), cq))

    order = {"raso": 0, "over_otimizado": 1, "atencao": 2, "ok": 3}
    rows = []
    for url, seq in per_url.items():
        seq.sort(key=lambda x: x[0])
        first_date, first_pos, first_cq = seq[0]
        last_date, last_pos, last_cq = seq[-1]
        delta = (
            round(first_pos - last_pos, 1)
            if (len(seq) >= 2 and first_pos is not None and last_pos is not None)
            else None
        )
        rows.append(
            {
                "url": url,
                "snapshots": len(seq),
                "first_date": first_date,
                "last_date": last_date,
                "first_position": first_pos,
                "last_position": last_pos,
                "position_delta": delta,
                "first_verdict": first_cq.get("verdict"),
                "last_verdict": last_cq.get("verdict"),
                "last_density": last_cq.get("density"),
                "last_words": last_cq.get("words"),
            }
        )

    rows.sort(
        key=lambda r: (
            order.get(r["last_verdict"], 9),
            -(abs(r["position_delta"]) if r["position_delta"] is not None else 0),
        )
    )
    return {"n_content_snapshots": len(content_dates), "rows": rows}


def print_content_tracking(tracking: dict) -> None:
    """Exibe o acompanhamento conteúdo × posição no terminal."""
    rows = tracking.get("rows", [])
    if not rows:
        return
    n = tracking.get("n_content_snapshots", 0)
    print(f"\n{'─' * 72}")
    print(
        f"  Acompanhamento Conteúdo × Posição  —  {len(rows)} URL(s), {n} snapshot(s) com conteúdo"
    )
    print(f"{'─' * 72}")
    if n < 2:
        print("  Baseline registrado. Otimize o conteúdo e rode de novo (outra data)")
        print("  para medir se a posição acompanha a melhora.")
    for r in rows:
        d = r["position_delta"]
        if d is None:
            delta = "baseline"
        elif d > 0:
            delta = f"melhorou +{d:.1f}"
        elif d < 0:
            delta = f"piorou {d:.1f}"
        else:
            delta = "estavel"
        pos = f"{r['last_position']:.1f}" if r["last_position"] is not None else "s/d"
        short = r["url"] if len(r["url"]) <= 50 else r["url"][:47] + "..."
        print(f"  [{r['last_verdict']:<14}] pos {pos:>5}  {delta:<16}  {short}")
    print(f"{'─' * 72}\n")
