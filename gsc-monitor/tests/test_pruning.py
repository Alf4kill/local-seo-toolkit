"""
test_pruning.py — Testes do Plano de Poda (core/pruning.py).

Cobertura (lógica pura, sem IO de rede):
  - normalize_for_match: tolerância a esquema/www/barra final/percent-encoding
  - find_ghost_urls: diff GSC × sitemap sem falsos fantasmas
  - build_pruning_plan: classificação 410/revisar, top queries, sugestão de
    destino (query compartilhada > slug semelhante > nenhum)
  - parse_plan_csv: validação das decisões do analista + aviso de home
  - build_poda_htaccess / build_poda_nginx: exact-match, query string, formatos
  - storage.save_poda_csv / load_poda_csv_lines / latest_poda_csv: roundtrip
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import storage
from core.pruning import (
    build_poda_htaccess,
    build_poda_nginx,
    build_poda_php,
    build_poda_redirect,
    build_pruning_plan,
    extract_urls_from_lines,
    find_ghost_urls,
    normalize_for_match,
    parse_plan_csv,
)

SITEMAP = [
    "https://www.ex.com/",
    "https://www.ex.com/cane-corso-preco/",
    "https://www.ex.com/cane-corso-filhote/",
]


def _api(url, clicks=0, impressions=0, position=50.0, ctr=0.0):
    return {url: {"clicks": clicks, "impressions": impressions, "ctr": ctr, "position": position}}


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------


class TestNormalizeForMatch(unittest.TestCase):
    def test_esquema_e_www_ignorados(self):
        self.assertEqual(
            normalize_for_match("http://www.ex.com/pagina"),
            normalize_for_match("https://ex.com/pagina"),
        )

    def test_barra_final_ignorada(self):
        self.assertEqual(
            normalize_for_match("https://ex.com/pagina/"),
            normalize_for_match("https://ex.com/pagina"),
        )

    def test_percent_encoding_decodificado(self):
        self.assertEqual(
            normalize_for_match("https://ex.com/pre%C3%A7o"),
            normalize_for_match("https://ex.com/preço"),
        )

    def test_query_string_preservada(self):
        self.assertNotEqual(
            normalize_for_match("https://ex.com/p?id=1"),
            normalize_for_match("https://ex.com/p?id=2"),
        )

    def test_fragmento_descartado(self):
        self.assertEqual(
            normalize_for_match("https://ex.com/p#secao"),
            normalize_for_match("https://ex.com/p"),
        )

    def test_home_normaliza_para_host_e_barra(self):
        self.assertEqual(normalize_for_match("https://www.ex.com/"), "ex.com/")


# ---------------------------------------------------------------------------
# Diff GSC × sitemap
# ---------------------------------------------------------------------------


class TestFindGhostUrls(unittest.TestCase):
    def test_url_fora_do_sitemap_e_fantasma(self):
        api = _api("https://www.ex.com/pagina-antiga/", impressions=5)
        ghosts = find_ghost_urls(api, SITEMAP)
        self.assertEqual(len(ghosts), 1)
        self.assertEqual(ghosts[0]["url"], "https://www.ex.com/pagina-antiga/")

    def test_variacao_barra_final_nao_e_fantasma(self):
        api = _api("https://www.ex.com/cane-corso-preco", impressions=100)
        self.assertEqual(find_ghost_urls(api, SITEMAP), [])

    def test_variacao_www_nao_e_fantasma(self):
        api = _api("https://ex.com/cane-corso-preco/", impressions=100)
        self.assertEqual(find_ghost_urls(api, SITEMAP), [])

    def test_ordenacao_por_impressoes_desc(self):
        api = {}
        api.update(_api("https://www.ex.com/a-antiga/", impressions=5))
        api.update(_api("https://www.ex.com/b-antiga/", impressions=500))
        ghosts = find_ghost_urls(api, SITEMAP)
        self.assertEqual(ghosts[0]["url"], "https://www.ex.com/b-antiga/")


# ---------------------------------------------------------------------------
# Plano: classificação e sugestão de destino
# ---------------------------------------------------------------------------


class TestBuildPruningPlan(unittest.TestCase):
    def test_sem_trafego_sugere_410(self):
        api = _api("https://www.ex.com/morta/", impressions=2, clicks=0)
        plan = build_pruning_plan(api, SITEMAP, min_impressions=10)
        self.assertEqual(plan["entries"][0]["action"], "410")
        self.assertEqual(plan["total_410"], 1)

    def test_com_cliques_sugere_revisar(self):
        api = _api("https://www.ex.com/viva/", impressions=2, clicks=1)
        plan = build_pruning_plan(api, SITEMAP, min_impressions=10)
        self.assertEqual(plan["entries"][0]["action"], "revisar")

    def test_com_impressoes_acima_do_piso_sugere_revisar(self):
        api = _api("https://www.ex.com/viva/", impressions=50, clicks=0)
        plan = build_pruning_plan(api, SITEMAP, min_impressions=10)
        self.assertEqual(plan["entries"][0]["action"], "revisar")
        self.assertEqual(plan["total_review"], 1)

    def test_revisar_vem_antes_de_410(self):
        api = {}
        api.update(_api("https://www.ex.com/morta/", impressions=1))
        api.update(_api("https://www.ex.com/viva/", impressions=200))
        plan = build_pruning_plan(api, SITEMAP, min_impressions=10)
        self.assertEqual(plan["entries"][0]["action"], "revisar")
        self.assertEqual(plan["entries"][1]["action"], "410")

    def test_destino_por_query_compartilhada(self):
        api = _api("https://www.ex.com/antiga-preco/", impressions=100)
        query_rows = [
            {"query": "cane corso preco", "url": "https://www.ex.com/antiga-preco/",
             "clicks": 0, "impressions": 100, "ctr": 0.0, "position": 12.0},
            {"query": "cane corso preco", "url": "https://www.ex.com/cane-corso-preco/",
             "clicks": 10, "impressions": 900, "ctr": 1.1, "position": 5.0},
        ]
        plan = build_pruning_plan(api, SITEMAP, query_rows=query_rows)
        entry = plan["entries"][0]
        self.assertEqual(entry["suggested_target"], "https://www.ex.com/cane-corso-preco/")
        self.assertEqual(entry["target_source"], "query compartilhada")
        self.assertEqual(entry["top_queries"], ["cane corso preco"])

    def test_destino_canonizado_para_url_do_sitemap(self):
        # A sugestao por query devolve a forma vista no GSC (aqui sem barra
        # final); o destino final deve ser a URL exata do sitemap atual
        # (com barra final) — e ela que sera aplicada no redirect.
        api = _api("https://www.ex.com/antiga-preco/", impressions=100)
        query_rows = [
            {"query": "cane corso preco", "url": "https://www.ex.com/antiga-preco/",
             "clicks": 0, "impressions": 100, "ctr": 0.0, "position": 12.0},
            {"query": "cane corso preco", "url": "https://www.ex.com/cane-corso-preco",
             "clicks": 10, "impressions": 900, "ctr": 1.1, "position": 5.0},
        ]
        plan = build_pruning_plan(api, SITEMAP, query_rows=query_rows)
        # SITEMAP tem "https://www.ex.com/cane-corso-preco/" (com barra)
        self.assertEqual(
            plan["entries"][0]["suggested_target"],
            "https://www.ex.com/cane-corso-preco/",
        )

    def test_home_nunca_e_sugerida_por_query(self):
        api = _api("https://www.ex.com/antiga/", impressions=100)
        query_rows = [
            {"query": "kw", "url": "https://www.ex.com/antiga/",
             "clicks": 0, "impressions": 100, "ctr": 0.0, "position": 12.0},
            {"query": "kw", "url": "https://www.ex.com/",
             "clicks": 50, "impressions": 900, "ctr": 1.0, "position": 3.0},
        ]
        # home_fallback desligado isola o mecanismo de query: a home, ainda que
        # compartilhe a query, NUNCA é escolhida como destino por query.
        plan = build_pruning_plan(api, SITEMAP, query_rows=query_rows, home_fallback=False)
        self.assertIsNone(plan["entries"][0]["suggested_target"])

    def test_destino_por_slug_semelhante_no_fallback(self):
        api = _api("https://www.ex.com/cane-corso-preco-2023/", impressions=100)
        plan = build_pruning_plan(api, SITEMAP)  # sem query_rows
        entry = plan["entries"][0]
        self.assertEqual(entry["suggested_target"], "https://www.ex.com/cane-corso-preco/")
        self.assertEqual(entry["target_source"], "slug semelhante")

    def test_sem_candidato_confiavel_usa_home_fallback(self):
        # "revisar" (com tráfego) sem destino por query/slug recebe a home
        # como sugestão de último recurso — não fica em branco para revisão.
        api = _api("https://www.ex.com/politica-privacidade-old/", impressions=100)
        plan = build_pruning_plan(api, SITEMAP)
        entry = plan["entries"][0]
        self.assertEqual(entry["suggested_target"], "https://www.ex.com/")
        self.assertEqual(entry["target_source"], "home (fallback)")

    def test_home_fallback_desligado_deixa_destino_vazio(self):
        api = _api("https://www.ex.com/politica-privacidade-old/", impressions=100)
        plan = build_pruning_plan(api, SITEMAP, home_fallback=False)
        self.assertIsNone(plan["entries"][0]["suggested_target"])

    def test_home_fallback_nao_se_aplica_a_410_sem_trafego(self):
        # sem tráfego (410) não há o que redirecionar — destino fica vazio
        api = _api("https://www.ex.com/morta-old/", impressions=1, clicks=0)
        plan = build_pruning_plan(api, SITEMAP)
        entry = plan["entries"][0]
        self.assertEqual(entry["action"], "410")
        self.assertIsNone(entry["suggested_target"])

    def test_destino_por_query_tem_prioridade_sobre_home_fallback(self):
        # com destino confiável por query, o fallback da home não entra
        api = _api("https://www.ex.com/antiga-preco/", impressions=100)
        query_rows = [
            {"query": "cane corso preco", "url": "https://www.ex.com/antiga-preco/",
             "clicks": 0, "impressions": 100, "ctr": 0.0, "position": 12.0},
            {"query": "cane corso preco", "url": "https://www.ex.com/cane-corso-preco/",
             "clicks": 10, "impressions": 900, "ctr": 1.1, "position": 5.0},
        ]
        plan = build_pruning_plan(api, SITEMAP, query_rows=query_rows)
        entry = plan["entries"][0]
        self.assertEqual(entry["suggested_target"], "https://www.ex.com/cane-corso-preco/")
        self.assertEqual(entry["target_source"], "query compartilhada")

    def test_disclaimer_presente(self):
        api = _api("https://www.ex.com/morta/", impressions=1)
        plan = build_pruning_plan(api, SITEMAP)
        self.assertIn("SUGESTAO", plan["disclaimer"])

    def test_query_de_marca_nao_pontua_destino(self):
        # "exemplo kits" casa com qualquer página do site — não pode gerar
        # sugestão de destino sem relação real (caso visto na exemplokits)
        sitemap = [
            "https://www.exemplokits.com.br/",
            "https://www.exemplokits.com.br/embalagens/",
        ]
        api = _api("https://www.exemplokits.com.br/sobre-nos/", impressions=100)
        query_rows = [
            {"query": "exemplo kits", "url": "https://www.exemplokits.com.br/sobre-nos/",
             "clicks": 2, "impressions": 100, "ctr": 2.0, "position": 3.0},
            {"query": "exemplo kits", "url": "https://www.exemplokits.com.br/embalagens/",
             "clicks": 5, "impressions": 300, "ctr": 1.7, "position": 5.0},
        ]
        plan = build_pruning_plan(api, sitemap, query_rows=query_rows)
        self.assertNotEqual(plan["entries"][0]["target_source"], "query compartilhada")

    def test_query_nao_marca_continua_pontuando(self):
        sitemap = [
            "https://www.exemplokits.com.br/",
            "https://www.exemplokits.com.br/o-que-e-kit-mitigacao/",
        ]
        api = _api("https://www.exemplokits.com.br/kit-mitigacao/", impressions=100)
        query_rows = [
            {"query": "kit mitigacao", "url": "https://www.exemplokits.com.br/kit-mitigacao/",
             "clicks": 2, "impressions": 100, "ctr": 2.0, "position": 8.0},
            {"query": "kit mitigacao",
             "url": "https://www.exemplokits.com.br/o-que-e-kit-mitigacao/",
             "clicks": 5, "impressions": 300, "ctr": 1.7, "position": 5.0},
        ]
        plan = build_pruning_plan(api, sitemap, query_rows=query_rows)
        self.assertEqual(
            plan["entries"][0]["suggested_target"],
            "https://www.exemplokits.com.br/o-que-e-kit-mitigacao/",
        )

    def test_origem_busca_por_padrao(self):
        api = _api("https://www.ex.com/morta/", impressions=1)
        plan = build_pruning_plan(api, SITEMAP)
        self.assertEqual(plan["entries"][0]["origem"], "busca")

    def test_extra_urls_do_export_entram_com_origem_propria(self):
        api = _api("https://www.ex.com/morta/", impressions=1)
        extra = [
            "https://www.ex.com/cane-corso-preco/",  # no sitemap — ignorada
            "https://www.ex.com/morta",  # duplicata da busca (sem barra) — ignorada
            "https://www.ex.com/so-no-export/",  # nova — entra com métricas 0
        ]
        plan = build_pruning_plan(api, SITEMAP, extra_urls=extra)
        self.assertEqual(plan["total"], 2)
        by_url = {e["url"]: e for e in plan["entries"]}
        entry = by_url["https://www.ex.com/so-no-export/"]
        self.assertEqual(entry["origem"], "export-gsc")
        self.assertEqual(entry["action"], "410")
        self.assertEqual(entry["impressions"], 0)


# ---------------------------------------------------------------------------
# Extração de URLs do export do GSC
# ---------------------------------------------------------------------------


class TestExtractUrls(unittest.TestCase):
    def test_extrai_filtra_dominio_e_deduplica(self):
        lines = [
            "URL,Última varredura\n",
            "https://www.ex.com/antiga-1/,2026-05-01\n",
            "https://ex.com/antiga-1/,2026-05-02\n",  # duplicata sem www
            "https://outrosite.com/pagina/,2026-05-01\n",  # outro domínio
            '"https://www.ex.com/antiga-2/",2026-05-03\n',
        ]
        urls = extract_urls_from_lines(lines, "www.ex.com")
        self.assertEqual(
            urls, ["https://www.ex.com/antiga-1/", "https://www.ex.com/antiga-2/"]
        )

    def test_linhas_sem_url_ignoradas(self):
        self.assertEqual(extract_urls_from_lines(["Motivo,Páginas\n", "404,15\n"], "ex.com"), [])


# ---------------------------------------------------------------------------
# Parse do CSV revisado
# ---------------------------------------------------------------------------

# Formato LEGADO (vírgula, colunas da 1ª versão) — o parser detecta o
# delimitador e mapeia colunas por nome, então CSVs antigos seguem válidos.
_HEADER = (
    "url,impressoes,cliques,posicao,top_queries,acao_sugerida,"
    "destino_sugerido,fonte_sugestao,acao_final,destino_final"
)


def _csv_lines(*rows):
    return ["# comentario\n", _HEADER + "\n"] + [r + "\n" for r in rows]


class TestParsePlanCsv(unittest.TestCase):
    def test_410_e_404_aceitos(self):
        out = parse_plan_csv(
            _csv_lines(
                "https://ex.com/a,0,0,,,410,,,410,",
                "https://ex.com/b,0,0,,,410,,,404,",
            )
        )
        self.assertEqual([e["action"] for e in out["entries"]], ["410", "404"])
        self.assertEqual(out["errors"], [])

    def test_301_valido(self):
        out = parse_plan_csv(
            _csv_lines("https://ex.com/a,9,0,,,revisar,,,301,https://ex.com/destino")
        )
        self.assertEqual(out["entries"][0]["target"], "https://ex.com/destino")

    def test_301_sem_destino_e_erro(self):
        out = parse_plan_csv(_csv_lines("https://ex.com/a,9,0,,,revisar,,,301,"))
        self.assertEqual(out["entries"], [])
        self.assertEqual(len(out["errors"]), 1)

    def test_301_destino_igual_origem_e_erro(self):
        out = parse_plan_csv(_csv_lines("https://ex.com/a,9,0,,,revisar,,,301,https://ex.com/a/"))
        self.assertEqual(out["entries"], [])
        self.assertEqual(len(out["errors"]), 1)

    def test_acao_invalida_e_erro(self):
        out = parse_plan_csv(_csv_lines("https://ex.com/a,0,0,,,410,,,302,"))
        self.assertEqual(out["entries"], [])
        self.assertEqual(len(out["errors"]), 1)

    def test_revisar_e_manter_nao_geram_diretiva(self):
        out = parse_plan_csv(
            _csv_lines(
                "https://ex.com/a,9,0,,,revisar,,,revisar,",
                "https://ex.com/b,9,0,,,revisar,,,manter,",
                "https://ex.com/c,9,0,,,revisar,,,,",  # vazio = revisar
            )
        )
        self.assertEqual(out["entries"], [])
        self.assertEqual(out["pending"], ["https://ex.com/a", "https://ex.com/c"])
        self.assertEqual(out["kept"], ["https://ex.com/b"])

    def test_aviso_de_redirects_em_massa_para_home(self):
        rows = [
            f"https://ex.com/p{i},9,0,,,revisar,,,301,https://ex.com/" for i in range(5)
        ]
        out = parse_plan_csv(_csv_lines(*rows))
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("soft-404", out["warnings"][0])

    def test_poucos_redirects_para_home_sem_aviso(self):
        out = parse_plan_csv(_csv_lines("https://ex.com/p,9,0,,,revisar,,,301,https://ex.com/"))
        self.assertEqual(out["warnings"], [])

    def test_formato_novo_ponto_e_virgula(self):
        header = (
            "url;acao_final;destino_final;origem;impressoes;cliques;"
            "posicao;fonte_sugestao;top_queries"
        )
        lines = [
            "# comentario\n",
            header + "\n",
            "https://ex.com/a;410;;busca;0;0;;;\n",
            "https://ex.com/b;301;https://ex.com/dest;busca;9;1;3,5;query compartilhada;kw\n",
        ]
        out = parse_plan_csv(lines)
        self.assertEqual(len(out["entries"]), 2)
        self.assertEqual(out["entries"][1]["target"], "https://ex.com/dest")
        self.assertEqual(out["errors"], [])


# ---------------------------------------------------------------------------
# Blocos de servidor
# ---------------------------------------------------------------------------

_ENTRIES = [
    {"url": "https://ex.com/morta/", "action": "410", "target": None},
    {"url": "https://ex.com/outra", "action": "404", "target": None},
    {"url": "https://ex.com/antiga/", "action": "301", "target": "https://ex.com/nova/"},
    {"url": "https://ex.com/?p=123", "action": "410", "target": None},
]


class TestPodaHtaccess(unittest.TestCase):
    def setUp(self):
        self.block = build_poda_htaccess(_ENTRIES, "2026-06-12")

    def test_path_com_barra_final_e_query_sem_barra_dupla(self):
        # Regressão (visto na exemplokits): /blog/page/8/?et_blog gerava
        # pattern "^blog/page/8//?$" (barra dupla)
        entries = [{"url": "https://ex.com/blog/page/8/?et_blog", "action": "410", "target": None}]
        block = build_poda_htaccess(entries, "2026-06-12")
        self.assertIn("RewriteRule ^blog/page/8/?$ - [G,L]", block)
        self.assertNotIn("//?$", block)

    def test_410_exact_match_redirectmatch(self):
        self.assertIn("RedirectMatch 410 ^/morta/?$", self.block)

    def test_404_suportado(self):
        self.assertIn("RedirectMatch 404 ^/outra/?$", self.block)

    def test_301_com_destino(self):
        self.assertIn("RedirectMatch 301 ^/antiga/?$ https://ex.com/nova/", self.block)

    def test_url_com_query_usa_mod_rewrite(self):
        self.assertIn("RewriteEngine On", self.block)
        self.assertIn("RewriteCond %{QUERY_STRING} ^p=123$", self.block)
        self.assertIn("[G,L]", self.block)

    def test_disclaimer_presente(self):
        self.assertIn("SUGESTAO", self.block)

    def test_sem_prefix_match_do_mod_alias(self):
        # Redirect (prefix-match) derrubaria /morta/sub-pagina-ativa
        self.assertNotIn("\nRedirect 410", self.block)


class TestPodaPhp(unittest.TestCase):
    def setUp(self):
        self.block = build_poda_php(_ENTRIES, "2026-06-12", filename="2026-06-12_poda.php")

    def test_410_com_barra_final_normalizada(self):
        # chave sem barra final ('/morta', não '/morta/') — runtime faz rtrim
        self.assertIn("'/morta' => array(", self.block)
        self.assertIn("array(null, 410, null),", self.block)

    def test_404_suportado(self):
        self.assertIn("'/outra' => array(", self.block)
        self.assertIn("array(null, 404, null),", self.block)

    def test_301_com_destino(self):
        self.assertIn("array(null, 301, 'https://ex.com/nova/'),", self.block)

    def test_url_com_query_exige_query_exata(self):
        # entrada https://ex.com/?p=123 → path raiz, regra com query
        self.assertIn("'/' => array(", self.block)
        self.assertIn("array('p=123', 410, null),", self.block)

    def test_mesmo_path_query_e_sem_query_agrupados_query_primeiro(self):
        entries = [
            {"url": "https://ex.com/oculos", "action": "410", "target": None},
            {"url": "https://ex.com/oculos?slug=oculos-de-seguranca", "action": "410",
             "target": None},
        ]
        block = build_poda_php(entries, "2026-06-12")
        self.assertEqual(block.count("'/oculos' => array("), 1)
        idx_query = block.index("array('slug=oculos-de-seguranca', 410, null),")
        idx_plain = block.index("array(null, 410, null),")
        self.assertLess(idx_query, idx_plain)

    def test_instrucoes_e_disclaimer(self):
        self.assertIn("SUGESTAO", self.block)
        self.assertIn("require __DIR__ . '/2026-06-12_poda.php';", self.block)
        self.assertIn("wp-config.php", self.block)
        self.assertIn("http_response_code", self.block)

    def test_runtime_presente(self):
        for snippet in (
            "$_SERVER['REQUEST_URI']",
            "rawurldecode",
            "rtrim($path, '/')",
            "header('Location: ' . $rule[2], true, 301);",
            "gsc_monitor_poda();",
        ):
            self.assertIn(snippet, self.block)

    def test_aspas_simples_escapadas(self):
        entries = [{"url": "https://ex.com/page-d'or", "action": "410", "target": None}]
        block = build_poda_php(entries, "2026-06-12")
        self.assertIn("'/page-d\\'or' => array(", block)


class TestPodaNginx(unittest.TestCase):
    def setUp(self):
        self.block = build_poda_nginx(_ENTRIES, "2026-06-12")

    def test_410_location_exact(self):
        self.assertIn("location = /morta/ { return 410; }", self.block)

    def test_301_com_destino(self):
        self.assertIn("location = /antiga/ { return 301 https://ex.com/nova/; }", self.block)

    def test_url_com_query_usa_args(self):
        self.assertIn('if ($args = "p=123")', self.block)


class TestPodaRedirect(unittest.TestCase):
    """Estilo clássico do mod_alias: Redirect 301 /caminho/ https://destino/."""

    def setUp(self):
        self.block = build_poda_redirect(_ENTRIES, "2026-06-12")

    def test_301_estilo_redirect_simples(self):
        self.assertIn("Redirect 301 /antiga/ https://ex.com/nova/", self.block)

    def test_410_e_404_sem_destino(self):
        self.assertIn("Redirect 410 /morta/", self.block)
        self.assertIn("Redirect 404 /outra", self.block)

    def test_barra_final_preservada_e_sem_ancora(self):
        # usa o caminho original (com barra final), nao a forma ancorada
        # ^/morta/?$ do RedirectMatch
        self.assertIn("Redirect 410 /morta/", self.block)
        self.assertNotIn("^/morta", self.block)

    def test_url_com_query_vira_comentario(self):
        # query string nao cabe no Redirect simples (mod_alias ignora a query)
        self.assertNotIn("Redirect 410 /?p=123", self.block)
        self.assertIn("https://ex.com/?p=123", self.block)
        self.assertIn("query string", self.block.lower())

    def test_disclaimer_presente(self):
        self.assertIn("SUGESTAO", self.block)


