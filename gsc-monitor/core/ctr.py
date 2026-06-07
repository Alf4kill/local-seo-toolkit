"""
ctr.py — CTR esperado por posição (cálculo único, puro).

Fonte única do CTR esperado, antes duplicado em core/analytics.py e
reporters/excel_reporter.py. As duas cópias diferiam só na borda (`[k]` vs
`.get(k, [10])`), o que, como `pos_floor` é sempre 1..10, produzia o MESMO
resultado — a unificação é, portanto, sem mudança de comportamento. A tabela de
benchmark vive em config.CTR_BENCHMARK.
"""

from config import CTR_BENCHMARK


def expected_ctr(position: float) -> float | None:
    """CTR esperado (%) para uma posição média, interpolando entre inteiros.

    Retorna None para posições ausentes ou fora da 1ª página (> 10) — o
    benchmark só é definido para o top 10.
    """
    if position is None or position > 10:
        return None
    pos_floor = max(1, min(int(position), 10))
    pos_ceil  = min(pos_floor + 1, 10)
    frac      = position - int(position)
    ctr_low   = CTR_BENCHMARK[pos_floor]
    ctr_high  = CTR_BENCHMARK.get(pos_ceil, CTR_BENCHMARK[10])
    return ctr_low + frac * (ctr_high - ctr_low)
