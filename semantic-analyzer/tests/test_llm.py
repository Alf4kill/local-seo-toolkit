"""test_llm.py — Testa o parser de JSON robusto (sem servidor LLM)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm import parse_json_block


class TestParseJson(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_json_block('{"a": 1}'), {"a": 1})

    def test_fenced(self):
        self.assertEqual(parse_json_block('```json\n{"verdict": "spun"}\n```'), {"verdict": "spun"})

    def test_noise_around(self):
        self.assertEqual(
            parse_json_block('Claro! Aqui está: {"verdict":"raso"} espero ter ajudado.'),
            {"verdict": "raso"},
        )

    def test_trailing_comma(self):
        self.assertEqual(parse_json_block('{"a":1, "b":[1,2,],}'), {"a": 1, "b": [1, 2]})

    def test_empty_e_lixo(self):
        self.assertEqual(parse_json_block(""), {})
        self.assertEqual(parse_json_block("sem json nenhum aqui"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
