"""
batch.py — Orquestrador do modo lote (headless) do posicao.py.

Roda o pipeline de posicionamento para uma lista de domínios, sequencialmente,
isolando erros por site (um site que falha não interrompe os demais).

Componentes:
    parse_sites_file(path)        → lê sites.txt (um domínio/linha, # comenta)
    run_batch(sites, pipeline_fn) → executa pipeline_fn(site) para cada site
    format_site_summary(result)   → linha-resumo ASCII de um resultado
    write_batch_report(results)   → CSV consolidado em relatorios/_batch/

O orquestrador não conhece a implementação do pipeline — recebe uma função
`pipeline_fn(site) -> dict` (resumo de posicao.run_pipeline), o que mantém
este módulo puro e testável com mocks.
"""

import csv
import os

# Importa o MÓDULO (não a constante) para respeitar redirecionamentos de
# RELATORIOS_DIR feitos em runtime (ex.: isolamento dos testes no conftest).
from core import storage

# Ordem fixa dos vereditos de conteúdo nas colunas do CSV
VERDICT_KEYS = ("ok", "atencao", "over_otimizado", "raso")


# ---------------------------------------------------------------------------
# Arquivo de sites
# ---------------------------------------------------------------------------


def parse_sites_file(path: str) -> list:
    """
    Lê um arquivo de sites: um domínio por linha.

    - Linhas vazias são ignoradas.
    - Linhas iniciadas com '#' são comentários.
    - Comentários inline ('dominio.com  # nota') também são removidos.
    - Espaços nas bordas são descartados.

    Levanta FileNotFoundError se o arquivo não existe e ValueError se nenhum
    domínio válido for encontrado.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Arquivo de sites não encontrado: {path}")

    sites = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if line:
                sites.append(line)

    if not sites:
        raise ValueError(f"Nenhum domínio válido encontrado em: {path}")
    return sites


# ---------------------------------------------------------------------------
# Execução do lote
# ---------------------------------------------------------------------------


def format_site_summary(result: dict) -> str:
    """
    Linha-resumo ASCII de um resultado do lote (health + grade + snapshots).

    Exemplos:
        [OK]   exemplo.com.br            health 70.7 (Bom)   snapshots: 5
        [ERRO] outro.com.br              Falha ao consultar Search Analytics...
    """
    site = result.get("site", "?")
    if not result.get("ok"):
        return f"[ERRO] {site:<28} {result.get('error', 'erro desconhecido')}"

    s = result.get("summary") or {}
    score = s.get("health_score")
    grade = s.get("health_grade")
    snaps = s.get("snapshot_count", 0)
    if score is None:
        return f"[OK]   {site:<28} sem dados (0 URLs no sitemap)   snapshots: {snaps}"
    return f"[OK]   {site:<28} health {score:.1f} ({grade})   snapshots: {snaps}"


def run_batch(sites: list, pipeline_fn) -> list:
    """
    Executa pipeline_fn(site) para cada site, em sequência.

    Qualquer exceção em um site é capturada e registrada — os demais sites
    continuam. Imprime uma linha-resumo após cada site e um recap ao final.

    Retorna lista de resultados, na ordem de entrada:
    [
        {"site": str, "ok": True,  "summary": dict, "error": None},
        {"site": str, "ok": False, "summary": None, "error": str},
        ...
    ]
    """
    results = []
    total = len(sites)

    for idx, site in enumerate(sites, start=1):
        print(f"\n[batch] ({idx}/{total}) Iniciando: {site}")
        try:
            summary = pipeline_fn(site)
            result = {"site": site, "ok": True, "summary": summary, "error": None}
        except Exception as exc:  # noqa: BLE001 — isolamento por site é o objetivo
            result = {"site": site, "ok": False, "summary": None, "error": str(exc)}
            print(f"[batch] ERRO em {site}: {exc}")
        results.append(result)
        print(f"[batch] {format_site_summary(result)}")

    print("\n" + "=" * 62)
    print("  Resumo do lote")
    print("=" * 62)
    for result in results:
        print(f"  {format_site_summary(result)}")
    ok_count = sum(1 for r in results if r["ok"])
    print("-" * 62)
    print(f"  {ok_count}/{total} site(s) concluido(s) com sucesso.")
    print("=" * 62 + "\n")

    return results


# ---------------------------------------------------------------------------
# Relatório consolidado do lote
# ---------------------------------------------------------------------------


def write_batch_report(results: list, date: str) -> str:
    """
    Grava o resumo consolidado do lote em:
        relatorios/_batch/{date}_resumo.csv

    Colunas: Site, Status, Health, Grade, Posicao Media, CTR(%),
             Grupos Canibalizacao, Conteudo OK, Conteudo Atencao,
             Conteudo Over-otimizado, Conteudo Raso, Snapshots, Erro

    Encoding utf-8-sig para compatibilidade com Excel no Windows.
    Retorna o caminho do arquivo gerado.
    """
    batch_dir = os.path.join(storage.RELATORIOS_DIR, "_batch")
    os.makedirs(batch_dir, exist_ok=True)
    filepath = os.path.join(batch_dir, f"{date}_resumo.csv")

    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Site",
                "Status",
                "Health",
                "Grade",
                "Posicao Media",
                "CTR(%)",
                "Grupos Canibalizacao",
                "Conteudo OK",
                "Conteudo Atencao",
                "Conteudo Over-otimizado",
                "Conteudo Raso",
                "Snapshots",
                "Erro",
            ]
        )
        for result in results:
            if result.get("ok"):
                s = result.get("summary") or {}
                verdicts = s.get("content_verdicts") or {}
                cann = s.get("cannibalization_groups")
                writer.writerow(
                    [
                        result.get("site", ""),
                        "OK",
                        s.get("health_score", ""),
                        s.get("health_grade", ""),
                        s.get("avg_position", ""),
                        s.get("ctr", ""),
                        cann if cann is not None else "",
                        *[verdicts.get(k, 0) for k in VERDICT_KEYS],
                        s.get("snapshot_count", ""),
                        "",
                    ]
                )
            else:
                writer.writerow(
                    [
                        result.get("site", ""),
                        "ERRO",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        result.get("error", ""),
                    ]
                )

    return filepath
