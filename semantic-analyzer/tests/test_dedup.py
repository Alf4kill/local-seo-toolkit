"""test_dedup.py — Dedup de keyword entre grupos (puro, sem deps de ML/servidor)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.dedup import find_keyword_collisions, normalize_kw


def _diffed(groups):
    """groups: lista de (impressões_do_grupo, [(slug, keyword_alvo), ...])."""
    return [
        {"group_impressions": impr,
         "diff": {"paginas": [{"slug": s, "keyword_alvo": k} for s, k in pages]}}
        for impr, pages in groups
    ]


class TestDedup(unittest.TestCase):

    def test_normalize_kw(self):
        self.assertEqual(normalize_kw("Preço do Cão!"), "preco do cao")
        self.assertEqual(normalize_kw("  Cane   Corso  "), "cane corso")

    def test_colisao_exata_cross_cluster(self):
        diffed = _diffed([
            (1000, [("a", "cane corso preço"), ("b", "valor do cane corso")]),
            (500,  [("c", "Cane Corso Preço"), ("d", "custo mensal cane corso")]),
        ])
        cols = find_keyword_collisions(diffed)
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0]["kind"], "exata")
        self.assertTrue(cols[0]["cross"])
        self.assertEqual(cols[0]["n"], 2)
        # dono = maior tráfego (grupo de 1000 impressões → slug "a")
        self.assertEqual(cols[0]["owner"]["slug"], "a")

    def test_sem_colisao_quando_distintas(self):
        diffed = _diffed([
            (1000, [("a", "preço cane corso"), ("b", "custo mensal cane corso")]),
            (500,  [("c", "filhote rottweiler preço"), ("d", "adestramento rottweiler")]),
        ])
        self.assertEqual(find_keyword_collisions(diffed), [])

    def test_colisao_parecida_por_subconjunto(self):
        diffed = _diffed([
            (1000, [("a", "cane corso preço")]),
            (500,  [("c", "cane corso preço filhote")]),
        ])
        cols = find_keyword_collisions(diffed)
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0]["kind"], "parecida")
        self.assertEqual(cols[0]["owner"]["slug"], "a")   # maior tráfego mantém

    def test_keyword_de_um_token_nao_gera_falsa_colisao(self):
        # "rottweiler" (1 token de conteúdo) NÃO deve casar com "rottweiler preço".
        diffed = _diffed([
            (1000, [("a", "rottweiler")]),
            (500,  [("c", "rottweiler preço")]),
        ])
        self.assertEqual(find_keyword_collisions(diffed), [])

    def test_ordena_por_impressoes(self):
        diffed = _diffed([
            (100, [("a", "kw comum aqui"), ("b", "kw comum aqui")]),         # intra, 100
            (900, [("c", "outra kw repetida"), ("d", "outra kw repetida")]), # intra, 900
        ])
        cols = find_keyword_collisions(diffed)
        self.assertEqual(len(cols), 2)
        self.assertGreaterEqual(cols[0]["impr_total"], cols[1]["impr_total"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
