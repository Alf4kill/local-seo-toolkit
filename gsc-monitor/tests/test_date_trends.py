"""
test_date_trends.py — Testes do P5: tendências first-party via dimensão `date`.

Cobertura (sem rede):
  - _classify_thirds: rising / declining / stable / série curta
  - compute_date_trends: site primeiro, top_n, datas faltantes = 0, sparse,
    shape compatível com as superfícies de Trends
  - fetch_date_trends: parsing com service mockado, corpos das 2 chamadas,
    cache 24h (hit evita chamada à API)
  - _trends_chart_data: modo line (gsc) vs modo bar (pytrends legado)
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import storage
from core.analytics import (
    SITE_TREND_KEY,
    _classify_thirds,
    compute_date_trends,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _date_data(site_vals: list, queries: "dict | None" = None) -> dict:
    """Monta o bruto de fetch_date_trends a partir de listas de impressões/dia."""
    dates = [f"2026-05-{d:02d}" for d in range(1, len(site_vals) + 1)]
    site_rows = [
        {"date": dt, "clicks": v // 10, "impressions": v} for dt, v in zip(dates, site_vals)
    ]
    query_rows = []
    for q, vals in (queries or {}).items():
        for dt, v in zip(dates, vals):
            if v:  # API não retorna linha para dia sem dados
                query_rows.append({"date": dt, "query": q, "clicks": v // 10, "impressions": v})
    return {
        "start_date": dates[0],
        "end_date": dates[-1],
        "site_rows": site_rows,
        "query_rows": query_rows,
    }


RISING = [10] * 10 + [15] * 10 + [30] * 10  # 1º terço 10 → último 30
DECLINING = [30] * 10 + [15] * 10 + [10] * 10
STABLE = [10] * 30


# ---------------------------------------------------------------------------
# Classificação por terços
# ---------------------------------------------------------------------------


class TestClassifyThirds(unittest.TestCase):
    def test_rising(self):
        trend, first, last = _classify_thirds(RISING)
        self.assertEqual(trend, "rising")
        self.assertEqual(first, 10.0)
        self.assertEqual(last, 30.0)

    def test_declining(self):
        self.assertEqual(_classify_thirds(DECLINING)[0], "declining")

    def test_stable(self):
        self.assertEqual(_classify_thirds(STABLE)[0], "stable")

    def test_dentro_da_banda_e_stable(self):
        # +10% fica dentro da banda (limiar é ±15%)
        vals = [100] * 10 + [100] * 10 + [110] * 10
        self.assertEqual(_classify_thirds(vals)[0], "stable")

    def test_serie_curta_e_stable(self):
        self.assertEqual(_classify_thirds([5, 10, 20])[0], "stable")
        self.assertEqual(_classify_thirds([])[0], "stable")

    def test_primeiro_terco_zero_vira_rising(self):
        vals = [0] * 10 + [0] * 10 + [50] * 10
        self.assertEqual(_classify_thirds(vals)[0], "rising")


# ---------------------------------------------------------------------------
# compute_date_trends
# ---------------------------------------------------------------------------


class TestComputeDateTrends(unittest.TestCase):
    def test_site_e_a_primeira_entrada(self):
        out = compute_date_trends(_date_data(RISING))
        self.assertEqual(list(out)[0], SITE_TREND_KEY)
        self.assertEqual(out[SITE_TREND_KEY]["trend"], "rising")

    def test_shape_compativel_com_superficies(self):
        out = compute_date_trends(_date_data(STABLE, {"kw": STABLE}))
        for entry in out.values():
            for field in ("trend", "peak", "latest", "values", "sparse"):
                self.assertIn(field, entry)
            self.assertEqual(entry["source"], "gsc")
            self.assertEqual(entry["metric"], "impressions")

    def test_top_n_por_impressoes_totais(self):
        queries = {
            "grande": [100] * 30,
            "media": [50] * 30,
            "pequena": [1] * 30,
        }
        out = compute_date_trends(_date_data(STABLE, queries), top_n=2)
        self.assertIn("grande", out)
        self.assertIn("media", out)
        self.assertNotIn("pequena", out)

    def test_datas_faltantes_contam_como_zero(self):
        # Query só aparece nos últimos 10 dias → começo da série deve ser 0
        q_vals = [0] * 20 + [40] * 10
        out = compute_date_trends(_date_data(STABLE, {"nova": q_vals}))
        entry = out["nova"]
        self.assertEqual(len(entry["values"]), 30)  # alinhada ao eixo do site
        self.assertEqual(entry["values"][0], 0)
        self.assertEqual(entry["trend"], "rising")

    def test_sparse_com_poucos_dias(self):
        q_vals = [0] * 25 + [10] * 5  # só 5 dias com dados
        out = compute_date_trends(_date_data(STABLE, {"rara": q_vals}))
        self.assertTrue(out["rara"]["sparse"])
        self.assertFalse(out[SITE_TREND_KEY]["sparse"])

    def test_latest_e_media_do_ultimo_terco(self):
        out = compute_date_trends(_date_data(RISING))
        self.assertEqual(out[SITE_TREND_KEY]["latest"], 30)
        self.assertEqual(out[SITE_TREND_KEY]["peak"], 30)

    def test_site_carrega_eixo_de_datas(self):
        out = compute_date_trends(_date_data(STABLE))
        self.assertEqual(len(out[SITE_TREND_KEY]["dates"]), 30)
        self.assertEqual(out[SITE_TREND_KEY]["dates"][0], "2026-05-01")

    def test_vazio(self):
        self.assertEqual(compute_date_trends({}), {})
        self.assertEqual(compute_date_trends(None), {})
        self.assertEqual(compute_date_trends({"site_rows": []}), {})


# ---------------------------------------------------------------------------
# fetch_date_trends (service mockado, cache isolado)
# ---------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, resp):
        self._resp = resp

    def execute(self):
        return self._resp


class _FakeService:
    """Imita service.searchanalytics().query(...).execute()."""

    def __init__(self, responses: dict):
        self._responses = responses  # {("date",): resp, ("date","query"): resp}
        self.bodies = []

    def searchanalytics(self):
        return self

    def query(self, siteUrl, body):
        self.bodies.append(body)
        return _FakeRequest(self._responses[tuple(body["dimensions"])])


def _api_responses():
    return {
        ("date",): {
            "rows": [
                {"keys": ["2026-05-01"], "clicks": 5.0, "impressions": 100.0},
                {"keys": ["2026-05-02"], "clicks": 7.0, "impressions": 140.0},
            ]
        },
        ("date", "query"): {
            "rows": [
                {"keys": ["2026-05-01", "kw a"], "clicks": 3.0, "impressions": 60.0},
                {"keys": ["2026-05-02", "kw a"], "clicks": 4.0, "impressions": 80.0},
            ]
        },
    }


class TestFetchDateTrends(unittest.TestCase):
    def setUp(self):
        self._original_dir = storage.RELATORIOS_DIR
        storage.RELATORIOS_DIR = tempfile.mkdtemp(prefix="gsc_test_dtrends_")

    def tearDown(self):
        shutil.rmtree(storage.RELATORIOS_DIR, ignore_errors=True)
        storage.RELATORIOS_DIR = self._original_dir

    def test_duas_chamadas_e_parsing(self):
        from fetchers.position_fetcher import fetch_date_trends

        svc = _FakeService(_api_responses())
        data = fetch_date_trends(svc, "ex.com", use_cache=False)

        self.assertEqual(len(svc.bodies), 2)
        self.assertEqual(svc.bodies[0]["dimensions"], ["date"])
        self.assertEqual(svc.bodies[1]["dimensions"], ["date", "query"])
        self.assertEqual(svc.bodies[0]["dataState"], "final")

        self.assertEqual(
            data["site_rows"][0], {"date": "2026-05-01", "clicks": 5, "impressions": 100}
        )
        self.assertEqual(
            data["query_rows"][1],
            {"date": "2026-05-02", "query": "kw a", "clicks": 4, "impressions": 80},
        )
        self.assertTrue(data["start_date"] < data["end_date"])

    def test_cache_hit_evita_api(self):
        from fetchers.position_fetcher import fetch_date_trends

        svc1 = _FakeService(_api_responses())
        first = fetch_date_trends(svc1, "ex.com", use_cache=True)
        self.assertEqual(len(svc1.bodies), 2)

        # 2ª chamada: serviço SEM respostas — se tocar a API, KeyError
        svc2 = _FakeService({})
        second = fetch_date_trends(svc2, "ex.com", use_cache=True)
        self.assertEqual(svc2.bodies, [])  # nenhuma chamada
        self.assertEqual(second, first)

    def test_no_cache_sempre_consulta(self):
        from fetchers.position_fetcher import fetch_date_trends

        fetch_date_trends(_FakeService(_api_responses()), "ex.com", use_cache=True)
        svc = _FakeService(_api_responses())
        fetch_date_trends(svc, "ex.com", use_cache=False)
        self.assertEqual(len(svc.bodies), 2)  # consultou mesmo com cache


# ---------------------------------------------------------------------------
# Chart data — line (gsc) vs bar (pytrends legado)
# ---------------------------------------------------------------------------


class TestTrendsChartData(unittest.TestCase):
    def test_gsc_vira_linha_com_series(self):
        from reporters.html_reporter import _trends_chart_data

        out = compute_date_trends(_date_data(RISING, {"kw": STABLE}))
        chart = _trends_chart_data(out)
        self.assertEqual(chart["mode"], "line")
        self.assertEqual(len(chart["dates"]), 30)
        labels = [s["label"] for s in chart["series"]]
        self.assertIn(SITE_TREND_KEY[:35], labels)
        site_series = next(s for s in chart["series"] if s["site"])
        self.assertEqual(len(site_series["values"]), 30)

    def test_pytrends_continua_barras(self):
        from reporters.html_reporter import _trends_chart_data

        legacy = {
            "pizza": {
                "trend": "rising",
                "peak": 90,
                "latest": 80,
                "values": [1, 2],
                "sparse": False,
            }
        }
        chart = _trends_chart_data(legacy)
        self.assertEqual(chart["mode"], "bar")
        self.assertEqual(chart["labels"], ["pizza"])


# ---------------------------------------------------------------------------
# Regressão — guards do JS do dashboard
# ---------------------------------------------------------------------------


class TestDashboardJsGuards(unittest.TestCase):
    """
    Regressão (bug desde a Fase 6, descoberto no dashboard real): as
    constantes são declaradas com `const` no escopo global do script, e
    `const` NÃO cria propriedade em `window`. Guards como
    `if (window.HIST_DATA)` eram sempre undefined/falsos — NENHUM gráfico
    renderizava no navegador. Os guards devem referenciar as constantes
    diretamente (sempre declaradas; valem null quando não há dados).
    """

    def test_guards_nao_usam_window(self):
        # Checa o padrão de GUARD ("if (window.X") — o comentário explicativo
        # do bugfix pode citar window.X livremente.
        from reporters.html_reporter import _JS

        for const in ("POS_DATA", "IDX_DATA", "HIST_DATA", "TRENDS_DATA"):
            self.assertNotIn(
                f"if (window.{const}", _JS, f"guard window.{const} nunca é true com const global"
            )

    def test_guards_referenciam_constantes_diretamente(self):
        from reporters.html_reporter import _JS

        self.assertIn("if (POS_DATA)", _JS)
        self.assertIn("if (HIST_DATA && HIST_DATA.datasets.length > 0)", _JS)
        self.assertIn("if (TRENDS_DATA && TRENDS_DATA.mode === 'line'", _JS)


# ---------------------------------------------
