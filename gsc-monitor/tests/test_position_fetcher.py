"""
test_position_fetcher.py — Testa os helpers puros do fetcher de posição.

`fetch_positions` chama a Search Analytics API (rede + cota) e é melhor exercido
em integração; mas a formatação de siteUrl, a normalização de domínio (chave de
cache) e o cálculo da janela de datas são puros e críticos — um erro aqui
desalinha cache, quebra a chamada de API ou consulta o período errado.
"""

from datetime import date, timedelta

import pytest

from core.urls import build_site_url, normalize_domain
from fetchers.position_fetcher import _build_date_range


class TestBuildSiteUrl:

    def test_dominio_simples_vira_https_com_barra(self):
        assert build_site_url("exemplo.com.br") == "https://exemplo.com.br/"

    def test_sc_domain_passa_intacto(self):
        assert build_site_url("sc-domain:exemplo.com.br") == "sc-domain:exemplo.com.br"

    def test_url_https_normaliza_barra_final(self):
        assert build_site_url("https://exemplo.com.br") == "https://exemplo.com.br/"
        assert build_site_url("https://exemplo.com.br/") == "https://exemplo.com.br/"

    def test_url_http_preservada(self):
        assert build_site_url("http://exemplo.com.br") == "http://exemplo.com.br/"


class TestNormalizeDomain:

    def test_remove_sc_domain(self):
        assert normalize_domain("sc-domain:exemplo.com.br") == "exemplo.com.br"

    def test_remove_https_e_barra(self):
        assert normalize_domain("https://exemplo.com.br/") == "exemplo.com.br"

    def test_remove_http(self):
        assert normalize_domain("http://exemplo.com.br") == "exemplo.com.br"

    def test_dominio_limpo_inalterado(self):
        assert normalize_domain("exemplo.com.br") == "exemplo.com.br"

    def test_site_url_e_sc_domain_geram_mesma_chave(self):
        # Importante p/ cache: as duas formas do mesmo site devem coincidir.
        assert normalize_domain("https://exemplo.com.br/") == \
               normalize_domain("sc-domain:exemplo.com.br")


class TestBuildDateRange:

    def test_end_e_hoje_menos_3_dias(self):
        start, end = _build_date_range(days_back=30)
        assert end == (date.today() - timedelta(days=3)).isoformat()

    def test_janela_tem_o_tamanho_pedido(self):
        start, end = _build_date_range(days_back=30)
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
        assert (d1 - d0).days == 30

    def test_days_back_customizado(self):
        start, end = _build_date_range(days_back=7)
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
        assert (d1 - d0).days == 7

    def test_formato_iso(self):
        start, end = _build_date_range()
        # ISO 8601 → fromisoformat não levanta.
        date.fromisoformat(start)
        date.fromisoformat(end)
