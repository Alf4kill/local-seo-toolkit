"""
test_acervo_plano.py — Testes da camada PURA do acervo (P7): plan.py e rows.py.

Sem rede, sem sqlite, sem disco. É o volume barato de cobertura e trava as
decisões que mais fácil se perdem num refactor:

  - `fim = hoje - GSC_DELAY_DAYS` (o GSC atrasa 2-3 dias);
  - `startRow` NÃO vai no corpo quando é 0 (é o default da API);
  - um lote nunca junta dias por cima de um gap;
  - a fronteira do assentamento (atraso + assentamento) para o dia ser definitivo;
  - `total` sempre primeiro, porque é a régua da cobertura;
  - discover/googleNews não aceitam a dimensão `query`.
"""

import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ACERVO_TETO_DIA_TIPO, GSC_DELAY_DAYS, ROW_LIMIT
from core.warehouse import plan, rows

HOJE = date(2026, 10, 16)


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------


class TestIntervaloDatas(unittest.TestCase):
    def test_fim_respeita_o_atraso_do_gsc(self):
        inicio, fim = plan.intervalo_datas(30, hoje=HOJE)
        self.assertEqual(fim, (HOJE - timedelta(days=GSC_DELAY_DAYS)).isoformat())
        self.assertEqual(fim, "2026-10-13")
        self.assertEqual(inicio, "2026-09-13")

    def test_janela_de_480_dias(self):
        inicio, fim = plan.intervalo_datas(480, hoje=HOJE)
        # 481 dias: o intervalo é inclusivo nas duas pontas.
        self.assertEqual(len(plan.listar_dias(inicio, fim)), 481)

    def test_formato_iso(self):
        for valor in plan.intervalo_datas(10, hoje=HOJE):
            self.assertEqual(date.fromisoformat(valor).isoformat(), valor)


class TestListarDias(unittest.TestCase):
    def test_inclusivo_nas_duas_pontas(self):
        dias = plan.listar_dias("2026-01-01", "2026-01-03")
        self.assertEqual(dias, ["2026-01-01", "2026-01-02", "2026-01-03"])

    def test_um_dia_so(self):
        self.assertEqual(plan.listar_dias("2026-01-01", "2026-01-01"), ["2026-01-01"])

    def test_fim_antes_do_inicio_e_vazio(self):
        self.assertEqual(plan.listar_dias("2026-01-05", "2026-01-01"), [])


class TestAgruparEmLotes(unittest.TestCase):
    def test_fatia_pelo_tamanho(self):
        dias = plan.listar_dias("2026-01-01", "2026-01-10")
        lotes = plan.agrupar_em_lotes(dias, 4)
        self.assertEqual([len(lote) for lote in lotes], [4, 4, 2])

    def test_nunca_junta_por_cima_de_um_gap(self):
        # 03 e 04 faltando: juntar traria dias já ingeridos de volta.
        dias = ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"]
        lotes = plan.agrupar_em_lotes(dias, 30)
        self.assertEqual(lotes, [["2026-01-01", "2026-01-02"], ["2026-01-05", "2026-01-06"]])

    def test_dias_fora_de_ordem_sao_ordenados(self):
        lotes = plan.agrupar_em_lotes(["2026-01-02", "2026-01-01"], 30)
        self.assertEqual(lotes, [["2026-01-01", "2026-01-02"]])

    def test_lista_vazia(self):
        self.assertEqual(plan.agrupar_em_lotes([], 10), [])

    def test_tamanho_invalido_levanta(self):
        with self.assertRaises(ValueError):
            plan.agrupar_em_lotes(["2026-01-01"], 0)


