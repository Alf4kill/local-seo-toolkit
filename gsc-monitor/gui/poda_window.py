"""
poda_window.py — Janela do Plano de Poda (app_poda.py).

Fluxo em duas etapas, com revisão humana obrigatória entre elas:

  ┌──────────────────────────────────────────────────────────┐
  │  ┌─ Plano de Poda ─────────────────────────────────────┐ │
  │  │  Domínio  [_____________________]                   │ │
  │  │  Piso de impressões p/ revisar [10]  ☐ Ignorar cache│ │
  │  │  [1 · Gerar plano] [Abrir CSV] [2 · Compilar] [Pasta]│ │
  │  └─────────────────────────────────────────────────────┘ │
  │  ┌─ Terminal ────────────────────────────── [Limpar] ──┐ │
  │  │  (output em tempo real)                             │ │
  │  └─────────────────────────────────────────────────────┘ │
  │  Status: Pronto                          Concluído 14:32 │
  └──────────────────────────────────────────────────────────┘

Etapa 1 gera {data}_poda.csv (URLs antigas = fora do sitemap, com ação
sugerida). O analista edita acao_final/destino_final no CSV. Etapa 2 compila
o CSV revisado em blocos Apache/nginx prontos para o servidor.
"""

import os
import queue
import re
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk

from core.pruning import PODA_MIN_IMPRESSIONS
from core.storage import latest_poda_csv
from core.urls import normalize_domain
from poda import PODA_DAYS_BACK

from gui.poda_runner import run_poda_task

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Paleta do terminal (mesma de gui/main_window.py)
_T_BG = "#1e1e1e"
_T_FG = "#d4d4d4"
_T_FONT = ("Consolas", 9)
_C_CACHE = "#4ec9b0"
_C_ERRO = "#f44747"
_C_HEADER = "#569cd6"
_C_STORAGE = "#858585"
_C_AUTH = "#c586c0"
_C_OK = "#4ec9b0"
_C_WARN = "#dcdcaa"


