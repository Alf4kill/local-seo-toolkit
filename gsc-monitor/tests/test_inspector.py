"""
test_inspector.py — inspect_urls paralelo (fetchers/inspector.py).

Cobre o que o paralelismo pode quebrar e o cache por veredito:
ordem da saída, Http por thread, freio de cota, janela de TTL por veredito,
gravação em lote e a recusa de paralelizar sem credenciais.

Nada aqui toca a rede: o service é um fake que conta chamadas.
"""

import threading
from datetime import date, timedelta

import fetchers.inspector as insp
import pytest
from core.cache import (
    _cache_path,
    _write_entry,
    load_inspect_window,
    set_inspect_cache_bulk,
)

DOMAIN = "www.inspector-test.com.br"
HOJE = date.today().isoformat()


# ---------------------------------------------------------------------------
# Service fake
# ---------------------------------------------------------------------------


class FakeRequest:
    def __init__(self, service, body):
        self._service = service
        self._body = body

    def execute(self, **kwargs):
        url = self._body["inspectionUrl"]
        with self._service.lock:
            self._service.chamadas.append(url)
            self._service.threads.add(threading.current_thread().name)
            self._service.https.append(kwargs.get("http"))
        if url in self._service.falhas:
            raise RuntimeError("falha simulada")
        return {
            "inspectionResult": {
                "indexStatusResult": {
                    "verdict": self._service.vereditos.get(url, "PASS"),
                    "coverageState": "Submitted and indexed",
                    "lastCrawlTime": "2026-11-01T00:00:00Z",
                }
            }
        }


class FakeIndex:
    def __init__(self, service):
        self._service = service

    def inspect(self, body):
        return FakeRequest(self._service, body)


class FakeUrlInspection:
    def __init__(self, service):
        self._service = service

    def index(self):
        return FakeIndex(self._service)


class FakeService:
    def __init__(self, vereditos=None, falhas=()):
        self.chamadas = []
        self.threads = set()
        self.https = []
        self.vereditos = vereditos or {}
        self.falhas = set(falhas)
        self.lock = threading.Lock()

    def urlInspection(self):
        return FakeUrlInspection(self)


class FakeCredentials:
    """Credenciais só o bastante para o inspector aceitar o modo paralelo."""

    expiry = None
    refresh_token = "fake"


@pytest.fixture
def http_por_thread(monkeypatch):
    """
    Substitui _thread_http por um que devolve um objeto distinto por thread,
    sem depender de httplib2/google_auth_httplib2.
    """
    local = threading.local()
    criados = []
    lock = threading.Lock()

    def _fake(credentials):
        if getattr(local, "http", None) is None:
            local.http = object()
            with lock:
                criados.append(local.http)
        return local.http

    monkeypatch.setattr(insp, "_thread_http", _fake)
    return criados


def _urls(n, prefixo="https://www.inspector-test.com.br/p"):
    return [f"{prefixo}{i}" for i in range(n)]


def _limpa_cache():
    """Remove o arquivo de cache do dia entre testes."""
    import os

    from core.urls import normalize_domain

    path = _cache_path(normalize_domain(DOMAIN), f"inspect_{HOJE}")
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture(autouse=True)
def _cache_limpo():
    _limpa_cache()
    yield
    _limpa_cache()


# ---------------------------------------------------------------------------
# Ordem e integridade
# ---------------------------------------------------------------------------


def test_ordem_preservada_no_modo_paralelo(http_por_thread):
    """
    O pool devolve as tarefas fora de ordem; a saída tem de sair na ordem da
    entrada, senão o relatório casa URL com o veredito errado.
    """
    urls = _urls(40)
    service = FakeService()

    resultados = insp.inspect_urls(
        service,
        DOMAIN,
        urls,
        use_cache=False,
        workers=8,
        credentials=FakeCredentials(),
    )

    assert [r["url"] for r in resultados] == urls
    assert len(service.chamadas) == 40
    # De fato usou mais de uma thread (senão o teste de ordem não prova nada).
    assert len(service.threads) > 1


def test_cada_thread_recebe_seu_proprio_http(http_por_thread):
    """
    O Http do service não é thread-safe: cada thread precisa do seu, e ele
    precisa chegar até o execute().
    """
    service = FakeService()
    insp.inspect_urls(
        service,
        DOMAIN,
        _urls(30),
        use_cache=False,
        workers=6,
        credentials=FakeCredentials(),
    )

    # Nenhuma chamada passou sem http...
    assert all(h is not None for h in service.https)
    # ...e há exatamente um http por thread usada, nunca um compartilhado.
    assert len(set(id(h) for h in service.https)) == len(service.threads)


def test_sem_credenciais_cai_no_sequencial(http_por_thread, capsys):
    """Sem credenciais não dá para isolar o Http — tem de recusar o paralelo."""
    service = FakeService()
    resultados = insp.inspect_urls(
        service, DOMAIN, _urls(5), use_cache=False, workers=8, credentials=None
    )

    assert len(resultados) == 5
    assert len(service.threads) == 1  # tudo na thread do chamador
    assert "sequencial" in capsys.readouterr().out.lower()


def test_erro_em_uma_url_nao_derruba_as_outras(http_por_thread):
    """Uma URL que explode vira 'unknown'; as demais seguem normalmente."""
    urls = _urls(10)
    service = FakeService(falhas=[urls[3]])

    resultados = insp.inspect_urls(
        service, DOMAIN, urls, use_cache=False, workers=4, credentials=FakeCredentials()
    )

    assert len(resultados) == 10
    assert resultados[3]["category"] == "unknown"
    assert resultados[3]["coverageState"] == "fetch_error"
    assert all(r["category"] == "indexed" for i, r in enumerate(resultados) if i != 3)


