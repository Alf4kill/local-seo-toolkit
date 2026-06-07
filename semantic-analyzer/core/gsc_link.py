"""
gsc_link.py — Cruza os clusters semânticos com os dados de posição do gsc-monitor.

Acoplamento FROUXO: lê o arquivo {data}_posicao.json gerado pelo gsc-monitor
(NÃO importa nenhum módulo dele). Para cada grupo de duplicatas, escolhe a
página "canônica" pela PERFORMANCE REAL (cliques → impressões → posição), em vez
de só pela centralidade no embedding — a decisão de consolidação fica orientada a
dados.
"""

import json
import os
import re
import unicodedata


def _slug_from_url(url: str) -> str:
    """Extrai o slug (último segmento) de uma URL e normaliza p/ casar com os clusters."""
    path = re.sub(r"^https?://[^/]+", "", url or "").strip("/")
    seg = path.split("/")[-1] if path else "index"
    return unicodedata.normalize("NFKD", seg).encode("ascii", "ignore").decode().lower()


def load_gsc_positions(path: str):
    """
    Carrega {slug: métricas} a partir de um *_posicao.json do gsc-monitor.
    `path` pode ser o arquivo OU um diretório (usa o *_posicao.json mais recente).
    Retorna (dados, nome_do_arquivo).
    """
    if os.path.isdir(path):
        # Apenas o relatório datado YYYY-MM-DD_posicao.json (evita historico_posicao.json)
        files = sorted([f for f in os.listdir(path)
                        if re.match(r"\d{4}-\d{2}-\d{2}_posicao\.json$", f)], reverse=True)
        if not files:
            raise FileNotFoundError(f"Nenhum YYYY-MM-DD_posicao.json encontrado em {path}")
        path = os.path.join(path, files[0])

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    out = {}
    for r in data.get("urls", []):
        out[_slug_from_url(r.get("url", ""))] = {
            "url":         r.get("url"),
            "clicks":      r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "position":    r.get("position"),
            "ctr":         r.get("ctr", 0.0),
            "has_data":    r.get("has_data", False),
        }
    return out, os.path.basename(path)


def _perf_key(m: dict):
    """Ordena 'melhor primeiro': mais cliques, mais impressões, melhor posição."""
    pos = m["position"] if m.get("position") is not None else 9999
    return (-m.get("clicks", 0), -m.get("impressions", 0), pos)


_EMPTY = {"url": None, "clicks": 0, "impressions": 0, "position": None, "ctr": 0.0, "has_data": False}


def enrich_clusters(clusters: list, gsc: dict) -> list:
    """
    Anexa métricas GSC a cada membro e escolhe a canônica por performance.
    Adiciona a cada cluster: members_gsc, canonical_by_performance,
    group_clicks, group_impressions, canonical_differs.
    """
    for c in clusters:
        members = [{"slug": s, **(gsc.get(s) or _EMPTY)} for s in c["members"]]
        members.sort(key=_perf_key)
        c["members_gsc"]              = members
        c["canonical_by_performance"] = members[0]["slug"]
        c["group_clicks"]             = sum(m["clicks"] for m in members)
        c["group_impressions"]        = sum(m["impressions"] for m in members)
        c["canonical_differs"]        = c["canonical_by_performance"] != c["representative"]
    return clusters
