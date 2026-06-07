"""
clusterer.py — Agrupa páginas por similaridade SEMÂNTICA a partir de embeddings.

Núcleo puro (só numpy): recebe os vetores já prontos, não depende de nenhum
modelo de ML. Usa similaridade do cosseno + agrupamento por LIMIAR (componentes
conexos): duas páginas com similaridade >= threshold ficam no mesmo grupo.

Objetivo SEO: detectar páginas near-duplicate / mesma intenção (doorway pages,
canibalização por conteúdo) e sugerir uma página "representante" (a mais central
do grupo) como candidata a canônica numa consolidação.
"""

import numpy as np


def normalize(embeddings) -> np.ndarray:
    """Normaliza cada vetor para norma 1 (cosseno vira produto escalar)."""
    emb = np.asarray(embeddings, dtype=float)
    if emb.ndim != 2:
        raise ValueError("embeddings deve ser uma matriz 2D (n_itens x n_dims)")
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return emb / norms


def cosine_similarity_matrix(embeddings) -> np.ndarray:
    """Matriz NxN de similaridade do cosseno (valores ~ -1..1)."""
    unit = normalize(embeddings)
    return unit @ unit.T


def cluster_by_threshold(sim: np.ndarray, threshold: float) -> list:
    """
    Agrupa por componentes conexos: existe aresta entre i e j se
    sim[i, j] >= threshold. Retorna lista de clusters (listas de índices).
    """
    n = sim.shape[0]
    visited = [False] * n
    clusters = []
    for start in range(n):
        if visited[start]:
            continue
        stack, comp = [start], []
        visited[start] = True
        while stack:
            node = stack.pop()
            comp.append(node)
            for nb in np.where(sim[node] >= threshold)[0]:
                nb = int(nb)
                if not visited[nb]:
                    visited[nb] = True
                    stack.append(nb)
        clusters.append(sorted(comp))
    return clusters


def _groups_from_assignments(assign) -> list:
    from collections import defaultdict
    g = defaultdict(list)
    for i, a in enumerate(assign):
        g[int(a)].append(i)
    return [sorted(v) for v in g.values()]


def cluster_agglomerative(embeddings, threshold: float, linkage: str = "complete") -> list:
    """
    Agrupamento aglomerativo (sklearn) por distância do cosseno.

    linkage="complete" exige que TODAS as páginas de um grupo sejam mutuamente
    similares (>= threshold) — evita o "encadeamento" do single-linkage, ideal
    para detectar grupos de near-duplicates em conteúdo homogêneo.
    """
    from sklearn.cluster import AgglomerativeClustering
    emb = normalize(embeddings)
    model = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage=linkage,
        distance_threshold=1.0 - threshold,
    )
    return _groups_from_assignments(model.fit_predict(emb))


def cluster_cohesion(indices: list, sim: np.ndarray) -> float:
    """Similaridade média intra-cluster (0..1). Cluster de 1 elemento => 1.0."""
    if len(indices) < 2:
        return 1.0
    sub = sim[np.ix_(indices, indices)]
    n = len(indices)
    total = sub.sum() - np.trace(sub)          # exclui a diagonal (auto-similaridade)
    return float(total / (n * (n - 1)))


def _representative(indices: list, labels: list, sim: np.ndarray):
    """Página mais central do grupo (maior soma de similaridade aos demais)."""
    if len(indices) == 1:
        return labels[indices[0]]
    sub = sim[np.ix_(indices, indices)]
    scores = sub.sum(axis=1)
    return labels[indices[int(np.argmax(scores))]]


def build_clusters(embeddings, labels: list, threshold: float = 0.85,
                   method: str = "threshold", linkage: str = "complete"):
    """
    Pipeline completo: embeddings + labels -> clusters ordenados por tamanho.

    method:
      "threshold"     — componentes conexos (single-linkage), só numpy. Tende a
                        encadear em conteúdo homogêneo; ok para dados separáveis.
      "agglomerative" — aglomerativo (sklearn) com linkage (default "complete");
                        grupos mais coesos, sem encadeamento. RECOMENDADO p/ sites.

    Retorna (clusters, sim). Cada cluster:
      {"size", "cohesion", "representative", "members", "indices"}.
    """
    if len(labels) != len(embeddings):
        raise ValueError("labels e embeddings devem ter o mesmo tamanho")
    sim = cosine_similarity_matrix(embeddings)
    if method == "agglomerative":
        groups = cluster_agglomerative(embeddings, threshold, linkage)
    else:
        groups = cluster_by_threshold(sim, threshold)
    result = []
    for g in groups:
        result.append({
            "size":           len(g),
            "cohesion":       round(cluster_cohesion(g, sim), 3),
            "representative": _representative(g, labels, sim),
            "members":        [labels[i] for i in g],
            "indices":        g,
        })
    result.sort(key=lambda c: (-c["size"], -c["cohesion"]))
    return result, sim


def nearest_pairs(sim: np.ndarray, labels: list, top: int = 15) -> list:
    """Top pares de páginas mais similares — inspeção direta de duplicatas."""
    n = sim.shape[0]
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append((round(float(sim[i, j]), 3), labels[i], labels[j]))
    pairs.sort(key=lambda p: -p[0])
    return pairs[:top]
