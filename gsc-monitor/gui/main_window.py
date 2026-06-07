"""
main_window.py — Janela principal do GSC Monitor.

Layout:
  ┌──────────────────────────────────────────────────────┐
  │  ┌─ Configuração ──────────────────────────────────┐ │
  │  │  Domínio   [_______________________]            │ │
  │  │  Análises  ☑ Indexação  ☑ Posicionamento        │ │
  │  │  Exportar  ☑ CSV  ☑ Excel  ☐ TXT               │ │
  │  │  Limite    [___]  ☐ Ignorar cache               │ │
  │  │                      [Abrir pasta] [  Executar ]│ │
  │  └─────────────────────────────────────────────────┘ │
  │  ┌─ Terminal ──────────────────────────── [Limpar] ┐ │
  │  │  (output em tempo real com cores)               │ │
  │  └─────────────────────────────────────────────────┘ │
  │  Status: Pronto                    Concluído 14:32   │
  └──────────────────────────────────────────────────────┘
"""

import os
import queue
import re
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk

from gui.runner import run_tasks

# ---------------------------------------------------------------------------
# Paleta do terminal  (estilo VS Code dark)
# ---------------------------------------------------------------------------
_T_BG = "#1e1e1e"
_T_FG = "#d4d4d4"
_T_FONT = ("Consolas", 9)

_C_CACHE = "#4ec9b0"  # verde-azulado — [CACHE]
_C_ERRO = "#f44747"  # vermelho       — [ERRO]
_C_HEADER = "#569cd6"  # azul           — linhas === e ───
_C_STORAGE = "#858585"  # cinza          — [storage]
_C_AUTH = "#c586c0"  # lilás          — [auth]
_C_OK = "#4ec9b0"  # verde          — Concluído
_C_WARN = "#dcdcaa"  # amarelo        — avisos gerais


