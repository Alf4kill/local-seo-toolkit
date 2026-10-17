"""
test_acervo_pacote.py — Testes do pacote de análise do acervo (P7.2).

Offline, em banco temporário. O pacote é o que atravessa a fronteira para a
sessão de análise, então o que está travado aqui não é "o arquivo foi gerado":
são as três leituras erradas que o dado real produziu e que o `DADOS.md` existe
para impedir.

  1. COBERTURA AO LADO DA AGREGAÇÃO. `cobertura_impressoes` não significa a
     mesma coisa em todos os grãos: `byPage` conta uma impressão de SERP uma vez
     por URL do site que apareceu nela, então passa de 1,0; `byProperty` conta
     uma só, e aí o que falta é a cauda anonimizada. Sem as duas coisas lado a
     lado e com os dois mecanismos explicados, 1,29 é lido como banco corrompido
     e 0,61 como coleta falha.
  2. AS DUAS PONTAS DAS COORTES SÃO ARTEFATO. Toda URL que já existia quando a
     janela abriu aparece "surgindo" no primeiro mês; toda URL ainda viva
     aparece "vista por último" no último. Sem rótulo, as duas pontas são lidas
     como onda real de publicação e de mortandade.
  3. O CASAMENTO DAS URLs DO EVENTO. A forma da URL no GSC difere da do projeto
     em protocolo, www, barra final, query e percent-encoding. Se não casar, a
     coorte "tratadas contra não tratadas" — o argumento inteiro da análise —
     simplesmente não existe.

Mais o contrato básico: as 9 seções do plano presentes, buracos listados, o
snapshot abrindo com as mesmas contagens, e TODA consulta de `consultas.sql`
executando de fato contra o snapshot.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.warehouse import pacote, store

PROPRIEDADE = "https://www.exemplo.com.br/"
DOMINIO = "www.exemplo.com.br"

# Janela curta e totalmente controlada: 2 meses, para as coortes terem um mês de
# borda inicial, um mês de MEIO e um mês de borda final distinguíveis.
DIAS_JAN = [f"2026-01-{d:02d}" for d in range(1, 32)]
DIAS_FEV = [f"2026-02-{d:02d}" for d in range(1, 29)]
DIAS = DIAS_JAN + DIAS_FEV

URL_VELHA = "https://www.exemplo.com.br/pagina-velha"
URL_MEIO = "https://www.exemplo.com.br/publicada-no-meio"
URL_MORTA = "https://www.exemplo.com.br/morreu-no-meio"
URL_ACENTO = "https://www.exemplo.com.br/categoria/pe%C3%A7as"


def _linha(data, chaves, *, clicks=2, impressions=20, position=5.0):
    return {
        "data": data,
        "chaves": chaves,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": clicks / impressions,
        "position": position,
    }


class _PacoteBase(unittest.TestCase):
    """Semeia um acervo pequeno mas com todas as formas que o DADOS.md declara."""

    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gsc_test_pacote_")
        self.caminho = os.path.join(self.tmp, "acervo.sqlite3")
        self.destino = os.path.join(self.tmp, "pacote")
        self.conn = store.abrir_caminho(self.caminho)
        store.semear_meta(self.conn, propriedade=PROPRIEDADE)
        self._semear()

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- semeadura ---------------------------------------------------------

    def _semear(self):
        # Grão `total` — a régua. Cobertura é medida contra ele.
        store.gravar_lote(
            self.conn,
            grao="total",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[_linha(dia, {}, clicks=10, impressions=100) for dia in DIAS],
            dias_do_lote=DIAS,
            data_state="final",
            agregacao="byProperty",
        )

        # Grão `pagina` — byPage, cobertura ACIMA de 1,0 (é o esperado).
        # URL_VELHA: todos os dias (censurada nas duas pontas).
        # URL_MEIO: só de 2026-02-01 em diante (surgimento REAL).
        # URL_MORTA: só até 2026-01-20 (desaparecimento REAL).
        # URL_ACENTO: percent-encoded, como o GSC devolve.
        linhas_pagina = []
        for dia in DIAS:
            linhas_pagina.append(_linha(dia, {"pagina_id": URL_VELHA}))
            linhas_pagina.append(_linha(dia, {"pagina_id": URL_ACENTO}))
            if dia >= "2026-02-01":
                linhas_pagina.append(_linha(dia, {"pagina_id": URL_MEIO}))
            if dia <= "2026-01-20":
                linhas_pagina.append(_linha(dia, {"pagina_id": URL_MORTA}))
        store.gravar_lote(
            self.conn,
            grao="pagina",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=linhas_pagina,
            dias_do_lote=DIAS,
            data_state="final",
            agregacao="byPage",
            # 1,29 e 1,06: acima de 1,0 de propósito. Se o DADOS.md não explicar
            # o mecanismo byPage, estes números viram "banco corrompido".
            cobertura={dia: (1.29 if dia in DIAS_JAN else 1.06) for dia in DIAS},
        )

        # Grão `query` — byProperty, cobertura ABAIXO de 1,0 (a cauda anonimizada).
        store.gravar_lote(
            self.conn,
            grao="query",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[_linha(dia, {"query_id": "termo exemplo"}) for dia in DIAS],
            dias_do_lote=DIAS,
            data_state="final",
            agregacao="byProperty",
            cobertura={dia: (0.61 if dia in DIAS_JAN else 0.25) for dia in DIAS},
        )

        # Grão `query_pagina` — byPage E com cauda: atravessa 1,0.
        store.gravar_lote(
            self.conn,
            grao="query_pagina",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[
                _linha(dia, {"query_id": "termo exemplo", "pagina_id": URL_VELHA}) for dia in DIAS
            ],
            dias_do_lote=DIAS,
            data_state="final",
            agregacao="byPage",
            cobertura={dia: (1.04 if dia in DIAS_JAN else 0.88) for dia in DIAS},
        )

        # Um buraco de verdade na escrituração do grão `pagina`: 3 dias sem
        # registro nenhum (e não status='vazio', que é registro).
        with self.conn:
            self.conn.execute(
                "DELETE FROM ingestao WHERE grao='pagina' AND data BETWEEN ? AND ?",
                ("2026-01-10", "2026-01-12"),
            )
            # E um dia que bateu no teto: dado TRUNCADO naquele dia.
            self.conn.execute(
                "UPDATE ingestao SET status=? WHERE grao='pagina' AND data=?",
                (store.STATUS_TETO, "2026-01-15"),
            )

    def _gerar(self, **kwargs):
        return pacote.gerar(
            self.conn,
            propriedade=PROPRIEDADE,
            site=DOMINIO,
            destino=self.destino,
            **kwargs,
        )

    def _dados_md(self, **kwargs):
        self._gerar(**kwargs)
        with open(os.path.join(self.destino, "DADOS.md"), encoding="utf-8") as f:
            return f.read()


# ---------------------------------------------------------------------------
# Estrutura do pacote
# ---------------------------------------------------------------------------


class TestEstrutura(_PacoteBase):
    def test_gera_todos_os_arquivos_e_a_pasta_extras(self):
        resultado = self._gerar()
        for nome in ("DADOS.md", "eventos.csv", "evento_urls.csv", "consultas.sql"):
            self.assertTrue(
                os.path.exists(os.path.join(self.destino, nome)), f"{nome} nao foi gerado"
            )
        leia = os.path.join(self.destino, "extras", "LEIA.md")
        self.assertTrue(os.path.exists(leia))
        with open(leia, encoding="utf-8") as f:
            self.assertIn("exports manuais", f.read())
        self.assertTrue(resultado["snapshot"].endswith(pacote.NOME_SNAPSHOT))

    def test_snapshot_abre_e_tem_as_mesmas_contagens(self):
        resultado = self._gerar()
        copia = store.abrir_caminho(resultado["snapshot"])
        try:
            for tabela in ("fato_total", "fato_pagina", "fato_query", "fato_query_pagina"):
                self.assertEqual(
                    store.contar_linhas(copia, tabela),
                    store.contar_linhas(self.conn, tabela),
                    f"{tabela} divergiu entre o banco e o snapshot",
                )
        finally:
            copia.close()

    def test_extras_largados_pelo_usuario_aparecem_no_dados_md(self):
        self._gerar()
        with open(os.path.join(self.destino, "extras", "export_ia.csv"), "w") as f:
            f.write("a,b\n1,2\n")
        texto = self._dados_md()
        self.assertIn("export_ia.csv", texto)

    def test_sem_extras_o_dados_md_diz_que_esta_vazio(self):
        texto = self._dados_md()
        self.assertIn("Nenhum export manual", texto)

    def test_regerar_e_idempotente_e_nao_duplica_o_leia(self):
        self._gerar()
        leia = os.path.join(self.destino, "extras", "LEIA.md")
        with open(leia, "a", encoding="utf-8") as f:
            f.write("\nanotacao do usuario\n")
        self._gerar()
        with open(leia, encoding="utf-8") as f:
            # O LEIA.md existente NÃO é sobrescrito: pode ter anotação do usuário.
            self.assertIn("anotacao do usuario", f.read())


# ---------------------------------------------------------------------------
# DADOS.md — as 9 seções do plano
# ---------------------------------------------------------------------------


class TestSecoesDoDadosMd(_PacoteBase):
    def test_todas_as_secoes_estao_presentes(self):
        texto = self._dados_md()
        for titulo in (
            "## 1. Identificação",
            "## 2. Arquivos deste pacote",
            "## 3. Período coberto, por grão",
            "## 4. Buracos, explícitos",
            "## 5. Dias provisórios",
            "## 6. Cauda anonimizada e agregação da API, medidas",
            "## 7. Coortes de URL",
            "## 8. Dicionário de tabelas e views",
            "## 9. Ressalvas obrigatórias",
            "## 10. Timeline de eventos",
            "## 11. O que NÃO está aqui",
        ):
            self.assertIn(titulo, texto, f"falta a secao: {titulo}")

    def test_identifica_a_propriedade_a_forma_e_o_esquema(self):
        texto = self._dados_md()
        self.assertIn(PROPRIEDADE, texto)
        self.assertIn("PREFIXO de URL", texto)
        self.assertIn("user_version", texto)
        self.assertIn("America/Los_Angeles", texto)

    def test_ressalva_de_nao_somar_ctr_e_position_com_as_formulas(self):
        texto = self._dados_md()
        self.assertIn("NUNCA podem ser somados", texto)
        self.assertIn("SUM(clicks) / SUM(impressions)", texto)
        self.assertIn("SUM(position * impressions) / SUM(impressions)", texto)

    def test_ressalva_da_janela_movel_cita_a_data_mais_antiga(self):
        texto = self._dados_md()
        self.assertIn("perdido para sempre", texto)
        self.assertIn("2026-01-01", texto)

    def test_secao_do_que_nao_esta_aqui_cita_ia_ga4_e_core_updates(self):
        texto = self._dados_md()
        trecho = texto.split("## 11.")[1]
        self.assertIn("IA", trecho)
        self.assertIn("GA4", trecho)
        self.assertIn("core update", trecho)
        # "Ausência não é zero" é a razão de a seção existir.
        self.assertIn("ausência de dado", trecho.lower())

    def test_buracos_listados_batem_com_os_dias_semeados(self):
        texto = self._dados_md()
        bloco = texto.split("## 4.")[1].split("## 5.")[0]
        # Os 3 dias sem registro vêm comprimidos num intervalo.
        self.assertIn("2026-01-10 a 2026-01-12", bloco)
        self.assertIn("faltando (3 dias)", bloco)
        # E o dia no teto é declarado como truncado, não como normal.
        self.assertIn("2026-01-15", bloco)
        self.assertIn("TRUNCADO", bloco)

    def test_acervo_vazio_nao_diz_que_esta_tudo_certo(self):
        # Sem ingestao nenhuma, "nenhum buraco" e verdade vazia lida como
        # tranquilizacao — e "o dado mais antigo e —" nao e uma data.
        with self.conn:
            self.conn.execute("DELETE FROM ingestao")
            self.conn.execute("DELETE FROM fato_pagina")
            self.conn.execute("DELETE FROM fato_total")
        texto = self._dados_md()
        self.assertIn("Não há ingestão nenhuma neste acervo", texto)
        self.assertIn("ainda não tem dado nenhum", texto)
        self.assertNotIn("Nenhum buraco e nenhum dia no teto", texto)
        self.assertNotIn("mais antigo aqui é de **—**", texto)

    def test_sem_buraco_o_dados_md_diz_isso_em_vez_de_calar(self):
        with self.conn:
            self.conn.execute("DELETE FROM ingestao WHERE grao='pagina'")
            self.conn.execute("UPDATE ingestao SET status='ok'")
        texto = self._dados_md()
        self.assertIn("Nenhum buraco e nenhum dia no teto", texto)

    def test_dias_provisorios_carregam_o_aviso_da_ponta(self):
        store.gravar_lote(
            self.conn,
            grao="total",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[_linha("2026-03-01", {})],
            dias_do_lote=["2026-03-01"],
            data_state="final_provisorio",
        )
        texto = self._dados_md()
        bloco = texto.split("## 5.")[1].split("## 6.")[0]
        self.assertIn("2026-03-01", bloco)
        self.assertIn("Não tire conclusão da ponta", bloco)


# ---------------------------------------------------------------------------
# Cobertura × agregação — a correção que o dado real impôs
# ---------------------------------------------------------------------------


class TestCoberturaEAgregacao(_PacoteBase):
    """Cobertura sem a agregação ao lado é número que mente."""

    def setUp(self):
        super().setUp()
        self.texto = self._dados_md()
        self.bloco = self.texto.split("## 6.")[1].split("## 7.")[0]

    def test_a_agregacao_declarada_aparece_ao_lado_da_cobertura(self):
        # Cada grão tem de trazer, na MESMA linha da tabela, o que a API
        # declarou em responseAggregationType e a cobertura medida.
        for linha in self.bloco.splitlines():
            if linha.startswith("| `pagina`"):
                self.assertIn("byPage", linha)
                self.assertIn("1,290", linha)
                break
        else:
            self.fail("o grao `pagina` nao aparece na tabela de cobertura")

        for linha in self.bloco.splitlines():
            if linha.startswith("| `query`"):
                self.assertIn("byProperty", linha)
                self.assertIn("0,", linha)
                break
        else:
            self.fail("o grao `query` nao aparece na tabela de cobertura")

    def test_explica_os_dois_mecanismos_separadamente(self):
        # Mecanismo 1: a cauda anonimizada puxa para baixo.
        self.assertIn("para BAIXO", self.bloco)
        self.assertIn("anonimizada", self.bloco)
        # Mecanismo 2: byPage puxa para cima.
        self.assertIn("para CIMA", self.bloco)
        self.assertIn("uma vez por URL do site", self.bloco)

    def test_diz_que_acima_de_1_e_esperado_e_nao_corrupcao(self):
        self.assertIn("acima de 1,0 é esperada", self.bloco)
        self.assertIn("não é banco corrompido", self.bloco)

    def test_diz_que_abaixo_de_1_e_a_cauda_e_nao_coleta_falha(self):
        self.assertIn("não", self.bloco.lower())
        self.assertIn("a coleta falhou", self.bloco)

    def test_avisa_que_query_pagina_sofre_os_dois_efeitos(self):
        self.assertIn("query_pagina", self.bloco)
        self.assertIn("sentidos opostos", self.bloco)
        self.assertIn("atravessa 1,0", self.bloco)

    def test_cobertura_so_e_comparavel_entre_graos_com_a_mesma_agregacao(self):
        self.assertIn("mesma", self.bloco)
        self.assertIn("comparável entre grãos", self.bloco)

    def test_a_cobertura_mes_a_mes_traz_a_agregacao_no_cabecalho(self):
        # Sem a agregação no cabeçalho, a tabela mensal reintroduz o erro que a
        # tabela por grão acabou de evitar.
        self.assertIn("### Cobertura mês a mês", self.bloco)
        cabecalho = next(
            linha
            for linha in self.bloco.splitlines()
            if linha.startswith("| mês |") and "query" in linha
        )
        self.assertIn("byProperty", cabecalho)
        self.assertIn("byPage", cabecalho)

    def test_a_cobertura_usa_virgula_decimal_para_nao_confundir_com_milhar(self):
        # O documento usa ponto como separador de milhar ("94.720 linhas"), logo
        # "1.060" de cobertura seria ambiguo entre "um e pouco" e "mil e sessenta".
        self.assertIn("1,290", self.bloco)
        self.assertNotIn("1.290", self.bloco)

    def test_a_faixa_medida_e_a_desta_propriedade_nao_a_de_outra(self):
        # Regressão: a primeira versão citava a faixa medida no site-piloto
        # (1,06 a 1,72) dentro do DADOS.md de QUALQUER site. Um número de outra
        # propriedade no meio deste relatório é lido como fato local.
        self.assertIn("NESTE acervo", self.bloco)
        self.assertIn("`pagina` (`byPage`): 1,060 a 1,290", self.bloco)
        self.assertNotIn("1,06 a 1,72", self.bloco)
        self.assertNotIn("0,25 a 0,79", self.bloco)

    def test_cada_grao_vem_com_o_mecanismo_que_o_explica(self):
        # `pagina` é byPage sem query: só o mecanismo da agregação age.
        linha_pagina = next(
            linha for linha in self.bloco.splitlines() if linha.startswith("- `pagina`")
        )
        self.assertIn("acima de 1,0 em todos os dias medidos", linha_pagina)
        self.assertIn("só o mecanismo 2", linha_pagina)
        # `query` é byProperty com query: é o grão que mede a cauda.
        linha_query = next(
            linha for linha in self.bloco.splitlines() if linha.startswith("- `query`")
        )
        self.assertIn("abaixo de 1,0 em todos os dias medidos", linha_query)
        self.assertIn("medir a cauda", linha_query)
        # `query_pagina` é byPage COM query: os dois mecanismos, em oposição.
        linha_qp = next(
            linha for linha in self.bloco.splitlines() if linha.startswith("- `query_pagina`")
        )
        self.assertIn("atravessa 1,0", linha_qp)
        self.assertIn("DOIS mecanismos", linha_qp)

    def test_cobertura_constante_nao_e_descrita_como_atravessando_1(self):
        # Em dado real, `dispositivo` e `pais` medem exatamente 1,000 TODO dia:
        # nenhum dos dois mecanismos age neles. Dizer "atravessa 1,0" afirmaria
        # ao analista que o valor varia em volta de 1,0, quando é constante — e
        # este documento existe para não induzir leitura.
        with self.conn:
            self.conn.execute(
                "UPDATE ingestao SET cobertura_impressoes = 1.0 WHERE grao = 'pagina'"
            )
        bloco = self._dados_md().split("## 6.")[1].split("## 7.")[0]
        linha = next(li for li in bloco.splitlines() if li.startswith("- `pagina`"))
        self.assertIn("exatamente 1,000 em todos os dias medidos", linha)
        self.assertNotIn("atravessa", linha)

    def test_sem_cobertura_medida_explica_por_que_falta(self):
        with self.conn:
            self.conn.execute("UPDATE ingestao SET cobertura_impressoes = NULL")
        bloco = self._dados_md().split("## 6.")[1].split("## 7.")[0]
        self.assertIn("Nenhuma cobertura medida ainda", bloco)
        self.assertIn("`total` precisa estar ingerido", bloco)

    def test_a_consulta_de_cobertura_tambem_pede_a_agregacao(self):
        sql = dict((slug, s) for slug, _, _, s in pacote.CONSULTAS)["cobertura_e_agregacao"]
        self.assertIn("agregacao_resposta", sql)


# ---------------------------------------------------------------------------
# Coortes de URL — as duas pontas são artefato
# ---------------------------------------------------------------------------


class TestGraosNaoIngeridos(_PacoteBase):
    """0 linhas num grão nunca pedido à API não é ausência de tráfego."""

    def test_grao_sem_ingestao_vem_rotulado_na_tabela_de_linhas(self):
        texto = self._dados_md()
        bloco = texto.split("## 1.")[1].split("## 2.")[0]
        linha = next(linha for linha in bloco.splitlines() if linha.startswith("| `dispositivo`"))
        self.assertIn("NÃO INGERIDO", linha)
        self.assertIn("ausência de coleta, não ausência de tráfego", linha)
        # E o grão que de fato foi ingerido NÃO leva o rótulo.
        linha_pagina = next(linha for linha in bloco.splitlines() if linha.startswith("| `pagina`"))
        self.assertNotIn("NÃO INGERIDO", linha_pagina)

    def test_a_secao_de_periodo_lista_os_graos_que_nunca_vieram(self):
        bloco = self._dados_md().split("## 3.")[1].split("## 4.")[0]
        self.assertIn("nunca foram ingeridos", bloco)
        self.assertIn("`dispositivo`", bloco)
        self.assertIn("`pais`", bloco)
        self.assertIn("não têm NENHUM dia", bloco)

    def test_aparencia_e_rotulada_como_grao_de_fase_futura(self):
        bloco = self._dados_md().split("## 1.")[1].split("## 2.")[0]
        linha = next(linha for linha in bloco.splitlines() if linha.startswith("| `aparencia`"))
        self.assertIn("P7.4", linha)


class TestCoortesDeUrl(_PacoteBase):
    def setUp(self):
        super().setUp()
        self.coortes = store.coortes_url(self.conn, propriedade=PROPRIEDADE, tipo="web")
        self.texto = self._dados_md()
        self.bloco = self.texto.split("## 7.")[1].split("## 8.")[0]

    def test_mede_o_primeiro_e_o_ultimo_dia_de_cada_url(self):
        self.assertEqual(self.coortes["primeiro_dia"], "2026-01-01")
        self.assertEqual(self.coortes["ultimo_dia"], "2026-02-28")
        self.assertEqual(self.coortes["urls"], 4)

    def test_agrupa_surgimentos_e_desaparecimentos_por_mes(self):
        surgimentos = {i["ano_mes"]: i["urls"] for i in self.coortes["surgimentos"]}
        # URL_VELHA, URL_ACENTO e URL_MORTA começam em janeiro; URL_MEIO em fevereiro.
        self.assertEqual(surgimentos, {"2026-01": 3, "2026-02": 1})
        desaparecimentos = {i["ano_mes"]: i["urls"] for i in self.coortes["desaparecimentos"]}
        # URL_MORTA morre em janeiro; as outras três chegam ao último dia.
        self.assertEqual(desaparecimentos, {"2026-01": 1, "2026-02": 3})

    def test_as_duas_pontas_vem_marcadas_como_borda(self):
        bordas_surgimento = {i["ano_mes"]: i["borda"] for i in self.coortes["surgimentos"]}
        self.assertTrue(bordas_surgimento["2026-01"], "o primeiro mes tem de ser borda")
        self.assertFalse(bordas_surgimento["2026-02"], "mes do meio/fim nao e borda de surgimento")
        bordas_fim = {i["ano_mes"]: i["borda"] for i in self.coortes["desaparecimentos"]}
        self.assertTrue(bordas_fim["2026-02"], "o ultimo mes tem de ser borda")
        self.assertFalse(bordas_fim["2026-01"], "desaparecimento no meio e real, nao borda")

    def test_conta_as_urls_censuradas_em_cada_ponta(self):
        # Tocam o primeiro dia: URL_VELHA, URL_ACENTO e URL_MORTA.
        self.assertEqual(self.coortes["censuradas_a_esquerda"], 3)
        # Tocam o último dia: URL_VELHA, URL_ACENTO e URL_MEIO.
        self.assertEqual(self.coortes["censuradas_a_direita"], 3)

    def test_o_dados_md_rotula_as_duas_pontas_como_artefato(self):
        # ESTE é o teste que trava o erro de leitura: sem o rótulo, o analista lê
        # as duas pontas como onda real de publicação e de mortandade.
        self.assertIn("ARTEFATO DA JANELA", self.bloco)
        self.assertIn("(borda — artefato)", self.bloco)
        self.assertIn("**3 URL(s)** já apareciam no primeiro dia", self.bloco)
        self.assertIn("**3 URL(s)** ainda apareciam no", self.bloco)
        self.assertIn("Só os meses do MEIO são", self.bloco)

    def test_a_marca_de_borda_cai_nas_linhas_certas(self):
        linhas_surgimento = (
            self.bloco.split("### URLs que surgiram, por mês")[1]
            .split("### URLs vistas por último")[0]
            .splitlines()
        )
        por_mes = {
            linha.split("|")[1].strip(): linha
            for linha in linhas_surgimento
            if linha.startswith("| 2026-")
        }
        self.assertIn("artefato", por_mes["2026-01"])
        self.assertNotIn("artefato", por_mes["2026-02"])

    def test_banco_sem_fato_pagina_nao_explode(self):
        with self.conn:
            self.conn.execute("DELETE FROM fato_pagina")
        vazio = store.coortes_url(self.conn, propriedade=PROPRIEDADE, tipo="web")
        self.assertIsNone(vazio["primeiro_dia"])
        self.assertEqual(vazio["surgimentos"], [])
        self.assertIn("## 7. Coortes de URL", self._dados_md())


# ---------------------------------------------------------------------------
# Eventos e o casamento das URLs
# ---------------------------------------------------------------------------


class TestEventosEUrls(_PacoteBase):
    def _evento(self, urls, **kwargs):
        ident = store.adicionar_evento(
            self.conn,
            propriedade=PROPRIEDADE,
            data=kwargs.pop("data", "2026-01-25"),
            tipo=kwargs.pop("tipo", "conteudo-editado"),
            descricao=kwargs.pop("descricao", "reescrevi o texto destas URLs"),
            urls=urls,
            **kwargs,
        )
        return ident

    def test_chave_pagina_casa_as_sete_formas_que_o_usuario_cola(self):
        # As listas vêm do projeto do site, de planilha e de export de crawler:
        # a forma SEM protocolo, com host nu, é comum. Ela falhava, porque
        # urlsplit() só reconhece netloc depois de '//' e o host inteiro vazava
        # para dentro do caminho — e URL que não casa vai para o grupo NÃO
        # TRATADO, contaminando o controle da comparação.
        host = "www.exemplo.com.br"
        alvo = "/pagina-velha"
        for forma in (
            "https://www.exemplo.com.br/pagina-velha",
            "https://www.exemplo.com.br/pagina-velha/",
            "https://exemplo.com.br/pagina-velha",
            "/pagina-velha",
            "pagina-velha",
            "exemplo.com.br/pagina-velha",
            "www.exemplo.com.br/pagina-velha",
        ):
            self.assertEqual(store.chave_pagina(forma, host=host), alvo, forma)

    def test_chave_pagina_nao_estraga_caminho_relativo_com_ponto(self):
        # 'arquivo.pdf/x' é caminho relativo legítimo e também tem ponto: o
        # corte só vale para o host DA PROPRIEDADE, nunca por heurística de
        # string. Sem isso, a correção abriria um buraco pior do que fecha.
        host = "www.exemplo.com.br"
        for forma, esperado in (
            ("arquivo.pdf/x", "/arquivo.pdf/x"),
            ("/catalogo/v1.2/ficha", "/catalogo/v1.2/ficha"),
            ("manual.v2.pdf", "/manual.v2.pdf"),
            # Host de OUTRO site não é cortado: não é a propriedade deste acervo.
            ("outro-site.com.br/pagina-velha", "/outro-site.com.br/pagina-velha"),
        ):
            self.assertEqual(store.chave_pagina(forma, host=host), esperado, forma)

    def test_chave_pagina_sem_host_mantem_o_comportamento_anterior(self):
        # Sem a propriedade não se adivinha: o host nu continua no caminho.
        self.assertEqual(
            store.chave_pagina("exemplo.com.br/pagina-velha"), "/exemplo.com.br/pagina-velha"
        )

    def test_chave_pagina_aceita_a_propriedade_so_com_o_host(self):
        # O host nu sozinho é a raiz do site, não um caminho chamado como o host.
        self.assertEqual(store.chave_pagina("www.exemplo.com.br", host="exemplo.com.br"), "/")
        self.assertEqual(store.chave_pagina("exemplo.com.br/", host="www.exemplo.com.br"), "/")

    def test_casa_url_sem_protocolo_com_host_nu_de_ponta_a_ponta(self):
        # O caso que a sessão par mediu contra o dim_pagina real.
        ident = self._evento(["www.exemplo.com.br/pagina-velha", "exemplo.com.br/categoria/peças"])
        relatorio = store.casar_urls_evento(self.conn, evento_id=ident)[ident]
        self.assertEqual(relatorio["informadas"], 2)
        self.assertEqual(relatorio["casadas"], 2)
        self.assertEqual(relatorio["sem_casamento"], [])
        self.assertEqual(store.paginas_do_evento(self.conn, ident), sorted([URL_ACENTO, URL_VELHA]))

    def test_evento_urls_csv_nao_contradiz_a_coorte_do_banco(self):
        # Se o CSV normalizasse sem o host, a URL apareceria como casou=0
        # enquanto `evento_pagina` a tem: o pacote se contradiria.
        ident = self._evento(["www.exemplo.com.br/pagina-velha"])
        self._gerar()
        with open(os.path.join(self.destino, "evento_urls.csv"), encoding="utf-8-sig") as f:
            linhas = [linha for linha in f.read().splitlines() if not linha.startswith("#")]
        self.assertEqual(len(linhas), 2)
        self.assertIn(f"{URL_VELHA},1", linhas[1])
        self.assertEqual(store.paginas_do_evento(self.conn, ident), [URL_VELHA])

    def test_chave_pagina_normaliza_as_divergencias_do_gsc(self):
        alvo = store.chave_pagina("https://www.exemplo.com.br/pagina-velha")
        for forma in (
            "http://exemplo.com.br/pagina-velha",  # protocolo e www
            "https://www.exemplo.com.br/pagina-velha/",  # barra final
            "https://www.exemplo.com.br/pagina-velha?utm_source=x",  # query
            "/pagina-velha",  # caminho cru, como no projeto
            "  https://www.exemplo.com.br/pagina-velha  ",  # espaço
        ):
            self.assertEqual(store.chave_pagina(forma), alvo, forma)

    def test_casa_url_em_forma_divergente_com_dim_pagina(self):
        # O projeto do site tem '/pagina-velha/' (barra final, sem www);
        # o GSC devolveu 'https://www.exemplo.com.br/pagina-velha'.
        ident = self._evento(["http://exemplo.com.br/pagina-velha/"])
        relatorio = store.casar_urls_evento(self.conn, evento_id=ident)[ident]
        self.assertEqual(relatorio["informadas"], 1)
        self.assertEqual(relatorio["casadas"], 1)
        self.assertEqual(relatorio["sem_casamento"], [])
        self.assertEqual(store.paginas_do_evento(self.conn, ident), [URL_VELHA])

    def test_casa_url_acentuada_contra_a_forma_percent_encoded_do_gsc(self):
        # O GSC devolve '/categoria/pe%C3%A7as'; o projeto tem '/categoria/peças'.
        ident = self._evento(["https://www.exemplo.com.br/categoria/peças"])
        relatorio = store.casar_urls_evento(self.conn, evento_id=ident)[ident]
        self.assertEqual(relatorio["casadas"], 1)
        self.assertEqual(store.paginas_do_evento(self.conn, ident), [URL_ACENTO])

    def test_url_que_nao_existe_em_dim_pagina_e_reportada_e_nao_silenciada(self):
        ident = self._evento(
            ["https://www.exemplo.com.br/pagina-velha", "https://www.exemplo.com.br/nunca-existiu"]
        )
        relatorio = store.casar_urls_evento(self.conn, evento_id=ident)[ident]
        self.assertEqual(relatorio["informadas"], 2)
        self.assertEqual(relatorio["casadas"], 1)
        self.assertEqual(relatorio["sem_casamento"], ["https://www.exemplo.com.br/nunca-existiu"])

    def test_recasa_no_pacote_url_que_so_entrou_em_dim_pagina_depois(self):
        # O evento é anotado ANTES de a URL ter impressão: casa zero.
        ident = self._evento(["https://www.exemplo.com.br/publicada-depois"])
        self.assertEqual(store.casar_urls_evento(self.conn, evento_id=ident)[ident]["casadas"], 0)
        # A ingestão seguinte traz a URL; o `pacote` re-casa sem intervenção.
        store.gravar_lote(
            self.conn,
            grao="pagina",
            propriedade=PROPRIEDADE,
            tipo="web",
            linhas=[
                _linha("2026-02-20", {"pagina_id": "https://www.exemplo.com.br/publicada-depois"})
            ],
            dias_do_lote=["2026-02-20"],
            data_state="final",
        )
        resultado = self._gerar()
        self.assertEqual(resultado["casamento"][ident]["casadas"], 1)

    def test_remover_evento_leva_a_coorte_embora(self):
        ident = self._evento(["https://www.exemplo.com.br/pagina-velha"])
        store.casar_urls_evento(self.conn, evento_id=ident)
        self.assertTrue(store.remover_evento(self.conn, ident))
        sobrou = self.conn.execute(
            "SELECT COUNT(*) AS n FROM evento_pagina WHERE evento_id = ?", (ident,)
        ).fetchone()["n"]
        self.assertEqual(sobrou, 0)

    def test_muitas_urls_num_evento_unico(self):
        # O caso real: "estas 243 URLs são o lote regionalizado".
        urls = [f"/lote-regionalizado/{n}" for n in range(243)]
        with self.conn:
            for n in range(240):  # 3 nunca tiveram impressão
                self.conn.execute(
                    "INSERT INTO dim_pagina (url) VALUES (?)",
                    (f"https://www.exemplo.com.br/lote-regionalizado/{n}",),
                )
        ident = self._evento(urls)
        relatorio = store.casar_urls_evento(self.conn, evento_id=ident)[ident]
        self.assertEqual(relatorio["informadas"], 243)
        self.assertEqual(relatorio["casadas"], 240)
        self.assertEqual(len(relatorio["sem_casamento"]), 3)

    def test_timeline_do_dados_md_mostra_informadas_e_casadas(self):
        self._evento(
            ["https://www.exemplo.com.br/pagina-velha", "https://www.exemplo.com.br/nunca-existiu"]
        )
        texto = self._dados_md()
        bloco = texto.split("## 10.")[1].split("## 11.")[0]
        self.assertIn("reescrevi o texto destas URLs", bloco)
        self.assertIn("conteudo-editado", bloco)
        self.assertIn("| 2 | 1 |", bloco)
        # Core updates não entram na timeline, e o documento diz isso.
        self.assertIn("NÃO estão aqui", bloco)

    def test_sem_evento_a_timeline_avisa_do_custo_analitico(self):
        bloco = self._dados_md().split("## 10.")[1].split("## 11.")[0]
        self.assertIn("nenhum evento anotado", bloco)
        self.assertIn("sem causa", bloco)

    def test_eventos_csv_e_evento_urls_csv_batem_com_o_banco(self):
        ident = self._evento(
            ["https://www.exemplo.com.br/pagina-velha", "https://www.exemplo.com.br/nunca-existiu"]
        )
        self._gerar()
        with open(os.path.join(self.destino, "eventos.csv"), encoding="utf-8-sig") as f:
            eventos = [linha for linha in f.read().splitlines() if not linha.startswith("#")]
        self.assertIn("urls_informadas", eventos[0])
        self.assertTrue(eventos[1].startswith(f"{ident},2026-01-25"))
        self.assertTrue(eventos[1].endswith(",2,1"))

        with open(os.path.join(self.destino, "evento_urls.csv"), encoding="utf-8-sig") as f:
            linhas = [linha for linha in f.read().splitlines() if not linha.startswith("#")]
        self.assertEqual(len(linhas), 3)  # cabeçalho + 2 URLs informadas
        self.assertIn(f"{URL_VELHA},1", linhas[1])
        self.assertTrue(linhas[2].endswith(",,0"))


# ---------------------------------------------------------------------------
# consultas.sql — tem de EXECUTAR, não só existir
# ---------------------------------------------------------------------------


class TestConsultas(_PacoteBase):
    def test_toda_consulta_executa_contra_o_snapshot(self):
        store.adicionar_evento(
            self.conn,
            propriedade=PROPRIEDADE,
            data="2026-01-25",
            tipo="conteudo-editado",
            descricao="reescrevi",
            urls=[URL_VELHA],
        )
        resultado = self._gerar()
        copia = sqlite3.connect(resultado["snapshot"])
        copia.row_factory = sqlite3.Row
        try:
            for slug, _titulo, _expl, sql in pacote.CONSULTAS:
                with self.subTest(consulta=slug):
                    copia.execute(sql).fetchall()
        finally:
            copia.close()

    def test_o_arquivo_contem_toda_consulta_e_o_aviso_de_troque(self):
        self._gerar()
        with open(os.path.join(self.destino, "consultas.sql"), encoding="utf-8") as f:
            texto = f.read()
        for slug, titulo, _expl, _sql in pacote.CONSULTAS:
            self.assertIn(slug, texto)
            self.assertIn(titulo, texto)
        self.assertIn("TROQUE", texto)

    def test_existe_a_consulta_de_antes_depois_tratadas_contra_demais(self):
        # Sem ela o pacote não serve ao argumento que a análise precisa fazer.
        por_slug = {slug: sql for slug, _, _, sql in pacote.CONSULTAS}
        sql = por_slug["antes_depois_evento_tratadas_x_demais"]
        self.assertIn("evento_pagina", sql)
        self.assertIn("tratada", sql)
        self.assertIn("nao_tratada", sql)

    def test_antes_depois_do_evento_separa_de_fato_as_duas_coortes(self):
        # A URL tratada cai depois do evento; as não tratadas seguem iguais.
        # Se a consulta misturasse as coortes, as duas linhas viriam idênticas.
        ident = store.adicionar_evento(
            self.conn,
            propriedade=PROPRIEDADE,
            data="2026-02-01",
            tipo="conteudo-editado",
            descricao="reescrevi uma URL",
            urls=[URL_VELHA],
        )
        store.casar_urls_evento(self.conn, evento_id=ident)
        with self.conn:
            # Queda só na URL tratada, só depois do evento.
            self.conn.execute(
                "UPDATE fato_pagina SET clicks=0, impressions=1 "
                "WHERE data > '2026-02-01' AND pagina_id = "
                "(SELECT id FROM dim_pagina WHERE url = ?)",
                (URL_VELHA,),
            )
        sql = (
            {slug: s for slug, _, _, s in pacote.CONSULTAS}["antes_depois_evento_tratadas_x_demais"]
            .replace("id = 1", f"id = {ident}")
            .replace("ep.evento_id = 1", f"ep.evento_id = {ident}")
        )
        por_coorte = {
            (linha["coorte"], linha["fase"]): linha["clicks"] for linha in self.conn.execute(sql)
        }
        self.assertGreater(por_coorte[("tratada", "antes")], por_coorte[("tratada", "depois")])
        self.assertEqual(
            por_coorte[("nao_tratada", "antes")] > 0,
            por_coorte[("nao_tratada", "depois")] > 0,
        )


# ---------------------------------------------------------------------------
# Snapshot reduzido
# ---------------------------------------------------------------------------


class TestSnapshotReduzido(_PacoteBase):
    def test_reduzido_esvazia_query_pagina_e_mantem_o_resto(self):
        resultado = self._gerar(reduzido=True)
        copia = store.abrir_caminho(resultado["snapshot"])
        try:
            self.assertEqual(store.contar_linhas(copia, "fato_query_pagina"), 0)
            self.assertGreater(store.contar_linhas(copia, "fato_pagina"), 0)
            self.assertGreater(store.contar_linhas(copia, "fato_total"), 0)
        finally:
            copia.close()

    def test_o_dados_md_do_reduzido_declara_o_que_ficou_de_fora(self):
        texto = self._dados_md(reduzido=True)
        self.assertIn("REDUZIDO", texto)
        self.assertIn("fato_query_pagina", texto)
        self.assertIn("queries_que_trocaram_de_url", texto)
        # Precisa dizer onde o dado completo continua, senão esconde a perda.
        self.assertIn("banco completo continua", texto)

    def test_o_dados_md_do_completo_diz_que_e_completo_e_oferece_o_reduzido(self):
        texto = self._dados_md()
        self.assertIn("snapshot é COMPLETO", texto)
        self.assertIn("--reduzido", texto)

    def test_consultas_continuam_executando_no_reduzido(self):
        resultado = self._gerar(reduzido=True)
        copia = sqlite3.connect(resultado["snapshot"])
        try:
            for slug, _t, _e, sql in pacote.CONSULTAS:
                with self.subTest(consulta=slug):
                    copia.execute(sql).fetchall()
        finally:
            copia.close()

    def test_sem_snapshot_gera_so_os_documentos(self):
        resultado = self._gerar(com_snapshot=False)
        self.assertIsNone(resultado["snapshot"])
        self.assertFalse(os.path.exists(os.path.join(self.destino, pacote.NOME_SNAPSHOT)))
        self.assertTrue(os.path.exists(os.path.join(self.destino, "DADOS.md")))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers(unittest.TestCase):
    def test_comprimir_intervalos(self):
        self.assertEqual(pacote._comprimir_intervalos([]), [])
        self.assertEqual(
            pacote._comprimir_intervalos(["2026-01-02", "2026-01-01", "2026-01-03"]),
            ["2026-01-01 a 2026-01-03"],
        )
        self.assertEqual(
            pacote._comprimir_intervalos(["2026-01-01", "2026-01-05", "2026-01-06"]),
            ["2026-01-01", "2026-01-05 a 2026-01-06"],
        )
        # Virada de mês é dia consecutivo, não dois blocos.
        self.assertEqual(
            pacote._comprimir_intervalos(["2026-01-31", "2026-02-01"]),
            ["2026-01-31 a 2026-02-01"],
        )

    def test_lista_curta_trunca_e_diz_quanto_sobrou(self):
        self.assertEqual(pacote._lista_curta([], 3), "—")
        self.assertEqual(pacote._lista_curta(["a", "b"], 3), "a, b")
        self.assertEqual(pacote._lista_curta(["a", "b", "c", "d"], 2), "a, b … (+2)")

    def test_urls_informadas_tolera_nulo_e_lixo(self):
        self.assertEqual(store.urls_informadas(None), [])
        self.assertEqual(store.urls_informadas(""), [])
        self.assertEqual(store.urls_informadas("nao e json"), [])
        self.assertEqual(store.urls_informadas('{"a": 1}'), [])
        self.assertEqual(store.urls_informadas('["/a", " /b ", ""]'), ["/a", "/b"])


if __name__ == "__main__":
    unittest.main()
