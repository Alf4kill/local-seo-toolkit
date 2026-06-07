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
    1: 28.5, 2: 15.7, 3: 11.0, 4: 8.0, 5: 7.2,
    6: 5.1,  7: 4.0,  8: 3.2,  9: 2.8, 10: 2.5,
}
