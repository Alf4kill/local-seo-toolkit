"""
app.py — Ponto de entrada da interface gráfica do GSC Monitor.

Uso:
    py app.py

Abre uma janela local com:
  - Campo de domínio
  - Seleção de análises (Indexação / Posicionamento)
  - Seleção de formatos de saída (CSV, Excel, TXT)
  - Limite de URLs e opção de ignorar cache
  - Terminal integrado com output em tempo real
  - Botão para abrir a pasta de relatórios do domínio
"""

import os
import sys

# Garante que gsc-monitor/ está no path para todos os módulos do projeto
_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

import tkinter as tk
from tkinter import ttk

from gui.main_window import MainWindow


def _apply_theme(root: tk.Tk) -> None:
    """Aplica o melhor tema ttk disponível na plataforma."""
    style = ttk.Style(root)

    # Preferência de tema: nativo do Windows primeiro, depois genérico
    for theme in ("vista", "xpnative", "winnative", "clam", "alt", "default"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break

    # Estilo para o botão Executar (destaque visual)
    style.configure(
        "Accent.TButton",
        font=("", 9, "bold"),
        padding=(6, 4),
    )


def main() -> None:
    root = tk.Tk()
    _apply_theme(root)
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
