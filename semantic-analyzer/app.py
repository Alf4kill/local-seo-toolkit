"""
app.py — Interface gráfica do Semantic Analyzer.

Uso:
    py app.py

Mesmo estilo da GUI do gsc-monitor (Tkinter + terminal integrado), mas SEM
segundo call site: a janela monta as opções com analisar.make_options() e
chama analisar.run_analysis() — exatamente o pipeline do CLI.

Janela:
  - Fonte: pasta projeto base / pasta de .php/.html / arquivo .txt de URLs
  - Clustering: limiar, método, backend de embeddings, mínimo de caracteres
  - Cruzamento GSC opcional (escolhe a canônica por performance real)
  - Camada LLM local opcional: julgamento, diferenciação, grafo de links
  - Terminal com output em tempo real + botão para abrir o relatório HTML
"""

import os
import queue
import sys
import threading
import traceback
from datetime import datetime

_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

RELATORIOS_DIR = os.path.join(_BASE, "relatorios")


# ---------------------------------------------------------------------------
# Redirect de stdout para a queue (mesmo padrão do gsc-monitor/gui/runner.py)
# ---------------------------------------------------------------------------

class QueueStream:
    """Stream que redireciona write() para uma queue.Queue thread-safe."""
    encoding = "utf-8"

    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text: str) -> None:
        if text:
            self._q.put(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Worker (thread separada — a GUI nunca bloqueia)
# ---------------------------------------------------------------------------

def run_analysis_thread(params: dict, output_queue: queue.Queue,
                        done_callback, result_store: dict) -> None:
    """Roda analisar.run_analysis() em uma thread daemon, stdout → queue."""

    def worker() -> None:
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout = QueueStream(output_queue)
            sys.stderr = QueueStream(output_queue)

            # Import aqui dentro: a janela abre instantânea; os módulos de
            # análise (numpy etc.) só carregam ao executar.
            from analisar import make_options, run_analysis, AnalysisError

            opts = make_options(**params)
            print("=" * 55)
            print(f"  Semantic Analyzer — {datetime.now():%Y-%m-%d %H:%M:%S}")
            print("=" * 55)
            try:
                out_path = run_analysis(opts)
                result_store["report_path"] = out_path
            except AnalysisError as exc:
                print(f"\n[erro] {exc}")

        except Exception as exc:  # noqa: BLE001 — mostra qualquer falha no terminal
            print(f"\n[erro inesperado] {exc}")
            print(traceback.format_exc())
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            done_callback()

    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Paleta do terminal (estilo VS Code dark — igual ao gsc-monitor)
# ---------------------------------------------------------------------------
_T_BG   = "#1e1e1e"
_T_FG   = "#d4d4d4"
_T_FONT = ("Consolas", 9)

_TAG_COLORS = {
    "erro":   ("#f44747", True),
    "embed":  ("#4ec9b0", False),
    "llm":    ("#c586c0", False),
    "gsc":    ("#569cd6", False),
    "link":   ("#dcdcaa", False),
    "diff":   ("#dcdcaa", False),
    "header": ("#569cd6", True),
    "ok":     ("#4ec9b0", True),
}


class MainWindow:
    """Janela principal do Semantic Analyzer."""

    def __init__(self, root: tk.Tk) -> None:
        self.root          = root
        self._out_queue    = queue.Queue()
        self._running      = False
        self._result_store = {}

        self._setup_window()
        self._build_config_panel()
        self._build_terminal_panel()
        self._build_status_bar()
        self._poll_queue()

    # -- Janela --------------------------------------------------------------

    def _setup_window(self) -> None:
        self.root.title("Semantic Analyzer")
        self.root.geometry("900x760")
        self.root.minsize(760, 600)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

    # -- Painel de configuração ----------------------------------------------

    def _build_config_panel(self) -> None:
        outer = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)
        self._outer_frame = outer

        cfg = ttk.LabelFrame(outer, text="  Configuração  ", padding=(14, 10))
        cfg.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        cfg.columnconfigure(1, weight=1)

        # ── Fonte ─────────────────────────────────────────────────────────
        ttk.Label(cfg, text="Fonte:").grid(row=0, column=0, sticky="w", pady=4)
        self._src_type = tk.StringVar(value="primeweb")
        src_row = ttk.Frame(cfg)
        src_row.grid(row=0, column=1, columnspan=2, sticky="w", padx=(8, 0))
        ttk.Radiobutton(src_row, text="Projeto Base", value="primeweb",
                        variable=self._src_type).pack(side="left")
        ttk.Radiobutton(src_row, text="Pasta .php/.html", value="folder",
                        variable=self._src_type).pack(side="left", padx=(14, 0))
        ttk.Radiobutton(src_row, text="URLs (.txt)", value="urls",
                        variable=self._src_type).pack(side="left", padx=(14, 0))

        ttk.Label(cfg, text="Caminho:").grid(row=1, column=0, sticky="w", pady=4)
        path_row = ttk.Frame(cfg)
        path_row.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        path_row.columnconfigure(0, weight=1)
        self._src_path = tk.StringVar()
        src_e = ttk.Entry(path_row, textvariable=self._src_path)
        src_e.grid(row=0, column=0, sticky="ew")
        src_e.bind("<Return>", lambda _: self._on_execute())
        ttk.Button(path_row, text="Procurar...", width=11,
                   command=self._on_browse_source).grid(row=0, column=1, padx=(6, 0))

        # ── Clustering ────────────────────────────────────────────────────
        ttk.Label(cfg, text="Clustering:").grid(row=2, column=0, sticky="w", pady=(8, 4))
        cl_row = ttk.Frame(cfg)
        cl_row.grid(row=2, column=1, columnspan=2, sticky="w", padx=(8, 0))

        ttk.Label(cl_row, text="Limiar:").pack(side="left")
        self._threshold = tk.StringVar(value="0.85")
        ttk.Entry(cl_row, textvariable=self._threshold, width=6).pack(side="left", padx=(4, 14))

        ttk.Label(cl_row, text="Método:").pack(side="left")
        self._method = tk.StringVar(value="agglomerative")
        ttk.Combobox(cl_row, textvariable=self._method, width=14, state="readonly",
                     values=("agglomerative", "threshold")).pack(side="left", padx=(4, 14))

        ttk.Label(cl_row, text="Embeddings:").pack(side="left")
        self._backend = tk.StringVar(value="auto")
        ttk.Combobox(cl_row, textvariable=self._backend, width=7, state="readonly",
                     values=("auto", "st", "tfidf")).pack(side="left", padx=(4, 14))

        ttk.Label(cl_row, text="Mín. chars:").pack(side="left")
        self._min_chars = tk.StringVar(value="300")
        ttk.Entry(cl_row, textvariable=self._min_chars, width=6).pack(side="left", padx=(4, 0))

        # ── GSC (opcional) ────────────────────────────────────────────────
        ttk.Label(cfg, text="GSC:").grid(row=3, column=0, sticky="w", pady=4)
        gsc_row = ttk.Frame(cfg)
        gsc_row.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        gsc_row.columnconfigure(0, weight=1)
        self._gsc_path = tk.StringVar()
        ttk.Entry(gsc_row, textvariable=self._gsc_path).grid(row=0, column=0, sticky="ew")
        ttk.Button(gsc_row, text="Procurar...", width=11,
                   command=self._on_browse_gsc).grid(row=0, column=1, padx=(6, 0))
        ttk.Label(cfg, text="(opcional — pasta relatorios/<site> ou *_posicao.json do "
                            "gsc-monitor: canônica por performance real)",
                  foreground="#888888").grid(row=4, column=1, columnspan=2,
                                             sticky="w", padx=(8, 0))

        # ── Análises opcionais ────────────────────────────────────────────
        ttk.Label(cfg, text="Análises:").grid(row=5, column=0, sticky="w", pady=(8, 4))
        an_row = ttk.Frame(cfg)
        an_row.grid(row=5, column=1, columnspan=2, sticky="w", padx=(8, 0))

        self._do_llm      = tk.BooleanVar(value=False)
        self._do_diff     = tk.BooleanVar(value=False)
        self._do_links    = tk.BooleanVar(value=False)
        self._no_cache    = tk.BooleanVar(value=False)
        self._llm_unload  = tk.BooleanVar(value=False)
        ttk.Checkbutton(an_row, text="Julgamento LLM",
                        variable=self._do_llm).pack(side="left")
        ttk.Checkbutton(an_row, text="Diferenciação",
                        variable=self._do_diff).pack(side="left", padx=(14, 0))
        ttk.Checkbutton(an_row, text="Grafo de links",
                        variable=self._do_links).pack(side="left", padx=(14, 0))
        ttk.Checkbutton(an_row, text="Ignorar cache",
                        variable=self._no_cache).pack(side="left", padx=(14, 0))

        # ── LLM local (opcional) ──────────────────────────────────────────
        ttk.Label(cfg, text="LLM local:").grid(row=6, column=0, sticky="w", pady=4)
        llm_row = ttk.Frame(cfg)
        llm_row.grid(row=6, column=1, columnspan=2, sticky="w", padx=(8, 0))

        ttk.Label(llm_row, text="Modelo:").pack(side="left")
        self._llm_model = tk.StringVar()
        ttk.Entry(llm_row, textvariable=self._llm_model, width=24).pack(side="left", padx=(4, 4))
        ttk.Label(llm_row, text="(vazio = padrão)",
                  foreground="#888888").pack(side="left", padx=(0, 14))

        ttk.Label(llm_row, text="Backend:").pack(side="left")
        self._llm_backend = tk.StringVar(value="http")
        ttk.Combobox(llm_row, textvariable=self._llm_backend, width=12, state="readonly",
                     values=("http", "transformers")).pack(side="left", padx=(4, 14))

        ttk.Checkbutton(llm_row, text="Descarregar ao terminar",
                        variable=self._llm_unload).pack(side="left")

        ttk.Label(cfg, text="Contexto:").grid(row=7, column=0, sticky="w", pady=4)
        self._site_context = tk.StringVar()
        ttk.Entry(cfg, textvariable=self._site_context).grid(
            row=7, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=4)
        ttk.Label(cfg, text="(opcional — 1 linha sobre o site/nicho para o LLM, "
                            "ex.: 'canil que vende filhotes de Cane Corso')",
                  foreground="#888888").grid(row=8, column=1, columnspan=2,
                                             sticky="w", padx=(8, 0))

        # ── Botões ────────────────────────────────────────────────────────
        btn_row = ttk.Frame(cfg)
        btn_row.grid(row=9, column=0, columnspan=3, sticky="e", pady=(12, 2))

        ttk.Button(btn_row, text="Abrir pasta", width=12,
                   command=self._on_open_folder).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Abrir relatório", width=14,
                   command=self._on_open_report).pack(side="left", padx=(0, 8))
        self._exec_btn = ttk.Button(btn_row, text="  Executar  ",
                                    command=self._on_execute, style="Accent.TButton")
        self._exec_btn.pack(side="left")

    # -- Terminal --------------------------------------------------------------

    def _build_terminal_panel(self) -> None:
        outer = self._outer_frame
        term_frame = ttk.Frame(outer)
        term_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        term_frame.columnconfigure(0, weight=1)
        term_frame.rowconfigure(1, weight=1)

        hdr = ttk.Frame(term_frame)
        hdr.grid(row=0, column=0, sticky="ew")
        ttk.Label(hdr, text="  Terminal", font=("", 9, "bold")).pack(side="left")
        ttk.Button(hdr, text="Limpar", width=7,
                   command=self._clear_terminal).pack(side="right")
        ttk.Separator(term_frame, orient="horizontal").grid(
            row=0, column=0, sticky="ew", pady=(22, 0))

        self._terminal = scrolledtext.ScrolledText(
            term_frame, bg=_T_BG, fg=_T_FG, font=_T_FONT, wrap=tk.WORD,
            state=tk.DISABLED, relief=tk.FLAT, borderwidth=0,
            insertbackground=_T_FG,
        )
        self._terminal.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

        for tag, (color, bold) in _TAG_COLORS.items():
            font = (_T_FONT[0], _T_FONT[1], "bold") if bold else _T_FONT
            self._terminal.tag_configure(tag, foreground=color, font=font)

        self._write_terminal(
            "  Semantic Analyzer está pronto.\n"
            "  Escolha a fonte (pasta projeto base, pasta de páginas ou lista de URLs)\n"
            "  e clique em Executar. O relatório HTML abre pelo botão acima.\n\n"
        )

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        bar.grid(row=1, column=0, sticky="ew")
        ttk.Separator(bar, orient="horizontal").pack(fill="x", pady=(0, 4))
        inner = ttk.Frame(bar)
        inner.pack(fill="x")

        self._status_var = tk.StringVar(value="Pronto")
        self._time_var   = tk.StringVar(value="")
        ttk.Label(inner, textvariable=self._status_var,
                  foreground="#444444").pack(side="left")
        ttk.Label(inner, textvariable=self._time_var,
                  foreground="#888888").pack(side="right")

    # -- Colorização -----------------------------------------------------------

    @staticmethod
    def _tag_for_line(line: str) -> "str | None":
        stripped = line.strip()
        low = line.lower()
        if "[erro" in low:                                          return "erro"
        if stripped.startswith("=") or stripped.startswith("─"):    return "header"
        if "relatório salvo" in low or "relatorio salvo" in low:    return "ok"
        if "[embed]" in low:                                        return "embed"
        if "[llm]" in low:                                          return "llm"
        if "[gsc]" in low:                                          return "gsc"
        if "[link]" in low:                                         return "link"
        if "[diff]" in low:                                         return "diff"
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
                self._write_terminal(self._out_queue.get_nowait())
        except queue.Empty:
            pass
        finally:
            self.root.after(50, self._poll_queue)

    # -- Ações -------------------------------------------------------------------

    def _on_browse_source(self) -> None:
        if self._src_type.get() == "urls":
            path = filedialog.askopenfilename(
                title="Arquivo de URLs (um por linha)",
                filetypes=[("Texto", "*.txt"), ("Todos", "*.*")])
        else:
            path = filedialog.askdirectory(title="Pasta do site")
        if path:
            self._src_path.set(path)

    def _on_browse_gsc(self) -> None:
        path = filedialog.askdirectory(
            title="Pasta relatorios/<site> do gsc-monitor (ou cancele e cole "
                  "o caminho de um *_posicao.json)")
        if path:
            self._gsc_path.set(path)

    def _on_execute(self) -> None:
        if self._running:
            return

        src = self._src_path.get().strip()
        if not src:
            messagebox.showwarning("Fonte necessária",
                                   "Informe o caminho da fonte antes de executar.")
            return
        if not os.path.exists(src):
            messagebox.showerror("Caminho inválido", f"Não encontrado:\n{src}")
            return

        try:
            threshold = float(self._threshold.get().strip().replace(",", "."))
            if not 0.0 < threshold <= 1.0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Limiar inválido",
                                 "O limiar deve ser um número entre 0 e 1 (ex.: 0.85).")
            return

        try:
            min_chars = int(self._min_chars.get().strip() or "300")
            if min_chars < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Mínimo inválido",
                                 "Mín. chars deve ser um inteiro ≥ 0.")
            return

        params = {
            "threshold":   threshold,
            "method":      self._method.get(),
            "backend":     self._backend.get(),
            "min_chars":   min_chars,
            "no_cache":    self._no_cache.get(),
            "gsc":         self._gsc_path.get().strip() or None,
            "llm":         self._do_llm.get(),
            "differentiate": self._do_diff.get(),
            "linkgraph":   self._do_links.get(),
            "llm_backend": self._llm_backend.get(),
            "llm_model":   self._llm_model.get().strip() or None,
            "llm_unload":  self._llm_unload.get(),
            "site_context": self._site_context.get().strip() or None,
        }
        params[self._src_type.get()] = src   # primeweb / folder / urls

        self._running = True
        self._result_store = {}
        self._exec_btn.configure(state=tk.DISABLED, text="  Executando...  ")
        self._status_var.set(f"Executando — {os.path.basename(src)}")
        self._time_var.set(f"Iniciado: {datetime.now():%H:%M:%S}")

        run_analysis_thread(params, self._out_queue,
                            self._on_task_done, self._result_store)

    def _on_task_done(self) -> None:
        self.root.after(0, self._on_task_done_ui)

    def _on_task_done_ui(self) -> None:
        self._running = False
        self._exec_btn.configure(state=tk.NORMAL, text="  Executar  ")
        self._status_var.set("Pronto")
        self._time_var.set(f"Concluído: {datetime.now():%H:%M:%S}")

    def _on_open_report(self) -> None:
        """Abre o relatório HTML da última execução no navegador padrão."""
        import webbrowser
        path = self._result_store.get("report_path")
        if path and os.path.exists(path):
            webbrowser.open(f"file:///{os.path.abspath(path).replace(os.sep, '/')}")
        else:
            messagebox.showinfo("Relatório",
                                "Nenhum relatório nesta sessão ainda.\n"
                                "Execute uma análise primeiro (ou use Abrir pasta).")

    def _on_open_folder(self) -> None:
        """Abre a pasta de relatórios no gerenciador de arquivos."""
        os.makedirs(RELATORIOS_DIR, exist_ok=True)
        try:
            os.startfile(RELATORIOS_DIR)            # Windows
        except AttributeError:                      # Linux/Mac (dev)
            import subprocess
            subprocess.Popen(["xdg-open", RELATORIOS_DIR])


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def _apply_theme(root: tk.Tk) -> None:
    style = ttk.Style(root)
    for theme in ("vista", "xpnative", "winnative", "clam", "alt", "default"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break
    style.configure("Accent.TButton", font=("", 9, "bold"), padding=(6, 4))


def main() -> None:
    root = tk.Tk()
    _apply_theme(root)
    MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
