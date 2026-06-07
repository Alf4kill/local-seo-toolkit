"""test_loaders.py — Testa slugify e extração de texto (sem rede, sem ML)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.loaders import extract_text, slugify


class TestLoaders(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(
            slugify("Cane Corso em Apartamentos: É Possível?"),
            "cane-corso-em-apartamentos-e-possivel",
        )
        self.assertEqual(slugify("Preço do Cane Corso"), "preco-do-cane-corso")
        self.assertEqual(slugify("Rottweiler cabeça de touro"), "rottweiler-cabeca-de-touro")

    def test_extract_text_remove_php_html_script(self):
        markup = (
            "<?php $x = 1; ?>"
            "<html><head><style>.a{color:red}</style></head>"
            "<body><h1>Cane Corso</h1>"
            "<script>var z=2;</script>"
            "<p>Texto &amp; conte&uacute;do real.</p></body></html>"
        )
        txt = extract_text(markup)
        self.assertIn("Cane Corso", txt)
        self.assertIn("Texto & conteúdo real.", txt)
        self.assertNotIn("color:red", txt)  # style removido
        self.assertNotIn("var z", txt)  # script removido
        self.assertNotIn("$x", txt)  # php removido

    def test_extract_text_collapse_spaces(self):
        self.assertEqual(extract_text("<p>a</p>\n\n   <p>b</p>"), "a b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
