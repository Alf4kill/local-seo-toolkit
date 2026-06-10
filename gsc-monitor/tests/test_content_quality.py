"""
test_content_quality.py — Testes do diagnóstico de qualidade de conteúdo (Move 1).

Cobre os sinais locais (densidade, repetição, diversidade, tamanho), os sinais
NLP opcionais (concentração de saliência, amplitude, classificável, keyword
saliente), a derivação do veredito e a extração de keywords-alvo do GSC.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.content_quality import (
    analyze_content_quality,
    dominant_ngram,
    keyword_density,
    salience_concentration,
    slug_phrase,
    target_keywords_for_url,
    vocab_diversity,
)

# ---------------------------------------------------------------------------
# Helpers para gerar textos sintéticos
# ---------------------------------------------------------------------------


def _balanced_text(n_words=400, keyword="aquecedor industrial", kw_times=4):
    """Texto longo, vocabulário variado, keyword em densidade natural."""
    words = [f"palavra{i}" for i in range(n_words)]
    for j in range(kw_times):
        words[j * (n_words // (kw_times + 1))] = keyword
    return " ".join(words)


def _stuffed_text(n_words=400, keyword="aquecedor industrial", kw_times=25):
    """Texto longo mas com a keyword repetida de forma exagerada."""
    words = [f"palavra{i % 30}" for i in range(n_words)]  # vocabulário pobre de propósito
    step = max(1, n_words // (kw_times + 1))
    for j in range(kw_times):
        words[j * step] = keyword
    return " ".join(words)


# ---------------------------------------------------------------------------
# Sinais locais isolados
# ---------------------------------------------------------------------------


class TestLocalSignals(unittest.TestCase):
    def test_density_multiword(self):
        text = "aquecedor industrial " + "outra palavra qualquer " * 48  # 2 + 144 = 146 tokens
        dens, occ = keyword_density(text, "aquecedor industrial")
        self.assertEqual(occ, 1)
        # 1 ocorrência × 2 palavras / 146 tokens ≈ 1.37%
        self.assertAlmostEqual(dens, round(2 / 146 * 100, 2), places=2)

    def test_density_texto_vazio(self):
        self.assertEqual(keyword_density("", "x"), (0.0, 0))

    def test_vocab_diversity(self):
        self.assertEqual(vocab_diversity("a b c d"), 1.0)
        self.assertLess(vocab_diversity("a a a a b"), 0.5)

    def test_salience_concentration(self):
        nlp = {"entities": [{"name": "x", "salience": 0.8}, {"name": "y", "salience": 0.2}]}
        self.assertAlmostEqual(salience_concentration(nlp), 0.8, places=2)
        self.assertIsNone(salience_concentration({"entities": []}))


# ---------------------------------------------------------------------------
# Veredito — sinais locais
# ---------------------------------------------------------------------------


class TestVerdictLocal(unittest.TestCase):
    def test_conteudo_raso(self):
        cq = analyze_content_quality("Texto muito curto sobre o tema.", ["tema"])
        self.assertEqual(cq["verdict"], "raso")
        self.assertIn("conteudo_curto", cq["flags"])

    def test_over_optimization(self):
        text = _stuffed_text(keyword="aquecedor industrial", kw_times=25)
        cq = analyze_content_quality(text, ["aquecedor industrial"])
        self.assertEqual(cq["verdict"], "over_otimizado")
        self.assertTrue(cq["keyword_density"] >= 5.0)
        self.assertIn("densidade_muito_alta", cq["flags"])
        self.assertGreaterEqual(cq["exact_repetitions"], 8)

    def test_conteudo_equilibrado(self):
        text = _balanced_text(keyword="aquecedor industrial", kw_times=4)
        cq = analyze_content_quality(text, ["aquecedor industrial"])
        self.assertEqual(cq["verdict"], "ok")
        self.assertEqual(cq["flags"], [])

    def test_sem_keyword_alvo(self):
        """
        Sem keyword-alvo do GSC: o n-grama dominante ainda mede a densidade
        (P3 — antes reportava 0% e dava veredito falsamente limpo).
        No texto balanceado a keyword repete 4× ≈ 2% → continua ok.
        """
        cq = analyze_content_quality(_balanced_text(), [])
        self.assertEqual(cq["densest_keyword"], "aquecedor industrial")
        self.assertEqual(cq["density_source"], "ngram")
        self.assertGreater(cq["keyword_density"], 0.0)
        self.assertEqual(cq["verdict"], "ok")


# ---------------------------------------------------------------------------
# P3 — Densidade vs slug e n-grama dominante
# ---------------------------------------------------------------------------


class TestSlugPhrase(unittest.TestCase):
    def test_slug_simples(self):
        self.assertEqual(
            slug_phrase("https://ex.com/aquecedor-industrial/"),
            "aquecedor industrial",
        )

    def test_remove_stopwords_e_numeros(self):
        self.assertEqual(
            slug_phrase("https://ex.com/blog/aquecedor-de-agua-para-industria-2024/"),
            "aquecedor agua industria",
        )

    def test_remove_extensao(self):
        self.assertEqual(slug_phrase("https://ex.com/cane-corso-preco.html"), "cane corso preco")

    def test_sem_slug_util(self):
        self.assertIsNone(slug_phrase("https://ex.com/"))
        self.assertIsNone(slug_phrase(None))
        self.assertIsNone(slug_phrase("https://ex.com/2024/"))


class TestDominantNgram(unittest.TestCase):
    def test_detecta_bigrama_repetido(self):
        text = ("cane corso e um cachorro grande. " * 6) + " ".join(f"w{i}" for i in range(100))
        phrase, occ = dominant_ngram(text)
        self.assertIn("cane corso", phrase)
        self.assertGreaterEqual(occ, 4)

    def test_abaixo_do_piso_retorna_none(self):
        # bigrama repete só 2× (< NGRAM_MIN_COUNT) → ruído, não "dominante"
        text = "cane corso aqui. cane corso ali. " + " ".join(f"w{i}" for i in range(100))
        self.assertIsNone(dominant_ngram(text))

    def test_ignora_ngrama_com_borda_stopword(self):
        # "de agua" começa com stopword → não pode ser o n-grama dominante
        text = ("tratamento de agua " * 5) + " ".join(f"w{i}" for i in range(100))
        result = dominant_ngram(text)
        self.assertIsNotNone(result)
        phrase, _ = result
        self.assertFalse(phrase.startswith("de "))
        self.assertFalse(phrase.endswith(" de"))

    def test_agrupa_acentos(self):
        # "preço" (3×) e "preco" (2×) contam juntos: trigrama domina com 5 ocorrências
        text = (
            ("cane corso preço ótimo. " * 3)
            + ("cane corso preco bom. " * 2)
            + " ".join(f"w{i}" for i in range(80))
        )
        phrase, occ = dominant_ngram(text)
        self.assertEqual(phrase, "cane corso preco")  # normalizado (sem acento)
        self.assertEqual(occ, 5)


class TestDensitySources(unittest.TestCase):
    def test_pagina_slug_stuffed_sem_query_gsc_nao_e_ok(self):
        """
        O caso P3: página otimizada para o slug, SEM query GSC correspondente.
        Antes: densidade 0% → veredito falsamente "ok". Agora: slug/n-grama
        medem a densidade real e o veredito NÃO pode ser ok.
        """
        text = _stuffed_text(keyword="aquecedor industrial preco", kw_times=20)
        cq = analyze_content_quality(
            text,
            target_keywords=[],  # nenhuma query GSC
            url="https://ex.com/aquecedor-industrial-preco/",
        )
        self.assertNotEqual(cq["verdict"], "ok")
        self.assertIn(cq["density_source"], ("slug", "ngram"))
        self.assertGreaterEqual(cq["keyword_density"], 3.0)
        self.assertIn("aquecedor industrial preco", cq["densest_keyword"])

    def test_pagina_limpa_continua_ok(self):
        """Texto equilibrado com slug coerente não pode virar falso positivo."""
        text = _balanced_text(keyword="aquecedor industrial", kw_times=4)
        cq = analyze_content_quality(
            text,
            ["aquecedor industrial"],
            url="https://ex.com/aquecedor-industrial/",
        )
        self.assertEqual(cq["verdict"], "ok")
        self.assertEqual(cq["flags"], [])

    def test_slug_com_acento_no_texto(self):
        """Slug sem acento ("preco") casa com texto acentuado ("preço")."""
        words = [f"palavra{i}" for i in range(400)]
        for j in range(18):
            words[j * 20] = "cane corso preço"
        text = " ".join(words)
        cq = analyze_content_quality(
            text,
            [],
            url="https://ex.com/cane-corso-preco/",
        )
        self.assertGreaterEqual(cq["keyword_density"], 5.0)
        self.assertNotEqual(cq["verdict"], "ok")

    def test_empate_prioriza_query_gsc(self):
        """Mesma densidade por query e por n-grama → fonte reportada é a query."""
        text = _stuffed_text(keyword="aquecedor industrial", kw_times=25)
        cq = analyze_content_quality(text, ["aquecedor industrial"])
        self.assertEqual(cq["density_source"], "query")

    def test_reason_menciona_keyword_gatilho(self):
        """A explicação do veredito precisa dizer qual keyword disparou (P3)."""
        text = _stuffed_text(keyword="aquecedor industrial preco", kw_times=20)
        cq = analyze_content_quality(
            text,
            [],
            url="https://ex.com/aquecedor-industrial-preco/",
        )
        density_reasons = [r for r in cq["reasons"] if "Densidade" in r]
        self.assertTrue(density_reasons)
        self.assertTrue(any("aquecedor industrial preco" in r for r in density_reasons))
        self.assertTrue(any("slug da URL" in r or "n-grama" in r for r in density_reasons))


# ---------------------------------------------------------------------------
# Veredito — sinais NLP
# ---------------------------------------------------------------------------


class TestVerdictNlp(unittest.TestCase):
    def test_saliencia_concentrada_e_amplitude_pobre(self):
        text = _balanced_text()  # tamanho ok, para isolar os sinais NLP
        nlp = {
            "entities": [{"name": "aquecedor", "salience": 0.92}, {"name": "x", "salience": 0.08}],
            "categories": [{"name": "/Business", "confidence": 0.9}],
        }
        cq = analyze_content_quality(text, ["aquecedor industrial"], nlp)
        self.assertIn("saliencia_concentrada", cq["flags"])
        self.assertIn("amplitude_pobre", cq["flags"])
        # 1 sinal de over + 1 de raso (mistos e brandos) → escala para "atenção",
        # não para um veredito confiante. Conservador de propósito.
        self.assertEqual(cq["verdict"], "atencao")
        self.assertNotEqual(cq["verdict"], "ok")

    def test_nao_classificavel(self):
        text = _balanced_text()
        nlp = {
            "entities": [
                {"name": "a", "salience": 0.3},
                {"name": "b", "salience": 0.25},
                {"name": "c", "salience": 0.25},
                {"name": "d", "salience": 0.2},
            ],
            "categories": [],
        }
        cq = analyze_content_quality(text, ["tema"], nlp)
        self.assertIn("nao_classificavel", cq["flags"])

    def test_keyword_nao_saliente(self):
        text = _balanced_text(keyword="aquecedor industrial", kw_times=4)
        nlp = {
            "entities": [
                {"name": "cidade", "salience": 0.3},
                {"name": "bairro", "salience": 0.25},
                {"name": "rua", "salience": 0.25},
                {"name": "telefone", "salience": 0.2},
            ],
            "categories": [{"name": "/Local", "confidence": 0.8}],
        }
        cq = analyze_content_quality(text, ["aquecedor industrial"], nlp)
        self.assertIn("keyword_nao_saliente", cq["flags"])
        self.assertFalse(cq["target_in_salient"])

    def test_target_in_salient_true(self):
        text = _balanced_text(keyword="aquecedor industrial", kw_times=4)
        nlp = {
            "entities": [
                {"name": "aquecedor industrial", "salience": 0.4},
                {"name": "manutenção", "salience": 0.3},
                {"name": "indústria", "salience": 0.3},
            ],
            "categories": [{"name": "/Business", "confidence": 0.8}],
        }
        cq = analyze_content_quality(text, ["aquecedor industrial"], nlp)
        self.assertTrue(cq["target_in_salient"])
        self.assertNotIn("keyword_nao_saliente", cq["flags"])


# ---------------------------------------------------------------------------
# Extração de keywords-alvo do GSC
# ---------------------------------------------------------------------------


class TestTargetKeywords(unittest.TestCase):
    def test_extrai_top_por_impressoes(self):
        rows = [
            {"query": "a", "url": "https://ex.com/p", "impressions": 50},
            {"query": "b", "url": "https://ex.com/p", "impressions": 300},
            {"query": "c", "url": "https://ex.com/p", "impressions": 100},
            {"query": "x", "url": "https://ex.com/outra", "impressions": 999},
        ]
        kws = target_keywords_for_url(rows, "https://ex.com/p", max_kw=2)
        self.assertEqual(kws, ["b", "c"])

    def test_sem_match(self):
        rows = [{"query": "a", "url": "https://ex.com/p", "impressions": 50}]
        self.assertEqual(target_keywords_for_url(rows, "https://ex.com/zzz"), [])

    def test_lista_vazia(self):
        self.assertEqual(target_keywords_for_url([], "https://ex.com/p"), [])


# ---------------------------------------------------------------------------
# Orquestrador (seleção de URLs de oportunidade) — fetch mockado, sem rede
# ---------------------------------------------------------------------------


class TestOrchestrator(unittest.TestCase):
    def test_seleciona_e_analisa(self):
        from unittest import mock

        import fetchers.content_fetcher as cf

        opp = [
            {"url": "https://ex.com/a", "position": 5.0, "impressions": 500, "has_data": True},
            {
                "url": "https://ex.com/b",
                "position": 2.0,
                "impressions": 900,
                "has_data": True,
            },  # pos<4 → fora
            {"url": "https://ex.com/c", "position": 8.0, "impressions": 100, "has_data": True},
        ]
        qr = [{"query": "foo", "url": "https://ex.com/a", "impressions": 500}]
        texts = {
            "https://ex.com/a": " ".join(f"w{i}" for i in range(400)),  # longo → não raso
            "https://ex.com/c": "texto curto",  # curto → raso
        }
        with mock.patch.object(cf, "_fetch_page_text", side_effect=lambda u: texts.get(u)):
            res = cf.analyze_opportunity_content_quality(
                opp, "ex.com", query_rows=qr, use_cache=False
            )

        self.assertIn("https://ex.com/a", res)
        self.assertIn("https://ex.com/c", res)
        self.assertNotIn("https://ex.com/b", res)  # posição 2 não é oportunidade
        self.assertEqual(res["https://ex.com/c"]["verdict"], "raso")


# ---------------------------------------------------------------------------
# Move 2 — acompanhamento conteúdo × posição
# ---------------------------------------------------------------------------


class TestContentTracking(unittest.TestCase):
    @staticmethod
    def _hist(snapshots):
        return {"site": "ex.com", "snapshots": snapshots}

    def test_baseline_um_snapshot(self):
        from core.content_quality import build_content_tracking

        hist = self._hist(
            [
                {
                    "date": "2026-06-01",
                    "urls": {
                        "https://ex.com/a": {
                            "position": 7.0,
                            "content": {"verdict": "over_otimizado", "density": 5.0, "words": 800},
                        },
                        "https://ex.com/b": {"position": 4.0},  # sem content → ignorada
                    },
                },
            ]
        )
        t = build_content_tracking(hist)
        self.assertEqual(t["n_content_snapshots"], 1)
        self.assertEqual(len(t["rows"]), 1)
        r = t["rows"][0]
        self.assertEqual(r["url"], "https://ex.com/a")
        self.assertIsNone(r["position_delta"])  # 1 snapshot → sem delta
        self.assertEqual(r["last_verdict"], "over_otimizado")

    def test_delta_dois_snapshots(self):
        from core.content_quality import build_content_tracking

        hist = self._hist(
            [
                {
                    "date": "2026-06-01",
                    "urls": {
                        "https://ex.com/a": {
                            "position": 8.0,
                            "content": {"verdict": "over_otimizado", "density": 6.0, "words": 800},
                        }
                    },
                },
                {
                    "date": "2026-06-08",
                    "urls": {
                        "https://ex.com/a": {
                            "position": 5.0,
                            "content": {"verdict": "ok", "density": 2.0, "words": 900},
                        }
                    },
                },
            ]
        )
        t = build_content_tracking(hist)
        self.assertEqual(t["n_content_snapshots"], 2)
        r = t["rows"][0]
        self.assertEqual(r["position_delta"], 3.0)  # 8 → 5 = melhorou +3
        self.assertEqual(r["first_verdict"], "over_otimizado")
        self.assertEqual(r["last_verdict"], "ok")

    def test_vazio(self):
        from core.content_quality import build_content_tracking

        self.assertEqual(build_content_tracking({"snapshots": []})["rows"], [])
        self.assertEqual(build_content_tracking(None)["rows"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
