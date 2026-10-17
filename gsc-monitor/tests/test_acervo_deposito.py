"""
test_acervo_deposito.py — Testes da camada SQLite do acervo (P7): store.py/schema.py.

Offline, em banco temporário. Trava as propriedades de que o acervo inteiro
depende, em ordem de importância:

  1. ATOMICIDADE: fatos e escrituração de um lote vivem na mesma transação —
     um crash nunca deixa um dia marcado `ok` sem suas linhas.
  2. IDEMPOTÊNCIA: re-ingerir o mesmo dia dá a MESMA contagem de linhas.
  3. RESUME: `dias_pendentes` sabe o que falta, e não re-pede dia resolvido.
  4. `revisoes` conta MUDANÇA, não re-busca (senão o `diario`, que re-busca 13
     dias toda semana, encheria a coluna de ruído).
  5. Separação de propriedade: 'https://x/' e 'sc-domain:x' são propriedades
     DIFERENTES do GSC e não podem se sobrescrever, mesmo morando no mesmo banco.
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.warehouse import rows, schema, store

HOJE = date(2026, 10, 16)
ANTIGO = (HOJE - timedelta(days=200)).isoformat()
PROPRIEDADE = "https://www.exemplo.com.br/"


def _linha(data: str, chaves: dict, *, clicks=1, impressions=10, ctr=0.1, position=5.0) -> dict:
    return {
        "data": data,
        "chaves": chaves,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr,
        "position": position,
    }


class _BancoTemp(unittest.TestCase):
    """Base: um banco novo por teste, em tmp próprio."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsc_test_acervo_")
        self.caminho = os.path.join(self.tmp, "acervo.sqlite3")
        self.conn = store.abrir_caminho(self.caminho)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Esquema
# ---------------------------------------------------------------------------


class TestEsquema(_BancoTemp):
    def test_banco_novo_nasce_na_versao_atual(self):
        versao = self.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(versao, schema.VERSAO_ESQUEMA)

    def test_aplicar_duas_vezes_e_no_op(self):
        schema.aplicar_esquema(self.conn)
        schema.aplicar_esquema(self.conn)
        self.assertEqual(
            self.conn.execute("PRAGMA user_version").fetchone()[0], schema.VERSAO_ESQUEMA
        )

    def test_tabelas_e_views_existem(self):
        nomes = {linha["name"] for linha in self.conn.execute("SELECT name FROM sqlite_master")}
        for tabela in ("fato_total", "fato_pagina", "fato_query_pagina", "ingestao", "evento"):
            self.assertIn(tabela, nomes)
        for view in ("v_pagina_dia", "v_pagina_mes", "v_cobertura", "v_evento"):
            self.assertIn(view, nomes)

    def test_migracao_aplica_e_bumpa_a_versao(self):
        versao_original = schema.VERSAO_ESQUEMA
        migracoes_originais = schema.MIGRACOES
        try:
            schema.VERSAO_ESQUEMA = versao_original + 1
            schema.MIGRACOES = {
                versao_original + 1: ("ALTER TABLE meta ADD COLUMN teste_migracao TEXT",)
            }
            self.assertEqual(schema.aplicar_esquema(self.conn), versao_original + 1)
            self.assertEqual(
                self.conn.execute("PRAGMA user_version").fetchone()[0], versao_original + 1
            )
            colunas = {linha["name"] for linha in self.conn.execute("PRAGMA table_info(meta)")}
            self.assertIn("teste_migracao", colunas)
        finally:
            schema.VERSAO_ESQUEMA = versao_original
            schema.MIGRACOES = migracoes_originais

    def test_banco_mais_novo_que_a_ferramenta_e_recusado(self):
        self.conn.execute(f"PRAGMA user_version = {schema.VERSAO_ESQUEMA + 5}")
        with self.assertRaises(RuntimeError):
            schema.aplicar_esquema(self.conn)

    def test_meta_registra_o_fuso_dos_dados(self):
        # Sem isso, uma análise futura juntaria estas datas com GA4 como se
        # fossem o mesmo dia — e elas são horário da Califórnia.
        store.semear_meta(self.conn, propriedade=PROPRIEDADE)
        self.assertEqual(store.ler_meta(self.conn, "fuso_dados"), "America/Los_Angeles")
        self.assertIn(PROPRIEDADE, store.ler_meta(self.conn, "propriedades"))


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


