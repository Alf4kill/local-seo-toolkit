"""
config.py — Configuração central do GSC Monitor.

Reúne as constantes transversais (usadas por mais de um módulo) e os caminhos-base
do projeto. Constantes de uso único e bem localizadas continuam no seu próprio
módulo — aqui ficam só as que se beneficiam de uma fonte única.
"""

import os

# Raiz do projeto (gsc-monitor/) — âncora para credenciais e pasta de relatórios.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# CTR esperado por posição no Google (benchmark de mercado).
# Usado pelo health score (core/analytics.py, via core/ctr.py) e pelo Excel
# (reporters/excel_reporter.py). Modifique aqui para usar outra referência.
# ---------------------------------------------------------------------------
CTR_BENCHMARK = {
    1: 28.5,
    2: 15.7,
    3: 11.0,
    4: 8.0,
    5: 7.2,
    6: 5.1,
    7: 4.0,
    8: 3.2,
    9: 2.8,
    10: 2.5,
}

# ---------------------------------------------------------------------------
# Health score (core/analytics.py): pesos dos 3 componentes (somam 1.0).
# ---------------------------------------------------------------------------
HEALTH_WEIGHTS = {"indexation": 0.4, "position": 0.4, "ctr": 0.2}

# Limiares de nota por faixa de score (0–100 → letra). Abaixo de REGULAR: "Crítico".
HEALTH_GRADE_EXCELENTE = 80  # score >= → "Excelente"
HEALTH_GRADE_BOM = 60  # score >= → "Bom"
HEALTH_GRADE_REGULAR = 40  # score >= → "Regular"

# ---------------------------------------------------------------------------
# Canibalização (core/analytics.py): limiares p/ duas URLs "competirem de fato".
# Sem eles, qualquer query com 2+ URLs (mesmo uma com 1 impressão na posição 80)
# virava "canibalização" — muito falso positivo.
# ---------------------------------------------------------------------------
CANNIBAL_MIN_IMPRESSIONS = 10  # volume mínimo da URL para a query
CANNIBAL_MAX_POSITION = 30  # acima disso a URL não disputa de fato

# ---------------------------------------------------------------------------
# Search Analytics (fetchers/position_fetcher.py): janela e limite de linhas.
# ---------------------------------------------------------------------------
DAYS_BACK = 30  # período retroativo analisado
ROW_LIMIT = 25000  # máximo de linhas por chamada (limite absoluto da API)
GSC_DELAY_DAYS = 3  # o GSC atrasa ~2-3 dias; end_date = hoje - este valor

# ---------------------------------------------------------------------------
# Outras APIs externas.
# ---------------------------------------------------------------------------
TRENDS_GEO = "BR"  # geo padrão do Google Trends (fetchers/trends_fetcher.py)
INSPECT_DELAY = 0.5  # s entre chamadas da URL Inspection (cota 2000/dia)
NLP_DELAY = 0.5  # s entre chamadas da Cloud Natural Language API

# ---------------------------------------------------------------------------
# Acervo (P7 — armazém histórico em SQLite; core/warehouse/ + acervo.py).
#
# O acervo existe porque a retenção do GSC é uma JANELA MÓVEL de ~16 meses:
# cada dia que passa apaga para sempre o dia mais antigo. Ele faz o backfill
# do que ainda existe e acumula para frente, sem nunca apagar.
# ---------------------------------------------------------------------------
ACERVO_DIAS_BACKFILL = 480  # mesma janela do Plano de Poda (máx. do GSC)
ACERVO_ASSENTAMENTO_DIAS = 10  # dias que ainda "assentam" após aparecer
ACERVO_TETO_DIA_TIPO = 50000  # teto documentado: linhas/dia/tipo/propriedade
ACERVO_MAX_PAGINAS = 40  # freio de startRow por corpo (40 x 25k = 1M linhas)
ACERVO_PAUSA_REQUISICAO = 1.0  # s entre chamadas (educado; não é cota)
ACERVO_ESPERA_CARGA = 900  # s (15 min) — guia oficial p/ a load quota
ACERVO_TENTATIVAS = 5  # retentativas para 429/5xx

