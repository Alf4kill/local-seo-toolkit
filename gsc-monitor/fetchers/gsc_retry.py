"""
gsc_retry.py — Retentativa com backoff exponencial + jitter para as APIs do GSC.

Não existia no repo: fetchers/position_fetcher.py imprime o HttpError e
re-levanta, o que é aceitável numa execução interativa de 2 requisições e
inaceitável num backfill que faz dezenas ou centenas.

Tratamento por classe de erro:

  - 429/403 de CARGA  -> a Search Console API tem uma "load quota" opaca, medida
    em janelas de 10 minutos, e a própria doc manda esperar 15 minutos. Backoff
    exponencial de segundos não resolve isso; esperar o ciclo resolve.
  - 429/5xx comum     -> backoff exponencial limitado por um teto, com jitter
    (duas execuções agendadas no mesmo minuto não devem bater juntas de novo).
  - 4xx restantes     -> re-levanta NA HORA. Corpo inválido não melhora com
    espera, e insistir só queima cota. É também assim que o chamador descobre
    que uma dimensão ou `type` não é aceito (ex.: searchAppearance agrupado com
    outra dimensão devolve 400).

`dormir` e `jitter` são injetáveis para os testes rodarem instantâneos e
determinísticos — nenhum teste deste módulo espera de verdade.
"""

import random
import time

from config import ACERVO_ESPERA_CARGA, ACERVO_TENTATIVAS
from googleapiclient.errors import HttpError

CODIGOS_RETENTATIVA = (429, 500, 502, 503, 504)

# Marcas textuais de esgotamento de carga/cota na mensagem do erro.
MARCAS_CARGA = ("load", "quota", "rate limit", "user rate", "ratelimit")


def _status(exc: HttpError) -> int:
    """Código HTTP do erro, tolerante a variações da biblioteca."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "resp", None), "status", 0)
    try:
        return int(status or 0)
    except (TypeError, ValueError):
        return 0


def _texto(exc: HttpError) -> str:
    """Motivo + conteúdo, em minúsculas, para casar com MARCAS_CARGA."""
    partes = [str(getattr(exc, "reason", "") or "")]
    conteudo = getattr(exc, "content", b"") or b""
    if isinstance(conteudo, bytes):
        conteudo = conteudo.decode("utf-8", errors="replace")
    partes.append(str(conteudo))
    return " ".join(partes).lower()


def e_carga_esgotada(exc: HttpError) -> bool:
    """429/403 cujo motivo cita carga/cota: o Google manda esperar 15 minutos."""
    if _status(exc) not in (403, 429):
        return False
    texto = _texto(exc)
    return any(marca in texto for marca in MARCAS_CARGA)


def executar_com_retentativa(
    fn,
    *,
    tentativas: int = ACERVO_TENTATIVAS,
    base: float = 2.0,
    teto: float = 60.0,
    espera_carga: float = ACERVO_ESPERA_CARGA,
    dormir=time.sleep,
    jitter=random.random,
    etiqueta: str = "",
    contador: "dict | None" = None,
):
    """Executa fn(), re-tentando 429/5xx. Retorna o valor de fn().

    `contador` (opcional) acumula {'retentativas': n, 'esperas_carga': n} para o
    log de execução do acervo.

    Esgotadas as tentativas, re-levanta o último HttpError — falhar é melhor que
    gravar dia incompleto como se estivesse completo.
    """
    ultimo: HttpError | None = None

    for tentativa in range(1, max(1, tentativas) + 1):
        try:
            return fn()
        except HttpError as exc:
            ultimo = exc
            status = _status(exc)

            if e_carga_esgotada(exc):
                if contador is not None:
                    contador["esperas_carga"] = contador.get("esperas_carga", 0) + 1
                print(
                    f"[acervo] Cota de carga esgotada ({status}) em {etiqueta or 'requisicao'}. "
                    f"Aguardando {int(espera_carga)}s antes de tentar de novo "
                    f"(tentativa {tentativa}/{tentativas})."
                )
                if tentativa >= tentativas:
                    break
                dormir(espera_carga)
                continue

            if status not in CODIGOS_RETENTATIVA:
                raise

            if tentativa >= tentativas:
                break

            if contador is not None:
                contador["retentativas"] = contador.get("retentativas", 0) + 1
            espera = min(base**tentativa, teto) + jitter() * base
            print(
                f"[acervo] Erro {status} em {etiqueta or 'requisicao'}; "
                f"nova tentativa em {espera:.1f}s ({tentativa}/{tentativas})."
            )
            dormir(espera)

    raise ultimo
