"""
test_phase5.py — Testes para a Fase 5 (KG, Trends, NLP).

Cobertura:
  5a — knowledge_graph: brand_from_domain, cache, fallback sem API key
  5b — trends_fetcher: top_keywords_from_queries, _classify_trend
  5c — nlp_analyzer: _parse_entities, _parse_categories (sem chamadas à API)
  Excel — novos parâmetros em generate_excel não quebram execução
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fetchers.knowledge_graph import brand_from_domain
from fetchers.trends_fetcher import top_keywords_from_queries, _classify_trend
from reporters.excel_reporter import generate_excel


# ---------------------------------------------------------------------------
# 5a — Knowledge Graph
# ---------------------------------------------------------------------------

class TestBrandFromDomain(unittest.TestCase):

    def test_www_prefix(self):
        self.assertEqual(brand_from_domain("www.exemplo.com.br"), "Exemplo")

    def test_sc_domain(self):
        self.assertEqual(brand_from_domain("sc-domain:exemplo.com.br"), "Exemplo")

    def test_hifen(self):
        self.assertEqual(brand_from_domain("www.exemplo-site.com.br"), "Exemplo Site")

    def test_simples(self):
        self.assertEqual(brand_from_domain("www.example.com"), "Example")


class TestKGWithoutApiKey(unittest.TestCase):

    def test_sem_api_key_retorna_none(self):
        from fetchers.knowledge_graph import search_entity
        # Garante que não há API key no ambiente de teste
        with patch.dict(os.environ, {}, clear=False):
            # Remove GOOGLE_API_KEY se existir
            env_bak = os.environ.pop("GOOGLE_API_KEY", None)
            # Aponta key_file para caminho inexistente
            with patch("fetchers.knowledge_graph.load_api_key", return_value=None):
                result = search_entity("www.example.com")
            if env_bak:
                os.environ["GOOGLE_API_KEY"] = env_bak
        self.assertIsNone(result)

    def test_cache_read_write(self):
        """Verifica que o cache KG lê e escreve corretamente."""
        from fetchers.knowledge_graph import _read_kg_cache, _write_kg_cache
        import core.storage as st

        tmp = tempfile.mkdtemp()
        orig = st.RELATORIOS_DIR
        st.RELATORIOS_DIR = tmp
        try:
            data = {"found": True, "brand": "Test", "name": "Test Corp",
                    "types": ["Organization"], "description": "desc",
                    "detailed_desc": "", "kg_id": "kg:/g/test", "score": 50.0, "url": ""}
            _write_kg_cache("test.com", data)
            cached = _read_kg_cache("test.com")
            self.assertIsNotNone(cached)
            self.assertEqual(cached["name"], "Test Corp")
        finally:
            st.RELATORIOS_DIR = orig
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5b — Trends
# ---------------------------------------------------------------------------

class TestClassifyTrend(unittest.TestCase):

    def test_crescente(self):
        vals = [20, 22, 21, 25, 28, 30, 35, 38, 40, 42, 45, 48]
        self.assertEqual(_classify_trend(vals), "rising")

    def test_queda(self):
        vals = [50, 48, 45, 40, 35, 30, 25, 20, 18, 15, 12, 10]
        self.assertEqual(_classify_trend(vals), "declining")

    def test_estavel(self):
        vals = [40, 42, 41, 43, 40, 42, 41, 43, 40, 42, 41, 43]
        self.assertEqual(_classify_trend(vals), "stable")

    def test_poucos_dados(self):
        self.assertEqual(_classify_trend([10, 20, 30]), "stable")

    def test_lista_vazia(self):
        self.assertEqual(_classify_trend([]), "stable")


class TestTopKeywords(unittest.TestCase):

    def _qrow(self, query, position, impressions):
        return {"query": query, "position": position, "impressions": impressions,
                "url": "https://ex.com/", "clicks": 1, "ctr": 1.0}

    def test_filtra_top10(self):
        rows = [
            self._qrow("pizza", 5.0, 500),
            self._qrow("burger", 15.0, 800),   # fora do top 10
            self._qrow("pasta", 3.0, 300),
        ]
        kws = top_keywords_from_queries(rows)
        self.assertIn("pizza", kws)
        self.assertIn("pasta", kws)
        self.assertNotIn("burger", kws)

    def test_ordenacao(self):
        rows = [
            self._qrow("kw1", 5.0, 100),
            self._qrow("kw2", 3.0, 500),
            self._qrow("kw3", 8.0, 250),
        ]
        kws = top_keywords_from_queries(rows)
        self.assertEqual(kws[0], "kw2")
        self.assertEqual(kws[1], "kw3")

    def test_limite_max_kw(self):
        rows = [self._qrow(f"kw{i}", float(i), 100) for i in range(1, 20)]
        kws = top_keywords_from_queries(rows, max_kw=5)
        self.assertEqual(len(kws), 5)

    def test_lista_vazia(self):
        self.assertEqual(top_keywords_from_queries([]), [])


# ---------------------------------------------------------------------------
# 5c — NLP parsers (sem chamadas à API)
# ---------------------------------------------------------------------------

class TestNlpParsers(unittest.TestCase):

    def test_parse_entities_filtra_skip_types(self):
        from fetchers.nlp_analyzer import _parse_entities
        raw = [
            {"name": "pizza",  "type": "OTHER",  "salience": 0.8},
            {"name": "10.00",  "type": "NUMBER", "salience": 0.6},
            {"name": "hoje",   "type": "DATE",   "salience": 0.5},
            {"name": "R$ 50",  "type": "PRICE",  "salience": 0.4},
        ]
        result = _parse_entities(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "pizza")

    def test_parse_entities_ordena_por_salience(self):
        from fetchers.nlp_analyzer import _parse_entities
        raw = [
            {"name": "b", "type": "OTHER", "salience": 0.3},
            {"name": "a", "type": "OTHER", "salience": 0.7},
            {"name": "c", "type": "OTHER", "salience": 0.5},
        ]
        result = _parse_entities(raw)
        self.assertEqual(result[0]["name"], "a")
        self.assertEqual(result[1]["name"], "c")

    def test_parse_entities_limita_8(self):
        from fetchers.nlp_analyzer import _parse_entities
        raw = [{"name": f"e{i}", "type": "OTHER", "salience": 0.9 - i * 0.05} for i in range(15)]
        self.assertLessEqual(len(_parse_entities(raw)), 8)

    def test_parse_categories_ordena_por_confidence(self):
        from fetchers.nlp_analyzer import _parse_categories
        raw = [
            {"name": "/Science/Engineering", "confidence": 0.4},
            {"name": "/Business & Industrial", "confidence": 0.9},
        ]
        result = _parse_categories(raw)
        self.assertEqual(result[0]["name"], "/Business & Industrial")

    def test_parse_categories_limita_3(self):
        from fetchers.nlp_analyzer import _parse_categories
        raw = [{"name": f"/Cat{i}", "confidence": 0.9 - i * 0.1} for i in range(6)]
        self.assertLessEqual(len(_parse_categories(raw)), 3)

    def test_parse_categories_lista_vazia(self):
        from fetchers.nlp_analyzer import _parse_categories
        self.assertEqual(_parse_categories([]), [])


# ---------------------------------------------------------------------------
# Excel — novos params não quebram generate_excel
# ---------------------------------------------------------------------------

class TestGenerateExcelPhase5(unittest.TestCase):

    def _base_data(self):
        rows = [
            {"url": "https://ex.com/1", "position": 5.0, "clicks": 10,
             "impressions": 200, "ctr": 5.0, "has_data": True},
            {"url": "https://ex.com/2", "position": None, "clicks": 0,
             "impressions": 0, "ctr": 0.0, "has_data": False},
        ]
        data = {"start_date": "2026-05-01", "end_date": "2026-05-28",
                "country": "global", "rows": rows}
        report = {
            "site": "ex.com", "date": "2026-05-30",
            "period": {"start": "2026-05-01", "end": "2026-05-28", "country": "global"},
            "summary": {"total_urls_sitemap": 2, "urls_with_data": 1, "urls_no_impressions": 1,
                        "avg_position_site": 5.0, "total_clicks": 10,
                        "total_impressions": 200, "avg_ctr_percent": 5.0},
            "urls": rows,
        }
        return data, report

    def test_sem_fase5(self):
        data, report = self._base_data()
        wb = generate_excel("ex.com", "2026-05-30", data, report)
        self.assertIsNotNone(wb)

    def test_com_kg_result(self):
        data, report = self._base_data()
        kg = {"found": True, "brand": "Ex", "name": "Example Corp",
              "types": ["Organization"], "description": "Desc", "detailed_desc": "",
              "kg_id": "kg:/g/x", "score": 80.0, "url": ""}
        wb = generate_excel("ex.com", "2026-05-30", data, report, kg_result=kg)
        self.assertIsNotNone(wb)

    def test_com_trends(self):
        data, report = self._base_data()
        trends = {
            "pizza delivery": {"trend": "rising", "peak": 80, "latest": 70, "values": list(range(12))},
        }
        query_rows = [
            {"query": "pizza delivery", "url": "https://ex.com/1",
             "position": 5.0, "clicks": 5, "impressions": 100, "ctr": 5.0},
        ]
        wb = generate_excel("ex.com", "2026-05-30", data, report,
                            trends_data=trends, query_rows=query_rows)
        sheets = [ws.title for ws in wb.worksheets]
        self.assertIn("Trends", sheets)

    def test_com_nlp(self):
        data, report = self._base_data()
        # novo formato: dict com entities + categories
        nlp = {
            "https://ex.com/1": {
                "entities":   [{"name": "Pizza", "type": "OTHER", "salience": 0.5}],
                "categories": [{"name": "/Food & Drink/Pizza", "confidence": 0.92}],
            }
        }
        wb = generate_excel("ex.com", "2026-05-30", data, report, nlp_results=nlp)
        ws_opp = next((ws for ws in wb.worksheets if ws.title == "Oportunidades CTR"), None)
        if ws_opp:
            self.assertIsNotNone(ws_opp.cell(row=3, column=10).value)   # Entidades
            self.assertIsNotNone(ws_opp.cell(row=3, column=11).value)   # Categoria NLP

    def test_com_nlp_formato_antigo(self):
        """Backward compat: formato lista ainda deve funcionar sem erro."""
        data, report = self._base_data()
        nlp = {
            "https://ex.com/1": [{"name": "Pizza", "type": "OTHER", "salience": 0.5}]
        }
        wb = generate_excel("ex.com", "2026-05-30", data, report, nlp_results=nlp)
        self.assertIsNotNone(wb)

    def test_kg_nao_encontrado(self):
        data, report = self._base_data()
        kg = {"found": False, "brand": "Ex", "message": "Não encontrado"}
        wb = generate_excel("ex.com", "2026-05-30", data, report, kg_result=kg)
        self.assertIsNotNone(wb)


if __name__ == "__main__":
    unittest.main(verbosity=2)
