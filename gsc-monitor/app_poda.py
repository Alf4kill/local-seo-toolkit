"""
app_poda.py — Ponto de entrada da interface gráfica do Plano de Poda.

Uso:
    py app_poda.py

Abre uma janela local com o fluxo de poda de páginas antigas em 2 etapas:
  1. Gerar plano  — URLs que o Google conhece mas estão FORA do sitemap
     (na convenção de sitemap completo, são páginas antigas), com ação
     sugerida (410 por padrão; "revisar" quando ainda há tráfego) e destino
     301 sugerido por query compartilhada ou slug semelhante.
  2. Compilar     — após revisão humana do CSV, gera os blocos Apache/nginx
     prontos para aplicar no servidor.
"""

import os
import sys

# Garante que gsc-monitor/ está no path para todos os módulos do projeto
_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

import tkinter as tk
from tkinter import ttk

from gui.poda_window import PodaWindow


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
    PodaWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