class TestAssentamento(unittest.TestCase):
    """Fronteira: definitivo só quando passaram (atraso + assentamento) dias."""

    def test_treze_dias_atras_ainda_nao_e_definitivo(self):
        dia = (HOJE - timedelta(days=13)).isoformat()
        self.assertFalse(plan.dia_definitivo(dia, hoje=HOJE))
        self.assertEqual(plan.estado_do_dia(dia, hoje=HOJE), plan.ESTADO_PROVISORIO)

    def test_quatorze_dias_atras_e_definitivo(self):
        dia = (HOJE - timedelta(days=14)).isoformat()
        self.assertTrue(plan.dia_definitivo(dia, hoje=HOJE))
        self.assertEqual(plan.estado_do_dia(dia, hoje=HOJE), plan.ESTADO_FINAL)

    def test_janela_do_diario_e_exatamente_os_dias_nao_definitivos(self):
        # As duas definicoes TEM de concordar: uma janela mais larga re-pede dia
        # que dias_pendentes ja considera resolvido; mais estreita deixa dia
        # revisado pelo GSC sem correcao.
        inicio, fim = plan.janela_assentamento(hoje=HOJE)
        self.assertEqual(fim, "2026-10-13")
        dias = plan.listar_dias(inicio, fim)
        self.assertEqual(len(dias), 11)
        self.assertTrue(all(not plan.dia_definitivo(d, hoje=HOJE) for d in dias))
        anterior = (date.fromisoformat(inicio) - timedelta(days=1)).isoformat()
        self.assertTrue(plan.dia_definitivo(anterior, hoje=HOJE))


# ---------------------------------------------------------------------------
# Corpo da requisição
# ---------------------------------------------------------------------------


class TestMontarCorpo(unittest.TestCase):
    def test_campos_obrigatorios(self):
        corpo = plan.montar_corpo("2026-01-01", "2026-01-31", ("date", "query"))
        self.assertEqual(corpo["startDate"], "2026-01-01")
        self.assertEqual(corpo["endDate"], "2026-01-31")
        self.assertEqual(corpo["dimensions"], ["date", "query"])
        self.assertEqual(corpo["rowLimit"], ROW_LIMIT)
        self.assertEqual(corpo["dataState"], "final")
        self.assertEqual(corpo["type"], "web")

    def test_start_row_ausente_quando_zero(self):
        # 0 é o default da API: enviar seria ruído e atrapalharia o diff de corpo.
        self.assertNotIn("startRow", plan.montar_corpo("2026-01-01", "2026-01-01", ("date",)))

    def test_start_row_presente_quando_nao_zero(self):
        corpo = plan.montar_corpo("2026-01-01", "2026-01-01", ("date",), start_row=25000)
        self.assertEqual(corpo["startRow"], 25000)

    def test_filtros_ausentes_por_default(self):
        self.assertNotIn(
            "dimensionFilterGroups", plan.montar_corpo("2026-01-01", "2026-01-01", ("date",))
        )

    def test_filtro_de_aparencia_bem_formado(self):
        filtros = plan.filtro_aparencia("AMP_BLUE_LINK")
        corpo = plan.montar_corpo("2026-01-01", "2026-01-01", ("date",), filtros=filtros)
        self.assertEqual(
            corpo["dimensionFilterGroups"],
            [
                {
                    "filters": [
                        {
                            "dimension": "searchAppearance",
                            "operator": "equals",
                            "expression": "AMP_BLUE_LINK",
                        }
                    ]
                }
            ],
        )

    def test_tipo_e_data_state_customizados(self):
        corpo = plan.montar_corpo(
            "2026-01-01", "2026-01-01", ("date",), tipo="discover", data_state="all"
        )
        self.assertEqual(corpo["type"], "discover")
        self.assertEqual(corpo["dataState"], "all")


# ---------------------------------------------------------------------------
# Truncamento
# ---------------------------------------------------------------------------


class TestTruncamento(unittest.TestCase):
    def test_longe_do_teto_nao_divide(self):
        self.assertFalse(plan.precisa_dia_a_dia({"2026-01-01": 340}))

    def test_noventa_por_cento_do_teto_divide(self):
        no_limite = int(ACERVO_TETO_DIA_TIPO * 0.9)
        self.assertTrue(plan.precisa_dia_a_dia({"2026-01-01": no_limite}))
        self.assertFalse(plan.precisa_dia_a_dia({"2026-01-01": no_limite - 1}))

    def test_sem_linhas_nao_divide(self):
        self.assertFalse(plan.precisa_dia_a_dia({}))

    def test_dias_no_teto_nomeia_os_dias(self):
        contagem = {"2026-01-01": 10, "2026-01-02": ACERVO_TETO_DIA_TIPO}
        self.assertEqual(plan.dias_no_teto(contagem), ["2026-01-02"])


