"""
test_log_analyzer.py — Testa o núcleo PURO do analisador de crawl budget.

Cobre parsing (combined/common/malformado/IPv6), normalização de caminho,
timestamp independente de locale, detecção de bot (real x falsificável),
verificação por DNS (mockada) e toda a agregação + cruzamentos (never-crawled,
money pages subcrawladas, mix de status, split bot/humano). Tudo offline.

O wrapper de IO `analyze_logs` é exercitado com arquivos temporários do pytest
(inclui .gz) — nunca toca na pasta real do usuário.
"""

import gzip

from core import log_analyzer as la

GB = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
HUMAN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"
BING = "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"


def line(
    ip="66.249.66.1", path="/x", status=200, ua=GB, ts="07/Jun/2026:13:55:36 -0300", size="512"
):
    return f'{ip} - - [{ts}] "GET {path} HTTP/1.1" {status} {size} "-" "{ua}"'


def common_line(
    ip="66.249.66.1", path="/x", status=200, ts="07/Jun/2026:13:55:36 -0300", size="512"
):
    return f'{ip} - - [{ts}] "GET {path} HTTP/1.1" {status} {size}'


class TestParseLogLine:
    def test_combined_extrai_todos_os_campos(self):
        rec = la.parse_log_line(line(path="/produtos/cane-corso", status=200, size="5123"))
        assert rec["ip"] == "66.249.66.1"
        assert rec["method"] == "GET"
        assert rec["path"] == "/produtos/cane-corso"
        assert rec["status"] == 200
        assert rec["bytes"] == 5123
        assert "Googlebot" in rec["ua"]

    def test_common_sem_user_agent(self):
        rec = la.parse_log_line(common_line(path="/sobre", status=404))
        assert rec["status"] == 404
        assert rec["ua"] == ""

    def test_query_string_separada_do_path(self):
        rec = la.parse_log_line(line(path="/p?cor=preto&size=g"))
        assert rec["has_query"] is True
        assert rec["path_only"] == "/p"

    def test_linha_malformada_retorna_none(self):
        assert la.parse_log_line("isto nao e um log") is None

    def test_linha_vazia_retorna_none(self):
        assert la.parse_log_line("") is None
        assert la.parse_log_line("\n") is None

    def test_bytes_traco_vira_none(self):
        rec = la.parse_log_line(line(size="-"))
        assert rec["bytes"] is None

    def test_ipv6(self):
        rec = la.parse_log_line(line(ip="2001:4860:4860::8888"))
        assert rec["ip"] == "2001:4860:4860::8888"

    def test_pattern_forcado(self):
        # Forçar 'common' numa linha combined ainda parseia o prefixo (sem UA).
        rec = la.parse_log_line(line(path="/x"), pattern=la._COMPILED_FORMATS["common"])
        assert rec["path_only"] == "/x"
        assert rec["ua"] == ""


class TestNormPath:
    def test_remove_barra_final(self):
        assert la._norm_path("/produtos/") == "/produtos"

    def test_raiz_preservada(self):
        assert la._norm_path("/") == "/"

    def test_vazio_vira_raiz(self):
        assert la._norm_path("") == "/"

    def test_remove_query_e_fragmento(self):
        assert la._norm_path("/p?x=1#frag") == "/p"

    def test_adiciona_barra_inicial(self):
        assert la._norm_path("produtos") == "/produtos"


class TestParseTimestamp:
    def test_valido_com_offset(self):
        dt = la.parse_timestamp("07/Jun/2026:13:55:36 -0300")
        assert (dt.year, dt.month, dt.day, dt.hour) == (2026, 6, 7, 13)
        assert dt.utcoffset().total_seconds() == -3 * 3600

    def test_mes_case_insensitive(self):
        assert la.parse_timestamp("01/jan/2026:00:00:00 +0000").month == 1
        assert la.parse_timestamp("01/DEC/2026:00:00:00 +0000").month == 12

    def test_mes_invalido_retorna_none(self):
        assert la.parse_timestamp("01/Zzz/2026:00:00:00 +0000") is None

    def test_formato_invalido_retorna_none(self):
        assert la.parse_timestamp("ontem de manha") is None


