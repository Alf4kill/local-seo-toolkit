"""
test_cache_phase2.py — Testa o módulo de cache da Fase 2.

Testes cobertos:
    1. get retorna None para cache inexistente
    2. set cria o arquivo e get lê os dados corretamente
    3. Cache de posição: set/get completo
    4. Cache de inspeção: set/get por URL individual
    5. Cache de inspeção: atualização incremental (múltiplas URLs no mesmo arquivo)
    6. TTL expirado: get retorna None após simular expiração
    7. Corrupção de arquivo: get retorna None sem levantar exceção
    8. --no-cache: inspector pula o cache e retorna dados da função mock

Execute com:  py test_cache_phase2.py
"""

import json
import os
import shutil
from datetime import datetime, timedelta

import pytest

# ── Garante que o diretório gsc-monitor está no path ─────────────────────────
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cache import (
    get_posicao_cache, set_posicao_cache,
    get_inspect_cache, set_inspect_cache,
    _cache_path, _cache_dir,
)

DOMAIN    = "www.cache-test.com.br"
TODAY     = "2026-05-30"
START     = "2026-04-27"
END       = "2026-05-27"

FAKE_API_DATA = {
    "https://www.cache-test.com.br/": {
        "clicks": 100, "impressions": 2000, "ctr": 5.0, "position": 3.2,
    },
    "https://www.cache-test.com.br/contato": {
        "clicks": 10,  "impressions": 500,  "ctr": 2.0, "position": 8.5,
    },
}

FAKE_INSPECT_RESULT = {
    "url":           "https://www.cache-test.com.br/",
    "verdict":       "PASS",
    "category":      "indexed",
    "coverageState": "Submitted and indexed",
    "lastCrawlTime": "2026-05-28T10:00:00Z",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True, scope="module")
def cleanup_test_cache():
    domain_dir = os.path.dirname(_cache_dir(DOMAIN))
    if os.path.isdir(domain_dir):
        shutil.rmtree(domain_dir)
    yield
    if os.path.isdir(domain_dir):
        shutil.rmtree(domain_dir)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def check(condition: bool, msg: str) -> None:
    status = "[OK]" if condition else "[FALHA]"
    print(f"  {status}  {msg}")
    if not condition:
        raise AssertionError(msg)


def _force_expire(site: str, key_prefix: str, suffix: str) -> None:
    """Sobrescreve o cached_at com uma data antiga para simular expiração."""
    path = _cache_path(site, f"{key_prefix}_{suffix}")
    with open(path, "r", encoding="utf-8") as f:
        entry = json.load(f)
    entry["cached_at"] = (datetime.now() - timedelta(hours=200)).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f)


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------
def test_posicao_miss():
    print("\n--- Teste 1: cache miss (posição) ---")
    result = get_posicao_cache(DOMAIN, START, END)
    check(result is None, "Retorna None quando cache não existe")


def test_posicao_set_get():
    print("\n--- Teste 2: set/get (posição) ---")
    set_posicao_cache(DOMAIN, START, END, FAKE_API_DATA)

    path = _cache_path(DOMAIN, f"posicao_{START}_{END}")
    check(os.path.isfile(path), f"Arquivo de cache criado: {path}")

    result = get_posicao_cache(DOMAIN, START, END)
    check(result is not None, "get retorna dados após set")
    check(result == FAKE_API_DATA, "Dados recuperados são idênticos aos salvos")
    check(len(result) == 2, "Quantidade de entradas correta")


def test_inspect_miss():
    print("\n--- Teste 3: cache miss (inspeção) ---")
    url = "https://www.cache-test.com.br/"
    result = get_inspect_cache(DOMAIN, TODAY, url)
    check(result is None, "Retorna None quando URL não está no cache")


def test_inspect_set_get():
    print("\n--- Teste 4: set/get (inspeção) ---")
    url = FAKE_INSPECT_RESULT["url"]
    set_inspect_cache(DOMAIN, TODAY, url, FAKE_INSPECT_RESULT)

    path = _cache_path(DOMAIN, f"inspect_{TODAY}")
    check(os.path.isfile(path), f"Arquivo de cache de inspeção criado: {path}")

    result = get_inspect_cache(DOMAIN, TODAY, url)
    check(result is not None, "get retorna dados após set")
    check(result["category"] == "indexed", "Categoria correta no cache")
    check(result["verdict"]  == "PASS",    "Verdict correto no cache")


