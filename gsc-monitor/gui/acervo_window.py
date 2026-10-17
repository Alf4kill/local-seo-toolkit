"""
acervo_window.py — Janela do Acervo histórico (app_acervo.py).

A janela é GUIADA porque a feature é sequencial e pouco óbvia: aferir uma vez,
backfill uma vez, e depois o diário para sempre. Cada etapa diz o que custa e
por que existe, e a próxima pendente fica destacada — é isso que faz a
ferramenta se explicar sozinha.

  ┌─────────────────────────────────────────────────────────────┐
  │  Domínio [________________]  [Verificar estado]             │
  │  A retenção do GSC é uma JANELA MÓVEL de ~16 meses: cada     │
  │  dia que passa apaga para sempre o dia mais antigo.         │
  │  ┌─ 1 · Aferir ───────────── ~8 req, não grava dado ──────┐ │
  │  ┌─ 2 · Backfill ─────────── 480 dias, uma vez ───────────┐ │
  │  ┌─ 3 · Diário ───────────── agende semanal ──────────────┐ │
  │  ┌─ Estado do acervo ────────────────────────────────────┐  │
  │  ┌─ Terminal ──────────────────────────────── [Limpar] ──┐  │
  │  Status: Pronto                            Concluído 14:32 │
  └─────────────────────────────────────────────────────────────┘

O que a janela NÃO faz: analisar. O acervo extrai e acumula; a análise acontece
depois, sobre o banco. Nenhum número aqui é veredito.
"""

import os
import queue
import re
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk

from config import ACERVO_ASSENTAMENTO_DIAS, ACERVO_DIAS_BACKFILL, GSC_DELAY_DAYS
from core.urls import normalize_domain

from gui import terminal
from gui.acervo_runner import run_acervo_task

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Texto de cada etapa: o que faz, o que custa, por que existe. É o conteúdo
# que transforma a janela num guia em vez de três botões soltos.
ETAPAS = (
    (
        "aferir",
        "1 · Aferir",
        "Mede, no seu site, se o teto de 50 mil linhas da API vale por dia ou por\n"
        "consulta — a documentação do Google não resolve isso. Decide o tamanho dos\n"
        "lotes. Custa ~8 requisições e NÃO grava nenhum dado. Rode uma vez por site.",
    ),
    (
        "backfill",
        "2 · Backfill",
        "Traz os 480 dias (~16 meses) que a API ainda guarda. Retoma de onde parou se\n"
        "for interrompido, e rodar de novo não duplica nada. Uma vez por site.",
    ),
    (
        "diario",
        "3 · Diário",
        "Re-busca a ponta que ainda assenta e incorpora os dias novos. É ESTE que faz\n"
        "os 16 meses virarem 2 anos — agende semanal. Sem ele, o backfill é uma foto e\n"
        "a janela continua andando.",
    ),
)


# ---------------------------------------------------------------------------
# Lógica pura — sem Tk, sem rede. É o que os testes exercitam.
# ---------------------------------------------------------------------------


def validar_dias(texto: str, padrao: int = ACERVO_DIAS_BACKFILL) -> int:
    """Converte o campo de dias. Vazio vira o padrão; inválido levanta."""
    texto = (texto or "").strip()
    if not texto:
        return padrao
    dias = int(texto)  # ValueError sobe para o chamador
    if dias <= 0:
        raise ValueError("a janela deve ser maior que zero")
    return dias


def montar_estado(
    afericao_em: "str | None",
    cobertura: list,
    provisorios: list,
    contagens: dict,
) -> dict:
    """Compõe o resumo do acervo a partir das leituras do store.

    Pura de propósito: a janela só formata o que sai daqui, e o teste cobre a
    composição sem abrir uma janela.
    """
    dias_por_status: dict = {}
    primeiro = ultimo = None
    for linha in cobertura:
        status = linha["status"]
        dias_por_status[status] = dias_por_status.get(status, 0) + (linha["dias"] or 0)
        if linha["primeiro"] and (primeiro is None or linha["primeiro"] < primeiro):
            primeiro = linha["primeiro"]
        if linha["ultimo"] and (ultimo is None or linha["ultimo"] > ultimo):
            ultimo = linha["ultimo"]

    # Cobertura de impressões do grão `query` = o tamanho da cauda que o GSC
    # anonimiza. Não é defeito do acervo, e precisa ficar visível.
    cauda = None
    for linha in cobertura:
        if linha["grao"] == "query" and linha.get("cobertura_media") is not None:
            cauda = linha["cobertura_media"]
            break

    return {
        "aferido": bool(afericao_em),
        "afericao_em": afericao_em,
        "primeiro_dia": primeiro,
        "ultimo_dia": ultimo,
        "dias_por_status": dias_por_status,
        "dias_ok": dias_por_status.get("ok", 0),
        "tem_buracos": bool(dias_por_status.get("teto") or dias_por_status.get("erro")),
        "provisorios": len(provisorios),
        "linhas": sum(contagens.values()),
        "cauda_anonimizada": cauda,
    }