class TestUpsert(_BancoTemp):
    def _grava(self, linhas, *, grao="pagina", fetched_at="2026-10-16T00:00:00+00:00", dias=None):
        return store.gravar_lote(
            self.conn,
            grao=grao,
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=linhas,
            dias_do_lote=dias or [ANTIGO],
            data_state="final",
            fetched_at=fetched_at,
        )

    def test_reingerir_o_mesmo_dia_nao_duplica(self):
        linhas = [_linha(ANTIGO, {"pagina_id": "https://ex/a"})]
        self._grava(linhas)
        self._grava(linhas)
        self.assertEqual(store.contar_linhas(self.conn, "fato_pagina"), 1)

    def test_valores_sao_sobrescritos(self):
        self._grava([_linha(ANTIGO, {"pagina_id": "https://ex/a"}, clicks=1)])
        self._grava([_linha(ANTIGO, {"pagina_id": "https://ex/a"}, clicks=9)])
        linha = self.conn.execute("SELECT clicks FROM fato_pagina").fetchone()
        self.assertEqual(linha["clicks"], 9)

    def test_revisoes_nao_incrementa_sem_mudanca(self):
        # O `diario` re-busca 13 dias toda semana: contar re-buscas encheria a
        # coluna de ruído em vez de mostrar o que o GSC revisou.
        linhas = [_linha(ANTIGO, {"pagina_id": "https://ex/a"})]
        self._grava(linhas, fetched_at="2026-10-16T00:00:00+00:00")
        self._grava(linhas, fetched_at="2026-10-17T00:00:00+00:00")
        linha = self.conn.execute("SELECT revisoes, alterado_em FROM fato_pagina").fetchone()
        self.assertEqual(linha["revisoes"], 0)
        self.assertEqual(linha["alterado_em"], "2026-10-16T00:00:00+00:00")

    def test_revisoes_incrementa_quando_o_valor_muda(self):
        self._grava(
            [_linha(ANTIGO, {"pagina_id": "https://ex/a"}, clicks=1)],
            fetched_at="2026-10-16T00:00:00+00:00",
        )
        self._grava(
            [_linha(ANTIGO, {"pagina_id": "https://ex/a"}, clicks=4)],
            fetched_at="2026-10-17T00:00:00+00:00",
        )
        linha = self.conn.execute("SELECT revisoes, alterado_em FROM fato_pagina").fetchone()
        self.assertEqual(linha["revisoes"], 1)
        self.assertEqual(linha["alterado_em"], "2026-10-17T00:00:00+00:00")

    def test_position_nula_e_comparada_null_safe(self):
        # `NULL <> NULL` é NULL: com <> o CASE nunca dispararia. Por isso IS NOT.
        linhas = [_linha(ANTIGO, {"pagina_id": "https://ex/a"}, position=None)]
        self._grava(linhas)
        self._grava(linhas)
        self.assertEqual(
            self.conn.execute("SELECT revisoes FROM fato_pagina").fetchone()["revisoes"], 0
        )

    def test_position_de_nula_para_valor_conta_revisao(self):
        self._grava([_linha(ANTIGO, {"pagina_id": "https://ex/a"}, position=None)])
        self._grava([_linha(ANTIGO, {"pagina_id": "https://ex/a"}, position=5.0)])
        self.assertEqual(
            self.conn.execute("SELECT revisoes FROM fato_pagina").fetchone()["revisoes"], 1
        )

    def test_propriedades_diferentes_coexistem(self):
        # normalize_domain() colapsa as duas formas na MESMA pasta (e banco), mas
        # são propriedades diferentes do GSC, com dados diferentes.
        for propriedade in (PROPRIEDADE, "sc-domain:exemplo.com.br"):
            store.gravar_lote(
                self.conn,
                grao="total",
                propriedade=propriedade,
                tipo="web",
                linhas=[_linha(ANTIGO, {})],
                dias_do_lote=[ANTIGO],
                data_state="final",
            )
        self.assertEqual(store.contar_linhas(self.conn, "fato_total"), 2)

    def test_dimensao_e_internada_uma_vez_so(self):
        dias = [(HOJE - timedelta(days=200 + i)).isoformat() for i in range(10)]
        self._grava(
            [_linha(dia, {"pagina_id": "https://ex/a"}) for dia in dias],
            dias=dias,
        )
        self.assertEqual(store.contar_linhas(self.conn, "dim_pagina"), 1)
        self.assertEqual(store.contar_linhas(self.conn, "fato_pagina"), 10)

    def test_dia_sem_linha_e_marcado_vazio(self):
        # Sem isso, dia vazio seria re-buscado em TODA execução, para sempre.
        self._grava([], dias=[ANTIGO])
        linha = self.conn.execute("SELECT status, linhas FROM ingestao").fetchone()
        self.assertEqual(linha["status"], store.STATUS_VAZIO)
        self.assertEqual(linha["linhas"], 0)

    def test_atomicidade_crash_no_meio_nao_deixa_rastro(self):
        # A propriedade de correção mais importante do desenho.
        boas_e_ruim = [
            _linha(ANTIGO, {"pagina_id": "https://ex/a"}),
            {
                "data": ANTIGO,
                "chaves": {},
                "clicks": 1,
                "impressions": 1,
                "ctr": 0.1,
                "position": 1.0,
            },
        ]
        with self.assertRaises(KeyError):
            self._grava(boas_e_ruim)
        self.assertEqual(store.contar_linhas(self.conn, "fato_pagina"), 0)
        self.assertEqual(store.contar_linhas(self.conn, "ingestao"), 0)
        self.assertEqual(store.contar_linhas(self.conn, "dim_pagina"), 0)


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


