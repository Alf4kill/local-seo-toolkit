"""test_hybrid.py — Testa a camada LLM com um cliente FALSO (sem servidor/modelo)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.hybrid import build_prompt, judge_clusters, build_diff_prompt, differentiate_clusters


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat(self, system, user, **kw):
        self.calls.append((system, user))
        return self.response


def _clusters():
    return [
        {"size": 3, "cohesion": 0.95, "representative": "b",
         "members": ["a", "b", "c"], "indices": [0, 1, 2], "group_impressions": 500},
        {"size": 2, "cohesion": 0.90, "representative": "d",
         "members": ["d", "e"], "indices": [3, 4], "group_impressions": 1000},
        {"size": 1, "cohesion": 1.0, "representative": "f",
         "members": ["f"], "indices": [5]},
    ]


class TestHybrid(unittest.TestCase):

    def test_build_prompt_inclui_slugs_e_texto(self):
        pages = {"a": "texto da pagina A sobre preço", "b": "texto B", "c": "texto C"}
        p = build_prompt(_clusters()[0], pages)
        self.assertIn("slug: a", p)
        self.assertIn("texto da pagina A", p)
        self.assertIn("verdict", p)          # schema presente

    def test_judge_seleciona_ordena_e_anexa(self):
        pages = {k: "texto " + k for k in "abcdef"}
        resp = ('```json\n{"verdict":"spun","base_recomendada":"a",'
                '"lacunas":["faltam dados reais"],"resumo":"quase iguais"}\n```')
        fake = FakeClient(resp)
        judged = judge_clusters(_clusters(), pages, fake, max_clusters=8)
        self.assertEqual(len(judged), 2)                       # só grupos 2+
        self.assertEqual(judged[0]["members"], ["d", "e"])     # mais impressões primeiro
        self.assertEqual(judged[0]["llm"]["verdict"], "spun")
        self.assertEqual(judged[0]["llm"]["base_recomendada"], "a")
        self.assertTrue(judged[0]["llm"]["raw_ok"])

    def test_judge_respeita_max(self):
        pages = {k: "t" for k in "abcdef"}
        judged = judge_clusters(_clusters(), pages, FakeClient('{"verdict":"ok"}'), max_clusters=1)
        self.assertEqual(len(judged), 1)

    def test_judge_json_sujo_nao_quebra(self):
        pages = {k: "t" for k in "abcdef"}
        judged = judge_clusters(_clusters(), pages, FakeClient("desculpe, não sei"), max_clusters=1)
        self.assertEqual(judged[0]["llm"]["verdict"], "?")
        self.assertFalse(judged[0]["llm"]["raw_ok"])

    def test_build_prompt_tem_anchors_fundir_e_nao_fundir(self):
        # O prompt precisa ensinar OS DOIS desfechos: spun (fundir) E ok (não fundir).
        # Sem o exemplo 'ok' o modelo tende a marcar tudo como 'spun'.
        pages = {"a": "texto A", "b": "texto B", "c": "texto C"}
        p = build_prompt(_clusters()[0], pages)
        self.assertIn('"verdict":"spun"', p)   # exemplo de FUNDIR
        self.assertIn('"verdict":"ok"', p)      # exemplo de NÃO fundir
        self.assertIn("EXEMPLO 2", p)

    def test_judge_veredito_ok_base_e_lacunas_vazias(self):
        # Caso 'ok': nada a consolidar → base vazia e lacunas vazias, mas raw_ok=True.
        pages = {k: "t" for k in "abcdef"}
        resp = '{"verdict":"ok","base_recomendada":"","lacunas":[],"resumo":"intenções distintas"}'
        judged = judge_clusters(_clusters(), pages, FakeClient(resp), max_clusters=1)
        self.assertEqual(judged[0]["llm"]["verdict"], "ok")
        self.assertEqual(judged[0]["llm"]["base_recomendada"], "")
        self.assertEqual(judged[0]["llm"]["lacunas"], [])
        self.assertTrue(judged[0]["llm"]["raw_ok"])

    # --- Modo DIFERENCIAÇÃO (contract-safe: mantém todas as páginas, sem 301) ---

    def test_build_diff_prompt_tem_restricao_e_schema(self):
        pages = {"a": "texto A", "b": "texto B", "c": "texto C"}
        p = build_diff_prompt(_clusters()[0], pages)
        self.assertIn("slug: a", p)
        self.assertIn("keyword_alvo", p)       # schema de diferenciação
        self.assertIn("redirecionar", p)        # menciona a restrição de não 301
        self.assertIn("cabeca", p)              # schema pede a página-cabeça

    def test_differentiate_attaches_plan(self):
        pages = {k: "texto " + k for k in "abcdef"}
        resp = ('{"cabeca":"d","paginas":['
                '{"slug":"d","papel":"cabeca","intencao":"visão geral","keyword_alvo":"k1","titulo":"T1","foco":"f1"},'
                '{"slug":"e","papel":"spoke","intencao":"ângulo 2","keyword_alvo":"k2","titulo":"T2","foco":"f2"}]}')
        diffed = differentiate_clusters(_clusters(), pages, FakeClient(resp), max_clusters=8)
        self.assertEqual(len(diffed), 2)                    # só grupos 2+
        self.assertEqual(diffed[0]["members"], ["d", "e"])  # mais impressões primeiro
        d = diffed[0]["diff"]
        self.assertEqual(d["cabeca"], "d")
        self.assertEqual(len(d["paginas"]), 2)
        self.assertEqual(d["paginas"][0]["keyword_alvo"], "k1")
        self.assertEqual(d["paginas"][1]["papel"], "spoke")
        self.assertTrue(d["raw_ok"])

    def test_differentiate_json_sujo_nao_quebra(self):
        pages = {k: "t" for k in "abcdef"}
        diffed = differentiate_clusters(_clusters(), pages, FakeClient("sem json aqui"), max_clusters=1)
        self.assertFalse(diffed[0]["diff"]["raw_ok"])
        self.assertEqual(diffed[0]["diff"]["paginas"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
