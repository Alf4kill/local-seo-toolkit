#!/usr/bin/env bash
# setup.sh — Configura o ambiente virtual do GSC Monitor no Linux/Mac.
#
# Uso (uma única vez, na pasta gsc-monitor/):
#   chmod +x setup.sh && ./setup.sh
#
# Após o setup, execute o app com:
#   .venv/bin/python app.py

set -euo pipefail

echo ""
echo "=== GSC Monitor — Setup ==="
echo ""

# ── 1. Localiza o Python ──────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERRO] Python não encontrado no PATH."
    echo "       Instale em: https://www.python.org/downloads/"
    exit 1
fi

echo "Python encontrado: $($PYTHON --version)"

# ── 2. Cria o ambiente virtual ────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "Criando ambiente virtual em .venv/ ..."
    "$PYTHON" -m venv .venv
    echo "Ambiente virtual criado."
else
    echo ".venv/ já existe — pulando criação."
fi

PIP=".venv/bin/pip"
PYTHON_VENV=".venv/bin/python"

# ── 3. Atualiza pip ───────────────────────────────────────────────────────────
echo "Atualizando pip..."
"$PYTHON_VENV" -m pip install --upgrade pip --quiet

# ── 4. Instala dependências ───────────────────────────────────────────────────
echo "Instalando dependências de requirements.txt..."
"$PIP" install -r requirements.txt

# ── 5. Verificação rápida ─────────────────────────────────────────────────────
echo "Verificando instalação..."
"$PYTHON_VENV" -c "import google.oauth2, googleapiclient, openpyxl, requests; print('OK')"

echo ""
echo "=== Setup concluído com sucesso! ==="
echo ""
echo "Como executar:"
echo "  Interface gráfica:  .venv/bin/python app.py"
echo "  CLI posicionamento: .venv/bin/python posicao.py --site www.exemplo.com.br --excel"
echo "  Testes:             .venv/bin/python -m unittest discover"
echo ""
echo "Próximo passo: coloque o arquivo client_secrets.json na pasta gsc-monitor/"
echo "(obtenha em: console.cloud.google.com → APIs e Serviços → Credenciais)"
echo ""
