"""
acervo_runner.py — Executa os comandos do Acervo em thread separada.

Mesmo padrão de gui/runner.py e gui/poda_runner.py: redireciona stdout/stderr
para uma queue.Queue (QueueStream) para a GUI exibir o output em tempo real.

A janela NÃO duplica a lógica do acervo: ela monta os mesmos argumentos que a
CLI monta e chama as mesmas funções `cmd_*` de acervo.py. Assim GUI e CLI nunca
divergem de comportamento — se um verdict é recusado na CLI, é recusado aqui.
"""

import argparse
import os
import queue
import sys
import threading
import traceback

# Garante que gsc-monitor/ está no sys.path para todos os imports do projeto
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from config import ACERVO_DIAS_BACKFILL, ACERVO_PAUSA_REQUISICAO

from gui.runner import QueueStream

# Modos expostos pela janela, na ordem do fluxo guiado.
MODOS = ("aferir", "backfill", "diario", "status")


def montar_args(modo: str, params: dict) -> argparse.Namespace:
    """Monta o Namespace que as funções cmd_* de acervo.py esperam.

    Função PURA (sem rede, sem Tk) — é o que os testes exercitam. Preenche
    TODOS os campos que cada comando lê, inclusive os que aquele comando não
    usa: um Namespace incompleto só estouraria AttributeError lá dentro, em
    thread, onde o erro aparece mal.
    """
    if modo not in MODOS:
        raise ValueError(f"modo desconhecido: {modo}")

    return argparse.Namespace(
        comando=modo,
        site=(params.get("site") or "").strip(),
        tipo=params.get("tipo", "web"),
        graos=params.get("graos") or None,
        pausa=float(params.get("pausa", ACERVO_PAUSA_REQUISICAO)),
        dias=int(params.get("dias", ACERVO_DIAS_BACKFILL)),
        dry_run=bool(params.get("dry_run", False)),
        forcar=bool(params.get("forcar", False)),
        ponta_fresca=bool(params.get("ponta_fresca", False)),
        batch=None,
    )


def run_acervo_task(
    modo: str,
    params: dict,
    output_queue: queue.Queue,
    done_callback,
    result_store: "dict | None" = None,
) -> None:
    """
    Executa um comando do Acervo em thread daemon.

    Parâmetros:
        modo   — "aferir" | "backfill" | "diario" | "status"
        params — {"site": str, "dias": int, "dry_run": bool, "pausa": float,
                  "graos": str|None, "ponta_fresca": bool, "forcar": bool}
        output_queue  — queue.Queue para as mensagens de log
        done_callback — chamado ao final, na thread worker
        result_store  — dict opcional; recebe o retorno do comando em "resultado"
    """

    def worker() -> None:
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout = QueueStream(output_queue)
            sys.stderr = QueueStream(output_queue)

            import acervo

            args = montar_args(modo, params)
            resultado = acervo.COMANDOS[modo](args)
            if result_store is not None:
                result_store["resultado"] = resultado
                result_store["modo"] = modo

            print("\nConcluído.")

        # AcervoError e AcervoFetchError são RuntimeError; FileNotFoundError
        # cobre credencial ausente. Mensagem limpa, sem traceback.
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"\n[ERRO] {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[ERRO INESPERADO] {exc}")
            print(traceback.format_exc())
        finally:
            sys.stdout = old_out
            sys.stderr = old_err
            done_callback()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