# Dias por requisição, por grão. Conservador até `acervo.py aferir` provar que
# o teto de 50k vale por DIA dentro da consulta (e não por consulta) — a doc do
# Google não resolve isso e as fontes de terceiros se contradizem.
# Grãos baratos (poucas linhas/dia) cobrem a janela inteira numa requisição:
# ACERVO_DIAS_BACKFILL + 1 porque o intervalo é inclusivo nas duas pontas.
_ACERVO_JANELA_INTEIRA = ACERVO_DIAS_BACKFILL + 1
ACERVO_DIAS_LOTE = {
    "total": _ACERVO_JANELA_INTEIRA,
    "dispositivo": _ACERVO_JANELA_INTEIRA,
    "aparencia": _ACERVO_JANELA_INTEIRA,
    "pais": 180,
    "pagina": 30,
    "query": 30,
    "query_pagina": 7,
}

# ---------------------------------------------------------------------------
# Análise de logs de servidor (core/log_analyzer.py, logs.py).
# 100% local, sem cota: lê o access log e mede o comportamento real do
# Googlebot (frequência de crawl, status, páginas nunca rastreadas, money pages
# subcrawladas). É o encaixe mais forte com a restrição "local-only, free tier".
# ---------------------------------------------------------------------------

# User-agents tratados como Googlebot (lowercase; match por substring no UA).
# Cobre o crawler principal + bots auxiliares do Google que também gastam crawl
# budget. ATENÇÃO: o UA é FALSIFICÁVEL — qualquer um pode mandar "Googlebot" no
# header. A verificação confiável é por DNS reverso/direto (verify_googlebot),
# oferecida como opt-in lento. Sem ela, o relatório rotula a detecção como
# "por UA (não verificado)" — honestidade analítica.
GOOGLEBOT_UA_PATTERNS = [
    "googlebot",
    "storebot-google",
    "google-inspectiontool",
    "googleother",
    "google-extended",
    "adsbot-google",
    "mediapartners-google",
]

# Formatos de access log suportados (regex com grupos nomeados). A ordem importa:
# o parser tenta "combined" primeiro e cai para "common". Cobre Apache e Nginx,
# que usam o mesmo "combined log format" por padrão. Só o "combined" traz o
# User-Agent — necessário para identificar o Googlebot; logs "common" (sem UA)
# rendem só agregados de path/status, sem separar bot de humano.
LOG_FORMATS = {
    "combined": (
        r"(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "
        r'"(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" '
        r"(?P<status>\d{3}) (?P<bytes>\S+) "
        r'"(?P<ref>[^"]*)" "(?P<ua>[^"]*)"'
    ),
    "common": (
        r"(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "
        r'"(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" '
        r"(?P<status>\d{3}) (?P<bytes>\S+)"
    ),
}

# Cruzamento com o GSC: só sinalizamos uma "money page subcrawlada" se a URL
# tiver pelo menos este volume de impressões no período (senão não é uma página
# que de fato importa para o tráfego).
UNDERCRAWLED_MIN_IMPRESSIONS = 1000

# Janela MÍNIMA do log para o veredito "money page subcrawlada" valer. As
# impressões vêm de uma janela de DAYS_BACK dias do GSC; cruzá-las com um log de
# 2 dias e concluir "subcrawlada" é veredito confiante e errado — uma página
# perfeitamente saudável passa dias sem ser rastreada. Abaixo deste piso o
# veredito é RECUSADO, com o motivo registrado em result["indisponivel"].
UNDERCRAWLED_MIN_LOG_DAYS = 7

# Quantas linhas exibir nas tabelas "top" do relatório de crawl (terminal/HTML).
CRAWL_TOP_N = 25