def proximo_passo(estado: dict) -> str:
    """Qual etapa está pendente: 'aferir' | 'backfill' | 'diario'.

    A janela destaca o botão correspondente. É a diferença entre três botões
    soltos e um fluxo que se explica.
    """
    if not estado.get("aferido"):
        return "aferir"
    if not estado.get("dias_ok"):
        return "backfill"
    return "diario"


def comando_agendador(site: str) -> str:
    """Linha do schtasks para agendar o diário semanal."""
    script = os.path.join(_BASE_DIR, "acervo.py")
    return (
        'schtasks /Create /TN "GSC Acervo Semanal" /SC WEEKLY /D MON /ST 07:00 '
        f'/TR "py {script} diario --site {site}"'
    )


def formatar_estado(estado: dict) -> str:
    """Resumo do acervo em texto, para o painel de estado."""
    if not estado["aferido"] and not estado["dias_ok"]:
        return "Acervo vazio para este domínio. Comece pela etapa 1."

    partes = []
    if estado["primeiro_dia"] and estado["ultimo_dia"]:
        partes.append(f"período: {estado['primeiro_dia']} a {estado['ultimo_dia']}")
    partes.append(f"{estado['dias_ok']} dias com dado")
    partes.append(f"{estado['linhas']:,} linhas".replace(",", "."))

    if estado["cauda_anonimizada"] is not None:
        partes.append(
            f"o grão query vê {estado['cauda_anonimizada']:.0%} das impressões "
            "(o resto o GSC anonimiza)"
        )
    if estado["provisorios"]:
        janela = GSC_DELAY_DAYS + ACERVO_ASSENTAMENTO_DIAS
        partes.append(
            f"{estado['provisorios']} dias ainda assentando — não tire "
            f"conclusão da ponta (janela de {janela} dias)"
        )
    if estado["tem_buracos"]:
        partes.append("ATENÇÃO: há dias com erro ou no teto de linhas")
    return " · ".join(partes)


