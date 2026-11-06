"""
test_ratelimit.py — TokenBucket (core/ratelimit.py).

O relógio e o sleep são injetados, então os testes são determinísticos e
instantâneos: nada aqui dorme de verdade.
"""

import threading

import pytest
from core.ratelimit import TokenBucket


class RelogioFalso:
    """Relógio monotônico controlado à mão; sleep() apenas avança o tempo."""

    def __init__(self):
        self.agora = 0.0
        self.dormiu = []

    def monotonic(self) -> float:
        return self.agora

    def sleep(self, segundos: float) -> None:
        self.dormiu.append(segundos)
        self.agora += segundos


def _bucket(rate, capacity=None):
    relogio = RelogioFalso()
    return (
        TokenBucket(
            rate=rate,
            capacity=capacity,
            monotonic=relogio.monotonic,
            sleep=relogio.sleep,
        ),
        relogio,
    )


def test_rate_invalido():
    with pytest.raises(ValueError):
        TokenBucket(rate=0)


def test_rajada_inicial_nao_espera():
    """O bucket começa cheio: as primeiras `capacity` chamadas saem na hora."""
    bucket, relogio = _bucket(rate=8.0)  # capacity default = rate = 8
    for _ in range(8):
        assert bucket.acquire() == 0.0
    assert relogio.dormiu == []


def test_nona_chamada_espera_o_intervalo():
    """Esgotada a rajada, cada chamada passa a esperar 1/rate."""
    bucket, relogio = _bucket(rate=8.0)
    for _ in range(8):
        bucket.acquire()

    esperou = bucket.acquire()
    assert esperou == pytest.approx(1 / 8.0)
    assert relogio.agora == pytest.approx(1 / 8.0)


def test_vazao_media_respeita_a_taxa():
    """
    O que de fato importa para a cota: em N chamadas, o tempo decorrido não
    deixa a vazão passar da taxa configurada (descontada a rajada inicial).
    """
    rate = 8.0
    bucket, relogio = _bucket(rate=rate)
    chamadas = 100
    for _ in range(chamadas):
        bucket.acquire()

    # capacity (=8) saem de graça; as demais a 1/rate cada.
    esperado = (chamadas - rate) / rate
    assert relogio.agora == pytest.approx(esperado)

    # O que a cota enxerga é a pior janela de 60 s: a rajada inicial MAIS o
    # regime permanente. Com rate 8 e rajada 8 dá 488 — abaixo dos 600 QPM
    # que o Google permite por site.
    pior_janela_60s = bucket.capacity + rate * 60
    assert pior_janela_60s < 600


def test_tokens_repoem_com_o_tempo():
    """Ficar parado devolve tokens, até o teto da capacidade."""
    bucket, relogio = _bucket(rate=4.0, capacity=4.0)
    for _ in range(4):
        bucket.acquire()

    relogio.agora += 10.0  # tempo de sobra para encher
    for _ in range(4):
        assert bucket.acquire() == 0.0  # cheio de novo, não mais que isso
    assert bucket.acquire() > 0.0


def test_uso_concorrente_nao_estoura_a_taxa():
    """
    Com threads de verdade e relógio de verdade: 20 chamadas a 50 req/s não
    podem terminar antes do tempo mínimo que a taxa impõe.
    """
    rate = 50.0
    bucket = TokenBucket(rate=rate, capacity=5.0)
    import time

    inicio = time.monotonic()

    def trabalho():
        for _ in range(4):
            bucket.acquire()

    threads = [threading.Thread(target=trabalho) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    decorrido = time.monotonic() - inicio
    # 20 chamadas, 5 de rajada → 15 a 1/50 s = 0,30 s no mínimo.
    minimo = (20 - 5) / rate
    assert decorrido >= minimo * 0.9  # folga para a granularidade do sleep