class PodaWindow:
    """Janela do Plano de Poda."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._out_queue = queue.Queue()
        self._running = False
        self._result_store = {}

        self._setup_window()
        self._build_config_panel()
        self._build_terminal_panel()
        self._build_status_bar()
        self._poll_queue()

    # -----------------------------------------------------------------------
    # Janela e painel de configuração
    # -----------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.root.title("GSC Monitor — Plano de Poda")
        self.root.geometry("860x640")
        self.root.minsize(720, 520)
        self.root.configure(bg="#f0f0f0")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

    def _build_config_panel(self) -> None:
        outer = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)  # terminal expande

        cfg = ttk.LabelFrame(outer, text="  Plano de Poda — páginas antigas  ", padding=(14, 10))
        cfg.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        cfg.columnconfigure(1, weight=1)

        # ── Domínio ─────────────────────────────────────────────────────
        ttk.Label(cfg, text="Domínio:").grid(row=0, column=0, sticky="w", pady=5)
        self._site_var = tk.StringVar()
        site_e = ttk.Entry(cfg, textvariable=self._site_var, width=48)
        site_e.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=5)
        site_e.bind("<Return>", lambda _: self._on_generate())

        ttk.Label(
            cfg,
            text="Premissa: o sitemap lista TODAS as páginas ativas — URLs fora dele são antigas.",
            foreground="#888888",
        ).grid(row=1, column=1, columnspan=3, sticky="w", padx=(8, 0))

        # ── Opções ──────────────────────────────────────────────────────
        ttk.Label(cfg, text="Opções:").grid(row=2, column=0, sticky="w", pady=(10, 4))

        opt_row = ttk.Frame(cfg)
        opt_row.grid(row=2, column=1, columnspan=3, sticky="w", padx=(8, 0), pady=(10, 4))

        ttk.Label(opt_row, text="Piso de impressões p/ revisar:").pack(side="left")
        self._min_impr_var = tk.StringVar(value=str(PODA_MIN_IMPRESSIONS))
        ttk.Entry(opt_row, textvariable=self._min_impr_var, width=6).pack(side="left", padx=(6, 0))

        ttk.Label(opt_row, text="Janela (dias):").pack(side="left", padx=(18, 0))
        self._days_var = tk.StringVar(value=str(PODA_DAYS_BACK))
        ttk.Entry(opt_row, textvariable=self._days_var, width=6).pack(side="left", padx=(6, 0))
        ttk.Label(opt_row, text="(480 ≈ 16 meses, máx. do GSC)", foreground="#888888").pack(
            side="left", padx=(6, 18)
        )

        self._no_cache_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_row, text="Ignorar cache", variable=self._no_cache_var).pack(
            side="left"
        )

        self._home_fallback_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opt_row,
            text="Sugerir home se não houver destino",
            variable=self._home_fallback_var,
        ).pack(side="left", padx=(18, 0))

        # ── Export do GSC (opcional — URLs sem impressões) ──────────────
        ttk.Label(cfg, text="Export GSC:").grid(row=3, column=0, sticky="w", pady=(6, 4))

        exp_row = ttk.Frame(cfg)
        exp_row.grid(row=3, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(6, 4))

        self._export_var = tk.StringVar()
        ttk.Entry(exp_row, textvariable=self._export_var, width=44).pack(side="left")
        ttk.Button(exp_row, text="Procurar...", command=self._on_pick_exports, width=11).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(
            exp_row,
            text="  (opcional — export do relatório 'Páginas' p/ URLs sem impressões)",
            foreground="#888888",
        ).pack(side="left")

        # ── Botões (fluxo em 2 etapas) ──────────────────────────────────
        btn_row = ttk.Frame(cfg)
        btn_row.grid(row=4, column=0, columnspan=4, sticky="e", pady=(12, 2))

        self._gen_btn = ttk.Button(
            btn_row, text="  1 · Gerar plano  ", command=self._on_generate, style="Accent.TButton"
        )
        self._gen_btn.pack(side="left", padx=(0, 8))

        self._csv_btn = ttk.Button(btn_row, text="Abrir CSV", command=self._on_open_csv, width=11)
        self._csv_btn.pack(side="left", padx=(0, 8))

        self._compile_btn = ttk.Button(
            btn_row, text="  2 · Compilar blocos  ", command=self._on_compile
        )
        self._compile_btn.pack(side="left", padx=(0, 8))

        self._open_btn = ttk.Button(
            btn_row, text="Abrir pasta", command=self._on_open_folder, width=12
        )
        self._open_btn.pack(side="left")

        self._outer_frame = outer

    # -----------------------------------------------------------------------
    # Terminal e status (mesmo padrão da janela principal)
    # -----------------------------------------------------------------------

    def _build_terminal_panel(self) -> None:
        outer = self._outer_frame

        term_frame = ttk.Frame(outer)
        term_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        term_frame.columnconfigure(0, weight=1)
        term_frame.rowconfigure(1, weight=1)

        hdr = ttk.Frame(term_frame)
        hdr.grid(row=0, column=0, sticky="ew")
        ttk.Label(hdr, text="  Terminal", font=("", 9, "bold")).pack(side="left")
        ttk.Button(hdr, text="Limpar", command=self._clear_terminal, width=7).pack(side="right")
        ttk.Separator(term_frame, orient="horizontal").grid(
            row=0, column=0, sticky="ew", pady=(22, 0)
        )

        self._terminal = scrolledtext.ScrolledText(
            term_frame,
            bg=_T_BG,
            fg=_T_FG,
            font=_T_FONT,
            wrap=tk.WORD,
            state=tk.DISABLED,
            relief=tk.FLAT,
            borderwidth=0,
            insertbackground=_T_FG,
        )
        self._terminal.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self._setup_terminal_tags()

        self._write_terminal(
            "  Plano de Poda está pronto.\n"
            "  Etapa 1: gere o plano — URLs que o Google conhece mas estão fora do sitemap.\n"
            "  Revise o CSV (acao_final / destino_final) e então compile os blocos (Etapa 2).\n\n"
        )

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        bar.grid(row=1, column=0, sticky="ew")
        ttk.Separator(bar, orient="horizontal").pack(fill="x", pady=(0, 4))

        inner = ttk.Frame(bar)
        inner.pack(fill="x")

        self._status_var = tk.StringVar(value="Pronto")
        self._time_var = tk.StringVar(value="")
        ttk.Label(inner, textvariable=self._status_var, foreground="#444444").pack(side="left")
        ttk.Label(inner, textvariable=self._time_var, foreground="#888888").pack(side="right")

    def _setup_terminal_tags(self) -> None:
        t = self._terminal
        t.tag_configure("cache", foreground=_C_CACHE)
        t.tag_configure("erro", foreground=_C_ERRO, font=(_T_FONT[0], _T_FONT[1], "bold"))
        t.tag_configure("header", foreground=_C_HEADER, font=(_T_FONT[0], _T_FONT[1], "bold"))
        t.tag_configure("storage", foreground=_C_STORAGE)
        t.tag_configure("auth", foreground=_C_AUTH)
        t.tag_configure("ok", foreground=_C_OK, font=(_T_FONT[0], _T_FONT[1], "bold"))
        t.tag_configure("warn", foreground=_C_WARN)

    @staticmethod
    def _tag_for_line(line: str) -> "str | None":
        stripped = line.strip()
        low = line.lower()
        if "[cache]" in low:
            return "cache"
        if "[erro" in low:
            return "erro"
        if "aviso" in low:
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

    def _write_terminal(self, text: str) -> None:
        t = self._terminal
        t.configure(state=tk.NORMAL)
        for line in text.splitlines(keepends=True):
            tag = self._tag_for_line(line)
            t.insert(tk.END, line, tag) if tag else t.insert(tk.END, line)
        t.see(tk.END)
        t.configure(state=tk.DISABLED)

    def _clear_terminal(self) -> None:
        self._terminal.configure(state=tk.NORMAL)
        self._terminal.delete("1.0", tk.END)
        self._terminal.configure(state=tk.DISABLED)

    def _poll_queue(self) -> None:
        try:
            while True:
                text = self._out_queue.get_nowait()
                self._write_terminal(text)
        except queue.Empty:
            pass
        finally:
            self.root.after(50, self._poll_queue)

    # -----------------------------------------------------------------------
    # Ações
    # -----------------------------------------------------------------------

    def _validated_site(self) -> "str | None":
        site = self._site_var.get().strip()
        if not site:
            messagebox.showwarning("Domínio necessário", "Informe o domínio antes de executar.")
            return None
        return site

    def _on_generate(self) -> None:
        if self._running:
            return
        site = self._validated_site()
        if not site:
            return

        try:
            min_impr = int(self._min_impr_var.get().strip() or PODA_MIN_IMPRESSIONS)
            if min_impr < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Piso inválido", "O piso de impressões deve ser um inteiro >= 0.")
            return

        try:
            days_back = int(self._days_var.get().strip() or PODA_DAYS_BACK)
            if days_back <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Janela inválida", "A janela deve ser um inteiro de dias > 0.")
            return

        exports = [p for p in self._export_var.get().split(os.pathsep) if p.strip()]

        params = {
            "site": site,
            "min_impressions": min_impr,
            "days_back": days_back,
            "gsc_exports": exports,
            "no_cache": self._no_cache_var.get(),
            "home_fallback": self._home_fallback_var.get(),
        }
        self._start("plan", params, f"Gerando plano — {site}")

    def _on_pick_exports(self) -> None:
        """Seleciona os arquivos exportados do relatório 'Páginas' do GSC."""
        paths = filedialog.askopenfilenames(
            title="Export do relatório 'Páginas' do GSC",
            filetypes=[("Export GSC", "*.csv *.xlsx *.txt"), ("Todos", "*.*")],
        )
        if paths:
            self._export_var.set(os.pathsep.join(paths))

    def _on_compile(self) -> None:
        if self._running:
            return
        site = self._validated_site()
        if not site:
            return

        csv_path = self._result_store.get("csv_path") or latest_poda_csv(normalize_domain(site))
        if not csv_path:
            messagebox.showinfo(
                "Plano não encontrado",
                "Nenhum *_poda.csv para este domínio. Gere o plano primeiro (Etapa 1).",
            )
            return

        if not messagebox.askyesno(
            "Compilar plano",
            "O CSV já foi revisado por um analista?\n\n"
            "URLs marcadas 'revisar' NÃO entram no bloco — apenas as ações "
            "definidas (410/404/301) são compiladas.",
        ):
            return

        self._start("compile", {"site": site, "csv_path": csv_path}, f"Compilando — {site}")

    def _start(self, mode: str, params: dict, status: str) -> None:
        self._running = True
        self._set_buttons_state(tk.DISABLED)
        self._status_var.set(status)
        self._time_var.set(f"Iniciado: {datetime.now():%H:%M:%S}")
        run_poda_task(mode, params, self._out_queue, self._on_task_done, self._result_store)

    def _on_task_done(self) -> None:
        self.root.after(0, self._on_task_done_ui)

    def _on_task_done_ui(self) -> None:
        self._running = False
        self._set_buttons_state(tk.NORMAL)
        self._status_var.set("Pronto")
        self._time_var.set(f"Concluído: {datetime.now():%H:%M:%S}")

    def _set_buttons_state(self, state) -> None:
        for btn in (self._gen_btn, self._csv_btn, self._compile_btn):
            btn.configure(state=state)

    def _on_open_csv(self) -> None:
        """Abre o CSV do plano (o gerado nesta sessão ou o mais recente)."""
        site = self._site_var.get().strip()
        csv_path = self._result_store.get("csv_path")
        if not csv_path and site:
            csv_path = latest_poda_csv(normalize_domain(site))
        if csv_path and os.path.exists(csv_path):
            os.startfile(csv_path)
        else:
            messagebox.showinfo(
                "CSV não encontrado",
                "Nenhum *_poda.csv para este domínio. Gere o plano primeiro (Etapa 1).",
            )

    def _on_open_folder(self) -> None:
        site = self._site_var.get().strip()
        if site:
            safe_domain = re.sub(r"[^\w\-.]", "_", normalize_domain(site))
            # Abre direto a pasta dedicada de poda; cai para a do domínio /
            # relatorios se ainda não houver nada gerado.
            folder = os.path.join(_BASE_DIR, "relatorios", safe_domain, "poda")
            if not os.path.isdir(folder):
                folder = os.path.join(_BASE_DIR, "relatorios", safe_domain)
            if not os.path.isdir(folder):
                folder = os.path.join(_BASE_DIR, "relatorios")
        else:
            folder = os.path.join(_BASE_DIR, "relatorios")
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)
