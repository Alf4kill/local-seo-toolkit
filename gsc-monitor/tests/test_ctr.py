"""
test_ctr.py — Trava o cálculo de CTR esperado nas bordas.

Protege a unificação de `expected_ctr` (antes duplicado em analytics e
excel_reporter): o veredito de saúde (ctr_component) e o score de oportunidade
do Excel dependem dele, então uma regressão aqui seria um "confident but wrong"
silencioso.
"""

import pytest
from config import CTR_BENCHMARK
from core.ctr import expected_ctr


def test_posicao_inteira_bate_o_benchmark():
    for pos, ctr in CTR_BENCHMARK.items():
        assert expected_ctr(pos) == pytest.approx(ctr)


def test_interpola_entre_inteiros():
    # 1.5 = meio caminho entre pos 1 (28.5) e pos 2 (15.7).
    assert expected_ctr(1.5) == pytest.approx((28.5 + 15.7) / 2)


def test_posicao_10_e_o_piso():
    assert expected_ctr(10) == pytest.approx(2.5)
    assert expected_ctr(10.0) == pytest.approx(2.5)


def test_fora_da_primeira_pagina_e_none():
    assert expected_ctr(10.5) is None
    assert expected_ctr(11) is None
    assert expected_ctr(50) is None


def test_none_e_none():
    assert expected_ctr(None) is None


def test_nunca_negativo_no_top10():
    p = 1.0
    while p <= 10.0001:
        assert expected_ctr(p) >= 0
        p += 0.1
