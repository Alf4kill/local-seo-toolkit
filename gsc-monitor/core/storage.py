"""
storage.py — Persistência de dados: historico.json e relatórios por execução.

Estrutura de pastas (a partir desta versão):
    relatorios/
        {dominio}/
            {data}_indexacao.json
            {data}_indexacao_consolidado.json
            {data}_indexacao.txt
            {data}_indexacao.csv
            {data}_posicao.json
            {data}_posicao.xlsx
            {data}_posicao.txt
            {data}_posicao.csv

Arquivos gerados por versões anteriores (formato plano) são mantidos intactos.
"""

import csv
import json
import os
import re

from config import BASE_DIR

HISTORICO_PATH = os.path.join(BASE_DIR, "historico.json")
RELATORIOS_DIR = os.path.join(BASE_DIR, "relatorios")


# ---------------------------------------------------------------------------
# Helpers de caminho
# ---------------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    """Remove caracteres inválidos para uso em nome de arquivo ou pasta."""
    return re.sub(r"[^\w\-.]", "_", name)


def _get_domain_dir(site: str) -> str:
    """
    Retorna (e cria se necessário) o diretório exclusivo do domínio:
        relatorios/{safe_domain}/
    """
    domain_folder = os.path.join(RELATORIOS_DIR, _safe_filename(site))
    os.makedirs(domain_folder, exist_ok=True)
    return domain_folder


def _report_path(site: str, date: str, suffix: str, ext: str) -> str:
    """
    Monta o caminho completo de um arquivo de relatório.
    Exemplo: relatorios/www.exemplo.com.br/2026-05-30_posicao.json
    """
    return os.path.join(_get_domain_dir(site), f"{date}_{suffix}.{ext}")


# ---------------------------------------------------------------------------
# historico.json  (arquivo global, não por domínio)
# ---------------------------------------------------------------------------

def load_historico() -> list[dict]:
    """Lê historico.json e retorna a lista de snapshots. Retorna [] se vazio."""
    if not os.path.exists(HISTORICO_PATH):
        return []
    with open(HISTORICO_PATH, encoding="utf-8") as f:
        try:
            data = json.load(f)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []


def append_historico(snapshot: dict) -> None:
    """
    Faz append de um novo snapshot no historico.json.
    Cria o arquivo se não existir. Nunca sobrescreve entradas anteriores.
    """
    historico = load_historico()
    historico.append(snapshot)
    with open(HISTORICO_PATH, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)
    print(f"[storage] Snapshot salvo em: {HISTORICO_PATH}")


def build_snapshot(site: str, date: str, url_results: list[dict]) -> dict:
    """Monta o dicionário de snapshot para o historico.json."""
    from collections import Counter
    counts = Counter(r["category"] for r in url_results)
    return {
        "site":        site,
        "date":        date,
        "total_urls":  len(url_results),
        "indexed":     counts.get("indexed",     0),
        "not_indexed": counts.get("not_indexed", 0),
        "warning":     counts.get("warning",     0),
        "unknown":     counts.get("unknown",     0),
    }


# ---------------------------------------------------------------------------
# Relatórios de indexação
# ---------------------------------------------------------------------------

def save_detailed_report(site: str, date: str, report: dict) -> str:
    """
    Salva o relatório detalhado em:
        relatorios/{site}/{date}_indexacao.json
    """
    filepath = _report_path(site, date, "indexacao", "json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[storage] Relatório detalhado salvo em: {filepath}")
    return filepath


def save_consolidated_report(site: str, date: str, report: dict) -> str:
    """
    Salva o relatório consolidado em:
        relatorios/{site}/{date}_indexacao_consolidado.json
    """
    filepath = _report_path(site, date, "indexacao_consolidado", "json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[storage] Relatório consolidado salvo em: {filepath}")
    return filepath


