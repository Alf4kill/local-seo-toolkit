"""
terminal.py — Paleta e colorização do painel de terminal das janelas da GUI.

Extraído porque a lógica estava copiada em gui/main_window.py e
gui/poda_window.py, com as cópias já DIVERGINDO: a da poda colore avisos, a da
janela principal definia _C_WARN e nunca o usava. Uma terceira cópia (a janela
do Acervo) consolidaria o problema, então as três passam a usar isto.

A colorização é por string porque é assim que o projeto funciona hoje: o código
de biblioteca imprime com prefixos ([CACHE], [ERRO], [auth], [storage]) e a GUI
lê o stdout redirecionado. Em outras palavras, **o texto dos prints é contrato**
— mudar um prefixo muda a cor na GUI. Logging estruturado está no backlog e
resolveria isso; até lá, mantenha os prefixos.
"""

import tkinter as tk

# Paleta do terminal
BG = "#1e1e1e"
FG = "#d4d4d4"
FONT = ("Consolas", 9)

C_CACHE = "#4ec9b0"  # verde-azulado — [CACHE]
C_ERRO = "#f44747"  # vermelho       — [ERRO]
C_HEADER = "#569cd6"  # azul           — linhas === e ───
C_STORAGE = "#858585"  # cinza          — [storage]
C_AUTH = "#c586c0"  # lilás          — [auth]
C_OK = "#4ec9b0"  # verde          — Concluído
C_WARN = "#dcdcaa"  # amarelo        — avisos e verdicts recusados


def tag_for_line(line: str) -> "str | None":
    """Nome do tag de cor para uma linha, ou None para a cor padrão.

    Função PURA — é o que os testes exercitam, sem precisar de Tk.

    A ordem importa: [ERRO] vence "aviso", e "RECUSADO" (verdict que a análise
    se negou a emitir) é um aviso, não um erro — o programa funcionou, ele só
    se recusou a afirmar o que não podia.
    """
    stripped = line.strip()
    low = line.lower()
    if "[cache]" in low:
        return "cache"
    if "[erro" in low:
        return "erro"
    if "aviso" in low or "recusado" in low:
        return "warn"
    if stripped.startswith("=") or stripped.startswith("─") or stripped.startswith("-" * 10):
        return "header"
    if "[auth]" in low:
        return "auth"
    if "[storage]" in low:
        return "storage"
    if "concluído" in low or "concluido" in low:
        return "ok"
    return None


def setup_tags(widget) -> None:
    """Registra os tags de cor num widget de texto."""
    widget.tag_configure("cache", foreground=C_CACHE)
    widget.tag_configure("erro", foreground=C_ERRO, font=(FONT[0], FONT[1], "bold"))
    widget.tag_configure("header", foreground=C_HEADER, font=(FONT[0], FONT[1], "bold"))
    widget.tag_configure("storage", foreground=C_STORAGE)
    widget.tag_configure("auth", foreground=C_AUTH)
    widget.tag_configure("ok", foreground=C_OK, font=(FONT[0], FONT[1], "bold"))
    widget.tag_configure("warn", foreground=C_WARN)


def write(widget, text: str) -> None:
    """Escreve texto no terminal, colorindo linha por linha."""
    widget.configure(state=tk.NORMAL)
    for line in text.splitlines(keepends=True):
        tag = tag_for_line(line)
        widget.insert(tk.END, line, tag) if tag else widget.insert(tk.END, line)
    widget.see(tk.END)
    widget.configure(state=tk.DISABLED)
