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

# Quantas linhas exibir nas tabelas "top" do relatório de crawl (terminal/HTML).
CRAWL_TOP_N = 25
