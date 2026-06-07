"""
conftest.py — Configuração compartilhada da bateria de testes (pytest).

Dois objetivos:

1. Garantir que a raiz do projeto está no sys.path, para que `from core...`
   e `from fetchers...` funcionem sem cada teste precisar do bloco
   `sys.path.insert(...)` repetido no topo do arquivo.

2. ISOLAMENTO: redirecionar a pasta de relatórios (`RELATORIOS_DIR`) para um
   diretório temporário durante TODA a sessão de testes. Assim os testes nunca
   escrevem na pasta real `relatorios/` do usuário, e a limpeza é automática
   (o tmp some no fim). Como `core.cache` deriva seu caminho de
   `core.storage._get_domain_dir`, redirecionar uma variável cobre os dois.
"""

import os
import sys
import tempfile

import pytest

# (1) raiz do projeto no path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True, scope="session")
def _isolar_relatorios():
    """Aponta storage.RELATORIOS_DIR (e, por tabela, o cache) para um tmp."""
    import core.storage as storage

    original = storage.RELATORIOS_DIR
    tmp = tempfile.mkdtemp(prefix="gsc_test_relatorios_")
    storage.RELATORIOS_DIR = tmp
    try:
        yield tmp
    finally:
        storage.RELATORIOS_DIR = original
        # best-effort: não falha o teste se o SO travar a remoção
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
