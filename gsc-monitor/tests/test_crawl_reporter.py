"""
test_crawl_reporter.py — Saída do analisador de crawl + helpers de storage.

Garante que o .txt traz as seções-chave, que o HTML é autocontido e ESCAPA
todo texto externo (anti-XSS), e que load_latest_position_report pega o
relatório datado mais recente ignorando historico_posicao.json.
"""

from core import log_analyzer as la
from core import storage
from reporters import crawl_reporter as cr

GB = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


def _line(path, status=200, ts="07/Jun/2026:13:55:36 -0300"):
    return f'66.249.66.1 - - [{ts}] "GET {path} HTTP/1.1" {status} 512 "-" "{GB}"'


def _result(extra_lines=None):
    # A primeira linha é datada 11 dias antes para o log cobrir uma janela
    # REALISTA: abaixo de UNDERCRAWLED_MIN_LOG_DAYS o veredito de money page
    # subcrawlada é recusado de propósito (ver test_log_analyzer).
    lines = [
        _line("/a", ts="27/May/2026:09:00:00 -0300"),
        _line("/a"),
        _line("/erro", 404),
    ] + (extra_lines or [])
    return la.analyze_lines(
        lines,
        sitemap_urls=["https://ex.com/a", "https://ex.com/nunca"],
        position_report={
            "urls": [
                {
                    "url": "https://ex.com/money",
                    "impressions": 9000,
                    "position": 4.0,
                    "has_data": True,
                }
            ]
        },
    )


class TestTxt:
    def test_tem_secoes_principais(self):
        lines = cr.build_crawl_txt_lines(_result(), "www.ex.com", "2026-06-07")
        text = "\n".join(lines)
        assert "RELATORIO DE CRAWL BUDGET" in text
        assert "www.ex.com" in text
        assert "CRAWL POR URL" in text
        assert "SITEMAP NUNCA RASTREADO" in text
        assert "MONEY PAGES SUBCRAWLADAS" in text

    def test_txt_e_ascii(self):
        # O .txt precisa abrir sem erro em console cp1252 — nada fora de ASCII.
        text = "\n".join(cr.build_crawl_txt_lines(_result(), "ex.com", "2026-06-07"))
        text.encode("ascii")  # levanta UnicodeEncodeError se houver acento


class TestHtml:
    def test_documento_autocontido(self):
        out = cr.generate_crawl_html(_result(), "www.ex.com", "2026-06-07")
        assert out.startswith("<!DOCTYPE html>")
        assert "www.ex.com" in out
        assert "Money pages" in out
        assert "Sitemap nunca rastreado" in out

    def test_escapa_path_malicioso(self):
        res = _result(extra_lines=[_line("/<script>alert(1)</script>")])
        out = cr.generate_crawl_html(res, "ex.com", "2026-06-07")
        assert "/<script>alert(1)" not in out  # nunca injeta cru
        assert "&lt;script&gt;alert(1)" in out  # aparece escapado


class TestLoadLatestPosition:
    def test_pega_mais_recente_e_ignora_historico(self):
        site = "load-latest.example"
        storage.save_position_report(site, "2026-06-01", {"marker": 1})
        storage.save_position_report(site, "2026-06-05", {"marker": 2})
        # historico_posicao.json também termina em _posicao.json — não pode vencer.
        storage.append_historico_posicao(
            site,
            "2026-06-05",
            {"start": "a", "end": "b"},
            [{"url": "u", "position": 1.0, "clicks": 1, "impressions": 1, "has_data": True}],
        )
        latest = storage.load_latest_position_report(site)
        assert latest == {"marker": 2}

    def test_sem_relatorio_retorna_none(self):
        assert storage.load_latest_position_report("dominio-inexistente.example") is None


class TestVerdictRecusado:
    """Verdict recusado tem de APARECER com o motivo, não desaparecer calado."""

    def _result_sem_ua(self):
        # Log sem User-Agent (formato 'common'): o analyzer recusa os dois
        # verdicts que dependem de identificar o Googlebot.
        linha = '66.249.66.1 - - [07/Jun/2026:13:55:36 -0300] "GET /a HTTP/1.1" 200 512'
        return la.analyze_lines(
            [linha],
            sitemap_urls=["https://ex.com/a", "https://ex.com/nunca"],
            position_report={
                "urls": [
                    {
                        "url": "https://ex.com/money",
                        "impressions": 9000,
                        "position": 4.0,
                        "has_data": True,
                    }
                ]
            },
        )

    def test_txt_mostra_o_motivo(self):
        res = self._result_sem_ua()
        assert res["indisponivel"]
        text = "\n".join(cr.build_crawl_txt_lines(res, "www.ex.com", "2026-06-07"))
        assert "RECUSADO" in text
        # E NÃO afirma o que não pode afirmar.
        assert "SITEMAP NUNCA RASTREADO" not in text
        assert "MONEY PAGES SUBCRAWLADAS" not in text

    def test_html_mostra_o_motivo(self):
        res = self._result_sem_ua()
        html = cr.generate_crawl_html(res, "www.ex.com", "2026-06-07")
        assert "Analise recusada" in html
        assert "Sitemap nunca rastreado no período" not in html

    def test_txt_continua_ascii_com_recusa(self):
        # O .txt tem garantia de ASCII puro (abre em console cp1252). O teste
        # geral de ASCII usa uma fixture que NAO recusa nada, então não cobria
        # as mensagens de recusa — que também vão para o arquivo.
        text = "\n".join(cr.build_crawl_txt_lines(self._result_sem_ua(), "ex.com", "2026-06-07"))
        assert "RECUSADO" in text
        nao_ascii = sorted({c for c in text if ord(c) > 127})
        assert not nao_ascii, f"caracteres fora de ASCII no .txt: {nao_ascii}"
