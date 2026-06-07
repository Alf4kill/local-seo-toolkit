"""
dedup.py — Dedup de keyword ENTRE grupos (cross-cluster).

A diferenciação (`hybrid.differentiate_clusters`) roda um grupo de cada vez, então
não enxerga os outros grupos. Resultado: dois grupos diferentes podem cair na MESMA
keyword-alvo (ou em uma quase idêntica) e voltar a canibalizar.

Este módulo é PURO (só stdlib) e testável: varre todas as keyword-alvo atribuídas
no plano de diferenciação e devolve as COLISÕES, indicando qual página fica com a
keyword (a de maior tráfego) e quais precisam de uma nova.
"""

import re
import unicodedata

# Stopwords PT comuns — ignoradas ao comparar o "miolo" das keywords.
_STOP = {
    "de",
    "do",
    "da",
    "dos",
    "das",
    "o",
    "a",
    "os",
    "as",
    "um",
    "uma",
    "uns",
    "umas",
    "e",
    "ou",
    "com",
    "sem",
    "para",
    "pra",
    "por",
    "no",
    "na",
    "nos",
    "nas",
    "em",
    "que",
    "se",
    "ao",
    "aos",
    "the",
}


def normalize_kw(s: str) -> str:
    """minúsculas + sem acento + só [a-z0-9 ] + espaços colapsados."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _content_tokens(norm: str) -> frozenset:
    return frozenset(t for t in norm.split() if t not in _STOP)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _near(ta: frozenset, tb: frozenset, thr: float) -> bool:
    """Quase-iguais: uma é subconjunto da outra, ou alta sobreposição (Jaccard)."""
    if min(len(ta), len(tb)) < 2:  # keywords de 1 token só colidem por igualdade exata
        return False
    if ta <= tb or tb <= ta:
        return True
    return _jaccard(ta, tb) >= thr


def _make_collision(group: list, kind: str) -> dict:
    members = sorted(group, key=lambda g: -g["impr"])
    owner = members[0]  # quem fica com a keyword = maior tráfego em disputa
    return {
        "kind": kind,  # "exata" | "parecida"
        "keyword": owner["keyword_alvo"],
        "owner": {"cluster": owner["cluster"], "slug": owner["slug"]},
        "members": [
            {
                "cluster": m["cluster"],
                "slug": m["slug"],
                "keyword_alvo": m["keyword_alvo"],
                "impr": m["impr"],
            }
            for m in members
        ],
        "impr_total": sum(m["impr"] for m in members),
        "n": len(members),
        "cross": len({m["cluster"] for m in group}) >= 2,
    }


def find_keyword_collisions(diffed: list, fuzzy_threshold: float = 0.7) -> list:
    """
    Recebe a lista de grupos com plano de diferenciação (cada um com
    c["diff"]["paginas"] e c["group_impressions"]) e devolve as colisões de
    keyword-alvo, ordenadas por impressões em disputa (maior primeiro).
    """
    items = []
    for ci, c in enumerate(diffed, 1):
        for p in (c.get("diff") or {}).get("paginas", []):
            kw = (p.get("keyword_alvo") or "").strip()
            norm = normalize_kw(kw)
            if not norm:
                continue
            items.append(
                {
                    "cluster": ci,
                    "slug": p.get("slug", ""),
                    "keyword_alvo": kw,
                    "norm": norm,
                    "tokens": _content_tokens(norm),
                    "impr": c.get("group_impressions", 0),
                }
            )

    collisions = []
    used = set()

    # 1) Colisões EXATAS (mesma keyword normalizada), em 2+ páginas distintas.
    by_norm = {}
    for idx, it in enumerate(items):
        by_norm.setdefault(it["norm"], []).append(idx)
    for idxs in by_norm.values():
        slugs = {items[i]["slug"] for i in idxs}
        if len(idxs) >= 2 and len(slugs) >= 2:
            collisions.append(_make_collision([items[i] for i in idxs], "exata"))
            used.update(idxs)

    # 2) Colisões PARECIDAS (subconjunto / alta sobreposição) entre o que sobrou.
    rest = [i for i in range(len(items)) if i not in used]
    for a in range(len(rest)):
        ia = rest[a]
        if ia in used:
            continue
        group = [ia]
        for ib in rest[a + 1 :]:
            if ib in used:
                continue
            if _near(items[ia]["tokens"], items[ib]["tokens"], fuzzy_threshold):
                group.append(ib)
                used.add(ib)
        if len(group) >= 2 and len({items[i]["slug"] for i in group}) >= 2:
            used.add(ia)
            collisions.append(_make_collision([items[i] for i in group], "parecida"))

    collisions.sort(key=lambda x: -x["impr_total"])
    return collisions
