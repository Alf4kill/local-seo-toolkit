"""
ratelimit.py — Token bucket thread-safe para respeitar o QPM das APIs.

Por que um bucket e não só `max_workers`: o número de threads limita quantas
requisições ficam EM VOO, não quantas partem por segundo. Se a API responder
em 200 ms, 8 threads disparam 40 req/s — muito acima dos 10 QPS (600 QPM) que
a URL Inspection permite por site. O bucket é o que de fato põe o teto na
vazão; os workers só definem quanta latência se consegue esconder.

Puro o bastante para testar sem rede: o relógio e o sleep são injetáveis.
"""

import threading
import time


class TokenBucket:
    """
    Limitador de vazão por token bucket.

    Enche a uma taxa constante de `rate` tokens por segundo até um teto de
    `capacity` tokens (o tamanho da rajada permitida). Cada acquire() consome
    um token, bloqueando se não houver.

    Uso típico:
        bucket = TokenBucket(rate=8.0)   # 8 req/s = 480 QPM
        bucket.acquire()                 # antes de cada chamada de API
    """

    def __init__(
        self,
        rate: float,
        capacity: float | None = None,
        monotonic=time.monotonic,
        sleep=time.sleep,
    ):
        if rate <= 0:
            raise ValueError("rate deve ser > 0")
        self.rate = float(rate)
        # Rajada padrão de 1 s de tráfego: deixa o início do run engatar sem
        # dar folga suficiente para estourar a janela de 1 minuto da cota.
        self.capacity = float(capacity) if capacity is not None else self.rate
        self._monotonic = monotonic
        self._sleep = sleep
        self._tokens = self.capacity
        self._updated = monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Repõe tokens pelo tempo decorrido. Chamar com o lock tomado."""
        agora = self._monotonic()
        decorrido = agora - self._updated
        if decorrido > 0:
            self._tokens = min(self.capacity, self._tokens + decorrido * self.rate)
            self._updated = agora

    def acquire(self) -> float:
        """
        Consome um token, dormindo o necessário. Retorna quantos segundos
        esperou (0.0 se havia token disponível) — útil para diagnóstico.
        """
        esperou = 0.0
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return esperou
                faltam = (1.0 - self._tokens) / self.rate
            # Dorme FORA do lock: senão uma thread esperando bloquearia as
            # outras, e a vazão viria a ser serial em vez de limitada.
            self._sleep(faltam)
            esperou += faltam
