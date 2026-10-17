"""
test_acervo_cli.py — Testes do wiring da CLI do acervo (acervo.py).

Offline e sem rede: `acervo.py` importa `core.auth.build_service` DENTRO das
funções justamente para o módulo ser importável e testável sem as libs do
Google, e nada aqui chama um comando — só o parser e os helpers de parsing.

O que está travado aqui:

  - `--tipos web,image` aceito, tipo inventado recusado com mensagem clara, e a
    recusa dizendo que NÃO existe valor de IA (é a pergunta que todo mundo faz).
  - `--tipo` e `--tipos` mutuamente exclusivos: permitir os dois deixaria
    expressável pedir coisas diferentes e exigiria inventar precedência.
  - `--tipo` (singular) continuando a valer, que é o que a GUI monta e o que
    scripts antigos passam.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import acervo  # noqa: E402
from core.warehouse import plan  # noqa: E402


def _args(**campos):
    """Namespace mínimo, como o argparse entregaria."""
    import argparse

    campos.setdefault("tipo", "web")
    campos.setdefault("tipos", None)
    return argparse.Namespace(**campos)


# ---------------------------------------------------------------------------
# _parse_tipos
# ---------------------------------------------------------------------------


class TestParseTipos:
    def test_sem_nada_e_web(self):
        assert acervo._parse_tipos(_args()) == ("web",)

    def test_tipo_singular_continua_valendo(self):
        # É o que gui/acervo_runner.montar_args monta.
        assert acervo._parse_tipos(_args(tipo="image")) == ("image",)

    def test_tipos_plural_separa_por_virgula(self):
        assert acervo._parse_tipos(_args(tipos="web,image")) == ("web", "image")

    def test_tipos_ignora_espaco_e_vazio(self):
        assert acervo._parse_tipos(_args(tipos=" web , image , ")) == ("web", "image")

    def test_tipos_preserva_a_ordem_pedida(self):
        # A ordem é a da linha de comando: quem pede image primeiro recebe
        # image primeiro, e o `total` de cada tipo é ingerido antes dos outros
        # grãos DAQUELE tipo (quem garante isso é plan.graos_aplicaveis).
        assert acervo._parse_tipos(_args(tipos="image,web")) == ("image", "web")

    def test_tipos_remove_duplicata_sem_reordenar(self):
        assert acervo._parse_tipos(_args(tipos="web,image,web")) == ("web", "image")

    def test_tipos_plural_vence_o_singular_default(self):
        # O argparse impede os dois juntos; aqui o `tipo` é só o default dele.
        assert acervo._parse_tipos(_args(tipo="web", tipos="image")) == ("image",)

    def test_tipo_desconhecido_levanta_com_os_validos(self):
        with pytest.raises(acervo.AcervoError) as ctx:
            acervo._parse_tipos(_args(tipos="web,ia"))
        mensagem = str(ctx.value)
        assert "ia" in mensagem
        for valido in plan.TIPOS_VALIDOS:
            assert valido in mensagem

    def test_a_recusa_diz_que_nao_existe_tipo_de_ia(self):
        # A API não tem dimensão nem `type` de IA; o relatório de IA generativa
        # é só da interface. Quem tenta `--tipos ia` precisa ler isso agora.
        with pytest.raises(acervo.AcervoError) as ctx:
            acervo._parse_tipos(_args(tipos="ia"))
        assert "IA" in str(ctx.value)

    def test_todo_tipo_valido_e_aceito(self):
        pedido = ",".join(plan.TIPOS_VALIDOS)
        assert acervo._parse_tipos(_args(tipos=pedido)) == tuple(plan.TIPOS_VALIDOS)


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


class TestArgparse:
    def test_backfill_aceita_tipos(self):
        args = acervo.parse_args(
            ["backfill", "--site", "www.exemplo.com.br", "--tipos", "web,image"]
        )
        assert args.tipos == "web,image"
        assert acervo._parse_tipos(args) == ("web", "image")

    def test_diario_aceita_tipos(self):
        args = acervo.parse_args(["diario", "--site", "www.exemplo.com.br", "--tipos", "image"])
        assert acervo._parse_tipos(args) == ("image",)

    def test_reingerir_aceita_tipos(self):
        args = acervo.parse_args(
            [
                "reingerir",
                "--site",
                "www.exemplo.com.br",
                "--de",
                "2026-01-01",
                "--ate",
                "2026-01-31",
                "--tipos",
                "web,image",
            ]
        )
        assert acervo._parse_tipos(args) == ("web", "image")

    def test_tipo_e_tipos_juntos_sao_recusados(self):
        # Mutuamente exclusivos: o argparse sai com codigo 2.
        with pytest.raises(SystemExit) as ctx:
            acervo.parse_args(
                ["backfill", "--site", "www.exemplo.com.br", "--tipo", "web", "--tipos", "image"]
            )
        assert ctx.value.code == 2

    def test_tipo_invalido_no_singular_e_recusado_pelo_choices(self):
        with pytest.raises(SystemExit):
            acervo.parse_args(["backfill", "--site", "www.exemplo.com.br", "--tipo", "ia"])

    def test_sem_tipos_o_default_e_web(self):
        args = acervo.parse_args(["backfill", "--site", "www.exemplo.com.br"])
        assert acervo._parse_tipos(args) == ("web",)


# ---------------------------------------------------------------------------
# _parse_graos — estava sem teste nenhum
# ---------------------------------------------------------------------------


class TestParseGraos:
    def test_sem_nada_e_o_padrao(self):
        assert acervo._parse_graos(None) == plan.GRAOS_PADRAO
        assert acervo._parse_graos("") == plan.GRAOS_PADRAO

    def test_lista_separada_por_virgula(self):
        assert acervo._parse_graos("pagina,query") == ("pagina", "query")

    def test_grao_desconhecido_levanta(self):
        with pytest.raises(acervo.AcervoError):
            acervo._parse_graos("pagina,inexistente")

    def test_grao_de_duas_etapas_e_recusado_com_a_fase(self):
        with pytest.raises(acervo.AcervoError) as ctx:
            acervo._parse_graos("aparencia")
        assert "P7.4" in str(ctx.value)
