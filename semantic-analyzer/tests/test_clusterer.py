"""
test_clusterer.py — Testa o núcleo de clustering com vetores sintéticos.
Só precisa de numpy (nenhum modelo de ML).
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.clusterer import (
    build_clusters,
    cluster_cohesion,
    cosine_similarity_matrix,
    nearest_pairs,
)


def _toy_embeddings():
    # 3 vetores ~ eixo X (grupo A), 2 ~ eixo Y (grupo B), 1 ~ eixo Z (isolado)
    emb = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.95, 0.05, 0.0],
            [0.90, 0.10, 0.0],  # A
            [0.0, 1.0, 0.0],
            [0.05, 0.95, 0.0],  # B
            [0.0, 0.0, 1.0],  # isolado
        ]
    )
    labels = ["a1", "a2", "a3", "b1", "b2", "c1"]
    return emb, labels


class TestClusterer(unittest.TestCase):
    def test_cosine_matrix_shape_and_diag(self):
        emb, _ = _toy_embeddings()
        sim = cosine_similarity_matrix(emb)
        self.assertEqual(sim.shape, (6, 6))
        # diagonal ~ 1.0 (auto-similaridade)
        for i in range(6):
            self.assertAlmostEqual(sim[i, i], 1.0, places=5)

    def test_two_clusters_and_singleton(self):
        emb, labels = _toy_embeddings()
        clusters, _ = build_clusters(emb, labels, threshold=0.8)
        sizes = sorted(c["size"] for c in clusters)
        self.assertEqual(sizes, [1, 2, 3])
        biggest = clusters[0]
        self.assertEqual(biggest["size"], 3)
        self.assertEqual(set(biggest["members"]), {"a1", "a2", "a3"})
        self.assertIn(biggest["representative"], {"a1", "a2", "a3"})

    def test_threshold_alto_separa_tudo(self):
        emb, labels = _toy_embeddings()
        clusters, _ = build_clusters(emb, labels, threshold=0.999)
        # com limiar quase 1, só vetores quase idênticos agrupam → maioria isolada
        self.assertGreaterEqual(len(clusters), 4)

    def test_threshold_baixo_une_tudo(self):
        emb, labels = _toy_embeddings()
        # limiar negativo: tudo conecta com tudo → 1 cluster só
        clusters, _ = build_clusters(emb, labels, threshold=-1.0)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["size"], 6)

    def test_cohesion_singleton_e_grupo(self):
        emb, labels = _toy_embeddings()
        sim = cosine_similarity_matrix(emb)
        self.assertEqual(cluster_cohesion([5], sim), 1.0)  # isolado
        coes_a = cluster_cohesion([0, 1, 2], sim)
        self.assertGreater(coes_a, 0.9)  # grupo A bem coeso

    def test_nearest_pairs(self):
        emb, labels = _toy_embeddings()
        sim = cosine_similarity_matrix(emb)
        pairs = nearest_pairs(sim, labels, top=3)
        self.assertEqual(len(pairs), 3)
        # o par mais similar deve ser dentro de A ou B (nunca envolvendo o isolado c1)
        top_pair = pairs[0]
        self.assertNotIn("c1", (top_pair[1], top_pair[2]))


class TestAgglomerative(unittest.TestCase):
    def test_agglomerative_matches_toy(self):
        try:
            import sklearn  # noqa: F401
        except ImportError:
            self.skipTest("sklearn não instalado")
        emb, labels = _toy_embeddings()
        clusters, _ = build_clusters(
            emb, labels, threshold=0.8, method="agglomerative", linkage="complete"
        )
        self.assertEqual(sorted(c["size"] for c in clusters), [1, 2, 3])
        biggest = clusters[0]
        self.assertEqual(set(biggest["members"]), {"a1", "a2", "a3"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