def test_inspect_incremental():
    print("\n--- Teste 5: atualização incremental (múltiplas URLs) ---")
    url2 = "https://www.cache-test.com.br/contato"
    result2 = {
        "url":           url2,
        "verdict":       "FAIL",
        "category":      "not_indexed",
        "coverageState": "Crawled - currently not indexed",
        "lastCrawlTime": "",
    }
    set_inspect_cache(DOMAIN, TODAY, url2, result2)

    # Ambas as URLs devem estar no mesmo arquivo
    path = _cache_path(DOMAIN, f"inspect_{TODAY}")
    with open(path, "r", encoding="utf-8") as f:
        entry = json.load(f)

    check(FAKE_INSPECT_RESULT["url"] in entry["data"], "URL 1 preservada após inserção de URL 2")
    check(url2 in entry["data"],                       "URL 2 inserida corretamente")
    check(len(entry["data"]) == 2,                     "Total de 2 URLs no arquivo")

    r2 = get_inspect_cache(DOMAIN, TODAY, url2)
    check(r2 is not None,               "get retorna dados da URL 2")
    check(r2["category"] == "not_indexed", "Categoria da URL 2 correta")


def test_posicao_ttl_expirado():
    print("\n--- Teste 6: TTL expirado (posição) ---")
    _force_expire(DOMAIN, "posicao", f"{START}_{END}")
    result = get_posicao_cache(DOMAIN, START, END)
    check(result is None, "Retorna None quando cache está expirado")


def test_inspect_ttl_expirado():
    print("\n--- Teste 7: TTL expirado (inspeção) ---")
    _force_expire(DOMAIN, "inspect", TODAY)
    url = FAKE_INSPECT_RESULT["url"]
    result = get_inspect_cache(DOMAIN, TODAY, url)
    check(result is None, "Retorna None quando cache de inspeção está expirado")


def test_corrupcao():
    print("\n--- Teste 8: arquivo corrompido não levanta exceção ---")
    path = _cache_path(DOMAIN, f"posicao_corrupto")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{isso nao e json valido!!!")

    result = get_posicao_cache(DOMAIN, "2020-01-01", "corrupto")
    check(result is None, "Retorna None para arquivo corrompido sem exceção")


def test_inspector_use_cache_false():
    """
    Testa que use_cache=False pula o cache e chama a função de API.
    Usa uma versão mock de inspect_urls que substitui o service.
    """
    print("\n--- Teste 9: use_cache=False ignora cache (mock) ---")

    # Popula cache manualmente
    url = "https://www.cache-test.com.br/pagina"
    cached_result = {
        "url": url, "verdict": "PASS", "category": "indexed",
        "coverageState": "Submitted and indexed", "lastCrawlTime": "2026-05-28T00:00:00Z",
    }
    set_inspect_cache(DOMAIN, TODAY, url, cached_result)
    check(get_inspect_cache(DOMAIN, TODAY, url) is not None, "Cache populado com sucesso")

    # Simula service que retorna um resultado diferente do cache
    class FakeIndex:
        def inspect(self, body):
            return self
        def execute(self):
            return {
                "inspectionResult": {
                    "indexStatusResult": {
                        "verdict":       "NEUTRAL",
                        "coverageState": "Discovered - currently not indexed",
                        "lastCrawlTime": "",
                    }
                }
            }

    class FakeUrlInspection:
        def index(self): return FakeIndex()

    class FakeService:
        def urlInspection(self): return FakeUrlInspection()

    import fetchers.inspector as insp_mod
    results = insp_mod.inspect_urls(FakeService(), DOMAIN, [url], use_cache=False)

    check(len(results) == 1, "Retornou 1 resultado")
    check(results[0]["category"] == "warning",
          f"Resultado veio da API mock (warning), não do cache (indexed) — got: {results[0]['category']}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  GSC Monitor — Fase 2: Testes de cache.py")
    print("=" * 60)

    try:
        test_posicao_miss()
        test_posicao_set_get()
        test_inspect_miss()
        test_inspect_set_get()
        test_inspect_incremental()
        test_posicao_ttl_expirado()
        test_inspect_ttl_expirado()
        test_corrupcao()
        test_inspector_use_cache_false()

        print("\n" + "=" * 60)
        print("  TODOS OS TESTES PASSARAM")
        print("=" * 60)

    finally:
        # Limpeza
        folder = _cache_dir(DOMAIN)
        parent = os.path.dirname(folder)   # relatorios/www.cache-test.com.br
        if os.path.isdir(parent):
            shutil.rmtree(parent)
        print("\n[cleanup] Pastas de teste removidas.")
