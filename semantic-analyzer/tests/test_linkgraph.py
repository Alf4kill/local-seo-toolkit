"""test_linkgraph.py — Grafo de links internos (puro, sem deps de ML/servidor)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.linkgraph import (
    extract_links, normalize_href, build_link_graph,
    find_orphans, inlink_report, underlinked_money_pages,
    anchor_collisions, cluster_link_plan,
    detect_array_emitters, build_template_inbound, classify_pages,
)


class TestExtractLinks(unittest.TestCase):

    def test_extrai_href_e_ancora(self):
        m = '<p>veja <a href="cane-corso-preco.php">preço do cane corso</a> hoje</p>'
        self.assertEqual(extract_links(m), [("cane-corso-preco.php", "preço do cane corso")])

    def test_aspas_simples_e_atributos_extras(self):
        m = "<a class='x' href='/rottweiler' title='t'>Rottweiler</a>"
        self.assertEqual(extract_links(m), [("/rottweiler", "Rottweiler")])

    def test_ancora_com_tags_internas_vira_texto(self):
        m = '<a href="x.php"><strong>Filhote</strong> &amp; cia</a>'
        self.assertEqual(extract_links(m), [("x.php", "Filhote & cia")])

    def test_link_de_imagem_ancora_vazia(self):
        m = '<a href="x.php"><img src="a.jpg"></a>'
        self.assertEqual(extract_links(m), [("x.php", "")])

    def test_href_dinamico_php_eh_descartado(self):
        # Depois de remover o bloco PHP, não sobra href utilizável.
        m = '<a href="<?= $url ?>">dinâmico</a>'
        links = extract_links(m)
        self.assertTrue(all(h.strip() == "" for h, _ in links))

    def test_markup_vazio(self):
        self.assertEqual(extract_links(""), [])


class TestNormalizeHref(unittest.TestCase):

    def test_relativo_com_extensao(self):
        self.assertEqual(normalize_href("cane-corso-preco.php"), "cane-corso-preco")

    def test_barra_inicial_e_final(self):
        self.assertEqual(normalize_href("/cane-corso-preco/"), "cane-corso-preco")

    def test_absoluto_tira_host(self):
        self.assertEqual(normalize_href("https://www.exemplo.com/rottweiler"), "rottweiler")

    def test_query_e_fragmento(self):
        self.assertEqual(normalize_href("pagina.php?id=2#sec"), "pagina")

    def test_nao_paginas_viram_none(self):
        for bad in ["#", "#top", "mailto:a@b.com", "tel:+55", "javascript:void(0)",
                    "//cdn.x.com/a", "", "   ", "/"]:
            self.assertIsNone(normalize_href(bad), bad)


class TestBuildGraph(unittest.TestCase):

    def _graph(self):
        sources = {
            "hub":    '<a href="spoke1.php">a</a> <a href="spoke2.php">b</a>',
            "spoke1": '<a href="hub.php">voltar ao hub</a>',
            "spoke2": '<a href="https://facebook.com/x">externo</a>',  # cai fora
            "solta":  'sem links',
        }
        return build_link_graph(sources)

    def test_arestas_internas_e_externas(self):
        g = self._graph()
        self.assertEqual(set(g["out"]["hub"]), {"spoke1", "spoke2"})
        self.assertEqual(set(g["in"]["hub"]), {"spoke1"})
        # link externo do spoke2 não vira aresta interna
        self.assertEqual(g["out"]["spoke2"], {})

    def test_auto_link_ignorado(self):
        g = build_link_graph({"a": '<a href="a.php">eu mesmo</a>'})
        self.assertEqual(g["out"]["a"], {})

    def test_destino_desconhecido_descartado(self):
        g = build_link_graph({"a": '<a href="nao-existe.php">x</a>'}, known={"a"})
        self.assertEqual(g["out"]["a"], {})

    def test_chaves_url_completas_resolvem_por_slug(self):
        # Modo --urls: chaves são URLs completas; os hrefs (absolutos ou relativos)
        # têm de casar com elas via slug normalizado.
        sources = {
            "https://site.com/hub":   '<a href="https://site.com/spoke">s</a>',
            "https://site.com/spoke": '<a href="/hub">h</a>',
        }
        g = build_link_graph(sources)
        self.assertEqual(set(g["out"]["https://site.com/hub"]), {"https://site.com/spoke"})
        self.assertEqual(set(g["in"]["https://site.com/hub"]), {"https://site.com/spoke"})


class TestDiagnostics(unittest.TestCase):

    def _graph(self):
        sources = {
            "hub":    '<a href="spoke1.php">preço cane corso</a>',
            "spoke1": '<a href="hub.php">hub</a>',
            "orfa":   'ninguém me linka',
        }
        return build_link_graph(sources)

    def test_orfas(self):
        g = self._graph()
        # 'hub' é linkado por spoke1; 'spoke1' por hub; 'orfa' por ninguém.
        self.assertEqual(find_orphans(g), ["orfa"])

    def test_orfas_restritas_a_targets(self):
        g = self._graph()
        self.assertEqual(find_orphans(g, targets={"hub", "spoke1"}), [])

    def test_money_page_sublinkada(self):
        g = self._graph()
        gsc = {"orfa": {"impressions": 5000, "clicks": 3},
               "hub":  {"impressions": 10, "clicks": 0}}
        rows = inlink_report(g, gsc=gsc)
        money = underlinked_money_pages(rows, max_inlinks=0)
        self.assertEqual([m["slug"] for m in money], ["orfa"])
        self.assertEqual(money[0]["impressions"], 5000)

    def test_colisao_de_ancora(self):
        # mesma âncora "preço cane corso" → dois destinos diferentes
        sources = {
            "a": '<a href="p1.php">preço cane corso</a>',
            "b": '<a href="p2.php">Preço Cane Corso</a>',
            "p1": "x", "p2": "y",
        }
        g = build_link_graph(sources)
        cols = anchor_collisions(g)
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0]["anchor"], "preco cane corso")
        self.assertEqual(set(cols[0]["targets"]), {"p1", "p2"})

    def test_ancora_generica_nao_colide(self):
        sources = {
            "a": '<a href="p1.php">clique aqui</a>',
            "b": '<a href="p2.php">clique aqui</a>',
            "p1": "x", "p2": "y",
        }
        g = build_link_graph(sources)
        self.assertEqual(anchor_collisions(g), [])


class TestClusterLinkPlan(unittest.TestCase):

    def test_plano_com_diff_acha_links_faltando(self):
        sources = {
            "hub":    "conteúdo do hub, sem linkar spokes",
            "spoke1": '<a href="hub.php">cane corso preço</a>',   # já linka o hub
            "spoke2": "não linka o hub",
        }
        g = build_link_graph(sources)
        clusters = [{
            "size": 3, "members": ["hub", "spoke1", "spoke2"],
            "diff": {"cabeca": "hub", "paginas": [
                {"slug": "hub", "papel": "cabeca", "keyword_alvo": "cane corso preço"},
                {"slug": "spoke1", "papel": "spoke", "keyword_alvo": "valor"},
                {"slug": "spoke2", "papel": "spoke", "keyword_alvo": "custo mensal"},
            ]},
        }]
        planned = cluster_link_plan(clusters, g)
        plan = planned[0]["link_plan"]
        self.assertEqual(plan["hub"], "hub")
        self.assertEqual(plan["hub_keyword"], "cane corso preço")
        self.assertEqual(plan["missing_spoke_to_hub"], ["spoke2"])
        self.assertEqual(plan["have_spoke_to_hub"], ["spoke1"])
        self.assertEqual(set(plan["missing_hub_to_spoke"]), {"spoke1", "spoke2"})
        self.assertFalse(plan["complete"])

    def test_fallback_sem_diff_usa_representante(self):
        sources = {"a": "x", "b": "y", "c": "z"}
        g = build_link_graph(sources)
        clusters = [{"size": 2, "members": ["a", "b"], "representative": "a"}]
        planned = cluster_link_plan(clusters, g)
        self.assertEqual(planned[0]["link_plan"]["hub"], "a")
        self.assertEqual(planned[0]["link_plan"]["missing_spoke_to_hub"], ["b"])

    def test_plano_completo_quando_links_existem(self):
        sources = {
            "hub":    '<a href="b.php">b</a>',
            "b":      '<a href="hub.php">hub</a>',
        }
        g = build_link_graph(sources)
        clusters = [{"size": 2, "members": ["hub", "b"], "representative": "hub"}]
        planned = cluster_link_plan(clusters, g)
        self.assertTrue(planned[0]["link_plan"]["complete"])

    def test_singleton_ignorado(self):
        g = build_link_graph({"a": "x"})
        self.assertEqual(cluster_link_plan([{"size": 1, "members": ["a"]}], g), [])


class TestTemplateLinks(unittest.TestCase):

    def test_foreach_array_inteiro_eh_index(self):
        src = ('<?php foreach ($blog as $link): ?>'
               '<a href="<?php echo $url.$prime->formatStringToURL($link);?>">x</a>'
               '<?php endforeach; ?>')
        self.assertEqual(detect_array_emitters(src, {"blog"}), [("blog", "index")])

    def test_array_rand_com_alias_eh_widget(self):
        src = '$a = $artigos; $k = array_rand($a, 4); echo $prime->formatStringToURL($a[$k]);'
        self.assertEqual(detect_array_emitters(src, {"artigos"}), [("artigos", "widget")])

    def test_array_slice_foreach_eh_widget(self):
        src = ('foreach (array_slice($palavras_chave, -6, 6) as $l): '
               'formatStringToURL($l); endforeach;')
        self.assertEqual(detect_array_emitters(src, {"palavras_chave"}), [("palavras_chave", "widget")])

    def test_sem_formatstringtourl_nao_conta(self):
        self.assertEqual(detect_array_emitters("foreach ($blog as $b) { echo $b; }", {"blog"}), [])

    def test_array_desconhecido_ignorado(self):
        src = 'foreach ($qualquer as $x) { formatStringToURL($x); }'
        self.assertEqual(detect_array_emitters(src, {"blog"}), [])

    def test_build_template_inbound_indice_linka_todos(self):
        sources = {
            "indice": '<?php foreach ($blog as $l): ?><a href="<?=formatStringToURL($l)?>">x</a><?php endforeach;?>',
            "p1": "x", "p2": "y",
        }
        tin = build_template_inbound(sources, "ignorado", {"blog": {"p1", "p2"}},
                                     known={"p1", "p2", "indice"})
        self.assertEqual(tin["p1"], {"index"})
        self.assertEqual(tin["p2"], {"index"})

    def test_classify_tres_niveis(self):
        graph = build_link_graph({"a": '<a href="b.php">x</a>', "b": "y", "c": "z"})
        cls = classify_pages({"a", "b", "c"}, graph, template_inbound={"c": {"index"}})
        self.assertEqual(cls["b"]["tier"], "contextual")     # b é linkada por a (corpo)
        self.assertEqual(cls["c"]["tier"], "template_only")  # só índice
        self.assertEqual(cls["a"]["tier"], "orphan")         # nada


if __name__ == "__main__":
    unittest.main(verbosity=2)
