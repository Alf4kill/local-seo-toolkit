"""
test_dossie.py — Testes do dossiê de análise (P8). Offline: sem rede, git local.

O que está travado aqui não é "o arquivo foi gerado". São as leituras que o
dossiê existe para não deixar errar:
  - a forma EXATA da URL que o Google indexou é preservada (maiúscula, barra
    final), só o fragmento sai — senão a variante some antes de ser fotografada;
  - a cadeia de redirect é registrada salto a salto, com loop detectado;
  - evento do projeto é CANDIDATO, com o casamento arquivo->URL rotulado;
  - o LEIA.md declara o que falta e de quando é cada fonte.
"""

import gzip
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

import pytest
from core.dossie import alvos, ficha, html, leia, projeto, saidas, sitemaps
from fetchers import site_crawler

HOST = "www.exemplo.com.br"
BASE = "https://www.exemplo.com.br"

PAGINA = """<!doctype html><html lang="pt-BR"><head>
<title>  Cane Corso   preço </title>
<meta name="description" content="Quanto custa">
<meta name="robots" content="index, follow">
<link rel="canonical" href="/cane-corso-preco">
<link rel="alternate" hreflang="pt-PT" href="/pt/cane-corso">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Article"},{"@type":["BreadcrumbList","Thing"]}]}</script>
<script type="application/ld+json">{quebrado</script>
<style>.x{color:red}</style>
</head><body>
<h1>Preço do <b>Cane Corso</b></h1>
<p>Um dois três quatro cinco.</p>
<script>var palavras_que_nao_contam = 1;</script>
<a href="/outra-pagina#secao">interno</a>
<a href="https://exemplo.com.br/sem-www">interno sem www</a>
<a href="/outra-pagina">repetido</a>
<a href="https://externo.com/x" rel="nofollow noopener">externo</a>
<a href="mailto:a@b.c">mail</a><a href="#topo">topo</a>
<div itemscope itemtype="https://schema.org/Product"></div>
</body></html>"""


class TestHtml(unittest.TestCase):
    def test_sinais_basicos(self):
        r = html.extrair(PAGINA, BASE + "/cane-corso-preco", HOST)
        self.assertEqual(r["titulo"], "Cane Corso preço")
        self.assertEqual(r["descricao"], "Quanto custa")
        self.assertEqual(r["robots_meta"], "index, follow")
        self.assertEqual(r["canonical"], BASE + "/cane-corso-preco")
        self.assertEqual(r["h1"], ["Preço do Cane Corso"])
        self.assertEqual(r["lang"], "pt-BR")
        self.assertEqual(r["hreflang"], [["pt-PT", BASE + "/pt/cane-corso"]])

    def test_links_internos_ignoram_www_e_fragmento(self):
        r = html.extrair(PAGINA, BASE + "/cane-corso-preco", HOST)
        self.assertEqual(
            r["links_internos"], [BASE + "/outra-pagina", "https://exemplo.com.br/sem-www"]
        )
        self.assertEqual(r["n_links_externos"], 1)
        self.assertEqual(r["n_links_nofollow"], 1)

    def test_schema_inclui_graph_lista_e_itemtype(self):
        r = html.extrair(PAGINA, BASE + "/x", HOST)
        self.assertEqual(r["schema_tipos"], ["Article", "BreadcrumbList", "Product", "Thing"])
        self.assertEqual(r["schema_blocos_invalidos"], 1)

    def test_palavras_so_do_texto_visivel(self):
        r = html.extrair(PAGINA, BASE + "/x", HOST)
        # "Preço do Cane Corso" (4) + 5 + texto das 6 âncoras (8 palavras)
        self.assertEqual(r["n_palavras"], 4 + 5 + 8)

    def test_html_quebrado_nao_explode(self):
        r = html.extrair("<html><title>a<b", BASE, HOST)
        self.assertIn("n_palavras", r)


