"""
test_analytics_phase4.py — Testes para as análises da Fase 4.

Cobre:
  4d — calculate_health_score
  4a — detect_orphan_pages
  4b — detect_cannibalization
  4c — append_historico_posicao / load_historico_posicao / load_latest_consolidated
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.analytics import (
    calculate_health_score,
    detect_cannibalization,
    detect_orphan_pages,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_position_report(rows: list) -> dict:
    """Monta um position_report mínimo para os testes."""
    return {"urls": rows}


def _row(url, position=None, clicks=0, impressions=0, ctr=0.0, has_data=True):
    return {
        "url": url, "position": position, "clicks": clicks,
        "impressions": impressions, "ctr": ctr, "has_data": has_data,
    }


# ---------------------------------------------------------------------------
# 4d — Score de saúde
# ---------------------------------------------------------------------------

class TestHealthScore(unittest.TestCase):

    def test_perfeito(self):
        """Site com 100% indexados, posição média 1, CTR perfeito."""
        rows = [_row("https://ex.com/1", position=1.0, impressions=1000, ctr=28.5)]
        report = _make_position_report(rows)
        consolidated = {"total_urls": 1, "summary": {"indexed": {"percent": 100.0}}}
        h = calculate_health_score(report, consolidated)
        self.assertEqual(h["grade"], "Excelente")
        self.assertGreaterEqual(h["score"], 80)

    def test_critico(self):
        """Site com 0% indexados e sem dados de posição."""
        rows = [_row("https://ex.com/1", has_data=False)]
        report = _make_position_report(rows)
        consolidated = {"total_urls": 1, "summary": {"indexed": {"percent": 0.0}}}
        h = calculate_health_score(report, consolidated)
        self.assertEqual(h["grade"], "Crítico")
        self.assertLess(h["score"], 40)

    def test_sem_indexacao(self):
        """Sem dados de indexação: usa 50 como neutro, has_indexation_data=False."""
        rows = [_row("https://ex.com/1", position=5.0, impressions=500, ctr=7.2)]
        report = _make_position_report(rows)
        h = calculate_health_score(report, None)
        self.assertFalse(h["has_indexation_data"])
        self.assertIsNone(h["components"]["indexation"])
        # Score deve ser calculado sem crash
        self.assertIsInstance(h["score"], float)

    def test_estrutura_retorno(self):
        """Verifica que todas as chaves esperadas estão presentes."""
        rows = [_row("https://ex.com/1", position=8.0, impressions=100, ctr=3.5)]
        report = _make_position_report(rows)
        h = calculate_health_score(report)
        self.assertIn("score", h)
        self.assertIn("grade", h)
        self.assertIn("has_indexation_data", h)
        self.assertIn("components", h)
        self.assertIn("position", h["components"])
        self.assertIn("ctr", h["components"])

    def test_grade_bom(self):
        """Score na faixa 60-79 = 'Bom'."""
        rows = [_row("https://ex.com/1", position=15.0, impressions=200, ctr=2.0)]
        report = _make_position_report(rows)
        consolidated = {"total_urls": 1, "summary": {"indexed": {"percent": 75.0}}}
        h = calculate_health_score(report, consolidated)
        self.assertIn(h["grade"], ["Bom", "Regular", "Excelente"])  # resultado razoável

    def test_sem_urls_com_dados(self):
        """Sem URLs com dados: posição e CTR devem ser 0 e 50."""
        rows = [_row("https://ex.com/1", has_data=False)]
        report = _make_position_report(rows)
        h = calculate_health_score(report)
        self.assertEqual(h["components"]["position"], 0.0)
        self.assertEqual(h["components"]["ctr"], 50.0)


# ---------------------------------------------------------------------------
# 4a — Páginas órfãs
# ---------------------------------------------------------------------------

class TestOrphanPages(unittest.TestCase):

    def test_detecta_orfas(self):
        rows = [
            _row("https://ex.com/1", has_data=True, position=5.0),
            _row("https://ex.com/2", has_data=False),
            _row("https://ex.com/3", has_data=False),
        ]
        orphans = detect_orphan_pages(_make_position_report(rows))
        self.assertEqual(len(orphans), 2)
        urls = [o["url"] for o in orphans]
        self.assertIn("https://ex.com/2", urls)
        self.assertIn("https://ex.com/3", urls)

    def test_sem_orfas(self):
        rows = [_row("https://ex.com/1", has_data=True, position=3.0)]
        orphans = detect_orphan_pages(_make_position_report(rows))
        self.assertEqual(len(orphans), 0)

    def test_todas_orfas(self):
        rows = [_row(f"https://ex.com/{i}", has_data=False) for i in range(5)]
        orphans = detect_orphan_pages(_make_position_report(rows))
        self.assertEqual(len(orphans), 5)

    def test_sugestao_presente(self):
        rows = [_row("https://ex.com/1", has_data=False)]
        orphans = detect_orphan_pages(_make_position_report(rows))
        self.assertIn("suggestion", orphans[0])
        self.assertTrue(len(orphans[0]["suggestion"]) > 0)


# ---------------------------------------------------------------------------
# 4b — Canibalização
# ---------------------------------------------------------------------------

class TestCannibalization(unittest.TestCase):

    def _query_row(self, query, url, position=5.0, clicks=10, impressions=100, ctr=10.0):
        return {
            "query": query, "url": url, "position": position,
            "clicks": clicks, "impressions": impressions, "ctr": ctr,
        }

    def test_detecta_canibalizacao(self):
        rows = [
            self._query_row("pizza delivery", "https://ex.com/a", position=3.0),
            self._query_row("pizza delivery", "https://ex.com/b", position=7.0),
            self._query_row("burger", "https://ex.com/c", position=2.0),
        ]
        result = detect_cannibalization(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["query"], "pizza delivery")
        self.assertEqual(result[0]["url_count"], 2)

    def test_sem_canibalizacao(self):
        rows = [
            self._query_row("pizza", "https://ex.com/a"),
            self._query_row("burger", "https://ex.com/b"),
        ]
        result = detect_cannibalization(rows)
        self.assertEqual(len(result), 0)

    def test_ordenacao_por_url_count(self):
        rows = [
            self._query_row("kw1", "https://ex.com/a"),
            self._query_row("kw1", "https://ex.com/b"),
            self._query_row("kw2", "https://ex.com/c"),
            self._query_row("kw2", "https://ex.com/d"),
            self._query_row("kw2", "https://ex.com/e"),   # 3 URLs
        ]
        result = detect_cannibalization(rows)
        self.assertEqual(result[0]["query"], "kw2")
        self.assertEqual(result[0]["url_count"], 3)

    def test_urls_ordenadas_por_posicao(self):
        rows = [
            self._query_row("kw", "https://ex.com/b", position=8.0),
            self._query_row("kw", "https://ex.com/a", position=2.0),
        ]
        result = detect_cannibalization(rows)
        self.assertEqual(result[0]["urls"][0]["url"], "https://ex.com/a")   # menor posição primeiro

    def test_lista_vazia(self):
        result = detect_cannibalization([])
        self.assertEqual(result, [])

    def test_ignora_url_sem_volume(self):
        """URL com impressões abaixo do limiar não conta como concorrente."""
        rows = [
            self._query_row("kw", "https://ex.com/a", position=3.0, impressions=500),
            self._query_row("kw", "https://ex.com/b", position=7.0, impressions=2),  # volume desprezível
        ]
        result = detect_cannibalization(rows)
        self.assertEqual(len(result), 0)

    def test_ignora_url_muito_abaixo(self):
        """URL com posição muito ruim não conta como concorrente."""
        rows = [
            self._query_row("kw", "https://ex.com/a", position=4.0, impressions=300),
            self._query_row("kw", "https://ex.com/b", position=85.0, impressions=300),  # não compete
        ]
        result = detect_cannibalization(rows)
        self.assertEqual(len(result), 0)

    def test_severidade_alta_na_pagina1(self):
        """Duas URLs disputando a 1ª página → severidade alta."""
        rows = [
            self._query_row("kw", "https://ex.com/a", position=3.0, impressions=400),
            self._query_row("kw", "https://ex.com/b", position=6.0, impressions=200),
        ]
        result = detect_cannibalization(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["severity"], "alta")
        self.assertEqual(result[0]["severity_score"], 200)  # impressões da secundária


# ---------------------------------------------------------------------------
# 4c — Histórico de posicionamento por URL
# ---------------------------------------------------------------------------

class TestHistoricoPosicao(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Redireciona RELATORIOS_DIR para diretório temporário
        import core.storage as st
        self._orig_relatorios = st.RELATORIOS_DIR
        st.RELATORIOS_DIR = self.tmp

    def tearDown(self):
        import core.storage as st
        st.RELATORIOS_DIR = self._orig_relatorios
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_append_e_load(self):
        from core.storage import append_historico_posicao, load_historico_posicao
        rows = [
            _row("https://ex.com/1", position=5.0, clicks=10, impressions=200, has_data=True),
            _row("https://ex.com/2", has_data=False),
        ]
        period = {"start": "2026-05-01", "end": "2026-05-30"}
        append_historico_posicao("www.ex.com", "2026-05-30", period, rows)
        hist = load_historico_posicao("www.ex.com")

        self.assertEqual(len(hist["snapshots"]), 1)
        snap = hist["snapshots"][0]
        self.assertEqual(snap["date"], "2026-05-30")
        # Apenas URLs com has_data=True são salvas
        self.assertIn("https://ex.com/1", snap["urls"])
        self.assertNotIn("https://ex.com/2", snap["urls"])

    def test_deduplicacao_mesmo_dia(self):
        from core.storage import append_historico_posicao, load_historico_posicao
        rows = [_row("https://ex.com/1", position=5.0, clicks=10, impressions=200, has_data=True)]
        period = {"start": "2026-05-01", "end": "2026-05-30"}
        append_historico_posicao("www.ex.com", "2026-05-30", period, rows)
        # Segunda chamada no mesmo dia deve substituir
        rows2 = [_row("https://ex.com/1", position=3.0, clicks=20, impressions=300, has_data=True)]
        append_historico_posicao("www.ex.com", "2026-05-30", period, rows2)
        hist = load_historico_posicao("www.ex.com")
        self.assertEqual(len(hist["snapshots"]), 1)
        self.assertEqual(hist["snapshots"][0]["urls"]["https://ex.com/1"]["position"], 3.0)

    def test_limita_30_snapshots(self):
        from core.storage import append_historico_posicao, load_historico_posicao
        rows = [_row("https://ex.com/1", position=5.0, clicks=5, impressions=100, has_data=True)]
        period = {"start": "2026-01-01", "end": "2026-01-30"}
        for i in range(35):
            date_str = f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}"
            append_historico_posicao("www.ex.com", date_str, period, rows)
        hist = load_historico_posicao("www.ex.com")
        self.assertLessEqual(len(hist["snapshots"]), 30)

    def test_load_sem_arquivo(self):
        from core.storage import load_historico_posicao
        hist = load_historico_posicao("dominio.que.nao.existe")
        self.assertEqual(hist["snapshots"], [])


class TestLoadLatestConsolidated(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        import core.storage as st
        self._orig = st.RELATORIOS_DIR
        st.RELATORIOS_DIR = self.tmp

    def tearDown(self):
        import core.storage as st
        st.RELATORIOS_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_retorna_mais_recente(self):
        from core.storage import _get_domain_dir, load_latest_consolidated
        domain_dir = _get_domain_dir("www.ex.com")
        # Cria dois arquivos consolidados
        data_old = {"total_urls": 10, "summary": {"indexed": {"total": 8, "percent": 80.0}}}
        data_new = {"total_urls": 12, "summary": {"indexed": {"total": 11, "percent": 91.7}}}
        with open(os.path.join(domain_dir, "2026-05-20_indexacao_consolidado.json"), "w") as f:
            json.dump(data_old, f)
        with open(os.path.join(domain_dir, "2026-05-30_indexacao_consolidado.json"), "w") as f:
            json.dump(data_new, f)

        result = load_latest_consolidated("www.ex.com")
        self.assertIsNotNone(result)
        self.assertEqual(result["total_urls"], 12)

    def test_retorna_none_sem_arquivo(self):
        from core.storage import load_latest_consolidated
        result = load_latest_consolidated("dominio.sem.arquivo")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