# ---------------------------------------------------------------------------
# Freio de cota
# ---------------------------------------------------------------------------


def test_freio_de_cota_para_e_marca_as_puladas(http_por_thread, capsys):
    """
    Paralelizar não aumenta a cota (2.000/dia por site), só a queima mais
    rápido. Acima do teto, as URLs restantes NÃO podem parecer inspecionadas.
    """
    urls = _urls(20)
    service = FakeService()

    resultados = insp.inspect_urls(
        service,
        DOMAIN,
        urls,
        use_cache=False,
        workers=4,
        credentials=FakeCredentials(),
        max_calls=7,
    )

    assert len(service.chamadas) == 7  # a API foi chamada só 7 vezes
    assert len(resultados) == 20  # mas o relatório cobre todas as URLs
    puladas = [r for r in resultados if r["coverageState"] == "quota_guard_skip"]
    assert len(puladas) == 13
    assert all(p["category"] == "unknown" for p in puladas)
    assert "freio de cota" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# Cache: janela por veredito e gravação em lote
# ---------------------------------------------------------------------------


def test_janela_so_reaproveita_pass_de_dias_anteriores():
    """
    De ontem, só PASS volta. Um problema (NEUTRAL) tem de ser reinspecionado —
    é exatamente o dado que muda.
    """
    from core.urls import normalize_domain

    site = normalize_domain(DOMAIN)
    ontem = (date.today() - timedelta(days=1)).isoformat()
    _write_entry(
        _cache_path(site, f"inspect_{ontem}"),
        {
            "https://x/ok": {"url": "https://x/ok", "verdict": "PASS", "category": "indexed"},
            "https://x/ruim": {
                "url": "https://x/ruim",
                "verdict": "NEUTRAL",
                "category": "warning",
            },
        },
    )

    janela = load_inspect_window(site, HOJE, ttl_ok_days=7)
    assert "https://x/ok" in janela
    assert "https://x/ruim" not in janela

    # Com a janela desligada, nem o PASS de ontem entra.
    assert load_inspect_window(site, HOJE, ttl_ok_days=0) == {}


def test_janela_respeita_o_limite_de_dias():
    """Fora da janela, nem PASS vale — o dado fica velho demais."""
    from core.urls import normalize_domain

    site = normalize_domain(DOMAIN)
    antigo = (date.today() - timedelta(days=10)).isoformat()
    _write_entry(
        _cache_path(site, f"inspect_{antigo}"),
        {"https://x/velho": {"url": "https://x/velho", "verdict": "PASS"}},
    )

    assert "https://x/velho" not in load_inspect_window(site, HOJE, ttl_ok_days=7)
    assert "https://x/velho" in load_inspect_window(site, HOJE, ttl_ok_days=14)


def test_hoje_ganha_de_um_dia_anterior():
    """O resultado mais recente da mesma URL é o que vale."""
    from core.urls import normalize_domain

    site = normalize_domain(DOMAIN)
    url = "https://x/muda"
    ontem = (date.today() - timedelta(days=1)).isoformat()
    _write_entry(
        _cache_path(site, f"inspect_{ontem}"),
        {url: {"url": url, "verdict": "PASS", "coverageState": "ontem"}},
    )
    set_inspect_cache_bulk(
        site, HOJE, {url: {"url": url, "verdict": "FAIL", "coverageState": "hoje"}}
    )

    janela = load_inspect_window(site, HOJE, ttl_ok_days=7)
    assert janela[url]["coverageState"] == "hoje"


def test_cache_poupa_chamadas_e_mantem_a_ordem(http_por_thread):
    """URL em cache não vai para a API, mas continua no lugar certo da saída."""
    from core.urls import normalize_domain

    urls = _urls(6)
    site = normalize_domain(DOMAIN)
    set_inspect_cache_bulk(
        site,
        HOJE,
        {
            urls[2]: {
                "url": urls[2],
                "verdict": "FAIL",
                "category": "not_indexed",
                "coverageState": "do cache",
                "lastCrawlTime": "",
            }
        },
    )

    service = FakeService()
    resultados = insp.inspect_urls(
        service, DOMAIN, urls, use_cache=True, workers=4, credentials=FakeCredentials()
    )

    assert [r["url"] for r in resultados] == urls
    assert urls[2] not in service.chamadas
    assert len(service.chamadas) == 5
    assert resultados[2]["coverageState"] == "do cache"


def test_resultados_sao_gravados_em_lote(http_por_thread):
    """Ao fim do run, tudo que deu certo tem de estar no cache do dia."""
    from core.urls import normalize_domain

    urls = _urls(60)  # > INSPECT_CACHE_FLUSH_EVERY, exercita flush + resto
    service = FakeService()
    insp.inspect_urls(
        service, DOMAIN, urls, use_cache=True, workers=6, credentials=FakeCredentials()
    )

    gravado = load_inspect_window(normalize_domain(DOMAIN), HOJE, ttl_ok_days=0)
    assert set(gravado) == set(urls)


def test_erro_nao_entra_no_cache(http_por_thread):
    """Erro de API é retentado na próxima execução — nunca cacheado."""
    from core.urls import normalize_domain

    urls = _urls(4)
    service = FakeService(falhas=[urls[1]])
    insp.inspect_urls(
        service, DOMAIN, urls, use_cache=True, workers=2, credentials=FakeCredentials()
    )

    gravado = load_inspect_window(normalize_domain(DOMAIN), HOJE, ttl_ok_days=0)
    assert urls[1] not in gravado
    assert len(gravado) == 3
