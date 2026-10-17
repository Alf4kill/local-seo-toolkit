"""
app_acervo.py — Ponto de entrada da interface gráfica do Acervo histórico.

Uso:
    py app_acervo.py

Janela separada (como app_poda.py é separada de app.py) porque o Acervo é uma
feature com fluxo próprio e sequencial, e misturá-la no painel de posicionamento
esconderia justamente o que ela tem de particular.

O fluxo, em três etapas que a janela destaca conforme o que falta:

  1. Aferir    — mede, no seu site, se o teto de 50 mil linhas da API vale por
                 dia ou por consulta (a doc do Google não resolve isso). Custa
                 ~8 requisições e não grava dado. Uma vez por site.
  2. Backfill  — traz os 480 dias (~16 meses) que a API ainda guarda. Retoma de
                 onde parou e rodar de novo não duplica. Uma vez por site.
  3. Diário    — re-busca a ponta que ainda assenta e incorpora os dias novos.
                 É este que faz os 16 meses virarem 2 anos; agende semanal.

A janela extrai e acumula — não analisa. A análise acontece depois, sobre o
banco SQLite em relatorios/{dominio}/acervo/acervo.sqlite3.
"""

import os
import sys

# Garante que gsc-monitor/ está no path para todos os módulos do projeto
_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

import tkinter as tk
from tkinter import ttk

from gui.acervo_window import AcervoWindow


def _apply_theme(root: tk.Tk) -> None:
    """Aplica o melhor tema ttk disponível na plataforma."""
    style = ttk.Style(root)
    for theme in ("vista", "xpnative", "winnative", "clam", "alt", "default"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break
    style.configure(
        "Accent.TButton",
        font=("", 9, "bold"),
        padding=(6, 4),
    )


def main() -> None:
    root = tk.Tk()
    _apply_theme(root)
    AcervoWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
