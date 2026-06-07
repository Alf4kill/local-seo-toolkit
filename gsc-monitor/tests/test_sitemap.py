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
    def test_extrai_diretiva_sitemap(self, monkeypatch):
        class FakeResp:
            text = "User-agent: *\nDisallow:\nSitemap: https://ex.com/meu-sitemap.xml\n"

        # Primeiro scheme (https) responde.
        monkeypatch.setattr(sm, "_get", lambda url: FakeResp() if url.startswith("https") else None)
        assert sm._sitemap_from_robots("ex.com") == "https://ex.com/meu-sitemap.xml"

    def test_sem_diretiva_retorna_none(self, monkeypatch):
        class FakeResp:
            text = "User-agent: *\nDisallow: /admin\n"

        monkeypatch.setattr(sm, "_get", lambda url: FakeResp())
        assert sm._sitemap_from_robots("ex.com") is None

    def test_robots_inacessivel_retorna_none(self, monkeypatch):
        monkeypatch.setattr(sm, "_get", lambda url: None)
        assert sm._sitemap_from_robots("ex.com") is None
