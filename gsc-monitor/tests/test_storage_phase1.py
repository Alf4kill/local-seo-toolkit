"""
test_storage_phase1.py — Testa a reorganização de pastas e funções CSV da Fase 1.
Execute com:  py test_storage_phase1.py
Remove os arquivos/pastas criados ao final.
"""

import csv
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.storage import (
    _safe_filename,
    _get_domain_dir,
    _report_path,
    save_detailed_report,
    save_consolidated_report,
    save_csv_indexacao,
    save_position_report,
    save_csv_posicao,
)

DOMAIN = "www.exemplo.com.br"
DATE   = "2026-05-30"

# ---------------------------------------------------------------------------
# Dados fake para os testes
# ---------------------------------------------------------------------------
FAKE_DETAILED = {
    "site": DOMAIN,
    "date": DATE,
    "urls": [
        {
            "url":           "https://www.exemplo.com.br/",
            "category":      "indexed",
            "verdict":       "PASS",
            "coverageState": "Submitted and indexed",
            "lastCrawlTime": "2026-05-28T10:00:00Z",
        },
        {
            "url":           "https://www.exemplo.com.br/contato",
            "category":      "not_indexed",
            "verdict":       "FAIL",
            "coverageState": "Crawled - currently not indexed",
            "lastCrawlTime": "2026-05-20T08:00:00Z",
        },
    ],
}

FAKE_CONSOLIDATED = {
    "site":       DOMAIN,
    "date":       DATE,
    "total_urls": 2,
    "summary": {
        "indexed":     {"total": 1, "percent": 50.0},
        "not_indexed": {"total": 1, "percent": 50.0},
        "warning":     {"total": 0, "percent": 0.0},
        "unknown":     {"total": 0, "percent": 0.0},
    },
}

FAKE_POSITION_REPORT = {
    "site": DOMAIN,
    "date": DATE,
    "urls": [
        {"url": "https://www.exemplo.com.br/",       "position": 3.2,  "clicks": 120, "impressions": 1500, "ctr": 8.0,  "has_data": True},
        {"url": "https://www.exemplo.com.br/contato", "position": None, "clicks": 0,   "impressions": 0,    "ctr": 0.0,  "has_data": False},
    ],
}


# ---------------------------------------------------------------------------
# Helpers de verificação
# ---------------------------------------------------------------------------
def check(condition: bool, msg: str) -> None:
    status = "[OK]" if condition else "[FALHA]"
    print(f"  {status}  {msg}")
    if not condition:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------
def test_pasta_por_dominio():
    print("\n--- Teste: criação de pasta por domínio ---")
    folder = _get_domain_dir(DOMAIN)
    check(os.path.isdir(folder), f"Pasta criada: {folder}")
    safe = _safe_filename(DOMAIN)
    check(safe in folder, f"Nome da pasta contém o domínio seguro: {safe}")


def test_caminhos():
    print("\n--- Teste: geração de caminhos ---")
    p = _report_path(DOMAIN, DATE, "posicao", "json")
    check(p.endswith(f"{DATE}_posicao.json"),           "Sufixo JSON posição correto")
    check(_safe_filename(DOMAIN) in p,                  "Pasta do domínio no caminho")

    p2 = _report_path(DOMAIN, DATE, "indexacao", "csv")
    check(p2.endswith(f"{DATE}_indexacao.csv"),         "Sufixo CSV indexação correto")


def test_save_indexacao_json():
    print("\n--- Teste: save_detailed_report ---")
    path = save_detailed_report(DOMAIN, DATE, FAKE_DETAILED)
    check(os.path.isfile(path), f"Arquivo criado: {path}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    check(data["site"] == DOMAIN, "Campo 'site' correto no JSON")
    check(len(data["urls"]) == 2, "Quantidade de URLs correta no JSON")


def test_save_csv_indexacao():
    print("\n--- Teste: save_csv_indexacao ---")
    path = save_csv_indexacao(DOMAIN, DATE, FAKE_DETAILED)
    check(os.path.isfile(path), f"Arquivo CSV criado: {path}")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    check(rows[0] == ["URL", "Categoria", "Verdict", "Estado de Cobertura", "Ultimo Rastreamento"],
          "Cabeçalho CSV de indexação correto")
    check(len(rows) == 3, "2 linhas de dados + 1 cabeçalho")
    check(rows[1][1] == "indexed",     "Categoria da 1ª URL correta")
    check(rows[2][1] == "not_indexed", "Categoria da 2ª URL correta")


def test_save_csv_posicao():
    print("\n--- Teste: save_csv_posicao ---")
    path = save_csv_posicao(DOMAIN, DATE, FAKE_POSITION_REPORT)
    check(os.path.isfile(path), f"Arquivo CSV criado: {path}")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    check(rows[0] == ["URL", "Posicao", "Cliques", "Impressoes", "CTR(%)", "Com Dados"],
          "Cabeçalho CSV de posição correto")
    check(len(rows) == 3,          "2 linhas de dados + 1 cabeçalho")
    check(rows[1][5] == "Sim",     "URL com dados marcada como Sim")
    check(rows[2][5] == "Nao",     "URL sem dados marcada como Nao")
    check(rows[2][1] == "",        "Posição vazia para URL sem dados")


def test_sem_colisao_dominio():
    print("\n--- Teste: dois domínios ficam em pastas separadas ---")
    d1 = _get_domain_dir("www.site-a.com.br")
    d2 = _get_domain_dir("www.site-b.com.br")
    check(d1 != d2, "Caminhos distintos para domínios distintos")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 55)
    print("  GSC Monitor — Fase 1: Testes de storage.py")
    print("=" * 55)

    try:
        test_pasta_por_dominio()
        test_caminhos()
        test_save_indexacao_json()
        test_save_csv_indexacao()
        test_save_csv_posicao()
        test_sem_colisao_dominio()

        print("\n" + "=" * 55)
        print("  TODOS OS TESTES PASSARAM")
        print("=" * 55)
    finally:
        # Limpeza: remove as pastas criadas pelos testes
        for d in [DOMAIN, "www.site-a.com.br", "www.site-b.com.br"]:
            folder = _get_domain_dir(d)
            if os.path.isdir(folder):
                shutil.rmtree(folder)
        print("\n[cleanup] Pastas de teste removidas.")
