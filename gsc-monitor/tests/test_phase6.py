"""
test_phase6.py — Testes para a Fase 6 (Dashboard HTML estático).

Cobertura:
  - _classify_range: faixas de posição
  - chart helpers: _pos_chart_data, _idx_chart_data, _hist_chart_data, _trends_chart_data
  - section builders: _sec_saude, _sec_posicionamento, _sec_indexacao,
                      _sec_kg, _sec_historico, _sec_trends, _sec_canibalizacao, _sec_orfas
  - generate_dashboard: saída mínima, completa e nav dinâmico
  - storage.save_dashboard: criação e sobrescrita
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reporters.html_reporter import (
    _classify_range,
    _hist_chart_data,
    _idx_chart_data,
    _pos_chart_data,
    _sec_canibalizacao,
    _sec_historico,
    _sec_indexacao,
    _sec_kg,
    _sec_orfas,
    _sec_posicionamento,
    _sec_saude,
    _sec_trends,
    _trends_chart_data,
    generate_dashboard,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_report(n_with=3, n_without=1):
    urls = [
        {"url": f"https://ex.com/p{i}", "position": float(i * 3 + 1),
         "clicks": 10, "impressions": 200, "ctr": 5.0, "has_data": True}
        for i in range(n_with)
    ] + [
        {"url": f"https://ex.com/orphan{i}", "position": None,
         "clicks": 0, "impressions": 0, "ctr": 0.0, "has_data": False}
        for i in range(n_without)
    ]
    return {
        "site": "ex.com", "date": "2026-05-30",
        "period": {"start": "2026-05-01", "end": "2026-05-28"},
        "summary": {
            "total_urls_sitemap": n_with + n_without,
            "urls_with_data": n_with,
            "urls_no_impressions": n_without,
            "avg_position_site": 5.0,
            "total_clicks": 30,
            "total_impressions": 600,
            "avg_ctr_percent": 5.0,
        },
        "urls": urls,
    }


def _make_data():
    return {"start_date": "2026-05-01", "end_date": "2026-05-28",
            "country": "global", "rows": _make_report()["urls"]}


def _make_health(grade="Bom", score=70.0, has_idx=True):
    return {
        "score": score,
        "grade": grade,
        "components": {"indexation": 75.0, "position": 68.0, "ctr": 55.0},
        "has_indexation_data": has_idx,
    }


def _make_consolidated():
    return {
        "total_urls": 10,
        "summary": {
            "indexed":     {"total": 7, "percent": 70.0},
            "not_indexed": {"total": 2, "percent": 20.0},
            "warning":     {"total": 1, "percent": 10.0},
            "unknown":     {"total": 0, "percent":  0.0},
        },
    }


def _make_historico(n_snaps=3):
    snaps = [
        {
            "date": f"2026-05-{i + 1:02d}",
            "period": {"start": "2026-04-01", "end": f"2026-05-{i + 1:02d}"},
            "urls": {
                "https://ex.com/p0": {"position": 5.0 + i, "clicks": 10, "impressions": 200},
            },
        }
        for i in range(n_snaps)
    ]
    return {"site": "ex.com", "snapshots": snaps}


# ---------------------------------------------------------------------------
# _classify_range
# ---------------------------------------------------------------------------

class TestClassifyRange(unittest.TestCase):

    def test_top3(self):
        self.assertEqual(_classify_range(1.0), "Top 3")
        self.assertEqual(_classify_range(3.0), "Top 3")

    def test_primeira_pagina(self):
        self.assertEqual(_classify_range(4.0), "1ª Página")
        self.assertEqual(_classify_range(10.0), "1ª Página")

    def test_sem_dados(self):
        self.assertEqual(_classify_range(None), "Sem Dados")

    def test_quarta_mais(self):
        self.assertEqual(_classify_range(51.0), "4ª+ Página")


# ---------------------------------------------------------------------------
# Chart data helpers
# ---------------------------------------------------------------------------

class TestPosChartData(unittest.TestCase):

    def test_contagens_corretas(self):
        # positions 1.0 (Top 3), 4.0 (1ª Página), 7.0 (1ª Página), None (Sem Dados)
        result = _pos_chart_data(_make_report(n_with=3, n_without=1))
        totals = dict(zip(result["labels"], result["counts"]))
        self.assertEqual(totals.get("Top 3"), 1)
        self.assertEqual(totals.get("1ª Página"), 2)
        self.assertEqual(totals.get("Sem Dados"), 1)

    def test_labels_counts_mesmo_tamanho(self):
        result = _pos_chart_data(_make_report())
        self.assertEqual(len(result["labels"]), len(result["counts"]))
        self.assertEqual(len(result["labels"]), len(result["colors"]))


class TestIdxChartData(unittest.TestCase):

    def test_labels_e_counts(self):
        result = _idx_chart_data(_make_consolidated())
        self.assertGreater(len(result["labels"]), 0)
        self.assertEqual(len(result["labels"]), len(result["counts"]))

    def test_filtra_zeros(self):
        # "unknown" tem total 0 → não deve aparecer
        result = _idx_chart_data(_make_consolidated())
        self.assertNotIn("Desconhecido", result["labels"])
        self.assertEqual(sum(result["counts"]), 10)


class TestHistChartData(unittest.TestCase):

    def test_com_snapshots(self):
        result = _hist_chart_data(_make_historico(n_snaps=3))
        self.assertEqual(len(result["labels"]), 3)
        self.assertGreater(len(result["datasets"]), 0)
        # eixo Y invertido é configurado no JS — não testado aqui

    def test_sem_snapshots(self):
        result = _hist_chart_data({"site": "ex.com", "snapshots": []})
        self.assertEqual(result["datasets"], [])
        self.assertEqual(result["labels"], [])


class TestTrendsChartData(unittest.TestCase):

    def test_basico(self):
        trends = {
            "pizza":  {"trend": "rising",   "peak": 80, "latest": 70, "values": []},
            "queijo": {"trend": "declining", "peak": 60, "latest": 20, "values": []},
        }
        result = _trends_chart_data(trends)
        self.assertEqual(len(result["labels"]), 2)
        self.assertIn("pizza", result["labels"])
        self.assertEqual(len(result["latest"]), 2)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

class TestSecSaude(unittest.TestCase):

    def test_presente(self):
        html = _sec_saude(_make_health())
        self.assertIn("Saúde", html)
        self.assertIn("70", html)
        self.assertIn("Bom", html)

    def test_ausente(self):
        self.assertEqual(_sec_saude(None), "")
        self.assertEqual(_sec_saude({}), "")

    def test_sem_indexacao_mostra_nota(self):
        html = _sec_saude(_make_health(has_idx=False))
        # Sem indexação: a nota deve indicar score só de Posição + CTR
        # (pesos re-normalizados), nunca presumir um valor de indexação.
        self.assertIn("Posição + CTR", html)


class TestSecPosicionamento(unittest.TestCase):

    def test_conteudo_basico(self):
        html = _sec_posicionamento(_make_report(), _make_data())
        self.assertIn("Posicionamento", html)
        self.assertIn("chart-pos", html)
        self.assertIn("2026-05-01", html)


class TestSecIndexacao(unittest.TestCase):

    def test_com_dados(self):
        html = _sec_indexacao(_make_consolidated())
        self.assertIn("Indexação", html)
        self.assertIn("chart-idx", html)
        self.assertIn("70.0%", html)

    def test_sem_dados(self):
        self.assertEqual(_sec_indexacao(None), "")


class TestSecKg(unittest.TestCase):

    def test_found(self):
        kg = {"found": True, "brand": "Ex", "name": "Example Corp",
              "types": ["Organization"], "description": "Uma empresa.",
              "detailed_desc": "", "kg_id": "kg:/g/x", "score": 80.0, "url": ""}
        html = _sec_kg(kg)
        self.assertIn("Example Corp", html)
        self.assertIn("Knowledge Graph", html)

    def test_not_found(self):
        html = _sec_kg({"found": False, "brand": "XYZ"})
        self.assertIn("não encontrada", html)

    def test_none(self):
        self.assertEqual(_sec_kg(None), "")


class TestSecHistorico(unittest.TestCase):

    def test_dois_snapshots(self):
        html = _sec_historico(_make_historico(n_snaps=2))
        self.assertIn("Histórico", html)
        self.assertIn("chart-hist", html)

    def test_um_snapshot_oculto(self):
        self.assertEqual(_sec_historico(_make_historico(n_snaps=1)), "")


class TestSecTrendsCanibOrfas(unittest.TestCase):

    def test_trends_presente(self):
        trends = {"pizza": {"trend": "rising", "peak": 80, "latest": 70}}
        html = _sec_trends(trends)
        self.assertIn("Trends", html)
        self.assertIn("pizza", html)

    def test_trends_vazio(self):
        self.assertEqual(_sec_trends({}), "")
        self.assertEqual(_sec_trends(None), "")

    def test_canibalizacao_presente(self):
        cannib = [{"query": "produto x", "url_count": 2, "urls": [
            {"url": "https://ex.com/a", "position": 5.0, "impressions": 100},
            {"url": "https://ex.com/b", "position": 8.0, "impressions": 60},
        ]}]
        html = _sec_canibalizacao(cannib)
        self.assertIn("Canibalização", html)
        self.assertIn("produto x", html)

    def test_canibalizacao_vazia(self):
        self.assertEqual(_sec_canibalizacao([]), "")

    def test_orfas_presente(self):
        html = _sec_orfas([{"url": "https://ex.com/o1"}, {"url": "https://ex.com/o2"}])
        self.assertIn("sem impressões", html)
        self.assertIn("o1", html)

    def test_orfas_vazia(self):
        self.assertEqual(_sec_orfas([]), "")


# ---------------------------------------------------------------------------
# generate_dashboard
# ---------------------------------------------------------------------------

class TestGenerateDashboard(unittest.TestCase):

    def _call(self, **kw):
        return generate_dashboard("ex.com", "2026-05-30", _make_data(), _make_report(), **kw)

    def test_estrutura_html(self):
        html = self._call()
        self.assertTrue(html.strip().startswith("<!DOCTYPE html>"))
        self.assertIn("<html", html)
        self.assertIn("chart.js", html.lower())
        self.assertIn("ex.com", html)
        self.assertIn("2026-05-30", html)

    def test_minimal_sem_opcoes(self):
        html = self._call()
        # canvas do posicionamento sempre presente
        self.assertIn('<canvas id="chart-pos">', html)
        # canvas de seções opcionais ausentes (o JS referencia os IDs mas os canvas não existem)
        self.assertNotIn('<canvas id="chart-idx">', html)
        self.assertNotIn('<canvas id="chart-hist">', html)
        self.assertNotIn('<canvas id="chart-trends">', html)

    def test_full_todas_secoes(self):
        html = self._call(
            health=_make_health(),
            consolidated=_make_consolidated(),
            historico_posicao=_make_historico(n_snaps=3),
            cannibalization=[{"query": "kw", "url_count": 2, "urls": [
                {"url": "https://ex.com/a", "position": 5.0, "impressions": 100},
                {"url": "https://ex.com/b", "position": 8.0, "impressions": 60},
            ]}],
            orphans=[{"url": "https://ex.com/o"}],
            trends_data={"pizza": {"trend": "rising", "peak": 80, "latest": 70}},
            kg_result={"found": True, "brand": "Ex", "name": "Example Corp",
                       "types": ["Organization"], "description": "desc",
                       "detailed_desc": "", "kg_id": "kg:/g/x", "score": 80.0, "url": ""},
        )
        for marker in ["chart-idx", "chart-hist", "chart-trends",
                       "Canibalização", "sem impressões", "Knowledge Graph", "Saúde"]:
            self.assertIn(marker, html, msg=f"Seção '{marker}' ausente no HTML completo")

    def test_nav_links_dinamicos(self):
        html_sem = self._call()
        html_com = self._call(health=_make_health(), consolidated=_make_consolidated())
        self.assertNotIn('href="#saude"',    html_sem)
        self.assertNotIn('href="#indexacao"', html_sem)
        self.assertIn('href="#saude"',    html_com)
        self.assertIn('href="#indexacao"', html_com)


# ---------------------------------------------------------------------------
# storage.save_dashboard
# ---------------------------------------------------------------------------

class TestSaveDashboard(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        import core.storage as st
        self._orig_dir = st.RELATORIOS_DIR
        st.RELATORIOS_DIR = self._tmp

    def tearDown(self):
        import core.storage as st
        st.RELATORIOS_DIR = self._orig_dir
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_cria_arquivo_no_caminho_correto(self):
        from core.storage import save_dashboard
        path = save_dashboard("ex.com", "<html>v1</html>")
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith("dashboard.html"))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "<html>v1</html>")

    def test_sobrescreve_na_segunda_chamada(self):
        from core.storage import save_dashboard
        save_dashboard("ex.com", "<html>v1</html>")
        save_dashboard("ex.com", "<html>v2</html>")
        domain_dir = os.path.join(self._tmp, "ex.com")
        with open(os.path.join(domain_dir, "dashboard.html"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "<html>v2</html>")


if __name__ == "__main__":
    unittest.main(verbosity=2)
