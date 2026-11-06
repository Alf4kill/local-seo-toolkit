"""
core/dossie — o dossiê de análise de UM site (P8).

O acervo (P7) guarda o que o Search Console devolve. O dossiê junta, numa pasta
fora do repositório, tudo o que é viável coletar de forma simples para a sessão
de análise: o pacote do acervo, os exports manuais da UI do GSC, uma foto do site
ao vivo e um inventário do projeto original.

Mesma regra do acervo: EXTRAÇÃO, NUNCA VEREDITO. Nada aqui pontua, classifica
como bom/ruim ou sugere causa. Contagens, datas, rótulos de proveniência e
listas de candidatos que um humano confirma.

Módulos (lógica pura, sem rede):
    ficha       FICHA.toml — o que muda por site
    html        extração de sinais de uma página HTML (stdlib, sem bs4)
    sitemaps    parse de sitemap/sitemapindex com lastmod
    alvos       a lista de URLs a fotografar (sitemap ∪ acervo)
    projeto     inventário do projeto original, eventos candidatos, redirects
    leia        LEIA.md — a escrituração do dossiê
"""