class TestBotDetection:
    def test_googlebot_real(self):
        assert la.is_googlebot(GB) is True

    def test_outros_bots_do_google(self):
        assert la.is_googlebot("Mozilla/5.0 (compatible; GoogleOther)") is True
        assert la.is_googlebot("Mozilla/5.0 (compatible; Storebot-Google/1.0)") is True

    def test_humano_nao_e_googlebot(self):
        assert la.is_googlebot(HUMAN) is False

    def test_ua_vazio(self):
        assert la.is_googlebot("") is False
        assert la.is_bot("") is False

    def test_ua_falsificado_passa_no_teste_de_ua(self):
        # Documenta a falsificabilidade: o teste por UA aceita qualquer um que
        # se diga Googlebot — por isso verify_googlebot() existe.
        assert la.is_googlebot("eu sou o Googlebot, juro") is True

    def test_is_bot_amplo(self):
        assert la.is_bot(BING) is True
        assert la.is_bot(HUMAN) is False


class TestClassifyGooglebotIp:
    def test_verified(self, monkeypatch):
        ip = "66.249.66.1"
        monkeypatch.setattr(la, "_reverse_dns", lambda _: "crawl-66-249-66-1.googlebot.com")
        monkeypatch.setattr(la, "_forward_dns", lambda _: [ip])
        assert la.classify_googlebot_ip(ip) == "verified"
        assert la.verify_googlebot(ip) is True  # wrapper de compatibilidade

    def test_forged_host_nao_google_que_resolve(self, monkeypatch):
        monkeypatch.setattr(la, "_reverse_dns", lambda _: "spam.evil.com")
        monkeypatch.setattr(la, "_forward_dns", lambda _: ["1.2.3.4"])  # host real
        assert la.classify_googlebot_ip("1.2.3.4") == "forged"

    def test_forged_ptr_google_mas_forward_nao_bate(self, monkeypatch):
        monkeypatch.setattr(la, "_reverse_dns", lambda _: "crawl.googlebot.com")
        monkeypatch.setattr(la, "_forward_dns", lambda _: ["9.9.9.9"])
        assert la.classify_googlebot_ip("66.249.66.1") == "forged"

    def test_unverifiable_sem_ptr(self, monkeypatch):
        # Caso típico atrás de CDN/proxy: IP logado é do proxy, sem PTR.
        monkeypatch.setattr(la, "_reverse_dns", lambda _: None)
        assert la.classify_googlebot_ip("104.22.42.151") == "unverifiable"
        assert la.verify_googlebot("104.22.42.151") is False

    def test_unverifiable_ptr_nao_google_que_nao_resolve(self, monkeypatch):
        monkeypatch.setattr(la, "_reverse_dns", lambda _: "ghost.invalido")
        monkeypatch.setattr(la, "_forward_dns", lambda _: [])
        assert la.classify_googlebot_ip("1.2.3.4") == "unverifiable"


