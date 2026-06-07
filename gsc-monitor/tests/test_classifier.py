"""
test_classifier.py — Testa o mapeamento verdict → categoria interna.

`core.classifier.classify` é uma função pura (sem I/O), mas é o ponto que
decide se uma URL conta como indexada, não-indexada, warning ou unknown — ou
seja, alimenta todo o health score e os relatórios de indexação. Estava sem
cobertura. Aqui travamos o contrato e o fallback seguro para valores
desconhecidos.
"""

import pytest
from core.classifier import VERDICT_MAP, classify


class TestClassify:
    @pytest.mark.parametrize(
        "verdict, esperado",
        [
            ("PASS", "indexed"),
            ("FAIL", "not_indexed"),
            ("NEUTRAL", "warning"),
            ("VERDICT_UNSPECIFIED", "unknown"),
        ],
    )
    def test_mapeamento_conhecido(self, verdict, esperado):
        assert classify(verdict) == esperado

    def test_valor_desconhecido_vira_unknown(self):
        # Qualquer coisa fora do mapa precisa cair em 'unknown', nunca crashar.
        assert classify("ALGO_NOVO_DA_API") == "unknown"

    def test_string_vazia_vira_unknown(self):
        assert classify("") == "unknown"

    def test_case_sensitive(self):
        # A API devolve maiúsculas; 'pass' minúsculo não é um verdict válido.
        assert classify("pass") == "unknown"

    def test_mapa_cobre_apenas_categorias_validas(self):
        # Garante que ninguém adicione um destino fora do vocabulário interno.
        assert set(VERDICT_MAP.values()) <= {"indexed", "not_indexed", "warning", "unknown"}