def save_text_report(site: str, date: str, detailed: dict, consolidated: dict) -> str:
    """
    Salva relatório legível em:
        relatorios/{site}/{date}_indexacao.txt
    """
    CATEGORIES = ("indexed", "not_indexed", "warning", "unknown")
    STATUS_LABELS = {
        "indexed":     "INDEXADO",
        "not_indexed": "NAO INDEXADO",
        "warning":     "AVISO",
        "unknown":     "DESCONHECIDO",
    }

    lines = []
    sep  = "=" * 70
    dash = "-" * 70

    lines.append(sep)
    lines.append(f"  RELATORIO DE INDEXACAO — {site}  ({date})")
    lines.append(sep)
    lines.append(f"  Total de URLs: {consolidated['total_urls']}")
    lines.append(dash)

    for cat in CATEGORIES:
        data    = consolidated["summary"].get(cat, {"total": 0, "percent": 0.0})
        label   = cat.replace("_", " ").capitalize()
        bar_len = int(data["percent"] / 5)
        bar     = "#" * bar_len
        lines.append(
            f"  {label:<15} {data['total']:>5}  ({data['percent']:>5.1f}%)  [{bar:<20}]"
        )

    lines.append(sep)
    lines.append("")
    lines.append("  DETALHE POR URL:")
    lines.append(dash)

    for entry in detailed["urls"]:
        cat   = entry["category"]
        label = STATUS_LABELS.get(cat, "DESCONHECIDO")
        lines.append(f"  [{label}]  {entry['url']}")
        if entry.get("coverageState"):
            lines.append(f"    Estado de cobertura : {entry['coverageState']}")
        if entry.get("lastCrawlTime"):
            lines.append(f"    Ultimo rastreamento : {entry['lastCrawlTime']}")
        lines.append("")

    lines.append(sep)

    filepath = _report_path(site, date, "indexacao", "txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[storage] Relatório .txt salvo em: {filepath}")
    return filepath


def save_csv_indexacao(site: str, date: str, detailed: dict) -> str:
    """
    Salva o relatório de indexação em CSV:
        relatorios/{site}/{date}_indexacao.csv

    Colunas: URL | Categoria | Verdict | Estado de Cobertura | Ultimo Rastreamento

    Encoding utf-8-sig para compatibilidade com Excel no Windows
    (evita problema de acentuação ao abrir direto pelo Excel).
    """
    filepath = _report_path(site, date, "indexacao", "csv")
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "URL",
            "Categoria",
            "Verdict",
            "Estado de Cobertura",
            "Ultimo Rastreamento",
        ])
        for entry in detailed["urls"]:
            writer.writerow([
                entry["url"],
                entry["category"],
                entry.get("verdict",       ""),
                entry.get("coverageState", ""),
                entry.get("lastCrawlTime", ""),
            ])
    print(f"[storage] Relatório CSV de indexação salvo em: {filepath}")
    return filepath


# ---------------------------------------------------------------------------
# Relatórios de posicionamento
# ---------------------------------------------------------------------------

def save_position_report(site: str, date: str, report: dict) -> str:
    """
    Salva o relatório de posicionamento em:
        relatorios/{site}/{date}_posicao.json
    """
    filepath = _report_path(site, date, "posicao", "json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[storage] Relatório de posicionamento salvo em: {filepath}")
    return filepath


def save_excel_report(site: str, date: str, workbook) -> str:
    """
    Salva o relatório Excel em:
        relatorios/{site}/{date}_posicao.xlsx
    """
    filepath = _report_path(site, date, "posicao", "xlsx")
    workbook.save(filepath)
    print(f"[storage] Relatório Excel salvo em: {filepath}")
    return filepath


def save_position_txt(site: str, date: str, data: dict, report: dict) -> str:
    """
    Salva o relatório de posicionamento em:
        relatorios/{site}/{date}_posicao.txt
    """
    from reporters.position_reporter import build_position_txt_lines
    lines = build_position_txt_lines(site, date, data, report)

    filepath = _report_path(site, date, "posicao", "txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[storage] Relatório de posicionamento .txt salvo em: {filepath}")
    return filepath


# ---------------------------------------------------------------------------
# Histórico de posicionamento por URL (arquivo por domínio — Fase 4c)
# ---------------------------------------------------------------------------

def _historico_posicao_path(site: str) -> str:
    return os.path.join(_get_domain_dir(site), "historico_posicao.json")