class TestSitemaps(unittest.TestCase):
    def test_urlset_com_lastmod(self):
        xml = (
            "<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
            "<url><loc> https://a.com/x </loc><lastmod>2026-03-01</lastmod></url>"
            "<url><loc>https://a.com/y</loc></url></urlset>"
        )
        r = sitemaps.parse(xml)
        self.assertEqual(r["tipo"], "urlset")
        self.assertEqual(
            r["entradas"],
            [
                {"loc": "https://a.com/x", "lastmod": "2026-03-01"},
                {"loc": "https://a.com/y", "lastmod": None},
            ],
        )

    def test_index_e_invalido(self):
        xml = (
            "<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
            "<sitemap><loc>https://a.com/s1.xml</loc></sitemap></sitemapindex>"
        )
        self.assertEqual(sitemaps.parse(xml)["tipo"], "sitemapindex")
        self.assertEqual(sitemaps.parse("<<nao xml")["tipo"], "invalido")

    def test_robots(self):
        self.assertEqual(
            sitemaps.sitemaps_do_robots(
                "User-agent: *\nSitemap: https://a.com/s.xml\nsitemap: https://a.com/s.xml"
            ),
            ["https://a.com/s.xml"],
        )


def _acervo_minimo(caminho, linhas):
    con = sqlite3.connect(caminho)
    con.executescript(
        "CREATE TABLE dim_pagina (id INTEGER PRIMARY KEY, url TEXT UNIQUE);"
        "CREATE TABLE fato_pagina (propriedade TEXT, tipo TEXT, data TEXT, pagina_id INTEGER,"
        " clicks INTEGER, impressions INTEGER);"
    )
    ids = {}
    for url, tipo, data, cl, im in linhas:
        if url not in ids:
            ids[url] = len(ids) + 1
            con.execute("INSERT INTO dim_pagina VALUES (?,?)", (ids[url], url))
        con.execute(
            "INSERT INTO fato_pagina VALUES ('p',?,?,?,?,?)", (tipo, data, ids[url], cl, im)
        )
    con.commit()
    con.close()


class TestAlvos(unittest.TestCase):
    def test_uniao_preserva_forma_exata_e_tira_fragmento(self):
        sitemap = [
            {"loc": BASE + "/a", "lastmod": "2026-01-01"},
            {"loc": BASE + "/foto.webp", "lastmod": None},
        ]
        acervo = [
            {
                "url": BASE + "/a",
                "impressoes": 10,
                "cliques": 1,
                "primeiro": "2025-07-01",
                "ultimo": "2026-01-01",
            },
            {
                "url": BASE + "/a#secao",
                "impressoes": 5,
                "cliques": 0,
                "primeiro": "2025-06-21",
                "ultimo": "2026-02-01",
            },
            {
                "url": BASE + "/A",
                "impressoes": 3,
                "cliques": 0,
                "primeiro": "2025-08-01",
                "ultimo": "2025-09-01",
            },
            {
                "url": BASE + "/b/",
                "impressoes": 50,
                "cliques": 2,
                "primeiro": "2025-06-21",
                "ultimo": "2026-10-01",
            },
            {
                "url": BASE + "/images/x.jpg",
                "impressoes": 99,
                "cliques": 0,
                "primeiro": None,
                "ultimo": None,
            },
        ]
        r = alvos.montar(sitemap, acervo, max_urls=0)
        urls = [a["url"] for a in r["alvos"]]
        self.assertEqual(urls, [BASE + "/a", BASE + "/b/", BASE + "/A"])
        a = r["alvos"][0]
        self.assertEqual(
            (a["origem"], a["acervo_impressoes"], a["acervo_primeiro"], a["acervo_ultimo"]),
            ("ambos", 15, "2025-06-21", "2026-02-01"),
        )
        self.assertEqual(r["fora"]["nao_pagina"], 2)
        self.assertEqual(r["fora"]["fragmento_fundido"], 1)

    def test_maximo_corta_a_cauda_de_menor_volume(self):
        acervo = [
            {"url": f"{BASE}/p{i}", "impressoes": i, "cliques": 0, "primeiro": None, "ultimo": None}
            for i in range(5)
        ]
        r = alvos.montar([], acervo, max_urls=2)
        self.assertEqual([a["url"] for a in r["alvos"]], [BASE + "/p4", BASE + "/p3"])
        self.assertEqual(r["fora"]["cortadas_pelo_maximo"], 3)

    def test_le_acervo_so_web_e_so_leitura(self):
        tmp = tempfile.mkdtemp()
        try:
            db = os.path.join(tmp, "a.sqlite3")
            _acervo_minimo(
                db,
                [
                    (BASE + "/a", "web", "2026-01-01", 1, 10),
                    (BASE + "/a", "web", "2026-01-02", 0, 5),
                    (BASE + "/i.webp", "image", "2026-01-01", 0, 7),
                ],
            )
            r = alvos.urls_do_acervo(db)
            self.assertEqual(
                r,
                [
                    {
                        "url": BASE + "/a",
                        "impressoes": 15,
                        "cliques": 1,
                        "primeiro": "2026-01-01",
                        "ultimo": "2026-01-02",
                    }
                ],
            )
            self.assertEqual(alvos.urls_do_acervo(os.path.join(tmp, "nao_existe")), [])
        finally:
            shutil.rmtree(tmp)