class TestAnalyzeLines:
    def _lines(self):
        return [
            line(path="/produtos/cane-corso"),
            line(path="/produtos/cane-corso"),
            line(path="/produtos/cane-corso?cor=preto"),  # mesma path canônica + query
            line(path="/inexistente", status=404),
            line(path="/produtos/cane-corso", ua=HUMAN),
            line(path="/blog", ua=BING),
            "linha lixo",
        ]

    def test_contagem_de_linhas(self):
        res = la.analyze_lines(self._lines())
        assert res["lines_total"] == 7
        assert res["lines_parsed"] == 6
        assert res["lines_malformed"] == 1

    def test_split_bot_humano(self):
        res = la.analyze_lines(self._lines())
        t = res["traffic"]
        assert t["googlebot"] == 4
        assert t["humans"] == 1
        assert t["other_bots"] == 1
        assert t["spoofed_googlebot"] == 0

    def test_agregacao_por_path(self):
        res = la.analyze_lines(self._lines())
        by = {r["path"]: r for r in res["googlebot"]["by_path"]}
        assert by["/produtos/cane-corso"]["hits"] == 3  # 2 limpas + 1 com query
        assert res["googlebot"]["unique_paths"] == 2

    def test_status_mix_e_erros(self):
        res = la.analyze_lines(self._lines())
        assert res["googlebot"]["status_mix"] == {"200": 3, "404": 1}
        assert res["googlebot"]["top_errors"][0] == {"path": "/inexistente", "hits": 1}

    def test_param_hits(self):
        res = la.analyze_lines(self._lines())
        assert res["googlebot"]["param_hits"] == 1
        assert res["googlebot"]["top_param"][0]["path"] == "/produtos/cane-corso?cor=preto"

    def test_date_range_e_daily(self):
        lines = [
            line(path="/a", ts="07/Jun/2026:10:00:00 -0300"),
            line(path="/b", ts="09/Jun/2026:10:00:00 -0300"),
        ]
        res = la.analyze_lines(lines)
        assert res["date_range"]["start"].startswith("2026-06-07")
        assert res["date_range"]["end"].startswith("2026-06-09")
        assert res["googlebot"]["daily"] == {"2026-06-07": 1, "2026-06-09": 1}

    def test_has_user_agent_false_em_common(self):
        res = la.analyze_lines([common_line(path="/x"), common_line(path="/y")])
        assert res["has_user_agent"] is False
        # Sem UA não dá para identificar bot — nada vira googlebot.
        assert res["traffic"]["googlebot"] == 0

    def test_never_crawled(self):
        sitemap = [
            "https://ex.com/produtos/cane-corso",  # rastreada
            "https://ex.com/precos/cane-corso",  # nunca
            "https://ex.com/contato/",  # nunca (barra final normalizada)
        ]
        res = la.analyze_lines(self._lines(), sitemap_urls=sitemap)
        nc = res["never_crawled"]
        assert nc["sitemap_total"] == 3
        assert nc["crawled"] == 1
        assert set(nc["urls"]) == {
            "https://ex.com/precos/cane-corso",
            "https://ex.com/contato/",
        }

    def test_undercrawled_money(self):
        position_report = {
            "urls": [
                # money page nunca rastreada -> flag
                {
                    "url": "https://ex.com/precos/cane-corso",
                    "impressions": 11000,
                    "position": 4.2,
                    "has_data": True,
                },
                # money page rastreada -> excluída
                {
                    "url": "https://ex.com/produtos/cane-corso",
                    "impressions": 9000,
                    "position": 6.0,
                    "has_data": True,
                },
                # impressões abaixo do mínimo -> excluída
                {
                    "url": "https://ex.com/irrelevante",
                    "impressions": 50,
                    "position": 9.0,
                    "has_data": True,
                },
                # sem dados -> excluída
                {
                    "url": "https://ex.com/sem-dados",
                    "impressions": 99999,
                    "position": None,
                    "has_data": False,
                },
            ]
        }
        res = la.analyze_lines(self._lines(), position_report=position_report)
        um = res["undercrawled_money"]
        assert [r["url"] for r in um] == ["https://ex.com/precos/cane-corso"]
        assert um[0]["crawl_hits"] == 0

    def test_sem_cruzamentos_retorna_none(self):
        res = la.analyze_lines(self._lines())
        assert res["never_crawled"] is None
        assert res["undercrawled_money"] is None

    def test_resolve_classifica_verified_forged_unverifiable(self, monkeypatch):
        status = {"66.249.66.1": "verified", "6.6.6.6": "forged", "104.22.42.151": "unverifiable"}
        monkeypatch.setattr(la, "classify_googlebot_ip", lambda ip: status.get(ip, "forged"))
        lines = [
            line(ip="66.249.66.1", path="/ok"),  # verified
            line(ip="6.6.6.6", path="/forjado"),  # forged (impostor real)
            line(ip="104.22.42.151", path="/cdn"),  # unverifiable (CDN: sem PTR)
        ]
        res = la.analyze_lines(lines, resolve_googlebot=True)
        t = res["traffic"]
        assert res["resolved"] is True
        assert t["googlebot"] == 2  # verified + unverifiable agregam como Googlebot
        assert t["googlebot_verified"] == 1
        assert t["googlebot_unverifiable"] == 1
        assert t["spoofed_googlebot"] == 1  # só o forjado
        assert t["humans"] == 0 and t["other_bots"] == 0
        # 1 verified vs 1 unverifiable -> não é maioria estrita -> não suspeita CDN
        assert res["behind_cdn_suspected"] is False

    def test_behind_cdn_suspected_quando_unverifiable_domina(self, monkeypatch):
        monkeypatch.setattr(la, "classify_googlebot_ip", lambda ip: "unverifiable")
        lines = [line(ip="104.22.42.151", path="/a"), line(ip="108.162.245.10", path="/b")]
        res = la.analyze_lines(lines, resolve_googlebot=True)
        assert res["traffic"]["googlebot"] == 2
        assert res["traffic"]["googlebot_unverifiable"] == 2
        assert res["traffic"]["spoofed_googlebot"] == 0
        assert res["behind_cdn_suspected"] is True

    def test_sem_resolve_conta_ambos_como_googlebot(self):
        lines = [line(ip="66.249.66.1", path="/ok"), line(ip="6.6.6.6", path="/fake")]
        res = la.analyze_lines(lines, resolve_googlebot=False)
        assert res["traffic"]["googlebot"] == 2
        assert res["traffic"]["spoofed_googlebot"] == 0
        assert res["behind_cdn_suspected"] is False


