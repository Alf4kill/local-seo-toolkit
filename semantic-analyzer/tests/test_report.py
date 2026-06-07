"""
test_report.py — Testa os geradores de HTML do relatorio de clusters (sem rede).

report.py tinha 365 linhas e zero cobertura. Nao testamos estetica, e sim
contratos que, se quebrarem, geram relatorio errado ou inseguro:
  - escape de HTML (conteudo vem de paginas reais -> risco de XSS / layout quebrado),
  - blocos opcionais que devem sumir quando nao ha dado (llm/diff/colisoes vazios),
  - a pagina canonica (representante) marcada corretamente,
  - badges de veredito presentes quando ha veredito.
"""

from core.report import (
    _collisions_html,
    _diff_html,
    _llm_html,
    generate_html,
)


class TestLlmHtml:
    def test_sem_llm_retorna_vazio(self):
        assert _llm_html({}) == ""
        assert _llm_html({"llm": None}) == ""

    def test_veredito_spun_tem_badge_e_base(self):
        c = {
            "llm": {
                "verdict": "spun",
                "base_recomendada": "pagina-a",
                "resumo": "quase iguais",
                "lacunas": ["faltam dados"],
            }
        }
        out = _llm_html(c)
        assert "SPUN" in out
        assert "pagina-a" in out
        assert "quase iguais" in out
        assert "faltam dados" in out

    def test_escapa_html_do_resumo(self):
        c = {"llm": {"verdict": "ok", "resumo": "<script>alert(1)</script>"}}
        out = _llm_html(c)
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out

    def test_limita_a_5_lacunas(self):
        c = {"llm": {"verdict": "raso", "lacunas": [f"g{i}" for i in range(10)]}}
        out = _llm_html(c)
        assert out.count("<li>") == 5


class TestDiffHtml:
    def test_sem_diff_retorna_vazio(self):
        assert _diff_html({}) == ""
        assert _diff_html({"diff": {"paginas": []}}) == ""

    def test_monta_linha_por_pagina(self):
        c = {
            "diff": {
                "paginas": [
                    {
                        "papel": "cabeca",
                        "slug": "a",
                        "keyword_alvo": "kw1",
                        "intencao": "informacional",
                        "titulo": "Titulo A",
                        "foco": "foco A",
                    },
                    {
                        "papel": "spoke",
                        "slug": "b",
                        "keyword_alvo": "kw2",
                        "intencao": "transacional",
                        "titulo": "Titulo B",
                        "foco": "foco B",
                    },
                ]
            }
        }
        out = _diff_html(c)
        assert "kw1" in out and "kw2" in out
        assert out.count("border-top:1px solid #e3edf9") == 2

    def test_omitidas_viram_aviso_canonical(self):
        c = {
            "diff": {
                "paginas": [
                    {
                        "papel": "cabeca",
                        "slug": "a",
                        "keyword_alvo": "kw",
                        "intencao": "x",
                        "titulo": "t",
                        "foco": "f",
                    }
                ],
                "omitidas": ["c", "d"],
            }
        }
        out = _diff_html(c)
        assert "canonical" in out.lower()
        assert "c, d" in out


class TestCollisionsHtml:
    def test_sem_colisoes_retorna_vazio(self):
        assert _collisions_html([]) == ""

    def test_renderiza_keyword_em_conflito(self):
        collisions = [
            {
                "kind": "exata",
                "keyword": "cane corso preco",
                "impr_total": 1234,
                "owner": {"cluster": 1, "slug": "a"},
                "members": [
                    {"cluster": 1, "slug": "a"},
                    {"cluster": 2, "slug": "b"},
                ],
            }
        ]
        out = _collisions_html(collisions)
        assert "cane corso preco" in out
        assert "1,234" in out
        assert "mantém" in out
        assert "nova keyword" in out


class TestGenerateHtml:
    def _clusters(self):
        return [
            {"size": 3, "cohesion": 0.91, "representative": "b", "members": ["a", "b", "c"]},
            {"size": 1, "cohesion": 1.0, "representative": "z", "members": ["z"]},
        ]

    def test_html_basico_bem_formado(self):
        out = generate_html(self._clusters(), "Meu Site", "semantic", 0.80)
        assert "<html" in out.lower()
        assert "Grupo 1" in out
        assert "Meu Site" in out

    def test_representante_marcado_como_canonica(self):
        out = generate_html(self._clusters(), "T", "semantic", 0.8)
        assert "canônica sugerida" in out

    def test_single_nao_vira_card_de_grupo(self):
        out = generate_html(self._clusters(), "T", "semantic", 0.8)
        assert "Grupo 2" not in out

    def test_escapa_membros(self):
        clusters = [
            {"size": 2, "cohesion": 0.9, "representative": "x", "members": ["x", "<b>y</b>"]}
        ]
        out = generate_html(clusters, "T", "semantic", 0.8)
        assert "<b>y</b>" not in out
        assert "&lt;b&gt;y&lt;/b&gt;" in out