LOG = (
    "\x1eaaa\x1f2026-02-07\x1fnovos artigos\n\n"
    "A\tartigos/um.php\nA\tartigos/dois.php\nA\tartigos/tres.php\nA\timg/x.webp\n"
    "\x1ebbb\x1f2026-02-07\x1fmais um\n\nA\tartigos/quatro.php\nM\t.htaccess\n"
    "\x1eccc\x1f2025-10-01\x1fprimeiro\n\nA\tindex.php\nA\tartigos/um.php\n"
)


class TestProjeto(unittest.TestCase):
    def test_parse_log_e_candidatos(self):
        commits = projeto.parse_log(LOG)
        self.assertEqual([c["hash"] for c in commits], ["aaa", "bbb", "ccc"])
        cand = projeto.eventos_candidatos(commits, extensoes_pagina=[".php"], min_arquivos=3)
        self.assertEqual(
            [(c["data"], c["tipo_sugerido"], c["n_arquivos"]) for c in cand],
            [("2026-02-07", "conteudo-novo", 4), ("2026-02-07", "tecnico", 1)],
        )
        self.assertEqual(cand[0]["pasta_dominante"], "artigos")
        self.assertEqual(cand[0]["assuntos"], ["novos artigos", "mais um"])

    def test_aplicar_git(self):
        itens = [{"arquivo": "artigos/um.php"}, {"arquivo": "nunca.php"}]
        projeto.aplicar_git(itens, projeto.parse_log(LOG))
        self.assertEqual(
            (itens[0]["criado_git"], itens[0]["alterado_git"], itens[0]["n_commits"]),
            ("2025-10-01", "2026-02-07", 2),
        )
        self.assertIsNone(itens[1]["criado_git"])

    def test_slug_e_mapeamento_rotulado(self):
        self.assertEqual(projeto.slug_do_arquivo("artigos/Cane-Corso.php"), "cane-corso")
        self.assertEqual(projeto.slug_do_arquivo("blog/x/index.md"), "x")
        itens = [
            {"arquivo": "a/cane-corso.php", "e_pagina": True},
            {"arquivo": "a/peças.php", "e_pagina": True},
            {"arquivo": "a/nada.php", "e_pagina": True},
            {"arquivo": "a/estilo.css", "e_pagina": False},
        ]
        projeto.mapear_urls(
            itens, [BASE + "/cane-corso", BASE + "/Cane-Corso", BASE + "/p/pe%C3%A7as"]
        )
        self.assertEqual([i["casamento"] for i in itens], ["ambiguo", "unico", "sem_par", None])
        self.assertEqual(itens[1]["url_casada"], BASE + "/p/pe%C3%A7as")

    def test_redirects_apache_nginx_next(self):
        htaccess = (
            "# Redirect 301 /comentado /x\n"
            "Redirect 301 /velha /nova\n"
            "Redirect permanent /a /b\n"
            "RedirectMatch 301 ^/preco-(.*)$ /preco\n"
            "RewriteRule ^antiga$ /atual [R=301,L]\n"
            "RewriteRule ^interna$ /index.php [L]\n"
        )
        r = projeto.redirects_de_texto(htaccess, "pub/.htaccess")
        self.assertEqual(
            [(x["linha"], x["regra"], x["origem"], x["destino"], x["codigo"]) for x in r],
            [
                (2, "Redirect", "/velha", "/nova", "301"),
                (3, "Redirect", "/a", "/b", "301"),
                (4, "RedirectMatch", "^/preco-(.*)$", "/preco", "301"),
                (5, "RewriteRule", "^antiga$", "/atual", "301"),
            ],
        )
        r = projeto.redirects_de_texto("location / {\n rewrite ^/x$ /y permanent;\n}", "nginx.conf")
        self.assertEqual((r[0]["origem"], r[0]["codigo"]), ("^/x$", "301"))
        nxt = "redirects() { return [\n { source: '/a', destination: '/b', permanent: true },\n]}"
        r = projeto.redirects_de_texto(nxt, "next.config.js")
        self.assertEqual((r[0]["linha"], r[0]["origem"], r[0]["codigo"]), (2, "/a", "308"))

    def test_parse_blame(self):
        texto = (
            "a" * 40
            + " 1 1 1\nauthor-time 1772323200\n\tlinha\n"
            + "b" * 40
            + " 2 2\nauthor-time 1759276800\n\toutra\n"
        )
        self.assertEqual(projeto.parse_blame(texto), {1: "2026-03-01", 2: "2025-10-01"})