def load_historico_posicao(site: str) -> dict:
    """Carrega o histórico de posicionamento por URL do domínio."""
    path = _historico_posicao_path(site)
    if not os.path.exists(path):
        return {"site": site, "snapshots": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "snapshots" in data:
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"site": site, "snapshots": []}


def append_historico_posicao(
    site: str,
    date: str,
    period: dict,
    rows: list,
    content_results: "dict | None" = None,
) -> None:
    """
    Adiciona (ou substitui) um snapshot de posicionamento por URL.
    Armazena apenas URLs com dados (has_data=True). Mantém os 30 mais recentes.

    Se content_results for fornecido (Move 2), anexa um resumo compacto da
    qualidade de conteúdo a cada URL analisada — permitindo correlacionar
    conteúdo × posição ao longo do tempo.
    """
    historico = load_historico_posicao(site)
    content_results = content_results or {}

    urls_snapshot = {}
    for r in rows:
        if not r.get("has_data"):
            continue
        entry = {
            "position":    r["position"],
            "clicks":      r["clicks"],
            "impressions": r["impressions"],
        }
        cq = content_results.get(r["url"])
        if cq:
            entry["content"] = {
                "verdict":   cq.get("verdict"),
                "density":   cq.get("keyword_density"),
                "words":     cq.get("word_count"),
                "diversity": cq.get("vocab_diversity"),
                "entities":  cq.get("entity_count"),
            }
        urls_snapshot[r["url"]] = entry

    # Deduplicação: remove snapshot do mesmo dia se existir
    historico["snapshots"] = [s for s in historico["snapshots"] if s.get("date") != date]
    historico["snapshots"].append({"date": date, "period": period, "urls": urls_snapshot})

    # Ordena e limita a 30 snapshots
    historico["snapshots"].sort(key=lambda s: s["date"])
    historico["snapshots"] = historico["snapshots"][-30:]

    path = _historico_posicao_path(site)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)
    print(f"[storage] Histórico de posicionamento atualizado: {os.path.basename(path)}")


def load_latest_consolidated(site: str) -> "dict | None":
    """
    Carrega o relatório consolidado de indexação mais recente do domínio.
    Retorna None se nenhum arquivo encontrado.
    """
    domain_dir = _get_domain_dir(site)
    try:
        files = sorted(
            [f for f in os.listdir(domain_dir) if f.endswith("_indexacao_consolidado.json")],
            reverse=True,
        )
    except OSError:
        return None
    if not files:
        return None
    try:
        with open(os.path.join(domain_dir, files[0]), encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_dashboard(site: str, html: str) -> str:
    """
    Salva o dashboard HTML em:
        relatorios/{site}/dashboard.html
    Sempre sobrescreve — é um arquivo único por domínio que reflete a última análise.
    """
    filepath = os.path.join(_get_domain_dir(site), "dashboard.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[storage] Dashboard salvo em: {filepath}")
    return filepath


def save_nlp_report(site: str, date: str, html: str) -> str:
    """
    Salva o relatório NLP detalhado em:
        relatorios/{site}/{date}_nlp.html
    Gerado automaticamente quando --nlp é usado em posicao.py.
    """
    filepath = _report_path(site, date, "nlp", "html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[storage] Relatório NLP salvo em: {filepath}")
    return filepath


def save_csv_posicao(site: str, date: str, report: dict) -> str:
    """
    Salva o relatório de posicionamento em CSV:
        relatorios/{site}/{date}_posicao.csv

    Colunas: URL | Posicao | Cliques | Impressoes | CTR(%) | Com Dados

    Encoding utf-8-sig para compatibilidade com Excel no Windows.
    """
    filepath = _report_path(site, date, "posicao", "csv")
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "URL",
            "Posicao",
            "Cliques",
            "Impressoes",
            "CTR(%)",
            "Com Dados",
        ])
        for row in report["urls"]:
            writer.writerow([
                row["url"],
                row["position"]  if row["has_data"] else "",
                row["clicks"],
                row["impressions"],
                row["ctr"]       if row["has_data"] else "",
                "Sim"            if row["has_data"] else "Nao",
            ])
    print(f"[storage] Relatório CSV de posicionamento salvo em: {filepath}")
    return filepath