class TestDiasPendentes(_BancoTemp):
    def _marcar(self, dia: str, status: str):
        store.gravar_lote(
            self.conn,
            grao="total",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[_linha(dia, {})] if status == store.STATUS_OK else [],
            dias_do_lote=[dia],
            data_state="final",
            status_por_dia={dia: status},
        )

    def _pendentes(self, dias, **kwargs):
        return store.dias_pendentes(
            self.conn,
            propriedade=PROPRIEDADE,
            tipo="web",
            grao="total",
            dias=dias,
            hoje=HOJE,
            **kwargs,
        )

    def test_sem_registro_e_pendente(self):
        self.assertEqual(self._pendentes([ANTIGO]), [ANTIGO])

    def test_ok_e_definitivo_nao_e_pendente(self):
        self._marcar(ANTIGO, store.STATUS_OK)
        self.assertEqual(self._pendentes([ANTIGO]), [])

    def test_ok_dentro_do_assentamento_volta_a_ser_pendente(self):
        # O GSC revisa o dado por ~10 dias depois dos 2-3 de atraso.
        recente = (HOJE - timedelta(days=5)).isoformat()
        self._marcar(recente, store.STATUS_OK)
        self.assertEqual(self._pendentes([recente]), [recente])

    def test_vazio_definitivo_nao_e_re_pedido(self):
        self._marcar(ANTIGO, store.STATUS_VAZIO)
        self.assertEqual(self._pendentes([ANTIGO]), [])

    def test_teto_definitivo_nao_e_re_pedido(self):
        # O GSC não vai mudar de ideia sobre a cauda que cortou.
        self._marcar(ANTIGO, store.STATUS_TETO)
        self.assertEqual(self._pendentes([ANTIGO]), [])

    def test_erro_volta_a_ser_pendente(self):
        store.marcar_erro(
            self.conn,
            grao="total",
            propriedade=PROPRIEDADE,
            tipo="web",
            dias=[ANTIGO],
            data_state="final",
            erro="429",
        )
        self.assertEqual(self._pendentes([ANTIGO]), [ANTIGO])

    def test_forcar_ignora_tudo(self):
        self._marcar(ANTIGO, store.STATUS_OK)
        self.assertEqual(self._pendentes([ANTIGO], forcar=True), [ANTIGO])

    def test_outra_propriedade_nao_conta_como_ingerida(self):
        self._marcar(ANTIGO, store.STATUS_OK)
        pendentes = store.dias_pendentes(
            self.conn,
            propriedade="sc-domain:exemplo.com.br",
            tipo="web",
            grao="total",
            dias=[ANTIGO],
            hoje=HOJE,
        )
        self.assertEqual(pendentes, [ANTIGO])


# ---------------------------------------------------------------------------
# Cobertura (truncamento + cauda anonimizada, no mesmo número)
# ---------------------------------------------------------------------------