def _git(pasta, *args, data=None):
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@t",
    )
    if data:
        env.update(
            GIT_AUTHOR_DATE=f"{data}T12:00:00+00:00", GIT_COMMITTER_DATE=f"{data}T12:00:00+00:00"
        )
    subprocess.run(["git", "-C", pasta, *args], check=True, capture_output=True, env=env)


def _escrever(pasta, rel, texto="x"):
    caminho = os.path.join(pasta, rel)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as fh:
        fh.write(texto)


SEM_GIT = shutil.which("git") is None


@pytest.mark.skipif(SEM_GIT, reason="git indisponivel")
class TestProjetoGitReal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "site")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q")
        _escrever(self.repo, "index.php")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-q", "-m", "inicio", data="2025-06-01")
        for slug in ("um", "dois", "tres"):
            _escrever(self.repo, f"artigos/{slug}.php")
        _escrever(self.repo, ".htaccess", "Redirect 301 /velha /um\n")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-q", "-m", "lote", data="2026-02-07")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_log_real_e_blame(self):
        self.assertTrue(projeto.tem_git(self.repo))
        commits = projeto.parse_log(projeto.log_git(self.repo))
        self.assertEqual([c["data"] for c in commits], ["2026-02-07", "2025-06-01"])
        self.assertEqual(projeto.datas_blame(self.repo, ".htaccess"), {1: "2026-02-07"})
        self.assertFalse(projeto.tem_git(self.tmp))


class _Resp:
    def __init__(self, status, headers=None, texto=""):
        self.status_code = status
        self.headers = headers or {}
        self.text = texto
        self.content = texto.encode("utf-8")


class _Sessao:
    def __init__(self, mapa):
        self.mapa = mapa
        self.pedidos = []

    def get(self, url, **kw):
        self.pedidos.append(url)
        resp = self.mapa.get(url)
        if isinstance(resp, Exception):
            raise resp
        return resp or _Resp(404)