def ler_estado(site: str) -> dict:
    """Lê o estado do acervo no disco. Sem rede — só abre o SQLite local."""
    from core.urls import build_site_url
    from core.warehouse import plan, store

    propriedade = build_site_url(site)
    conn = store.abrir(normalize_domain(site))
    try:
        return montar_estado(
            store.ler_meta(conn, "afericao_em"),
            store.cobertura(conn, propriedade=propriedade),
            store.dias_provisorios(conn, propriedade=propriedade),
            {g: store.contar_linhas(conn, s["tabela"]) for g, s in plan.GRAOS.items()},
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Janela
# ---------------------------------------------------------------------------


class AcervoWindow:
    """Janela do Acervo histórico do GSC."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._out_queue = queue.Queue()
        self._running = False
        self._result_store = {}
        self._botoes = {}
        self._estado = montar_estado(None, [], [], {})

        self._setup_window()
        self._build_config_panel()
        self._build_steps_panel()
        self._build_state_panel()
        self._build_terminal_panel()
        self._build_status_bar()
        self._poll_queue()

    # -----------------------------------------------------------------------
    # Construção
    # -----------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.root.title("GSC Monitor — Acervo histórico")
        # Alta de propósito: as três etapas carregam a explicação da feature, e
        # a altura requerida pelo conteúdo é ~930px. Menos que isso comprime o
        # terminal na primeira abertura.
        self.root.geometry("900x900")
        self.root.minsize(780, 700)
        self.root.configure(bg="#f0f0f0")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

    def _build_config_panel(self) -> None:
        outer = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)  # terminal expande
        self._outer_frame = outer

        cfg = ttk.LabelFrame(outer, text="  Acervo — histórico de longo prazo  ", padding=(14, 10))
        cfg.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        cfg.columnconfigure(1, weight=1)

        ttk.Label(cfg, text="Domínio:").grid(row=0, column=0, sticky="w", pady=5)
        self._site_var = tk.StringVar()
        site_e = ttk.Entry(cfg, textvariable=self._site_var, width=44)
        site_e.grid(row=0, column=1, sticky="ew", padx=(8, 8), pady=5)
        site_e.bind("<Return>", lambda _: self._on_verificar())

        ttk.Button(cfg, text="Verificar estado", command=self._on_verificar, width=16).grid(
            row=0, column=2, sticky="e", pady=5
        )

        ttk.Label(
            cfg,
            text=(
                "A retenção do GSC é uma JANELA MÓVEL de ~16 meses: cada dia que passa apaga "
                "para sempre o dia mais\nantigo. O acervo traz o que ainda existe e acumula "
                "para frente, sem nunca apagar."
            ),
            foreground="#888888",
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

    def _build_steps_panel(self) -> None:
        steps = ttk.Frame(self._outer_frame)
        steps.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        steps.columnconfigure(0, weight=1)

        for i, (modo, titulo, descricao) in enumerate(ETAPAS):
            frame = ttk.LabelFrame(steps, text=f"  {titulo}  ", padding=(12, 8))
            frame.grid(row=i, column=0, sticky="ew", pady=(0, 6))
            frame.columnconfigure(0, weight=1)

            ttk.Label(frame, text=descricao, justify="left", foreground="#555555").grid(
                row=0, column=0, sticky="w"
            )

            lado = ttk.Frame(frame)
            lado.grid(row=0, column=1, sticky="e", padx=(12, 0))

            btn = ttk.Button(
                lado,
                text=f"Rodar {titulo.split(' · ')[1].lower()}",
                width=16,
                command=lambda m=modo: self._on_run(m),
            )
            btn.pack(side="top", pady=(0, 4))
            self._botoes[modo] = btn

            if modo == "backfill":
                linha = ttk.Frame(lado)
                linha.pack(side="top")
                ttk.Label(linha, text="dias:").pack(side="left")
                self._dias_var = tk.StringVar(value=str(ACERVO_DIAS_BACKFILL))
                ttk.Entry(linha, textvariable=self._dias_var, width=6).pack(
                    side="left", padx=(4, 0)
                )
            elif modo == "diario":
                ttk.Button(
                    lado, text="Copiar agendamento", width=18, command=self._on_copiar_agendador
                ).pack(side="top")

        # Opção transversal: ver o plano sem gastar requisição.
        rodape = ttk.Frame(steps)
        rodape.grid(row=len(ETAPAS), column=0, sticky="w", pady=(2, 0))
        self._dry_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            rodape,
            text="Só mostrar o plano, sem chamar a API (--dry-run)",
            variable=self._dry_run_var,
        ).pack(side="left")
        ttk.Button(rodape, text="Abrir pasta", width=12, command=self._on_open_folder).pack(
            side="left", padx=(18, 0)
        )

    def _build_state_panel(self) -> None:
        frame = ttk.LabelFrame(self._outer_frame, text="  Estado do acervo  ", padding=(12, 8))
        frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)

        self._estado_var = tk.StringVar(value="Informe o domínio e clique em Verificar estado.")
        ttk.Label(frame, textvariable=self._estado_var, justify="left", wraplength=840).grid(
            row=0, column=0, sticky="w"
        )

        self._proximo_var = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self._proximo_var, foreground="#0a7", font=("", 9, "bold")
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _build_terminal_panel(self) -> None:
        term_frame = ttk.Frame(self._outer_frame)
        term_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 6))
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
            bg=terminal.BG,
            fg=terminal.FG,
            font=terminal.FONT,
            wrap=tk.WORD,
            state=tk.DISABLED,
            relief=tk.FLAT,
            borderwidth=0,
            insertbackground=terminal.FG,
        )
        self._terminal.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        terminal.setup_tags(self._terminal)

        self._write_terminal(
            "  Acervo pronto.\n"
            "  Informe o domínio e clique em Verificar estado — a janela diz qual etapa falta.\n"
            "  Nada aqui analisa: o acervo extrai e acumula; a análise vem depois, sobre o banco.\n\n"
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

    # -----------------------------------------------------------------------
    # Terminal
    # -----------------------------------------------------------------------

    def _write_terminal(self, text: str) -> None:
        terminal.write(self._terminal, text)

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

    # -----------------------------------------------------------------------
    # Ações
    # -----------------------------------------------------------------------

    def _validated_site(self) -> "str | None":
        site = self._site_var.get().strip()
        if not site:
            messagebox.showwarning("Domínio necessário", "Informe o domínio antes de executar.")
            return None
        return site

    def _on_verificar(self) -> None:
        site = self._validated_site()
        if not site:
            return
        try:
            self._estado = ler_estado(site)
        except Exception as exc:  # noqa: BLE001 — leitura local; a janela segue viva
            messagebox.showerror("Falha ao ler o acervo", str(exc))
            return
        self._refresh_estado()

    def _refresh_estado(self) -> None:
        self._estado_var.set(formatar_estado(self._estado))
        proximo = proximo_passo(self._estado)
        titulo = dict((m, t) for m, t, _ in ETAPAS)[proximo]
        self._proximo_var.set(f"Próxima etapa: {titulo}")
        # Destaca a etapa pendente — o fluxo fica óbvio sem ler documentação.
        for modo, btn in self._botoes.items():
            btn.configure(style="Accent.TButton" if modo == proximo else "TButton")

    def _on_run(self, modo: str) -> None:
        if self._running:
            return
        site = self._validated_site()
        if not site:
            return

        params = {"site": site, "dry_run": self._dry_run_var.get()}

        if modo == "backfill":
            try:
                params["dias"] = validar_dias(self._dias_var.get())
            except ValueError:
                messagebox.showerror(
                    "Janela inválida", "A janela deve ser um número inteiro de dias maior que 0."
                )
                return
            if not self._estado["aferido"] and not params["dry_run"]:
                if not messagebox.askyesno(
                    "Aferir primeiro?",
                    "A aferição ainda não rodou para este domínio.\n\n"
                    "Ela custa ~8 requisições, não grava dado e define o tamanho dos lotes "
                    "do backfill. Rodar o backfill sem ela usa os valores conservadores "
                    "do config.\n\nSeguir com o backfill mesmo assim?",
                ):
                    return

        self._start(modo, params)

    def _on_copiar_agendador(self) -> None:
        site = self._validated_site()
        if not site:
            return
        comando = comando_agendador(site)
        self.root.clipboard_clear()
        self.root.clipboard_append(comando)
        self._write_terminal(
            "\n  Comando do agendador copiado para a área de transferência:\n"
            f"  {comando}\n"
            "  Cole num PowerShell como administrador. Exige token.json já gerado.\n\n"
        )

    def _start(self, modo: str, params: dict) -> None:
        self._running = True
        self._set_buttons_state(tk.DISABLED)
        self._status_var.set(f"{modo} — {params['site']}")
        self._time_var.set(f"Iniciado: {datetime.now():%H:%M:%S}")
        run_acervo_task(modo, params, self._out_queue, self._on_task_done, self._result_store)

    def _on_task_done(self) -> None:
        self.root.after(0, self._on_task_done_ui)

    def _on_task_done_ui(self) -> None:
        self._running = False
        self._set_buttons_state(tk.NORMAL)
        self._status_var.set("Pronto")
        self._time_var.set(f"Concluído: {datetime.now():%H:%M:%S}")
        # Relê o estado: a etapa concluída deixa de ser a próxima.
        site = self._site_var.get().strip()
        if site:
            try:
                self._estado = ler_estado(site)
                self._refresh_estado()
            except Exception:  # noqa: BLE001 — o painel é informativo, não crítico
                pass

    def _set_buttons_state(self, state) -> None:
        for btn in self._botoes.values():
            btn.configure(state=state)

    def _on_open_folder(self) -> None:
        site = self._site_var.get().strip()
        folder = os.path.join(_BASE_DIR, "relatorios")
        if site:
            safe = re.sub(r"[^\w\-.]", "_", normalize_domain(site))
            candidato = os.path.join(folder, safe, "acervo")
            if os.path.isdir(candidato):
                folder = candidato
            elif os.path.isdir(os.path.join(folder, safe)):
                folder = os.path.join(folder, safe)
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)