# ---------------------------------------------------------------------------
# Storage: roundtrip CSV
# ---------------------------------------------------------------------------


class TestPodaStorage(unittest.TestCase):
    def setUp(self):
        self._original_dir = storage.RELATORIOS_DIR
        storage.RELATORIOS_DIR = tempfile.mkdtemp(prefix="gsc_test_poda_")

    def tearDown(self):
        shutil.rmtree(storage.RELATORIOS_DIR, ignore_errors=True)
        storage.RELATORIOS_DIR = self._original_dir

    def _plan(self):
        api = {}
        api.update(_api("https://www.ex.com/morta/", impressions=1))
        api.update(_api("https://www.ex.com/cane-corso-preco-2023/", impressions=100, clicks=3))
        return build_pruning_plan(api, SITEMAP, min_impressions=10)

    def test_roundtrip_csv_gerado_e_parseado(self):
        path = storage.save_poda_csv("ex.com", "2026-06-12", self._plan())
        self.assertTrue(path.endswith("2026-06-12_poda.csv"))

        out = parse_plan_csv(storage.load_poda_csv_lines(path))
        # 410 pré-preenchido vira diretiva; "revisar" fica pendente
        self.assertEqual(len(out["entries"]), 1)
        self.assertEqual(out["entries"][0]["url"], "https://www.ex.com/morta/")
        self.assertEqual(out["pending"], ["https://www.ex.com/cane-corso-preco-2023/"])
        self.assertEqual(out["errors"], [])

    def test_formato_excel_ptbr(self):
        path = storage.save_poda_csv("ex.com", "2026-06-12", self._plan())
        with open(path, encoding="utf-8-sig") as f:
            content = f.read()
        # delimitador ';' (Excel pt-BR abre direto em colunas), decimal com
        # vírgula, colunas editáveis logo após a url, e a sugestão de destino
        # pré-preenchida em destino_final
        self.assertIn("url;acao_final;destino_final;origem", content)
        self.assertIn(";50,0;", content)
        self.assertIn("https://www.ex.com/cane-corso-preco/", content)
        self.assertIn(";busca;", content)

    def test_aviso_soft404_no_topo_do_csv(self):
        path = storage.save_poda_csv("ex.com", "2026-06-12", self._plan())
        with open(path, encoding="utf-8-sig") as f:
            head = f.read()
        self.assertIn("soft-404", head)
        self.assertIn("home (fallback)", head)

    def test_queries_longas_truncadas_no_csv(self):
        long_query = "as perneiras sao utilizadas para proteger as pernas " * 4
        api = _api("https://www.ex.com/perneiras-velha/", impressions=100)
        query_rows = [
            {"query": long_query, "url": "https://www.ex.com/perneiras-velha/",
             "clicks": 0, "impressions": 100, "ctr": 0.0, "position": 10.0},
        ]
        plan = build_pruning_plan(api, SITEMAP, query_rows=query_rows)
        path = storage.save_poda_csv("ex.com", "2026-06-12", plan)
        with open(path, encoding="utf-8-sig") as f:
            content = f.read()
        self.assertNotIn(long_query.strip(), content)
        self.assertIn("...", content)

    def test_latest_poda_csv_pega_o_mais_recente(self):
        storage.save_poda_csv("ex.com", "2026-06-10", self._plan())
        newest = storage.save_poda_csv("ex.com", "2026-06-12", self._plan())
        self.assertEqual(storage.latest_poda_csv("ex.com"), newest)

    def test_latest_poda_csv_sem_arquivos_retorna_none(self):
        self.assertIsNone(storage.latest_poda_csv("vazio.com"))

    def test_arquivos_vao_para_subpasta_poda(self):
        path = storage.save_poda_csv("ex.com", "2026-06-12", self._plan())
        self.assertIn(os.path.join("ex.com", "poda"), path)
        self.assertTrue(
            os.path.isdir(os.path.join(storage.RELATORIOS_DIR, "ex.com", "poda"))
        )

    def test_save_poda_redirect_roundtrip(self):
        block = build_poda_redirect(
            [{"url": "https://ex.com/x/", "action": "301", "target": "https://ex.com/y/"}],
            "2026-06-12",
        )
        path = storage.save_poda_redirect("ex.com", "2026-06-12", block)
        self.assertTrue(path.endswith("2026-06-12_poda_redirect.txt"))
        self.assertIn(os.path.join("ex.com", "poda"), path)
        with open(path, encoding="utf-8") as f:
            self.assertIn("Redirect 301 /x/ https://ex.com/y/", f.read())

    def test_latest_poda_csv_retrocompat_pasta_do_dominio(self):
        # CSV no formato antigo (direto na pasta do dominio) ainda e encontrado
        domain_dir = os.path.join(storage.RELATORIOS_DIR, "legado.com")
        os.makedirs(domain_dir, exist_ok=True)
        legacy = os.path.join(domain_dir, "2026-01-01_poda.csv")
        with open(legacy, "w", encoding="utf-8") as f:
            f.write("url;acao_final\n")
        self.assertEqual(storage.latest_poda_csv("legado.com"), legacy)


if __name__ == "__main__":
    unittest.main()