class TestCrawler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mapa = {
            BASE + "/velha": _Resp(301, {"Location": "/meio"}),
            BASE + "/meio": _Resp(302, {"Location": BASE + "/nova"}),
            BASE + "/nova": _Resp(
                200, {"content-type": "text/html; charset=utf-8", "x-robots-tag": "noindex"}, PAGINA
            ),
            BASE + "/loop1": _Resp(301, {"Location": "/loop2"}),
            BASE + "/loop2": _Resp(301, {"Location": "/loop1"}),
        }

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_cadeia_salto_a_salto(self):
        r = site_crawler.obter(_Sessao(self.mapa), BASE + "/velha")
        self.assertEqual([p["status"] for p in r["cadeia"]], [301, 302, 200])
        self.assertEqual(
            (r["url_final"], r["status_final"], r["erro"]), (BASE + "/nova", 200, None)
        )

    def test_loop_detectado(self):
        r = site_crawler.obter(_Sessao(self.mapa), BASE + "/loop1")
        self.assertEqual(r["erro"], "loop de redirect")
        self.assertIsNone(r["status_final"])

    def test_erro_de_rede_vira_registro(self):
        import requests

        r = site_crawler.obter(
            _Sessao({BASE + "/x": requests.ConnectionError("caiu")}), BASE + "/x"
        )
        self.assertTrue(r["erro"].startswith("ConnectionError"))

    def test_fotografar_grava_html_e_sinais(self):
        reg = site_crawler.fotografar(
            _Sessao(self.mapa),
            {"url": BASE + "/velha", "origem": "acervo"},
            host=HOST,
            pasta_html=os.path.join(self.tmp, "html"),
        )
        self.assertEqual(
            (reg["status_inicial"], reg["n_redirects"], reg["status_final"]), (301, 2, 200)
        )
        self.assertEqual(reg["x_robots_tag"], "noindex")
        self.assertEqual(reg["titulo"], "Cane Corso preço")
        with gzip.open(os.path.join(self.tmp, reg["arquivo_html"]), "rt", encoding="utf-8") as fh:
            self.assertIn("<h1>", fh.read())

    def test_rodar_retoma_e_respeita_tempo(self):
        alvos_ = [{"url": BASE + "/nova"}, {"url": BASE + "/velha"}, {"url": BASE + "/404"}]
        s = _Sessao(self.mapa)
        r = site_crawler.rodar(
            s,
            alvos_,
            host=HOST,
            pasta_dia=self.tmp,
            pausa=0,
            tempo_max=-1,
            progresso=lambda *_: None,
        )
        self.assertEqual((r["fotografadas"], r["completo"]), (0, False))
        r = site_crawler.rodar(
            s, alvos_, host=HOST, pasta_dia=self.tmp, pausa=0, progresso=lambda *_: None
        )
        self.assertTrue(r["completo"])
        antes = len(s.pedidos)
        r = site_crawler.rodar(
            s, alvos_, host=HOST, pasta_dia=self.tmp, pausa=0, progresso=lambda *_: None
        )
        self.assertEqual((r["nesta_rodada"], len(s.pedidos)), (0, antes))

    def test_sitemaps_recursivos(self):
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        mapa = {
            BASE + "/indice.xml": _Resp(
                200,
                {},
                f"<sitemapindex xmlns='{ns}'><sitemap><loc>{BASE}/s1.xml</loc>"
                "</sitemap></sitemapindex>",
            ),
            BASE + "/s1.xml": _Resp(
                200,
                {},
                f"<urlset xmlns='{ns}'><url><loc>{BASE}/a</loc>"
                "<lastmod>2026-01-01</lastmod></url></urlset>",
            ),
        }
        r = site_crawler.coletar_sitemaps(
            _Sessao(mapa),
            HOST,
            f"Sitemap: {BASE}/indice.xml",
            os.path.join(self.tmp, "sm"),
            pausa=0,
        )
        self.assertEqual([a["tipo"] for a in r["arquivos"]], ["sitemapindex", "urlset"])
        self.assertEqual(r["entradas"][0]["lastmod"], "2026-01-01")


class TestSaidas(unittest.TestCase):
    def test_resumo_inlinks_canonical_e_grupo(self):
        regs = [
            {
                "url": BASE + "/a",
                "url_final": BASE + "/a",
                "status_final": 200,
                "links_internos": [BASE + "/b", BASE + "/b/", BASE + "/a"],
                "canonical": BASE + "/a",
            },
            {
                "url": BASE + "/b",
                "url_final": BASE + "/b",
                "status_final": 200,
                "links_internos": [BASE + "/a"],
                "canonical": "http://www.exemplo.com.br/b",
                "robots_meta": "noindex,follow",
            },
            {
                "url": BASE + "/velha",
                "url_final": BASE + "/a",
                "status_final": 200,
                "n_redirects": 1,
            },
        ]
        linhas, arestas = saidas.resumo_crawl(regs, regras_taxonomia=[["^/v", "antiga"]])
        por = {lin["url"]: lin for lin in linhas}
        self.assertEqual(por[BASE + "/b"]["n_inlinks"], 1)
        self.assertEqual(por[BASE + "/a"]["n_inlinks"], 1)
        self.assertFalse(por[BASE + "/a"]["canonical_e_outra"])
        self.assertTrue(por[BASE + "/b"]["canonical_e_outra"])
        self.assertEqual(por[BASE + "/velha"]["grupo"], "antiga")
        self.assertEqual(len(arestas), 2)
        st = saidas.contagem_status(regs)
        self.assertEqual(
            (st["2xx"], st["noindex"], st["canonical_para_outra"], st["com_redirect"]), (3, 1, 1, 1)
        )