class TestCobertura(_BancoTemp):
    def test_cobertura_e_medida_contra_o_total(self):
        store.gravar_lote(
            self.conn,
            grao="total",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[_linha(ANTIGO, {}, impressions=1000)],
            dias_do_lote=[ANTIGO],
            data_state="final",
        )
        totais = store.impressoes_total_por_dia(
            self.conn, propriedade=PROPRIEDADE, tipo="web", dias=[ANTIGO]
        )
        self.assertEqual(totais, {ANTIGO: 1000})

        linhas_query = [_linha(ANTIGO, {"query_id": "kw a"}, impressions=300)]
        cobertura = rows.cobertura_por_dia(rows.impressoes_por_dia(linhas_query), totais)
        store.gravar_lote(
            self.conn,
            grao="query",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=linhas_query,
            dias_do_lote=[ANTIGO],
            data_state="final",
            cobertura=cobertura,
        )
        valor = self.conn.execute(
            "SELECT cobertura_impressoes FROM ingestao WHERE grao='query'"
        ).fetchone()["cobertura_impressoes"]
        self.assertAlmostEqual(valor, 0.3)

    def test_media_linhas_por_dia_so_conta_dias_ok(self):
        dias = [(HOJE - timedelta(days=200 + i)).isoformat() for i in range(2)]
        store.gravar_lote(
            self.conn,
            grao="query",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[_linha(dias[0], {"query_id": "a"}), _linha(dias[0], {"query_id": "b"})],
            dias_do_lote=dias,
            data_state="final",
        )
        medias = store.media_linhas_por_dia(self.conn, propriedade=PROPRIEDADE, tipo="web")
        # dias[0] = 2 linhas (ok); dias[1] = 0 linhas (vazio, fora da média).
        self.assertAlmostEqual(medias["query"], 2.0)


# ---------------------------------------------------------------------------
# Separação por `type`
# ---------------------------------------------------------------------------


