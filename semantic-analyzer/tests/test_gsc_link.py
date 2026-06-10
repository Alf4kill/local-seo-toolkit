"""test_gsc_link.py — Testa o cruzamento clusters × GSC (sem arquivos)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.gsc_link import _slug_from_url, enrich_clusters


class TestGscLink(unittest.TestCase):
    def test_slug_from_url(self):
        self.assertEqual(_slug_from_url("https://www.x.com/cane-corso-preco"), "cane-corso-preco")
        self.assertEqual(
            _slug_from_url("http://x.com/a/b/filhote-de-rottweiler/"), "filhote-de-rottweiler"
        )
        self.assertEqual(_slug_from_url("https://x.com/"), "index")

    def test_enrich_escolhe_melhor_performance(self):
        clusters = [
            {
                "size": 3,
                "cohesion": 0.9,
                "representative": "b",
                "members": ["a", "b", "c"],
                "indices": [0, 1, 2],
            }
        ]
        gsc = {
            "a": {
                "url": "u/a",
                "clicks": 2,
                "impressions": 100,
                "position": 8.0,
                "ctr": 1.0,
                "has_data": True,
            },
            "b": {
                "url": "u/b",
                "clicks": 0,
                "impressions": 50,
                "position": 5.0,
                "ctr": 0.0,
                "has_data": True,
            },
            "c": {
                "url": "u/c",
                "clicks": 20,
                "impressions": 300,
                "position": 6.0,
                "ctr": 2.0,
                "has_data": True,
            },
        }
        enrich_clusters(clusters, gsc)
        c = clusters[0]
        self.assertEqual(c["canonical_by_performance"], "c")  # mais cliques
        self.assertTrue(c["canonical_differs"])  # central era "b"
        self.assertEqual(c["group_clicks"], 22)
        self.assertEqual(c["group_impressions"], 450)

    def test_enrich_membro_sem_dados(self):
        clusters = [
            {
                "size": 2,
                "cohesion": 0.9,
                "representative": "a",
                "members": ["a", "z"],
                "indices": [0, 1],
            }
        ]
        gsc = {
            "a": {
                "url": "u/a",
                "clicks": 5,
                "impressions": 100,
                "position": 4.0,
                "ctr": 5.0,
                "has_data": True,
            }
        }
        enrich_clusters(clusters, gsc)  # "z" não existe no GSC → vira zeros
        c = clusters[0]
        self.assertEqual(c["canonical_by_performance"], "a")
        self.assertEqual(c["group_clicks"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
