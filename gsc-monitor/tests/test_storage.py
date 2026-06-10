"""
test_storage.py — storage.py: organização de pastas por domínio e exportação CSV.

O isolamento de RELATORIOS_DIR num diretório temporário é feito pelo conftest.py
(fixture de sessão), então os testes não tocam a pasta real `relatorios/` nem
precisam de limpeza manual.
"""

import csv
import json
import os

from core.storage import (
    _get_domain_dir,
    _report_path,
    _safe_filename,
    save_csv_indexacao,
    save_csv_posicao,
    save_detailed_report,
)

DOMAIN = "www.exemplo.com.br"
DATE = "2026-05-30"

FAKE_DETAILED = {
    "site": DOMAIN,
    "date": DATE,
    "urls": [
        {
            "url": "https://www.exemplo.com.br/",
            "category": "indexed",
            "verdict": "PASS",
            "coverageState": "Submitted and indexed",
            "lastCrawlTime": "2026-05-28T10:00:00Z",
        },
        {
            "url": "https://www.exemplo.com.br/contato",
            "category": "not_indexed",
            "verdict": "FAIL",
            "coverageState": "Crawled - currently not indexed",
            "lastCrawlTime": "2026-05-20T08:00:00Z",
        },
    ],
}

FAKE_POSITION_REPORT = {
    "site": DOMAIN,
    "date": DATE,
    "urls": [
        {
            "url": "https://www.exemplo.com.br/",
            "position": 3.2,
            "clicks": 120,
            "impressions": 1500,
            "ctr": 8.0,
            "has_data": True,
        },
        {
            "url": "https://www.exemplo.com.br/contato",
            "position": None,
            "clicks": 0,
            "impressions": 0,
            "ctr": 0.0,
            "has_data": False,
        },
    ],
}


def test_pasta_por_dominio():
    folder = _get_domain_dir(DOMAIN)
    assert os.path.isdir(folder)
    assert _safe_filename(DOMAIN) in folder


def test_caminhos():
    p = _report_path(DOMAIN, DATE, "posicao", "json")
    assert p.endswith(f"{DATE}_posicao.json")
    assert _safe_filename(DOMAIN) in p

    p2 = _report_path(DOMAIN, DATE, "indexacao", "csv")
    assert p2.endswith(f"{DATE}_indexacao.csv")


def test_save_indexacao_json():
    path = save_detailed_report(DOMAIN, DATE, FAKE_DETAILED)
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["site"] == DOMAIN
    assert len(data["urls"]) == 2


def test_save_csv_indexacao():
    path = save_csv_indexacao(DOMAIN, DATE, FAKE_DETAILED)
    assert os.path.isfile(path)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["URL", "Categoria", "Verdict", "Estado de Cobertura", "Ultimo Rastreamento"]
    assert len(rows) == 3  # 2 linhas de dados + cabeçalho
    assert rows[1][1] == "indexed"
    assert rows[2][1] == "not_indexed"


def test_save_csv_posicao():
    path = save_csv_posicao(DOMAIN, DATE, FAKE_POSITION_REPORT)
    assert os.path.isfile(path)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["URL", "Posicao", "Cliques", "Impressoes", "CTR(%)", "Com Dados"]
    assert len(rows) == 3
    assert rows[1][5] == "Sim"  # URL com dados
    assert rows[2][5] == "Nao"  # URL sem dados
    assert rows[2][1] == ""  # posição vazia quando não há dados


def test_sem_colisao_dominio():
    d1 = _get_domain_dir("www.site-a.com.br")
    d2 = _get_domain_dir("www.site-b.com.br")
    assert d1 != d2