class TestSeparacaoPorTipo(_BancoTemp):
    """`web` e `image` são superfícies de busca DIFERENTES, no mesmo banco.

    Medido em site real: `image` pode ter mais impressões que `web` e cair de
    forma bem diferente dele. Se os dois se misturarem em qualquer lugar — chave,
    régua da cobertura ou escrituração — os dois ficam errados de uma vez.
    """

    def _gravar(self, tipo, *, grao, linhas, cobertura=None):
        store.gravar_lote(
            self.conn,
            grao=grao,
            propriedade=PROPRIEDADE,
            tipo=tipo,
            linhas=linhas,
            dias_do_lote=[ANTIGO],
            data_state="final",
            cobertura=cobertura,
        )

    def test_mesmo_dia_e_mesma_url_em_dois_tipos_sao_duas_linhas(self):
        for tipo in ("web", "image"):
            self._gravar(
                tipo,
                grao="pagina",
                linhas=[_linha(ANTIGO, {"pagina_id": "https://www.exemplo.com.br/x"})],
            )
        self.assertEqual(store.contar_linhas(self.conn, "fato_pagina"), 2)
        # E a URL é internada UMA vez: a dimensão não é por tipo.
        self.assertEqual(store.contar_linhas(self.conn, "dim_pagina"), 1)
        por_tipo = store.contar_linhas_por_tipo(self.conn, "fato_pagina")
        self.assertEqual(por_tipo, {"image": 1, "web": 1})

    def test_a_regua_da_cobertura_nao_cruza_tipos(self):
        # O erro mais perigoso desta fase: medir as impressões de `image` contra
        # o total de `web` daria uma cobertura que não é de nenhum dos dois.
        self._gravar("web", grao="total", linhas=[_linha(ANTIGO, {}, impressions=1000)])
        self._gravar("image", grao="total", linhas=[_linha(ANTIGO, {}, impressions=4000)])

        self.assertEqual(
            store.impressoes_total_por_dia(
                self.conn, propriedade=PROPRIEDADE, tipo="web", dias=[ANTIGO]
            ),
            {ANTIGO: 1000},
        )
        self.assertEqual(
            store.impressoes_total_por_dia(
                self.conn, propriedade=PROPRIEDADE, tipo="image", dias=[ANTIGO]
            ),
            {ANTIGO: 4000},
        )

    def test_cobertura_gravada_e_a_do_proprio_tipo(self):
        self._gravar("web", grao="total", linhas=[_linha(ANTIGO, {}, impressions=1000)])
        self._gravar("image", grao="total", linhas=[_linha(ANTIGO, {}, impressions=4000)])
        for tipo, impressoes in (("web", 300), ("image", 2000)):
            totais = store.impressoes_total_por_dia(
                self.conn, propriedade=PROPRIEDADE, tipo=tipo, dias=[ANTIGO]
            )
            linhas = [_linha(ANTIGO, {"query_id": "kw a"}, impressions=impressoes)]
            self._gravar(
                tipo,
                grao="query",
                linhas=linhas,
                cobertura=rows.cobertura_por_dia(rows.impressoes_por_dia(linhas), totais),
            )
        medidas = {
            linha["tipo"]: linha["cobertura_impressoes"]
            for linha in self.conn.execute(
                "SELECT tipo, cobertura_impressoes FROM ingestao WHERE grao='query'"
            )
        }
        # 300/1000 e 2000/4000 — e NÃO 300/4000 nem 2000/1000.
        self.assertAlmostEqual(medidas["web"], 0.3)
        self.assertAlmostEqual(medidas["image"], 0.5)

    def test_resume_e_por_tipo(self):
        # Ter `web` ingerido não pode marcar `image` como resolvido: seriam 16
        # meses de uma superfície inteira silenciosamente não coletados.
        self._gravar("web", grao="pagina", linhas=[_linha(ANTIGO, {"pagina_id": "/x"})])
        comuns = {"propriedade": PROPRIEDADE, "grao": "pagina", "dias": [ANTIGO]}
        self.assertEqual(store.dias_pendentes(self.conn, tipo="web", **comuns), [])
        self.assertEqual(store.dias_pendentes(self.conn, tipo="image", **comuns), [ANTIGO])

    def test_apagar_intervalo_de_um_tipo_nao_toca_no_outro(self):
        for tipo in ("web", "image"):
            self._gravar(tipo, grao="pagina", linhas=[_linha(ANTIGO, {"pagina_id": "/x"})])
        store.apagar_intervalo(
            self.conn,
            propriedade=PROPRIEDADE,
            tipo="image",
            graos=("pagina",),
            de=ANTIGO,
            ate=ANTIGO,
            apagar_fatos=True,
        )
        self.assertEqual(store.contar_linhas_por_tipo(self.conn, "fato_pagina"), {"web": 1})

    def test_cobertura_reporta_os_tipos_separados(self):
        for tipo in ("web", "image"):
            self._gravar(tipo, grao="total", linhas=[_linha(ANTIGO, {})])
        tipos = {linha["tipo"] for linha in store.cobertura(self.conn, propriedade=PROPRIEDADE)}
        self.assertEqual(tipos, {"web", "image"})


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class TestViews(_BancoTemp):
    def test_posicao_ponderada_nao_e_media_simples(self):
        dias = ["2026-03-01", "2026-03-02"]
        store.gravar_lote(
            self.conn,
            grao="pagina",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[
                _linha(
                    dias[0], {"pagina_id": "https://ex/a"}, clicks=1, impressions=100, position=10.0
                ),
                _linha(
                    dias[1], {"pagina_id": "https://ex/a"}, clicks=9, impressions=900, position=2.0
                ),
            ],
            dias_do_lote=dias,
            data_state="final",
        )
        linha = self.conn.execute("SELECT * FROM v_pagina_mes").fetchone()
        # (10*100 + 2*900) / 1000 = 2.8 — a média simples daria 6.0.
        self.assertAlmostEqual(linha["posicao_ponderada"], 2.8)
        self.assertNotAlmostEqual(linha["posicao_ponderada"], 6.0)
        self.assertAlmostEqual(linha["ctr_recalculado"], 10 / 1000)
        self.assertEqual(linha["dias_com_dado"], 2)

    def test_dia_com_position_nula_nao_enviesa_a_ponderacao(self):
        dias = ["2026-03-01", "2026-03-02", "2026-03-03"]
        store.gravar_lote(
            self.conn,
            grao="pagina",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[
                _linha(dias[0], {"pagina_id": "https://ex/a"}, impressions=100, position=10.0),
                _linha(dias[1], {"pagina_id": "https://ex/a"}, impressions=900, position=2.0),
                _linha(dias[2], {"pagina_id": "https://ex/a"}, impressions=1000, position=None),
            ],
            dias_do_lote=dias,
            data_state="final",
        )
        linha = self.conn.execute("SELECT * FROM v_pagina_mes").fetchone()
        # Sem o guard de NULL o denominador viraria 2000 e o valor cairia a 1.4.
        self.assertAlmostEqual(linha["posicao_ponderada"], 2.8)

    def test_semana_e_identificada_pela_segunda(self):
        # 2026-03-04 é uma quarta-feira; a semana começa em 2026-03-02.
        store.gravar_lote(
            self.conn,
            grao="total",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[_linha("2026-03-04", {})],
            dias_do_lote=["2026-03-04"],
            data_state="final",
        )
        linha = self.conn.execute("SELECT semana_inicio FROM v_site_semana").fetchone()
        self.assertEqual(linha["semana_inicio"], "2026-03-02")
        self.assertEqual(date.fromisoformat("2026-03-02").weekday(), 0)

    def test_cobertura_lista_buracos_por_status(self):
        store.gravar_lote(
            self.conn,
            grao="total",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[_linha(ANTIGO, {})],
            dias_do_lote=[ANTIGO],
            data_state="final",
        )
        linhas = store.cobertura(self.conn, propriedade=PROPRIEDADE)
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["status"], store.STATUS_OK)
        self.assertEqual(linhas[0]["dias"], 1)

    def test_dias_provisorios_sao_listados(self):
        store.gravar_lote(
            self.conn,
            grao="total",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[_linha(ANTIGO, {})],
            dias_do_lote=[ANTIGO],
            data_state="final_provisorio",
        )
        self.assertEqual(store.dias_provisorios(self.conn, propriedade=PROPRIEDADE), [ANTIGO])


