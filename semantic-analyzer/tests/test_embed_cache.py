"""test_embed_cache.py — Testa o cache de embeddings (embed_texts mockado, sem ML)."""

import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.embedder as E


class TestEmbedCache(unittest.TestCase):

    def test_miss_depois_hit(self):
        labels, texts = ["a", "b"], ["texto a", "texto b"]
        fake_emb = np.array([[1.0, 0.0], [0.0, 1.0]])
        calls = {"n": 0}

        def fake(texts, **kw):
            calls["n"] += 1
            return fake_emb, "fake"

        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(E, "embed_texts", side_effect=fake):
                emb1, b1, hit1 = E.embed_texts_cached(labels, texts, backend="x", cache_dir=d)
                emb2, b2, hit2 = E.embed_texts_cached(labels, texts, backend="x", cache_dir=d)
            self.assertFalse(hit1)
            self.assertTrue(hit2)
            self.assertEqual(calls["n"], 1)                  # 2ª veio do cache
            np.testing.assert_array_equal(emb1, emb2)

    def test_conteudo_diferente_invalida(self):
        calls = {"n": 0}

        def fake(texts, **kw):
            calls["n"] += 1
            return np.zeros((1, 2)), "fake"

        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(E, "embed_texts", side_effect=fake):
                E.embed_texts_cached(["a"], ["texto original"], backend="x", cache_dir=d)
                E.embed_texts_cached(["a"], ["texto MUDADO"], backend="x", cache_dir=d)
            self.assertEqual(calls["n"], 2)                  # chave diferente → recalcula

    def test_no_cache(self):
        calls = {"n": 0}

        def fake(texts, **kw):
            calls["n"] += 1
            return np.zeros((1, 2)), "fake"

        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(E, "embed_texts", side_effect=fake):
                E.embed_texts_cached(["a"], ["t"], cache_dir=d, use_cache=False)
                E.embed_texts_cached(["a"], ["t"], cache_dir=d, use_cache=False)
            self.assertEqual(calls["n"], 2)                  # sem cache, sempre embeda


if __name__ == "__main__":
    unittest.main(verbosity=2)