class TestPrintCrawlReport:
    def test_saida_e_ascii_inclui_aviso_cdn(self, capsys, monkeypatch):
        # print_crawl_report e codigo de biblioteca: precisa ser ASCII puro
        # (seguro em console cp1252). Exercita tambem o caminho do aviso de CDN.
        monkeypatch.setattr(la, "classify_googlebot_ip", lambda ip: "unverifiable")
        res = la.analyze_lines(
            [line(ip="104.22.42.151", path="/a"), line(ip="1.2.3.4", path="/b", ua=HUMAN)],
            resolve_googlebot=True,
        )
        la.print_crawl_report(res)
        out = capsys.readouterr().out
        out.encode("ascii")  # levanta UnicodeEncodeError se houver caractere fora de ASCII
        assert "AVISO" in out and "CF-Connecting-IP" in out


class TestAnalyzeLogs:
    def test_le_arquivo_simples(self, tmp_path):
        p = tmp_path / "access.log"
        p.write_text(line(path="/a") + "\n" + line(path="/b") + "\n", encoding="utf-8")
        res = la.analyze_logs(str(p))
        assert res["lines_parsed"] == 2
        assert res["log_paths"] == [str(p)]

    def test_le_gzip(self, tmp_path):
        p = tmp_path / "access.log.gz"
        with gzip.open(p, "wt", encoding="utf-8") as fh:
            fh.write(line(path="/a") + "\n")
            fh.write(line(path="/b", status=404) + "\n")
        res = la.analyze_logs(str(p))
        assert res["lines_parsed"] == 2
        assert res["googlebot"]["status_mix"] == {"200": 1, "404": 1}

    def test_multiplos_arquivos(self, tmp_path):
        p1 = tmp_path / "a.log"
        p2 = tmp_path / "b.log"
        p1.write_text(line(path="/a") + "\n", encoding="utf-8")
        p2.write_text(line(path="/b") + "\n", encoding="utf-8")
        res = la.analyze_logs([str(p1), str(p2)])
        assert res["lines_parsed"] == 2
        assert res["googlebot"]["unique_paths"] == 2
