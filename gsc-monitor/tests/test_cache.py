"""
test_cache.py — cache.py: cache JSON por domínio (posição + inspeção).

Cobre: miss, set/get, atualização incremental por URL, expiração de TTL,
arquivo corrompido (não levanta) e o caminho use_cache=False do inspector (mock).
O isolamento de RELATORIOS_DIR num tmp é feito pelo conftest.py.
"""

import json
import os
import shutil
from datetime import datetime, timedelta

import pytest
from core.cache import (
    _cache_dir,
    _cache_path,
    get_inspect_cache,
    get_posicao_cache,
    set_inspect_cache,
    set_posicao_cache,
)

DOMAIN = "www.cache-test.com.br"
TODAY = "2026-05-30"
START = "2026-04-27"
END = "2026-05-27"

FAKE_API_DATA = {
    "https://www.cache-test.com.br/": {
        "clicks": 100,
        "impressions": 2000,
        "ctr": 5.0,
        "position": 3.2,
    },
    "https://www.cache-test.com.br/contato": {
        "clicks": 10,
        "impressions": 500,
        "ctr": 2.0,
        "position": 8.5,
    },
}

FAKE_INSPECT_RESULT = {
    "url": "https://www.cache-test.com.br/",
    "verdict": "PASS",
    "category": "indexed",
    "coverageState": "Submitted and indexed",
    "lastCrawlTime": "2026-05-28T10:00:00Z",
}


@pytest.fixture(autouse=True, scope="module")
def cleanup_test_cache():
    """Garante um diretório de cache limpo para este domínio de teste."""
    domain_dir = os.path.dirname(_cache_dir(DOMAIN))
    if os.path.isdir(domain_dir):
        shutil.rmtree(domain_dir)
    yield
    if os.path.isdir(domain_dir):
        shutil.rmtree(domain_dir)


def _force_expire(site: str, key_prefix: str, suffix: str) -> None:
    """Sobrescreve o cached_at com uma data antiga para simular expiração."""
    path = _cache_path(site, f"{key_prefix}_{suffix}")
    with open(path, encoding="utf-8") as f:
        entry = json.load(f)
    entry["cached_at"] = (datetime.now() - timedelta(hours=200)).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f)


# Os testes deste módulo são intencionalmente sequenciais: populam o cache,
# leem, e então expiram — refletindo o ciclo de vida real de um cache.


def test_posicao_miss():
    assert get_posicao_cache(DOMAIN, START, END) is None


def test_posicao_set_get():
    set_posicao_cache(DOMAIN, START, END, FAKE_API_DATA)

    path = _cache_path(DOMAIN, f"posicao_{START}_{END}")
    assert os.path.isfile(path)

    result = get_posicao_cache(DOMAIN, START, END)
    assert result == FAKE_API_DATA
    assert len(result) == 2


def test_inspect_miss():
    url = "https://www.cache-test.com.br/"
    assert get_inspect_cache(DOMAIN, TODAY, url) is None


def test_inspect_set_get():
    url = FAKE_INSPECT_RESULT["url"]
    set_inspect_cache(DOMAIN, TODAY, url, FAKE_INSPECT_RESULT)

    path = _cache_path(DOMAIN, f"inspect_{TODAY}")
    assert os.path.isfile(path)

    result = get_inspect_cache(DOMAIN, TODAY, url)
    assert result is not None
    assert result["category"] == "indexed"
    assert result["verdict"] == "PASS"


def test_inspect_incremental():
    url2 = "https://www.cache-test.com.br/contato"
    result2 = {
        "url": url2,
        "verdict": "FAIL",
        "category": "not_indexed",
        "coverageState": "Crawled - currently not indexed",
        "lastCrawlTime": "",
    }
    set_inspect_cache(DOMAIN, TODAY, url2, result2)

    # Ambas as URLs devem coexistir no mesmo arquivo (atualização incremental).
    path = _cache_path(DOMAIN, f"inspect_{TODAY}")
    with open(path, encoding="utf-8") as f:
        entry = json.load(f)

    assert FAKE_INSPECT_RESULT["url"] in entry["data"]  # URL 1 preservada
    assert url2 in entry["data"]  # URL 2 inserida
    assert len(entry["data"]) == 2

    r2 = get_inspect_cache(DOMAIN, TODAY, url2)
    assert r2 is not None
    assert r2["category"] == "not_indexed"


def test_posicao_ttl_expirado():
    _force_expire(DOMAIN, "posicao", f"{START}_{END}")
    assert get_posicao_cache(DOMAIN, START, END) is None


def test_inspect_ttl_expirado():
    _force_expire(DOMAIN, "inspect", TODAY)
    url = FAKE_INSPECT_RESULT["url"]
    assert get_inspect_cache(DOMAIN, TODAY, url) is None


def test_corrupcao():
    path = _cache_path(DOMAIN, "posicao_corrupto")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{isso nao e json valido!!!")

    # Arquivo corrompido deve retornar None, sem levantar exceção.
    assert get_posicao_cache(DOMAIN, "2020-01-01", "corrupto") is None


def test_inspector_use_cache_false():
    """use_cache=False deve pular o cache e chamar a API (mock)."""
    # Popula o cache com um resultado "indexed"...
    url = "https://www.cache-test.com.br/pagina"
    cached_result = {
        "url": url,
        "verdict": "PASS",
        "category": "indexed",
        "coverageState": "Submitted and indexed",
        "lastCrawlTime": "2026-05-28T00:00:00Z",
    }
    set_inspect_cache(DOMAIN, TODAY, url, cached_result)
    assert get_inspect_cache(DOMAIN, TODAY, url) is not None

    # ...e um service que retorna algo DIFERENTE (NEUTRAL → "warning").
    class FakeIndex:
        def inspect(self, body):
            return self

        def execute(self):
            return {
                "inspectionResult": {
                    "indexStatusResult": {
                        "verdict": "NEUTRAL",
                        "coverageState": "Discovered - currently not indexed",
                        "lastCrawlTime": "",
                    }
                }
            }

    class FakeUrlInspection:
        def index(self):
            return FakeIndex()

    class FakeService:
        def urlInspection(self):
            return FakeUrlInspection()

    import fetchers.inspector as insp_mod

    results = insp_mod.inspect_urls(FakeService(), DOMAIN, [url], use_cache=False)

    assert len(results) == 1
    # Veio da API mock (warning), não do cache (indexed).
    assert results[0]["category"] == "warning"
