"""
test_sitemap.py — Testa o parse de sitemap (sem rede).

O fetch real (`fetch_urls`) faz HTTP e é coberto na prática rodando contra os
domínios reais; aqui isolamos a LÓGICA pura de parsing, que é onde moram os
bugs silenciosos: namespace errado, sitemapindex vs urlset, XML quebrado,
e a extração de Sitemap: do robots.txt. Tudo offline.
"""

import core.sitemap as sm
from core.sitemap import _parse_sitemap

NS = sm.SITEMAP_NS


def _urlset(*locs):
    body = "".join(f"<url><loc>{u}</loc></url>" for u in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="{NS}">{body}</urlset>'


def _sitemapindex(*locs):
    body = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="{NS}">{body}</sitemapindex>'


class TestParseSitemap:
    def test_urlset_retorna_paginas(self):
        pages, subs = _parse_sitemap(_urlset("https://ex.com/a", "https://ex.com/b"))
        assert pages == ["https://ex.com/a", "https://ex.com/b"]
        assert subs == []

    def test_sitemapindex_retorna_subsitemaps(self):
        pages, subs = _parse_sitemap(
            _sitemapindex("https://ex.com/sitemap1.xml", "https://ex.com/sitemap2.xml")
        )
        assert pages == []
        assert subs == ["https://ex.com/sitemap1.xml", "https://ex.com/sitemap2.xml"]

    def test_loc_com_espacos_e_quebras_sao_limpos(self):
        xml = f'<urlset xmlns="{NS}"><url><loc>\n  https://ex.com/x  \n</loc></url></urlset>'
        pages, _ = _parse_sitemap(xml)
        assert pages == ["https://ex.com/x"]

    def test_xml_invalido_nao_crasha(self):
        pages, subs = _parse_sitemap("<urlset><loc>quebrado")
        assert pages == []
        assert subs == []

    def test_loc_vazio_e_ignorado(self):
        xml = f'<urlset xmlns="{NS}"><url><loc></loc></url><url><loc>https://ex.com/ok</loc></url></urlset>'
        pages, _ = _parse_sitemap(xml)
        assert pages == ["https://ex.com/ok"]


class TestSitemapFromRobots:
    # _get agora devolve (Response | None, motivo) — os fakes acompanham.
    def test_extrai_diretiva_sitemap(self, monkeypatch):
        class FakeResp:
            text = "User-agent: *\nDisallow:\nSitemap: https://ex.com/meu-sitemap.xml\n"

        # Primeiro scheme (https) responde.
        monkeypatch.setattr(
            sm,
            "_get",
            lambda url, **kw: (FakeResp(), "") if url.startswith("https") else (None, "HTTP 404"),
        )
        assert sm._sitemap_from_robots("ex.com") == "https://ex.com/meu-sitemap.xml"

    def test_sem_diretiva_retorna_none(self, monkeypatch):
        class FakeResp:
            text = "User-agent: *\nDisallow: /admin\n"

        monkeypatch.setattr(sm, "_get", lambda url, **kw: (FakeResp(), ""))
        assert sm._sitemap_from_robots("ex.com") is None

    def test_robots_inacessivel_retorna_none(self, monkeypatch):
        monkeypatch.setattr(sm, "_get", lambda url, **kw: (None, "ConnectionError"))
        assert sm._sitemap_from_robots("ex.com") is None


# ---------------------------------------------------------------------------
# Retentativa de falha transitória e honestidade da mensagem de erro.
#
# Regressão de um caso real: site atrás de Cloudflare devolvendo 521 ("Web
# Server Is Down") em ~1 de cada 4 requisições. A etapa de indexação falhava
# e a de posicionamento, segundos depois, baixava o mesmo sitemap com 874
# URLs — e a mensagem afirmava que o sitemap não existia ou não era público.
# ---------------------------------------------------------------------------

import pytest
import requests


class FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def _candidatos(domain="ex.com"):
    """Os 4 endereços que fetch_urls tenta, na ordem."""
    return [
        f"https://{domain}/sitemap.xml",
        f"https://{domain}/sitemap_index.xml",
        f"http://{domain}/sitemap.xml",
        f"http://{domain}/sitemap_index.xml",
    ]


def _robots(domain="ex.com"):
    return [f"https://{domain}/robots.txt", f"http://{domain}/robots.txt"]


def _requests_falsos(monkeypatch, respostas):
    """
    Troca requests.get por uma sequência de respostas/exceções por URL.
    `respostas` é {url: [resposta_ou_excecao, ...]}; a última se repete.
    Devolve a lista de URLs chamadas, na ordem.
    """
    chamadas = []

    def fake_get(url, timeout=None, headers=None):
        chamadas.append(url)
        fila = respostas.get(url)
        if not fila:
            return FakeResp(404)
        item = fila.pop(0) if len(fila) > 1 else fila[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(sm.requests, "get", fake_get)
    return chamadas


@pytest.fixture
def sem_espera():
    """dormir/jitter injetados: nenhum teste aqui espera de verdade."""
    dormidas = []
    return {"dormir": dormidas.append, "jitter": lambda: 0.0}, dormidas


class TestRetentativaTransitoria:
    def test_521_e_retentado_e_tem_sucesso(self, monkeypatch, sem_espera):
        """O caso real: 521 na primeira, 200 na segunda. Não pode falhar."""
        kw, dormidas = sem_espera
        url = "https://ex.com/sitemap.xml"
        _requests_falsos(
            monkeypatch,
            {url: [FakeResp(521, "erro"), FakeResp(200, _urlset("https://ex.com/a"))]},
        )

        assert sm.fetch_urls("ex.com", **kw) == ["https://ex.com/a"]
        assert len(dormidas) == 1  # esperou uma vez antes de reter

    def test_timeout_e_retentado(self, monkeypatch, sem_espera):
        kw, _ = sem_espera
        url = "https://ex.com/sitemap.xml"
        _requests_falsos(
            monkeypatch,
            {
                url: [
                    requests.ConnectTimeout("estourou"),
                    FakeResp(200, _urlset("https://ex.com/a")),
                ]
            },
        )
        assert sm.fetch_urls("ex.com", **kw) == ["https://ex.com/a"]

    def test_404_nao_e_retentado(self, monkeypatch, sem_espera):
        """Esperar não faz sitemap ausente aparecer — e gastaria tempo à toa."""
        kw, dormidas = sem_espera
        chamadas = _requests_falsos(monkeypatch, {})  # tudo 404

        with pytest.raises(RuntimeError):
            sm.fetch_urls("ex.com", **kw)

        assert dormidas == []  # nenhuma espera
        # 4 candidatos + 2 robots (https/http), uma chamada cada.
        assert len(chamadas) == 6

    def test_desiste_apos_o_limite_de_tentativas(self, monkeypatch, sem_espera):
        kw, _ = sem_espera
        url = "https://ex.com/sitemap.xml"
        chamadas = _requests_falsos(monkeypatch, {url: [FakeResp(521, "")]})

        with pytest.raises(RuntimeError):
            sm.fetch_urls("ex.com", **kw)

        assert chamadas.count(url) == sm.SITEMAP_TENTATIVAS


class TestMensagemHonesta:
    def test_521_nao_acusa_sitemap_ausente(self, monkeypatch, sem_espera):
        """
        O bug original: falha de servidor virava 'verifique se o sitemap é
        público'. A mensagem tem de dizer que foi transitório.
        """
        kw, _ = sem_espera
        _requests_falsos(
            monkeypatch, {u: [FakeResp(521, "")] for u in [*_candidatos(), *_robots()]}
        )

        with pytest.raises(RuntimeError) as exc:
            sm.fetch_urls("ex.com", **kw)

        msg = str(exc.value)
        assert "TRANSIT" in msg.upper()
        assert "HTTP 521" in msg  # diz o que de fato aconteceu
        assert "NÃO significa que o sitemap não existe" in msg

    def test_404_em_tudo_afirma_ausencia(self, monkeypatch, sem_espera):
        kw, _ = sem_espera
        _requests_falsos(monkeypatch, {})  # tudo 404

        with pytest.raises(RuntimeError) as exc:
            sm.fetch_urls("ex.com", **kw)

        msg = str(exc.value)
        assert "404" in msg
        assert "realmente não está" in msg

    def test_403_fala_em_bloqueio_nao_em_ausencia(self, monkeypatch, sem_espera):
        kw, _ = sem_espera
        _requests_falsos(
            monkeypatch, {u: [FakeResp(403, "")] for u in [*_candidatos(), *_robots()]}
        )

        with pytest.raises(RuntimeError) as exc:
            sm.fetch_urls("ex.com", **kw)

        assert "recusou o acesso" in str(exc.value)


class TestSubSitemapIncompleto:
    def test_sub_sitemap_falho_levanta_em_vez_de_truncar(self, monkeypatch, sem_espera):
        """
        A poda trata o sitemap como a lista COMPLETA de páginas ativas: devolver
        lista truncada em silêncio marcaria página viva como fantasma (410).
        """
        kw, _ = sem_espera
        raiz = "https://ex.com/sitemap.xml"
        s1, s2 = "https://ex.com/s1.xml", "https://ex.com/s2.xml"
        _requests_falsos(
            monkeypatch,
            {
                raiz: [FakeResp(200, _sitemapindex(s1, s2))],
                s1: [FakeResp(200, _urlset("https://ex.com/a"))],
                s2: [FakeResp(521, "")],
            },
        )

        with pytest.raises(RuntimeError) as exc:
            sm.fetch_urls("ex.com", **kw)

        msg = str(exc.value)
        assert "INCOMPLETA" in msg
        assert s2 in msg

    def test_todos_os_sub_sitemaps_ok_concatena(self, monkeypatch, sem_espera):
        kw, _ = sem_espera
        raiz = "https://ex.com/sitemap.xml"
        s1, s2 = "https://ex.com/s1.xml", "https://ex.com/s2.xml"
        _requests_falsos(
            monkeypatch,
            {
                raiz: [FakeResp(200, _sitemapindex(s1, s2))],
                s1: [FakeResp(200, _urlset("https://ex.com/a", "https://ex.com/b"))],
                # 521 na primeira do sub-sitemap: a retentativa tem de salvar.
                s2: [
                    FakeResp(521, ""),
                    FakeResp(200, _urlset("https://ex.com/b", "https://ex.com/c")),
                ],
            },
        )

        # 'b' duplicado entre os dois sub-sitemaps sai uma vez só, na ordem.
        assert sm.fetch_urls("ex.com", **kw) == [
            "https://ex.com/a",
            "https://ex.com/b",
            "https://ex.com/c",
        ]


class TestUserAgent:
    def test_envia_user_agent_proprio(self, monkeypatch, sem_espera):
        """python-requests/x é bloqueado por parte dos WAFs."""
        kw, _ = sem_espera
        vistos = []

        def fake_get(url, timeout=None, headers=None):
            vistos.append((headers or {}).get("User-Agent"))
            return FakeResp(200, _urlset("https://ex.com/a"))

        monkeypatch.setattr(sm.requests, "get", fake_get)
        sm.fetch_urls("ex.com", **kw)

        assert vistos and all(ua == sm.USER_AGENT for ua in vistos)
        assert "gsc-monitor" in sm.USER_AGENT