class TestFichaELeia(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pasta = os.path.join(self.tmp, "dossies", HOST)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_ficha_com_caminho_windows_e_grupos(self):
        ficha.escrever_modelo(
            self.pasta,
            dominio=HOST,
            url=BASE + "/",
            projeto=r"E:\projetos\site",
            hoje="2026-10-18",
            pausa=0.5,
            max_urls=10,
        )
        f = ficha.ler(self.pasta)
        self.assertEqual(f["projeto"]["caminho"], r"E:\projetos\site")
        self.assertEqual(ficha.grupo_de("/images/x", f["taxonomia"]["regras"]), "imagem")
        self.assertEqual(ficha.grupo_de("/qualquer", f["taxonomia"]["regras"]), "sem_grupo")
        # não sobrescreve
        ficha.escrever_modelo(self.pasta, dominio="outro", url="x", hoje="h", pausa=1, max_urls=1)
        self.assertEqual(ficha.ler(self.pasta)["site"]["dominio"], HOST)

    def test_leia_declara_o_que_falta_e_reconhece_exports(self):
        ficha.escrever_modelo(
            self.pasta, dominio=HOST, url=BASE + "/", hoje="h", pausa=1, max_urls=1
        )
        os.makedirs(os.path.join(self.pasta, "gsc_ui"))
        for nome in ("2026-10-18_indexacao-paginas.zip", "2026-10-18_links.zip", "solto.png"):
            _escrever(self.pasta, f"gsc_ui/{nome}")
        texto = open(
            leia.gerar(self.pasta, ficha.ler(self.pasta), agora="T"), encoding="utf-8"
        ).read()
        self.assertIn("Acervo GSC (`acervo/`) | **ausente**", texto)
        self.assertIn("`2026-10-18_indexacao-paginas.zip`", texto)
        self.assertIn("| Indexação › Sitemaps | `sitemaps` | **falta** |", texto)
        self.assertIn("Core Web Vitals | `core-web-vitals` | falta (opcional)", texto)
        self.assertIn("sem item reconhecido: `solto.png`", texto)
        self.assertIn("2 de 9 itens", texto)


class TestCli(unittest.TestCase):
    def setUp(self):
        import core.storage as storage

        self.tmp = tempfile.mkdtemp()
        self.raiz = os.path.join(self.tmp, "dossies")
        self.storage = storage
        self.rel_original = storage.RELATORIOS_DIR
        storage.RELATORIOS_DIR = os.path.join(self.tmp, "relatorios")

    def tearDown(self):
        self.storage.RELATORIOS_DIR = self.rel_original
        shutil.rmtree(self.tmp)

    def _rodar(self, *argv):
        import dossie

        args = dossie.parse_args(list(argv) + ["--site", HOST, "--raiz", self.raiz])
        return dossie.COMANDOS[args.comando](args)

    def test_iniciar_fechar(self):
        r = self._rodar("iniciar")
        pasta = r["pasta"]
        for sub in ("acervo", "gsc_ui", "site_vivo", "projeto", "analise"):
            self.assertTrue(os.path.isdir(os.path.join(pasta, sub)))
        self.assertTrue(os.path.exists(os.path.join(self.raiz, "_comum", "google_updates.csv")))
        self.assertTrue(self._rodar("iniciar")["ficha_existia"])

        pacote = os.path.join(self.storage.RELATORIOS_DIR, HOST, "acervo", "pacote")
        os.makedirs(os.path.join(pacote, "web"))
        _escrever(pacote, "web/DADOS.md", "# dados")
        db = os.path.join(pacote, "acervo.sqlite3")
        con = sqlite3.connect(db)
        con.executescript(
            "CREATE TABLE ingestao (tipo TEXT, grao TEXT, data TEXT, data_state TEXT);"
            "INSERT INTO ingestao VALUES ('web','total','2025-06-21','final'),"
            "('web','total','2026-10-14','final_provisorio');"
            "CREATE TABLE evento (id INTEGER);"
        )
        con.commit()
        con.close()
        self.assertTrue(self._rodar("fechar")["copiado"])
        texto = open(os.path.join(pasta, "LEIA.md"), encoding="utf-8").read()
        self.assertIn("`web` 2025-06-21→2026-10-14", texto)
        self.assertTrue(os.path.exists(os.path.join(pasta, "acervo", "copia.json")))

    def test_site_com_sessao_falsa(self):
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        mapa = {
            BASE + "/robots.txt": _Resp(200, {}, f"Sitemap: {BASE}/s.xml"),
            BASE + "/s.xml": _Resp(
                200, {}, f"<urlset xmlns='{ns}'><url><loc>{BASE}/nova</loc></url></urlset>"
            ),
            BASE + "/nova": _Resp(200, {"content-type": "text/html"}, PAGINA),
        }
        self._rodar("iniciar")
        original = site_crawler.nova_sessao
        site_crawler.nova_sessao = lambda: _Sessao(mapa)
        try:
            r = self._rodar("site", "--pausa", "0")
        finally:
            site_crawler.nova_sessao = original
        self.assertTrue(r["completo"])
        pasta = os.path.join(self.raiz, HOST)
        dia = os.listdir(os.path.join(pasta, "site_vivo"))[0]
        with open(os.path.join(pasta, "site_vivo", dia, "resumo.csv"), encoding="utf-8-sig") as fh:
            self.assertIn("Cane Corso preço", fh.read())
        texto = open(os.path.join(pasta, "LEIA.md"), encoding="utf-8").read()
        self.assertIn("1 URLs fotografadas (2xx 1, canonical_para_outra 1)", texto)

    @pytest.mark.skipif(SEM_GIT, reason="git indisponivel")
    def test_projeto_gera_candidatos_com_urls(self):
        repo = os.path.join(self.tmp, "site")
        os.makedirs(repo)
        _git(repo, "init", "-q")
        for slug in ("um", "dois", "tres"):
            _escrever(repo, f"artigos/{slug}.php")
        _escrever(repo, ".htaccess", "Redirect 301 /velha /um\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", "lote", data="2026-02-07")
        db = os.path.join(self.storage.RELATORIOS_DIR, HOST, "acervo", "acervo.sqlite3")
        os.makedirs(os.path.dirname(db))
        _acervo_minimo(
            db,
            [
                (BASE + "/um", "web", "2026-02-10", 0, 3),
                (BASE + "/dois", "web", "2026-02-11", 0, 1),
            ],
        )
        self._rodar("iniciar", "--projeto", repo)
        r = self._rodar("projeto", "--min-arquivos", "3")
        self.assertEqual((r["git"], r["n_candidatos"]), (True, 2))
        pasta = os.path.join(self.raiz, HOST, "projeto")
        with open(
            os.path.join(pasta, "eventos", "2026-02-07_conteudo-novo.txt"), encoding="utf-8"
        ) as fh:
            linhas = [x for x in fh.read().splitlines() if not x.startswith("#")]
        self.assertEqual(sorted(linhas), [BASE + "/dois", BASE + "/um"])
        with open(os.path.join(pasta, "redirects.csv"), encoding="utf-8-sig") as fh:
            self.assertIn("/velha,/um,2026-02-07", fh.read())

    def test_projeto_sem_pasta_e_erro_explicito(self):
        import dossie

        self._rodar("iniciar")
        with self.assertRaises(dossie.DossieError):
            self._rodar("projeto")
