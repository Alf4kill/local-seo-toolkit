"""
conftest.py — Coloca a raiz do projeto no sys.path para a bateria de testes.

Permite `from core.xxx import ...` em qualquer teste sem o bloco
`sys.path.insert(...)` repetido. Rode tudo com:  py -m pytest
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