# ---------------------------------------------------------------------------
# Plano
# ---------------------------------------------------------------------------


class TestGraosAplicaveis(unittest.TestCase):
    def test_total_vem_sempre_primeiro(self):
        # É a régua da cobertura: sem ele gravado, cobertura_impressoes é None.
        ordem = plan.graos_aplicaveis(("query", "pagina", "total"), "web")
        self.assertEqual(ordem[0], "total")

    def test_discover_nao_aceita_dimensao_query(self):
        ordem = plan.graos_aplicaveis(plan.GRAOS_PADRAO, "discover")
        self.assertNotIn("query", ordem)
        self.assertNotIn("query_pagina", ordem)
        self.assertIn("pagina", ordem)

    def test_web_aceita_todos_os_graos_padrao(self):
        self.assertEqual(
            sorted(plan.graos_aplicaveis(plan.GRAOS_PADRAO, "web")),
            sorted(plan.GRAOS_PADRAO),
        )


class TestMontarPassos(unittest.TestCase):
    def test_grao_desconhecido_levanta(self):
        with self.assertRaises(ValueError):
            plan.montar_passos("inexistente", "web", ["2026-01-01"])

    def test_um_passo_por_lote_com_as_dimensoes_do_grao(self):
        dias = plan.listar_dias("2026-01-01", "2026-01-10")
        passos = plan.montar_passos("query", "web", dias, hoje=HOJE, tamanho_lote=4)
        self.assertEqual(len(passos), 3)
        self.assertEqual(passos[0].dimensoes, ("date", "query"))
        self.assertEqual(passos[0].inicio, "2026-01-01")
        self.assertEqual(passos[0].fim, "2026-01-04")

    def test_lote_antigo_e_final(self):
        passos = plan.montar_passos("total", "web", ["2026-01-01"], hoje=HOJE)
        self.assertEqual(passos[0].data_state, plan.ESTADO_FINAL)

    def test_lote_que_toca_a_ponta_e_provisorio(self):
        # Conservador de propósito: um lote com qualquer dia ainda assentando é
        # provisório como um todo.
        ponta = (HOJE - timedelta(days=4)).isoformat()
        passos = plan.montar_passos("total", "web", [ponta], hoje=HOJE)
        self.assertEqual(passos[0].data_state, plan.ESTADO_PROVISORIO)


class TestEstimarRequisicoes(unittest.TestCase):
    def test_sem_medicao_conta_um_por_lote(self):
        dias = plan.listar_dias("2026-01-01", "2026-01-10")
        passos = plan.montar_passos("query", "web", dias, hoje=HOJE, tamanho_lote=4)
        est = plan.estimar_requisicoes(passos)
        self.assertEqual(est["total"]["lotes"], 3)
        self.assertEqual(est["total"]["requisicoes"], 3)
        self.assertFalse(est["total"]["medido"])

    def test_com_medicao_soma_paginas_de_start_row(self):
        dias = plan.listar_dias("2026-01-01", "2026-01-10")
        passos = plan.montar_passos("query", "web", dias, hoje=HOJE, tamanho_lote=10)
        # 10 dias x 5.000 linhas/dia = 50.000 linhas = 1 lote + 2 paginas extras.
        est = plan.estimar_requisicoes(passos, {"query": 5000})
        self.assertEqual(est["por_grao"]["query"]["linhas"], 50000)
        self.assertEqual(est["por_grao"]["query"]["requisicoes"], 3)
        self.assertTrue(est["total"]["medido"])


# ---------------------------------------------------------------------------
# rows.py
# ---------------------------------------------------------------------------


