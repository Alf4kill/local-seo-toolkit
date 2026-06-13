"""
poda_runner.py — Executa as etapas do Plano de Poda em thread separada.

Mesmo padrão de gui/runner.py: redireciona stdout/stderr para uma
queue.Queue (QueueStream) para a GUI exibir o output em tempo real.
"""

import os
import queue
import sys
import threading
import traceback

# Garante que gsc-monitor/ está no sys.path para todos os imports do projeto
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from gui.runner import QueueStream


def run_poda_task(
    mode: str,
    params: dict,
    output_queue: queue.Queue,
    done_callback,
    result_store: "dict | None" = None,
) -> None:
    """
    Executa uma etapa do Plano de Poda em thread daemon.

    Parâmetros:
        mode   — "plan" (etapa 1: gerar plano) ou "compile" (etapa 2: blocos)
        params — {"site": str, "min_impressions": int, "no_cache": bool,
                  "csv_path": str|None}
        output_queue  — queue.Queue para as mensagens de log
        done_callback — chamado ao final, na thread worker
        result_store  — dict opcional; recebe "csv_path"/"path_apache"/...
    """

    def worker() -> None:
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout = QueueStream(output_queue)
            sys.stderr = QueueStream(output_queue)

            from poda import run_poda_compile, run_poda_plan

            site = params["site"].strip()

            if mode == "plan":
                plan_kwargs = {
                    "min_impressions": params.get("min_impressions", 10),
                    "use_cache": not params.get("no_cache", False),
                    "gsc_exports": params.get("gsc_exports") or None,
                    "home_fallback": params.get("home_fallback", True),
                }
                if params.get("days_back"):
                    plan_kwargs["days_back"] = params["days_back"]
                result = run_poda_plan(site, **plan_kwargs)
                if result_store is not None:
                    result_store["csv_path"] = result.get("csv_path")
            else:
                result = run_poda_compile(site, csv_path=params.get("csv_path"))
                if result_store is not None:
                    result_store["csv_path"] = result.get("csv_path")
                    result_store["path_apache"] = result.get("path_apache")
                    result_store["path_nginx"] = result.get("path_nginx")
                    result_store["path_redirect"] = result.get("path_redirect")
                    result_store["path_php"] = result.get("path_php")

            print("\nConcluído.")

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