# ---------------------------------------------------------------------------
# Re-ingestão, eventos, aparências, execução, snapshot
# ---------------------------------------------------------------------------


class TestOperacoes(_BancoTemp):
    def _semear(self, dia=ANTIGO):
        store.gravar_lote(
            self.conn,
            grao="pagina",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[_linha(dia, {"pagina_id": "https://ex/a"})],
            dias_do_lote=[dia],
            data_state="final",
        )

    def test_apagar_intervalo_limpa_so_a_escrituracao(self):
        self._semear()
        apagado = store.apagar_intervalo(
            self.conn,
            propriedade=PROPRIEDADE,
            tipo="web",
            graos=["pagina"],
            de=ANTIGO,
            ate=ANTIGO,
        )
        self.assertEqual(apagado["ingestao"], 1)
        self.assertEqual(apagado["fatos"], 0)
        self.assertEqual(store.contar_linhas(self.conn, "fato_pagina"), 1)

    def test_apagar_intervalo_com_fatos(self):
        self._semear()
        apagado = store.apagar_intervalo(
            self.conn,
            propriedade=PROPRIEDADE,
            tipo="web",
            graos=["pagina"],
            de=ANTIGO,
            ate=ANTIGO,
            apagar_fatos=True,
        )
        self.assertEqual(apagado["fatos"], 1)
        self.assertEqual(store.contar_linhas(self.conn, "fato_pagina"), 0)

    def test_evento_pontual_e_de_periodo(self):
        store.adicionar_evento(
            self.conn,
            propriedade=PROPRIEDADE,
            data="2026-03-10",
            tipo="titulo",
            descricao="troca de titulo",
        )
        ident = store.adicionar_evento(
            self.conn,
            propriedade=PROPRIEDADE,
            data="2026-04-01",
            data_fim="2026-04-05",
            tipo="migracao",
            descricao="migracao de hospedagem",
            urls=["https://ex/a"],
        )
        eventos = store.listar_eventos(self.conn, propriedade=PROPRIEDADE)
        self.assertEqual(len(eventos), 2)
        # v_evento faz COALESCE: evento pontual tem data_fim == data.
        self.assertEqual(eventos[0]["data_fim"], "2026-03-10")
        self.assertEqual(eventos[1]["data_fim"], "2026-04-05")
        self.assertTrue(store.remover_evento(self.conn, ident))
        self.assertEqual(len(store.listar_eventos(self.conn, propriedade=PROPRIEDADE)), 1)

    def test_aparencia_nova_e_sinalizada_uma_vez(self):
        # Valor novo aqui é como uma superfície de IA apareceria na API atual.
        self.assertEqual(store.registrar_aparencias(self.conn, ["AMP", "RICH"]), ["AMP", "RICH"])
        self.assertEqual(store.registrar_aparencias(self.conn, ["AMP"]), [])

    def test_log_de_execucao(self):
        ident = store.iniciar_execucao(self.conn, comando="backfill", propriedade=PROPRIEDADE)
        store.finalizar_execucao(self.conn, ident, requisicoes=7, linhas=120)
        ex = store.ultimas_execucoes(self.conn)[0]
        self.assertEqual(ex["requisicoes"], 7)
        self.assertEqual(ex["linhas"], 120)
        self.assertIsNotNone(ex["terminado_em"])

    def test_snapshot_preserva_as_contagens(self):
        self._semear()
        destino = os.path.join(self.tmp, "pacote", "acervo.sqlite3")
        store.snapshot(self.conn, destino)
        copia = store.abrir_caminho(destino)
        try:
            self.assertEqual(store.contar_linhas(copia, "fato_pagina"), 1)
        finally:
            copia.close()


if __name__ == "__main__":
    unittest.main()