class TestNormalizarLinhas(unittest.TestCase):
    def test_mapeamento_posicional_das_chaves(self):
        brutas = [
            {
                "keys": ["2026-01-01", "kw a", "https://ex/p"],
                "clicks": 3.0,
                "impressions": 60.0,
                "ctr": 0.05,
                "position": 7.34,
            }
        ]
        linhas = rows.normalizar_linhas(brutas, colunas=("query_id", "pagina_id"))
        self.assertEqual(
            linhas[0],
            {
                "data": "2026-01-01",
                "chaves": {"query_id": "kw a", "pagina_id": "https://ex/p"},
                "clicks": 3,
                "impressions": 60,
                "ctr": 0.05,
                "position": 7.34,
            },
        )

    def test_ctr_cru_e_posicao_sem_arredondar(self):
        # O arquivo não embute decisão de apresentação: arredondar a posição
        # destruiria os deltas pequenos que a análise de 2 anos procura.
        brutas = [{"keys": ["2026-01-01"], "ctr": 0.0475123, "position": 7.349999}]
        linha = rows.normalizar_linhas(brutas, colunas=())[0]
        self.assertAlmostEqual(linha["ctr"], 0.0475123)
        self.assertAlmostEqual(linha["position"], 7.349999)

    def test_linha_sem_keys_e_descartada(self):
        self.assertEqual(rows.normalizar_linhas([{"clicks": 1}], colunas=()), [])

    def test_linha_sem_valor_de_dimensao_e_descartada(self):
        # Nada é completado com vazio: chave incompleta não vira linha.
        brutas = [{"keys": ["2026-01-01", ""], "clicks": 1}]
        self.assertEqual(rows.normalizar_linhas(brutas, colunas=("query_id",)), [])

    def test_position_ausente_vira_none(self):
        linha = rows.normalizar_linhas([{"keys": ["2026-01-01"], "clicks": 1}], colunas=())[0]
        self.assertIsNone(linha["position"])

    def test_chave_fixa_vem_do_filtro_nao_de_keys(self):
        # Caso da aparência: a API não deixa agrupar searchAppearance com outra
        # dimensão, então o valor vem do filtro da requisição.
        brutas = [{"keys": ["2026-01-01"], "clicks": 2, "impressions": 10}]
        linhas = rows.normalizar_linhas(
            brutas, colunas=("aparencia",), fixo={"aparencia": "AMP_BLUE_LINK"}
        )
        self.assertEqual(linhas[0]["chaves"], {"aparencia": "AMP_BLUE_LINK"})


class TestAgregadosPorDia(unittest.TestCase):
    def _linhas(self):
        return [
            {
                "data": "2026-01-01",
                "chaves": {},
                "clicks": 1,
                "impressions": 10,
                "ctr": 0.1,
                "position": 5.0,
            },
            {
                "data": "2026-01-01",
                "chaves": {},
                "clicks": 2,
                "impressions": 20,
                "ctr": 0.1,
                "position": 6.0,
            },
            {
                "data": "2026-01-02",
                "chaves": {},
                "clicks": 0,
                "impressions": 5,
                "ctr": 0.0,
                "position": 9.0,
            },
        ]

    def test_contar_por_dia(self):
        self.assertEqual(rows.contar_por_dia(self._linhas()), {"2026-01-01": 2, "2026-01-02": 1})

    def test_impressoes_por_dia(self):
        self.assertEqual(
            rows.impressoes_por_dia(self._linhas()), {"2026-01-01": 30, "2026-01-02": 5}
        )

    def test_cobertura_mede_a_cauda_anonimizada(self):
        cobertura = rows.cobertura_por_dia({"2026-01-01": 30}, {"2026-01-01": 100})
        self.assertAlmostEqual(cobertura["2026-01-01"], 0.3)

    def test_cobertura_sem_total_conhecido_e_none(self):
        # Nunca 0 nem 1: inventar valor aqui seria falsa confiança.
        self.assertIsNone(rows.cobertura_por_dia({"2026-01-01": 30}, {})["2026-01-01"])

    def test_valores_aparencia_ordenados_e_unicos(self):
        brutas = [{"keys": ["RICH"]}, {"keys": ["AMP"]}, {"keys": ["RICH"]}, {"keys": [""]}]
        self.assertEqual(rows.valores_aparencia(brutas), ["AMP", "RICH"])


if __name__ == "__main__":
    unittest.main()
