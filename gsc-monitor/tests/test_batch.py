"""
test_batch.py — Testes do orquestrador de modo lote (core/batch.py).

Cobertura:
  - parse_sites_file: comentários, linhas vazias, inline, erros
  - run_batch: ordem, isolamento de erros (um site falhando não aborta o lote)
  - format_site_summary: linha-resumo OK / ERRO / sem dados
  - write_batch_report: CSV em relatorios/_batch/, colunas e vereditos

O pipeline real NUNCA é chamado — usa-se funções mock, como o design
do orquestrador pretende (pipeline_fn injetada).
"""

import csv
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import storage
from core.batch import (
    parse_sites_file,
    run_batch,
    format_site_summary,
    write_batch_report,
    VERDICT_KEYS,
)


def _make_summary(**overrides) -> dict:
    """Resumo mínimo no formato retornado por posicao.run_pipeline."""
    base = {
        "site":                   "ex.com",
        "date":                   "2026-06-09",
        "urls_total":             10,
        "urls_with_data":         8,
        "health_score":           70.7,
        "health_grade":           "Bom",
        "avg_position":           12.3,
        "ctr":                    2.5,
        "snapshot_count":         5,
        "cannibalization_groups": 3,
        "content_verdicts":       {"ok": 4, "atencao": 2, "over_otimizado": 1, "raso": 1},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# parse_sites_file
# ---------------------------------------------------------------------------

class TestParseSitesFile(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="gsc_test_batch_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, content: str) -> str:
        path = os.path.join(self.tmpdir, "sites.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_um_dominio_por_linha(self):
        path = self._write("a.com\nb.com.br\nsc-domain:c.com\n")
        self.assertEqual(parse_sites_file(path), ["a.com", "b.com.br", "sc-domain:c.com"])

    def test_ignora_comentarios_e_linhas_vazias(self):
        path = self._write("# comentario\n\na.com\n   \n# outro\nb.com\n")
        self.assertEqual(parse_sites_file(path), ["a.com", "b.com"])

    def test_comentario_inline_e_espacos(self):
        path = self._write("  a.com   # producao\nb.com#sem espaco\n")
        self.assertEqual(parse_sites_file(path), ["a.com", "b.com"])

    def test_arquivo_inexistente_levanta_filenotfound(self):
        with self.assertRaises(FileNotFoundError):
            parse_sites_file(os.path.join(self.tmpdir, "nao_existe.txt"))

    def test_arquivo_so_com_comentarios_levanta_valueerror(self):
        path = self._write("# so comentario\n\n# outro\n")
        with self.assertRaises(ValueError):
            parse_sites_file(path)


# ---------------------------------------------------------------------------
# run_batch
# ---------------------------------------------------------------------------

class TestRunBatch(unittest.TestCase):

    def test_executa_todos_em_ordem(self):
        chamados = []

        def pipeline(site):
            chamados.append(site)
            return _make_summary(site=site)

        results = run_batch(["a.com", "b.com", "c.com"], pipeline)

        self.assertEqual(chamados, ["a.com", "b.com", "c.com"])
        self.assertEqual([r["site"] for r in results], ["a.com", "b.com", "c.com"])
        self.assertTrue(all(r["ok"] for r in results))
        self.assertEqual(results[0]["summary"]["site"], "a.com")
        self.assertIsNone(results[0]["error"])

    def test_erro_em_um_site_nao_aborta_o_lote(self):
        chamados = []

        def pipeline(site):
            chamados.append(site)
            if site == "quebrado.com":
                raise RuntimeError("sitemap inacessivel")
            return _make_summary(site=site)

        results = run_batch(["a.com", "quebrado.com", "c.com"], pipeline)

        # Os 3 sites foram tentados — o erro do 2º não interrompeu o 3º
        self.assertEqual(chamados, ["a.com", "quebrado.com", "c.com"])
        self.assertEqual([r["ok"] for r in results], [True, False, True])

        falho = results[1]
        self.assertEqual(falho["site"], "quebrado.com")
        self.assertIsNone(falho["summary"])
        self.assertIn("sitemap inacessivel", falho["error"])

    def test_todos_falhando_retorna_todos_com_erro(self):
        def pipeline(site):
            raise ValueError("boom")

        results = run_batch(["a.com", "b.com"], pipeline)
        self.assertEqual(len(results), 2)
        self.assertFalse(any(r["ok"] for r in results))

    def test_lista_vazia_retorna_vazio(self):
        results = run_batch([], lambda s: _make_summary())
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# format_site_summary
# ---------------------------------------------------------------------------

class TestFormatSiteSummary(unittest.TestCase):

    def test_resultado_ok(self):
        line = format_site_summary(
            {"site": "ex.com", "ok": True, "summary": _make_summary(), "error": None}
        )
        self.assertIn("[OK]", line)
        self.assertIn("ex.com", line)
        self.assertIn("70.7", line)
        self.assertIn("Bom", line)
        self.assertIn("snapshots: 5", line)

    def test_resultado_erro(self):
        line = format_site_summary(
            {"site": "ex.com", "ok": False, "summary": None, "error": "falhou X"}
        )
        self.assertIn("[ERRO]", line)
        self.assertIn("falhou X", line)

    def test_resultado_sem_dados(self):
        summary = _make_summary(health_score=None, health_grade=None, snapshot_count=2)
        line = format_site_summary(
            {"site": "vazio.com", "ok": True, "summary": summary, "error": None}
        )
        self.assertIn("[OK]", line)
        self.assertIn("sem dados", line)
        self.assertIn("snapshots: 2", line)

    def test_linha_e_ascii_seguro(self):
        # Convenção do projeto: prints de fluxo devem funcionar em console cp1252
        line = format_site_summary(
            {"site": "ex.com", "ok": True, "summary": _make_summary(), "error": None}
        )
        line.encode("ascii")  # não deve levantar


# ---------------------------------------------------------------------------
# write_batch_report
# ---------------------------------------------------------------------------

class TestWriteBatchReport(unittest.TestCase):

    def setUp(self):
        # Isolamento independente do conftest (funciona em unittest discover puro)
        self._original_dir = storage.RELATORIOS_DIR
        storage.RELATORIOS_DIR = tempfile.mkdtemp(prefix="gsc_test_batchrep_")

    def tearDown(self):
        shutil.rmtree(storage.RELATORIOS_DIR, ignore_errors=True)
        storage.RELATORIOS_DIR = self._original_dir

    def _read_csv(self, path):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f))

    def test_cria_csv_no_diretorio_batch(self):
        results = [
            {"site": "a.com", "ok": True, "summary": _make_summary(site="a.com"), "error": None},
        ]
        path = write_batch_report(results, "2026-06-09")

        self.assertTrue(os.path.exists(path))
        self.assertEqual(os.path.basename(path), "2026-06-09_resumo.csv")
        self.assertEqual(
            os.path.basename(os.path.dirname(path)), "_batch",
            "relatório deve ficar em relatorios/_batch/",
        )

    def test_colunas_e_valores_site_ok(self):
        results = [
            {"site": "a.com", "ok": True, "summary": _make_summary(site="a.com"), "error": None},
        ]
        rows = self._read_csv(write_batch_report(results, "2026-06-09"))

        header, linha = rows[0], rows[1]
        self.assertEqual(header[0], "Site")
        self.assertIn("Health", header)
        self.assertIn("Grupos Canibalizacao", header)

        dado = dict(zip(header, linha))
        self.assertEqual(dado["Site"], "a.com")
        self.assertEqual(dado["Status"], "OK")
        self.assertEqual(dado["Health"], "70.7")
        self.assertEqual(dado["Grade"], "Bom")
        self.assertEqual(dado["Posicao Media"], "12.3")
        self.assertEqual(dado["CTR(%)"], "2.5")
        self.assertEqual(dado["Grupos Canibalizacao"], "3")
        self.assertEqual(dado["Conteudo OK"], "4")
        self.assertEqual(dado["Conteudo Atencao"], "2")
        self.assertEqual(dado["Conteudo Over-otimizado"], "1")
        self.assertEqual(dado["Conteudo Raso"], "1")
        self.assertEqual(dado["Snapshots"], "5")
        self.assertEqual(dado["Erro"], "")

    def test_vereditos_ausentes_viram_zero(self):
        summary = _make_summary(content_verdicts={"ok": 2})  # demais ausentes
        results = [{"site": "a.com", "ok": True, "summary": summary, "error": None}]
        rows = self._read_csv(write_batch_report(results, "2026-06-09"))

        dado = dict(zip(rows[0], rows[1]))
        self.assertEqual(dado["Conteudo OK"], "2")
        self.assertEqual(dado["Conteudo Atencao"], "0")
        self.assertEqual(dado["Conteudo Over-otimizado"], "0")
        self.assertEqual(dado["Conteudo Raso"], "0")

    def test_site_com_erro_registra_status_e_mensagem(self):
        results = [
            {"site": "a.com", "ok": True, "summary": _make_summary(site="a.com"), "error": None},
            {"site": "b.com", "ok": False, "summary": None, "error": "auth falhou"},
        ]
        rows = self._read_csv(write_batch_report(results, "2026-06-09"))

        self.assertEqual(len(rows), 3)  # header + 2 sites
        dado_erro = dict(zip(rows[0], rows[2]))
        self.assertEqual(dado_erro["Site"], "b.com")
        self.assertEqual(dado_erro["Status"], "ERRO")
        self.assertEqual(dado_erro["Erro"], "auth falhou")
        self.assertEqual(dado_erro["Health"], "")

    def test_ordem_dos_vereditos_no_header(self):
        # Garante que VERDICT_KEYS e o header andam juntos
        self.assertEqual(VERDICT_KEYS, ("ok", "atencao", "over_otimizado", "raso"))


if __name__ == "__main__":
    unittest.main()