class MainWindow:
    """Janela principal do GSC Monitor."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._out_queue = queue.Queue()
        self._running = False
        self._result_store = {}

        self._setup_window()
        self._build_config_panel()
        self._build_terminal_panel()
        self._build_status_bar()
        self._poll_queue()  # inicia o loop de polling da queue

    # -----------------------------------------------------------------------
    # Configuração da janela
    # -----------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.root.title("GSC Monitor")
        self.root.geometry("880x720")
        self.root.minsize(740, 560)
        self.root.configure(bg="#f0f0f0")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

    # -----------------------------------------------------------------------
    # Painel de configuração
    # -----------------------------------------------------------------------

    def _build_config_panel(self) -> None:
        outer = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)  # terminal expande

        cfg = ttk.LabelFrame(outer, text="  Configuração  ", padding=(14, 10))
        cfg.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        cfg.columnconfigure(1, weight=1)

        # ── Domínio ─────────────────────────────────────────────────────
        ttk.Label(cfg, text="Domínio:").grid(row=0, column=0, sticky="w", pady=5)
        self._site_var = tk.StringVar()
        site_e = ttk.Entry(cfg, textvariable=self._site_var, width=48)
        site_e.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=5)
        site_e.bind("<Return>", lambda _: self._on_execute())

        ttk.Label(
            cfg,
            text="Ex: www.exemplo.com.br  ou  sc-domain:exemplo.com.br",
            foreground="#888888",
        ).grid(row=1, column=1, columnspan=3, sticky="w", padx=(8, 0))

        # ── Análises ────────────────────────────────────────────────────
        ttk.Label(cfg, text="Análises:").grid(row=2, column=0, sticky="w", pady=(10, 4))
        self._do_index = tk.BooleanVar(value=True)
        self._do_pos = tk.BooleanVar(value=True)
        ttk.Checkbutton(cfg, text="Indexação", variable=self._do_index).grid(
            row=2, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Checkbutton(cfg, text="Posicionamento", variable=self._do_pos).grid(
            row=2, column=2, sticky="w", padx=(20, 0)
        )

        # ── Exportar ────────────────────────────────────────────────────
        ttk.Label(cfg, text="Exportar:").grid(row=3, column=0, sticky="w", pady=4)
        self._fmt_csv = tk.BooleanVar(value=True)
        self._fmt_excel = tk.BooleanVar(value=True)
        self._fmt_txt = tk.BooleanVar(value=False)

        fmt_row = ttk.Frame(cfg)
        fmt_row.grid(row=3, column=1, columnspan=3, sticky="w", padx=(8, 0))
        ttk.Checkbutton(fmt_row, text="CSV", variable=self._fmt_csv).pack(side="left")
        ttk.Checkbutton(fmt_row, text="Excel", variable=self._fmt_excel).pack(
            side="left", padx=(14, 0)
        )
        ttk.Checkbutton(fmt_row, text="TXT", variable=self._fmt_txt).pack(side="left", padx=(14, 0))
        ttk.Label(fmt_row, text="  (JSON salvo automaticamente)", foreground="#888888").pack(
            side="left", padx=(10, 0)
        )

        # ── Opções avançadas ─────────────────────────────────────────────
        ttk.Label(cfg, text="Opções:").grid(row=4, column=0, sticky="w", pady=(6, 4))

        opt_row = ttk.Frame(cfg)
        opt_row.grid(row=4, column=1, columnspan=3, sticky="w", padx=(8, 0))

        ttk.Label(opt_row, text="Limite de URLs:").pack(side="left")
        self._limit_var = tk.StringVar()
        ttk.Entry(opt_row, textvariable=self._limit_var, width=6).pack(side="left", padx=(6, 0))
        ttk.Label(opt_row, text="(vazio = todas)", foreground="#888888").pack(
            side="left", padx=(4, 22)
        )

        self._no_cache_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt_row, text="Ignorar cache  (–no-cache)", variable=self._no_cache_var
        ).pack(side="left")

        self._do_queries_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_row, text="Canibalização", variable=self._do_queries_var).pack(
            side="left", padx=(18, 0)
        )

        self._do_trends_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_row, text="Tendências", variable=self._do_trends_var).pack(
            side="left", padx=(14, 0)
        )

        self._do_nlp_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_row, text="NLP entidades", variable=self._do_nlp_var).pack(
            side="left", padx=(14, 0)
        )

        self._do_content_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_row, text="Qualidade conteúdo", variable=self._do_content_var).pack(
            side="left", padx=(14, 0)
        )

        # ── API Key Google (KG / NLP / Trends) ──────────────────────────────
        ttk.Label(cfg, text="API Key:").grid(row=5, column=0, sticky="w", pady=(6, 4))

        api_row = ttk.Frame(cfg)
        api_row.grid(row=5, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(6, 4))

        self._api_key_var = tk.StringVar(value=self._load_saved_api_key())
        ttk.Entry(api_row, textvariable=self._api_key_var, width=38, show="").pack(side="left")
        ttk.Label(api_row, text="  (opcional — KG, Trends, NLP)", foreground="#888888").pack(
            side="left"
        )

        # ── Botões ───────────────────────────────────────────────────────
        btn_row = ttk.Frame(cfg)
        btn_row.grid(row=6, column=0, columnspan=4, sticky="e", pady=(12, 2))

        self._open_btn = ttk.Button(
            btn_row, text="Abrir pasta", command=self._on_open_folder, width=12
        )
        self._open_btn.pack(side="left", padx=(0, 8))

        self._dash_btn = ttk.Button(
            btn_row, text="Dashboard", command=self._on_open_dashboard, width=12
        )
        self._dash_btn.pack(side="left", padx=(0, 8))

        self._exec_btn = ttk.Button(
            btn_row, text="  Executar  ", command=self._on_execute, style="Accent.TButton"
        )
        self._exec_btn.pack(side="left")

        # guarda referência para o painel externo (onde o terminal será adicionado)
        self._outer_frame = outer

    # -----------------------------------------------------------------------
    # Painel do terminal
    # -----------------------------------------------------------------------

    def _build_terminal_panel(self) -> None:
        outer = self._outer_frame

        term_frame = ttk.Frame(outer)
        term_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        term_frame.columnconfigure(0, weight=1)
        term_frame.rowconfigure(1, weight=1)

        # Cabeçalho do terminal
        hdr = ttk.Frame(term_frame)
        hdr.grid(row=0, column=0, sticky="ew")
        ttk.Label(hdr, text="  Terminal", font=("", 9, "bold")).pack(side="left")
        ttk.Button(hdr, text="Limpar", command=self._clear_terminal, width=7).pack(side="right")
        ttk.Separator(term_frame, orient="horizontal").grid(
            row=0, column=0, sticky="ew", pady=(22, 0)
        )

        # Widget de texto (terminal)
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

        # Mensagem inicial
        self._write_terminal(
            "  GSC Monitor está pronto.\n"
            "  Preencha o domínio, selecione as análises e clique em Executar.\n\n"
        )

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        bar.grid(row=1, column=0, sticky="ew")
        ttk.Separator(bar, orient="horizontal").pack(fill="x", pady=(0, 4))

        inner = ttk.Frame(bar)
        inner.pack(fill="x")

        self._status_var = tk.StringVar(value="Pronto")
        self._time_var = tk.StringVar(value="")
        self._health_var = tk.StringVar(value="")

        ttk.Label(inner, textvariable=self._status_var, foreground="#444444").pack(side="left")
        self._health_label = ttk.Label(
            inner, textvariable=self._health_var, foreground="#444444", font=("", 9, "bold")
        )
        self._health_label.pack(side="left", padx=(20, 0))
        ttk.Label(inner, textvariable=self._time_var, foreground="#888888").pack(side="right")

    # -----------------------------------------------------------------------
    # Colorização do terminal
    # -----------------------------------------------------------------------

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
    def _tag_for_line(line: str) -> str | None:
        """Retorna o nome do tag de cor para uma linha, ou None para a cor padrão."""
        stripped = line.strip()
        low = line.lower()
        if "[cache]" in low:
            return "cache"
        if "[erro" in low:
            return "erro"
        if stripped.startswith("=") or stripped.startswith("─"):
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

    # -----------------------------------------------------------------------
    # Polling da queue (Tkinter-safe)
    # -----------------------------------------------------------------------

    def _poll_queue(self) -> None:
        """
        Lê todas as mensagens disponíveis na queue e exibe no terminal.
        Executado a cada 50ms na thread principal via root.after().
        """
        try:
            while True:
                text = self._out_queue.get_nowait()
                self._write_terminal(text)
        except queue.Empty:
            pass
        finally:
            self.root.after(50, self._poll_queue)

    # -----------------------------------------------------------------------
    # Ações dos botões
    # -----------------------------------------------------------------------

    def _on_execute(self) -> None:
        if self._running:
            return

        # ── Valida entradas ─────────────────────────────────────────────
        site = self._site_var.get().strip()
        if not site:
            messagebox.showwarning("Domínio necessário", "Informe o domínio antes de executar.")
            return

        if not self._do_index.get() and not self._do_pos.get():
            messagebox.showwarning(
                "Nenhuma análise selecionada",
                "Selecione pelo menos uma análise (Indexação ou Posicionamento).",
            )
            return

        limit = None
        limit_str = self._limit_var.get().strip()
        if limit_str:
            try:
                limit = int(limit_str)
                if limit <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Limite inválido", "O limite deve ser um número inteiro positivo."
                )
                return

        # ── Monta parâmetros ─────────────────────────────────────────────
        formats = set()
        if self._fmt_csv.get():
            formats.add("csv")
        if self._fmt_excel.get():
            formats.add("excel")
        if self._fmt_txt.get():
            formats.add("txt")

        params = {
            "site": site,
            "do_indexation": self._do_index.get(),
            "do_position": self._do_pos.get(),
            "formats": formats,
            "limit": limit,
            "no_cache": self._no_cache_var.get(),
            "do_queries": self._do_queries_var.get(),
            "do_trends": self._do_trends_var.get(),
            "do_nlp": self._do_nlp_var.get(),
            "do_content": self._do_content_var.get(),
            "api_key": self._api_key_var.get().strip() or None,
        }

        self._start_execution(params)

    def _start_execution(self, params: dict) -> None:
        self._running = True
        self._result_store = {}
        self._health_var.set("")
        self._exec_btn.configure(state=tk.DISABLED, text="  Executando...  ")
        self._status_var.set(f"Executando — {params['site']}")
        self._time_var.set(f"Iniciado: {datetime.now():%H:%M:%S}")

        run_tasks(params, self._out_queue, self._on_task_done, self._result_store)

    def _on_task_done(self) -> None:
        """Chamado pela thread worker. Usa after(0) para thread-safety."""
        self.root.after(0, self._on_task_done_ui)

    def _on_task_done_ui(self) -> None:
        self._running = False
        self._exec_btn.configure(state=tk.NORMAL, text="  Executar  ")
        self._status_var.set("Pronto")
        self._time_var.set(f"Concluído: {datetime.now():%H:%M:%S}")

        health = self._result_store.get("health")
        if health:
            score = health["score"]
            grade = health["grade"]
            self._health_var.set(f"Saúde: {score:.0f}/100 — {grade}")
            _GRADE_COLORS = {
                "Excelente": "#1e7a1e",
                "Bom": "#2d7a2d",
                "Regular": "#b06000",
                "Crítico": "#b03030",
            }
            self._health_label.config(foreground=_GRADE_COLORS.get(grade, "#444444"))

    def _on_open_dashboard(self) -> None:
        """Abre o dashboard.html do domínio no navegador padrão."""
        import webbrowser

        # Tenta usar o caminho já conhecido do resultado da última execução
        dash_path = self._result_store.get("dashboard_path")

        if not dash_path:
            # Calcula o caminho a partir do domínio digitado
            site = self._site_var.get().strip()
            if not site:
                messagebox.showinfo("Dashboard", "Informe o domínio e execute a análise primeiro.")
                return
            domain = (
                site[len("sc-domain:") :]
                if site.startswith("sc-domain:")
                else site.removeprefix("https://").removeprefix("http://").rstrip("/")
            )
            safe = re.sub(r"[^\w\-.]", "_", domain)
            dash_path = os.path.join(_BASE_DIR, "relatorios", safe, "dashboard.html")

        if os.path.exists(dash_path):
            webbrowser.open(f"file:///{dash_path.replace(os.sep, '/')}")
        else:
            messagebox.showinfo(
                "Dashboard",
                "dashboard.html não encontrado.\nExecute a análise de posicionamento primeiro.",
            )

    @staticmethod
    def _load_saved_api_key() -> str:
        """Carrega a API key salva (arquivo ou env var), sem exibir erros."""
        try:
            from fetchers.knowledge_graph import load_api_key

            return load_api_key() or ""
        except Exception:
            return ""

    def _on_open_folder(self) -> None:
        """Abre no Explorer a pasta de relatórios do domínio informado."""
        site = self._site_var.get().strip()

        if site:
            if site.startswith("sc-domain:"):
                domain = site[len("sc-domain:") :]
            else:
                domain = site.removeprefix("https://").removeprefix("http://").rstrip("/")
            safe_domain = re.sub(r"[^\w\-.]", "_", domain)
            folder = os.path.join(_BASE_DIR, "relatorios", safe_domain)
            if not os.path.isdir(folder):
                folder = os.path.join(_BASE_DIR, "relatorios")
        else:
            folder = os.path.join(_BASE_DIR, "relatorios")

        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)


# ---------------------------------------------------------------------------
# Caminho base (gsc-monitor/) — necessário para _on_open_folder
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
