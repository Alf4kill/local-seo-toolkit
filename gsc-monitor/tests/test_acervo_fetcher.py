"""
test_acervo_fetcher.py — Testes do fetcher do acervo (P7), sem rede.

Usa o idioma de mock já estabelecido em tests/test_date_trends.py — um
_FakeService que grava cada corpo numa lista `bodies` — estendido para responder
em função do corpo recebido. `dormir` é injetado em todo lugar: nenhum teste
daqui espera de verdade.

O que está travado aqui:

  - PAGINAÇÃO com startRow até a resposta de ZERO linhas, inclusive no caso
    ambíguo em que o total é múltiplo exato do rowLimit (o atalho
    `len(rows) < rowLimit` erraria sozinho).
  - RETENTATIVA: 429/5xx com backoff; 429 de carga esperando o ciclo de 15 min;
    4xx restantes re-levantando NA HORA (é assim que o chamador descobre que uma
    dimensão foi recusada).
  - RESUME: nenhuma requisição cobre dia já resolvido.
  - FALLBACK dia a dia só quando um dia chega perto do teto de linhas.
  - O grão `aparencia` sendo recusado com mensagem clara enquanto a P7.4 não
    implementa as 2 etapas com dimensionFilterGroups.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.warehouse import plan, store
from fetchers import gsc_retry
from fetchers.acervo_fetcher import (
    AcervoFetchError,
    _executar_passo,
    consultar_paginado,
    ingerir_janela,
)
from googleapiclient.errors import HttpError

HOJE = date(2026, 10, 16)
PROPRIEDADE = "https://www.exemplo.com.br/"


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class _Resposta:
    """Resp mínimo que o HttpError consome (status + reason)."""

    def __init__(self, status: int, reason: str = ""):
        self.status = status
        self.reason = reason


def erro_http(status: int, mensagem: str = "erro") -> HttpError:
    conteudo = json.dumps({"error": {"message": mensagem}}).encode("utf-8")
    return HttpError(_Resposta(status, mensagem), conteudo)


class _FakeRequest:
    def __init__(self, resposta):
        self._resposta = resposta

    def execute(self):
        if isinstance(self._resposta, Exception):
            raise self._resposta
        return self._resposta


class _FakeService:
    """Imita service.searchanalytics().query(...).execute(), gravando os corpos."""

    def __init__(self, responder):
        self._responder = responder
        self.bodies = []

    def searchanalytics(self):
        return self

    def query(self, siteUrl, body):
        self.bodies.append(dict(body))
        return _FakeRequest(self._responder(body, len(self.bodies) - 1))


def _linhas_api(n: int, dia: str = "2026-01-01") -> list:
    return [
        {
            "keys": [dia, f"kw{i}"],
            "clicks": 1.0,
            "impressions": 10.0,
            "ctr": 0.1,
            "position": 5.0,
        }
        for i in range(n)
    ]


def responder_por_dia(impressoes: int = 100, por_dia: int = 1):
    """Responde com `por_dia` linhas para cada dia do intervalo pedido."""

    def responder(body, _indice):
        if body.get("startRow"):
            return {"rows": []}
        dimensoes = tuple(body["dimensions"])
        saida = []
        for dia in plan.listar_dias(body["startDate"], body["endDate"]):
            for i in range(por_dia):
                keys = [dia]
                for dimensao in dimensoes[1:]:
                    keys.append(f"https://ex/{i}" if dimensao == "page" else f"kw{i}")
                saida.append(
                    {
                        "keys": keys,
                        "clicks": 1.0,
                        "impressions": float(impressoes),
                        "ctr": 0.01,
                        "position": 5.0,
                    }
                )
        return {"rows": saida, "responseAggregationType": "byProperty"}

    return responder


class _BaseAcervo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsc_test_acervo_fetch_")
        self.conn = store.abrir_caminho(os.path.join(self.tmp, "acervo.sqlite3"))
        self.sonos = []

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dormir(self, segundos):
        self.sonos.append(segundos)


# ---------------------------------------------------------------------------
# Paginação
# ---------------------------------------------------------------------------


class TestPaginacao(_BaseAcervo):
    def _corpo(self, row_limit=2):
        return plan.montar_corpo("2026-01-01", "2026-01-01", ("date", "query"), row_limit=row_limit)

    def test_pagina_ate_a_resposta_vazia(self):
        paginas = [_linhas_api(2), _linhas_api(2), []]
        svc = _FakeService(lambda body, i: {"rows": paginas[i]})
        linhas, requisicoes, _, capado = consultar_paginado(
            svc, PROPRIEDADE, self._corpo(), pausa=0, dormir=self.dormir
        )
        self.assertEqual(requisicoes, 3)
        self.assertEqual(len(linhas), 4)
        self.assertFalse(capado)
        # startRow ausente na 1a pagina (0 e o default da API), depois 2 e 4.
        self.assertNotIn("startRow", svc.bodies[0])
        self.assertEqual(svc.bodies[1]["startRow"], 2)
        self.assertEqual(svc.bodies[2]["startRow"], 4)

    def test_multiplo_exato_do_row_limit_termina_pelo_zero(self):
        # O atalho `len(rows) < rowLimit` nao resolveria este caso: a pagina
        # cheia e ambigua e so a resposta vazia prova que acabou.
        paginas = [_linhas_api(2), []]
        svc = _FakeService(lambda body, i: {"rows": paginas[i]})
        linhas, requisicoes, _, _ = consultar_paginado(
            svc, PROPRIEDADE, self._corpo(), pausa=0, dormir=self.dormir
        )
        self.assertEqual(requisicoes, 2)
        self.assertEqual(len(linhas), 2)

    def test_pagina_parcial_encerra_sem_requisicao_extra(self):
        paginas = [_linhas_api(2), _linhas_api(1)]
        svc = _FakeService(lambda body, i: {"rows": paginas[i]})
        _, requisicoes, _, _ = consultar_paginado(
            svc, PROPRIEDADE, self._corpo(), pausa=0, dormir=self.dormir
        )
        self.assertEqual(requisicoes, 2)

    def test_freio_de_paginas_marca_capado_sem_loop_infinito(self):
        svc = _FakeService(lambda body, i: {"rows": _linhas_api(2)})
        linhas, requisicoes, _, capado = consultar_paginado(
            svc, PROPRIEDADE, self._corpo(), max_paginas=3, pausa=0, dormir=self.dormir
        )
        self.assertEqual(requisicoes, 3)
        self.assertEqual(len(linhas), 6)
        self.assertTrue(capado)

    def test_pausa_entre_paginas_e_respeitada(self):
        paginas = [_linhas_api(2), []]
        svc = _FakeService(lambda body, i: {"rows": paginas[i]})
        consultar_paginado(svc, PROPRIEDADE, self._corpo(), pausa=1.5, dormir=self.dormir)
        # Pausa só entre requisições: 2 chamadas => 1 pausa.
        self.assertEqual(self.sonos, [1.5])

    def test_agregacao_da_resposta_e_devolvida(self):
        svc = _FakeService(lambda body, i: {"rows": [], "responseAggregationType": "byProperty"})
        _, _, agregacao, _ = consultar_paginado(
            svc, PROPRIEDADE, self._corpo(), pausa=0, dormir=self.dormir
        )
        self.assertEqual(agregacao, "byProperty")


# ---------------------------------------------------------------------------
# Retentativa
# ---------------------------------------------------------------------------


class TestRetentativa(unittest.TestCase):
    def setUp(self):
        self.sonos = []

    def dormir(self, segundos):
        self.sonos.append(segundos)

    def test_429_comum_tem_backoff_exponencial_limitado(self):
        chamadas = {"n": 0}

        def fn():
            chamadas["n"] += 1
            if chamadas["n"] < 3:
                raise erro_http(429, "Too Many Requests")
            return {"ok": True}

        contador: dict = {}
        resultado = gsc_retry.executar_com_retentativa(
            fn, dormir=self.dormir, jitter=lambda: 0.0, contador=contador
        )
        self.assertEqual(resultado, {"ok": True})
        self.assertEqual(self.sonos, [2.0, 4.0])
        self.assertEqual(contador["retentativas"], 2)

    def test_backoff_respeita_o_teto(self):
        def fn():
            raise erro_http(503, "Service Unavailable")

        with self.assertRaises(HttpError):
            gsc_retry.executar_com_retentativa(
                fn, tentativas=8, teto=10.0, dormir=self.dormir, jitter=lambda: 0.0
            )
        self.assertTrue(all(s <= 10.0 for s in self.sonos), self.sonos)
        self.assertEqual(self.sonos[-1], 10.0)

    def test_carga_esgotada_espera_o_ciclo_de_quinze_minutos(self):
        # Backoff de segundos nao resolve load quota medida em janelas de 10 min:
        # a propria doc manda esperar 15 minutos.
        chamadas = {"n": 0}

        def fn():
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise erro_http(429, "User Rate Limit Exceeded: load quota")
            return {"ok": True}

        contador: dict = {}
        gsc_retry.executar_com_retentativa(
            fn, espera_carga=900, dormir=self.dormir, jitter=lambda: 0.0, contador=contador
        )
        self.assertEqual(self.sonos, [900])
        self.assertEqual(contador["esperas_carga"], 1)

    def test_400_re_levanta_na_hora_sem_dormir(self):
        # Corpo invalido nao melhora com espera — e e assim que o chamador
        # descobre que uma dimensao ou `type` foi recusado.
        def fn():
            raise erro_http(400, "Cannot group by search appearance dimension")

        with self.assertRaises(HttpError):
            gsc_retry.executar_com_retentativa(fn, dormir=self.dormir, jitter=lambda: 0.0)
        self.assertEqual(self.sonos, [])

    def test_e_carga_esgotada_so_para_403_e_429(self):
        self.assertTrue(gsc_retry.e_carga_esgotada(erro_http(429, "load quota")))
        self.assertTrue(gsc_retry.e_carga_esgotada(erro_http(403, "rate limit exceeded")))
        self.assertFalse(gsc_retry.e_carga_esgotada(erro_http(429, "Too Many Requests")))
        self.assertFalse(gsc_retry.e_carga_esgotada(erro_http(500, "load")))


# ---------------------------------------------------------------------------
# Ingestão
# ---------------------------------------------------------------------------


class TestIngestao(_BaseAcervo):
    def _ingerir(self, svc, *, dias=40, graos=("total",), **kwargs):
        inicio, fim = plan.intervalo_datas(dias, hoje=HOJE)
        return ingerir_janela(
            svc,
            self.conn,
            site_url=PROPRIEDADE,
            propriedade=PROPRIEDADE,
            inicio=inicio,
            fim=fim,
            graos=graos,
            hoje=HOJE,
            pausa=0,
            dormir=self.dormir,
            **kwargs,
        )

    def test_grava_a_serie_diaria_do_total(self):
        svc = _FakeService(responder_por_dia())
        resumo = self._ingerir(svc, dias=9)
        self.assertEqual(store.contar_linhas(self.conn, "fato_total"), 10)
        self.assertEqual(resumo["linhas"], 10)
        self.assertEqual(len(svc.bodies), 1)
        self.assertEqual(svc.bodies[0]["dimensions"], ["date"])
        self.assertEqual(svc.bodies[0]["type"], "web")

    def test_segunda_execucao_nao_repete_dia_resolvido(self):
        svc1 = _FakeService(responder_por_dia())
        self._ingerir(svc1, dias=40)
        svc2 = _FakeService(responder_por_dia())
        self._ingerir(svc2, dias=40)
        # Só os dias ainda não-definitivos voltam a ser pedidos.
        pedidos = plan.listar_dias(svc2.bodies[0]["startDate"], svc2.bodies[0]["endDate"])
        self.assertEqual(len(pedidos), 11)
        self.assertTrue(all(not plan.dia_definitivo(d, hoje=HOJE) for d in pedidos))
        self.assertEqual(store.contar_linhas(self.conn, "fato_total"), 41)

    def test_resume_nao_cobre_dia_ja_ingerido(self):
        inicio, fim = plan.intervalo_datas(40, hoje=HOJE)
        dias = plan.listar_dias(inicio, fim)
        semeados = dias[:20]
        store.gravar_lote(
            self.conn,
            grao="total",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[
                {
                    "data": dia,
                    "chaves": {},
                    "clicks": 1,
                    "impressions": 10,
                    "ctr": 0.1,
                    "position": 5.0,
                }
                for dia in semeados
            ],
            dias_do_lote=semeados,
            data_state="final",
        )
        svc = _FakeService(responder_por_dia())
        self._ingerir(svc, dias=40)
        for corpo in svc.bodies:
            self.assertGreaterEqual(corpo["startDate"], dias[20])

    def test_ponta_assentando_e_sobrescrita_com_o_valor_novo(self):
        svc1 = _FakeService(responder_por_dia(impressoes=100))
        self._ingerir(svc1, dias=5)
        svc2 = _FakeService(responder_por_dia(impressoes=250))
        self._ingerir(svc2, dias=5)

        linhas = self.conn.execute(
            "SELECT impressions, revisoes, data_state FROM fato_total"
        ).fetchall()
        self.assertEqual(len(linhas), 6)
        for linha in linhas:
            self.assertEqual(linha["impressions"], 250)
            self.assertEqual(linha["revisoes"], 1)
            self.assertEqual(linha["data_state"], plan.ESTADO_PROVISORIO)

    def test_cobertura_do_grao_query_e_medida_contra_o_total(self):
        # O `total` é ingerido primeiro (plan.graos_aplicaveis garante), então a
        # cobertura já tem régua na mesma execução.
        svc = _FakeService(responder_por_dia(impressoes=100, por_dia=1))
        self._ingerir(svc, dias=3, graos=("query", "total"))
        self.assertEqual(svc.bodies[0]["dimensions"], ["date"])
        valor = self.conn.execute(
            "SELECT cobertura_impressoes FROM ingestao WHERE grao='query' LIMIT 1"
        ).fetchone()["cobertura_impressoes"]
        self.assertAlmostEqual(valor, 1.0)

    def test_dia_vazio_e_marcado_e_nao_volta(self):
        svc = _FakeService(lambda body, i: {"rows": []})
        self._ingerir(svc, dias=40)
        status = {
            linha["status"]
            for linha in self.conn.execute("SELECT status FROM ingestao WHERE grao='total'")
        }
        self.assertEqual(status, {store.STATUS_VAZIO})

    def test_erro_http_marca_os_dias_e_propaga(self):
        svc = _FakeService(lambda body, i: erro_http(403, "Forbidden"))
        with self.assertRaises(HttpError):
            self._ingerir(svc, dias=5)
        linha = self.conn.execute(
            "SELECT status, erro FROM ingestao WHERE grao='total' LIMIT 1"
        ).fetchone()
        self.assertEqual(linha["status"], store.STATUS_ERRO)
        self.assertIn("403", linha["erro"])

    def test_aparencia_e_recusada_com_mensagem_clara(self):
        svc = _FakeService(responder_por_dia())
        with self.assertRaises(AcervoFetchError) as ctx:
            self._ingerir(svc, dias=5, graos=("aparencia",))
        self.assertIn("P7.4", str(ctx.exception))
        self.assertEqual(svc.bodies, [])

    def test_discover_pula_os_graos_de_query(self):
        svc = _FakeService(responder_por_dia())
        inicio, fim = plan.intervalo_datas(5, hoje=HOJE)
        ingerir_janela(
            svc,
            self.conn,
            site_url=PROPRIEDADE,
            propriedade=PROPRIEDADE,
            inicio=inicio,
            fim=fim,
            graos=("total", "query", "pagina"),
            tipo="discover",
            hoje=HOJE,
            pausa=0,
            dormir=self.dormir,
        )
        dimensoes = [tuple(c["dimensions"]) for c in svc.bodies]
        self.assertIn(("date",), dimensoes)
        self.assertIn(("date", "page"), dimensoes)
        self.assertNotIn(("date", "query"), dimensoes)


# ---------------------------------------------------------------------------
# Fallback dia a dia
# ---------------------------------------------------------------------------


class TestFallbackDiaADia(_BaseAcervo):
    def test_dia_perto_do_teto_refaz_o_lote_dia_a_dia(self):
        dias = ("2026-01-01", "2026-01-02")
        svc = _FakeService(responder_por_dia(por_dia=4))
        passo = plan.Passo(
            grao="query",
            tipo="web",
            dimensoes=("date", "query"),
            inicio=dias[0],
            fim=dias[1],
            dias=dias,
            data_state="final",
        )
        _executar_passo(
            svc,
            self.conn,
            PROPRIEDADE,
            passo,
            propriedade=PROPRIEDADE,
            pausa=0,
            dormir=self.dormir,
            teto=4,  # 4 linhas/dia já é 100% deste teto de teste
        )
        janelas = [(c["startDate"], c["endDate"]) for c in svc.bodies]
        self.assertEqual(janelas[0], (dias[0], dias[1]))
        self.assertEqual(janelas[1], (dias[0], dias[0]))
        self.assertEqual(janelas[2], (dias[1], dias[1]))
        # Cada dia isolado continua no teto: fica VISÍVEL, nunca silencioso.
        status = {
            linha["data"]: linha["status"]
            for linha in self.conn.execute("SELECT data, status FROM ingestao")
        }
        self.assertEqual(status, {dias[0]: store.STATUS_TETO, dias[1]: store.STATUS_TETO})

    def test_lote_longe_do_teto_nao_divide(self):
        dias = ("2026-01-01", "2026-01-02")
        svc = _FakeService(responder_por_dia(por_dia=2))
        passo = plan.Passo(
            grao="query",
            tipo="web",
            dimensoes=("date", "query"),
            inicio=dias[0],
            fim=dias[1],
            dias=dias,
            data_state="final",
        )
        resultado = _executar_passo(
            svc,
            self.conn,
            PROPRIEDADE,
            passo,
            propriedade=PROPRIEDADE,
            pausa=0,
            dormir=self.dormir,
            teto=100,
        )
        self.assertFalse(resultado["dividido"])
        self.assertEqual(len(svc.bodies), 1)
        self.assertEqual(resultado["linhas"], 4)


if __name__ == "__main__":
    unittest.main()
