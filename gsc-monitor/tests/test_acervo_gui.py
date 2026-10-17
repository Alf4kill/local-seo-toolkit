"""
test_acervo_gui.py — Testes da lógica da janela do Acervo (app_acervo.py).

Não abre janela nenhuma: exercita as funções PURAS que a janela só formata, mais
a montagem de argumentos do runner. É de propósito que essa lógica mora fora dos
métodos da classe — num método de Tk ela seria intestável sem display.

Cobre também gui/terminal.py, extraído porque a colorização estava duplicada
entre main_window e poda_window e as cópias já divergiam.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ACERVO_DIAS_BACKFILL
from gui import terminal
from gui.acervo_runner import montar_args
from gui.acervo_window import (
    TIPOS_OFERECIDOS,
    comando_agendador,
    formatar_estado,
    montar_estado,
    proximo_passo,
    tipos_para_args,
    validar_dias,
)


def _cobertura(
    grao="total",
    status="ok",
    dias=10,
    primeiro="2026-01-01",
    ultimo="2026-01-10",
    cobertura_media=None,
    tipo="web",
):
    """Uma linha de `v_cobertura`, que tem `tipo` — como o banco de verdade."""
    return {
        "tipo": tipo,
        "grao": grao,
        "status": status,
        "dias": dias,
        "primeiro": primeiro,
        "ultimo": ultimo,
        "cobertura_media": cobertura_media,
    }


def _contagens(**por_grao):
    """{grao: {tipo: linhas}} a partir de {grao: linhas} ou {grao: {tipo: n}}."""
    return {
        grao: (valor if isinstance(valor, dict) else {"web": valor})
        for grao, valor in por_grao.items()
    }


# ---------------------------------------------------------------------------
# validar_dias
# ---------------------------------------------------------------------------


class TestValidarDias:
    def test_vazio_vira_o_padrao(self):
        assert validar_dias("") == ACERVO_DIAS_BACKFILL
        assert validar_dias("   ") == ACERVO_DIAS_BACKFILL

    def test_valor_valido(self):
        assert validar_dias("30") == 30
        assert validar_dias("  480  ") == 480

    def test_zero_e_negativo_levantam(self):
        for ruim in ("0", "-5"):
            with pytest.raises(ValueError):
                validar_dias(ruim)

    def test_texto_levanta(self):
        with pytest.raises(ValueError):
            validar_dias("quinhentos")


# ---------------------------------------------------------------------------
# montar_estado / proximo_passo
# ---------------------------------------------------------------------------


class TestMontarEstado:
    def test_acervo_vazio(self):
        e = montar_estado(None, [], [], {})
        assert e["aferido"] is False
        assert e["dias_ok"] == 0
        assert e["linhas"] == 0
        assert e["primeiro_dia"] is None
        assert e["tem_buracos"] is False

    def test_periodo_e_o_intervalo_mais_amplo_entre_os_graos(self):
        cobertura = [
            _cobertura(grao="total", primeiro="2026-01-05", ultimo="2026-01-20"),
            _cobertura(grao="query", primeiro="2026-01-01", ultimo="2026-01-15"),
        ]
        e = montar_estado("2026-01-01T00:00:00+00:00", cobertura, [], {})
        assert e["primeiro_dia"] == "2026-01-01"
        assert e["ultimo_dia"] == "2026-01-20"

    def test_dias_somam_por_status_entre_graos(self):
        cobertura = [
            _cobertura(grao="total", status="ok", dias=10),
            _cobertura(grao="query", status="ok", dias=10),
            _cobertura(grao="query", status="vazio", dias=3),
        ]
        e = montar_estado(None, cobertura, [], {})
        assert e["dias_por_status"] == {"ok": 20, "vazio": 3}
        assert e["dias_ok"] == 20

    def test_teto_e_erro_contam_como_buraco(self):
        for status in ("teto", "erro"):
            e = montar_estado(None, [_cobertura(status=status)], [], {})
            assert e["tem_buracos"] is True, status

    def test_vazio_nao_e_buraco(self):
        # Dia sem dado no GSC é um fato, não uma falha de coleta.
        e = montar_estado(None, [_cobertura(status="vazio")], [], {})
        assert e["tem_buracos"] is False

    def test_cauda_anonimizada_vem_do_grao_query(self):
        cobertura = [
            _cobertura(grao="pagina", cobertura_media=0.98),
            _cobertura(grao="query", cobertura_media=0.42),
        ]
        e = montar_estado(None, cobertura, [], {})
        assert e["cauda_anonimizada"] == 0.42

    def test_linhas_somam_todas_as_tabelas(self):
        e = montar_estado(None, [], [], _contagens(total=10, pagina=500, query=900))
        assert e["linhas"] == 1410


class TestEstadoPorTipo:
    """Com dois tipos, nada pode ser somado — nem dias, nem cauda, nem linhas."""

    def _dois_tipos(self):
        return montar_estado(
            "2026-01-01T00:00:00+00:00",
            [
                _cobertura(
                    tipo="web", grao="total", dias=481, primeiro="2025-06-21", ultimo="2026-10-14"
                ),
                _cobertura(
                    tipo="web",
                    grao="query",
                    dias=481,
                    primeiro="2025-06-21",
                    ultimo="2026-10-14",
                    cobertura_media=0.61,
                ),
                _cobertura(
                    tipo="image", grao="total", dias=30, primeiro="2026-09-15", ultimo="2026-10-14"
                ),
                _cobertura(
                    tipo="image",
                    grao="query",
                    dias=30,
                    primeiro="2026-09-15",
                    ultimo="2026-10-14",
                    cobertura_media=0.88,
                ),
            ],
            [],
            # Valores inventados, redondos de propósito: nada aqui vem de dado
            # real de cliente (o repo é público).
            {"total": {"web": 400, "image": 30}, "query": {"web": 9000, "image": 700}},
        )

    def test_dias_nao_somam_entre_tipos(self):
        # 481 dias de web + 481 de image NÃO são 962 dias de acervo.
        estado = self._dois_tipos()
        assert estado["tipos"]["web"]["dias_ok"] == 481
        assert estado["tipos"]["image"]["dias_ok"] == 30

    def test_cada_tipo_tem_seu_periodo(self):
        estado = self._dois_tipos()
        assert estado["tipos"]["web"]["primeiro"] == "2025-06-21"
        assert estado["tipos"]["image"]["primeiro"] == "2026-09-15"

    def test_cada_tipo_tem_sua_cauda(self):
        estado = self._dois_tipos()
        assert estado["tipos"]["web"]["cauda"] == 0.61
        assert estado["tipos"]["image"]["cauda"] == 0.88

    def test_nao_ha_cauda_agregada_com_dois_tipos(self):
        # Uma cauda só, com dois tipos, seria o número de nenhum dos dois.
        assert self._dois_tipos()["cauda_anonimizada"] is None

    def test_com_um_tipo_so_a_cauda_agregada_continua_existindo(self):
        estado = montar_estado(
            "2026-01-01T00:00:00+00:00",
            [_cobertura(grao="query", cobertura_media=0.42)],
            [],
            {},
        )
        assert estado["cauda_anonimizada"] == 0.42

    def test_linhas_por_tipo(self):
        estado = self._dois_tipos()
        assert estado["linhas_por_tipo"] == {"web": 9400, "image": 730}
        assert estado["linhas"] == 10130

    def test_o_texto_nomeia_cada_tipo_e_nao_soma(self):
        texto = formatar_estado(self._dois_tipos())
        assert "web:" in texto and "image:" in texto
        assert "481 dias" in texto and "30 dias" in texto
        assert "962" not in texto

    def test_so_web_coletado_avisa_que_falta_image(self):
        # Medido em site real: image pode ter MAIS impressões que web. Sem este
        # aviso a janela deixa o analista achar que o acervo está completo.
        texto = formatar_estado(
            montar_estado("2026-01-01T00:00:00+00:00", [_cobertura()], [], _contagens(total=10))
        )
        assert "image" in texto
        assert "--tipos web,image" in texto

    def test_com_image_coletado_o_aviso_desaparece(self):
        texto = formatar_estado(self._dois_tipos())
        assert "--tipos web,image" not in texto

    def test_dias_com_dado_nao_multiplica_pelos_graos(self):
        # Regressão achada em dado real: `v_cobertura` tem uma linha por
        # (tipo, grão, status), então somar dava "2886 dias com dado" num acervo
        # de 481 dias — 481 x 6 grãos. Os grãos cobrem os MESMOS dias.
        cobertura = [
            _cobertura(grao=grao, dias=481, primeiro="2025-06-21", ultimo="2026-10-14")
            for grao in ("total", "pagina", "query", "query_pagina", "dispositivo", "pais")
        ]
        texto = formatar_estado(montar_estado("2026-01-01T00:00:00+00:00", cobertura, [], {}))
        assert "481 dias com dado" in texto
        assert "2886" not in texto


class TestProximoPasso:
    def test_sem_afericao_pede_aferir(self):
        assert proximo_passo(montar_estado(None, [], [], {})) == "aferir"

    def test_aferido_sem_dado_pede_backfill(self):
        e = montar_estado("2026-01-01T00:00:00+00:00", [], [], {})
        assert proximo_passo(e) == "backfill"

    def test_aferido_com_dado_pede_diario(self):
        # O diario nunca sai de "pendente": e ele que faz 16 meses virarem 2 anos.
        e = montar_estado("2026-01-01T00:00:00+00:00", [_cobertura()], [], {})
        assert proximo_passo(e) == "diario"


# ---------------------------------------------------------------------------
# formatar_estado — o texto que o analista le
# ---------------------------------------------------------------------------


class TestFormatarEstado:
    def test_vazio_manda_comecar_pela_etapa_1(self):
        texto = formatar_estado(montar_estado(None, [], [], {}))
        assert "etapa 1" in texto.lower()

    def test_mostra_periodo_e_linhas(self):
        e = montar_estado("2026-01-01T00:00:00+00:00", [_cobertura()], [], _contagens(total=10))
        texto = formatar_estado(e)
        assert "2026-01-01" in texto and "2026-01-10" in texto
        assert "10 dias com dado" in texto

    def test_cauda_anonimizada_e_explicada_como_normal(self):
        # O numero baixo no grao query nao e defeito; o texto precisa dizer isso.
        e = montar_estado(
            "2026-01-01T00:00:00+00:00",
            [_cobertura(grao="query", cobertura_media=0.42)],
            [],
            {},
        )
        texto = formatar_estado(e)
        assert "42%" in texto
        assert "anonimiza" in texto

    def test_provisorios_avisam_para_nao_concluir_da_ponta(self):
        e = montar_estado("2026-01-01T00:00:00+00:00", [_cobertura()], ["2026-10-10"], {})
        assert "ponta" in formatar_estado(e)

    def test_buraco_e_sinalizado(self):
        e = montar_estado("2026-01-01T00:00:00+00:00", [_cobertura(status="erro")], [], {})
        assert "ATENÇÃO" in formatar_estado(e)


class TestTiposParaArgs:
    def test_o_padrao_oferecido_e_web_e_image(self):
        # `image` pode carregar volume comparável ao de `web` e cair diferente
        # dele; a janela que coleta só `web` deixa metade do fato de fora.
        marcados = dict(TIPOS_OFERECIDOS)
        assert tipos_para_args(marcados) == "web,image"

    def test_respeita_a_ordem_de_tipos_oferecidos(self):
        # Não a ordem do dict de entrada: `total` de cada tipo é ingerido antes
        # dos outros grãos daquele tipo, e a ordem estável deixa o log legível.
        assert tipos_para_args({"image": True, "web": True}) == "web,image"

    def test_um_tipo_so(self):
        assert tipos_para_args({"web": True}) == "web"
        assert tipos_para_args({"image": True}) == "image"

    def test_inclui_os_tipos_raros_quando_marcados(self):
        marcados = {t: True for t, _ in TIPOS_OFERECIDOS}
        assert tipos_para_args(marcados) == "web,image,video,news,discover,googleNews"

    def test_nenhum_marcado_levanta(self):
        # Um clique que não faz nada e não diz por quê é pior que um erro.
        with pytest.raises(ValueError):
            tipos_para_args({t: False for t, _ in TIPOS_OFERECIDOS})
        with pytest.raises(ValueError):
            tipos_para_args({})

    def test_tudo_que_sai_daqui_e_aceito_pela_CLI(self):
        from core.warehouse import plan

        for tipo, _ in TIPOS_OFERECIDOS:
            assert tipo in plan.TIPOS_VALIDOS, tipo


class TestComandoAgendador:
    def test_inclui_o_site_e_o_subcomando_diario(self):
        cmd = comando_agendador("www.exemplo.com.br")
        assert "diario" in cmd
        assert "--site www.exemplo.com.br" in cmd
        assert "acervo.py" in cmd
        assert "WEEKLY" in cmd

    def test_leva_os_tipos_marcados(self):
        cmd = comando_agendador("www.exemplo.com.br", "web,image")
        assert "--tipos web,image" in cmd

    def test_o_tipos_vai_sempre_mesmo_com_um_so(self):
        # A armadilha que isto fecha: backfill de web,image com um diário
        # agendado sem --tipos deixa a série de image parada, e a janela móvel
        # de 16 meses vai comendo o que já foi coletado, sem erro e sem aviso.
        assert "--tipos web" in comando_agendador("www.exemplo.com.br", "web")
        assert "--tipos" in comando_agendador("www.exemplo.com.br")


# ---------------------------------------------------------------------------
# montar_args — a GUI chama os MESMOS comandos que a CLI
# ---------------------------------------------------------------------------


class TestMontarArgs:
    def test_campos_que_todo_comando_le_estao_presentes(self):
        # Namespace incompleto estouraria AttributeError dentro da thread, onde
        # o erro aparece mal — por isso todos os campos vao sempre.
        args = montar_args("backfill", {"site": "www.exemplo.com.br"})
        for campo in (
            "comando",
            "site",
            "tipo",
            "graos",
            "pausa",
            "dias",
            "dry_run",
            "forcar",
            "ponta_fresca",
            "batch",
        ):
            assert hasattr(args, campo), campo

    def test_comando_e_o_modo(self):
        assert montar_args("aferir", {"site": "x"}).comando == "aferir"

    def test_site_e_normalizado_de_espacos(self):
        assert montar_args("status", {"site": "  www.exemplo.com.br  "}).site == (
            "www.exemplo.com.br"
        )

    def test_defaults_sensatos(self):
        args = montar_args("diario", {"site": "x"})
        assert args.tipo == "web"
        assert args.graos is None
        assert args.batch is None
        assert args.dias == ACERVO_DIAS_BACKFILL
        assert args.dry_run is False

    def test_dias_vira_inteiro(self):
        assert montar_args("backfill", {"site": "x", "dias": "30"}).dias == 30

    def test_modo_desconhecido_levanta(self):
        with pytest.raises(ValueError):
            montar_args("apagar_tudo", {"site": "x"})

    def test_tipos_da_janela_chega_ao_namespace(self):
        args = montar_args("backfill", {"site": "x", "tipos": "web,image"})
        assert args.tipos == "web,image"

    def test_a_CLI_resolve_os_tipos_que_a_janela_mandou(self):
        # O elo que importa: a janela não reimplementa nada, ela monta o mesmo
        # Namespace e a CLI é quem interpreta. Se este elo quebrar, a janela
        # coletaria um conjunto de tipos diferente do que mostra marcado.
        import acervo

        args = montar_args("backfill", {"site": "x", "tipos": "web,image"})
        assert acervo._parse_tipos(args) == ("web", "image")

    def test_sem_tipos_a_janela_cai_no_web(self):
        args = montar_args("backfill", {"site": "x"})
        assert args.tipos is None
        import acervo

        assert acervo._parse_tipos(args) == ("web",)


# ---------------------------------------------------------------------------
# gui/terminal.py
# ---------------------------------------------------------------------------


class TestTagForLine:
    @pytest.mark.parametrize(
        "linha,esperado",
        [
            ("[CACHE] dados do cache", "cache"),
            ("[ERRO] falhou", "erro"),
            ("[ERRO INESPERADO] ops", "erro"),
            ("  AVISO: log sem User-Agent", "warn"),
            ("  RECUSADO: janela do log curta demais", "warn"),
            ("======================", "header"),
            ("──────────────────────", "header"),
            ("----------------------", "header"),
            ("[auth] Renovando token", "auth"),
            ("[storage] salvo em", "storage"),
            ("Concluído.", "ok"),
            ("linha comum", None),
        ],
    )
    def test_colore_pelo_prefixo(self, linha, esperado):
        assert terminal.tag_for_line(linha) == esperado

    def test_erro_vence_aviso(self):
        # Uma linha com os dois e erro: a severidade maior manda.
        assert terminal.tag_for_line("[ERRO] aviso ignorado") == "erro"

    def test_recusado_e_aviso_nao_erro(self):
        # Verdict recusado significa que o programa funcionou e se negou a
        # afirmar o que nao podia — isso e aviso, nao falha.
        assert terminal.tag_for_line("  RECUSADO: log sem User-Agent") == "warn"
