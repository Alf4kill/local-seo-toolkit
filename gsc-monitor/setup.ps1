# setup.ps1 — Configura o ambiente virtual do GSC Monitor no Windows.
#
# Uso (uma única vez, na pasta gsc-monitor/):
#   .\setup.ps1
#
# Após o setup, execute o app com:
#   .\.venv\Scripts\python.exe app.py

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== GSC Monitor — Setup ===" -ForegroundColor Cyan
Write-Host ""

# ── 1. Localiza o Python ──────────────────────────────────────────────────────
$python = $null
foreach ($cmd in @("py", "python3", "python")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $python = $cmd
        break
    }
}

if (-not $python) {
    Write-Host "[ERRO] Python nao encontrado no PATH." -ForegroundColor Red
    Write-Host "       Instale em: https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

$pyVersion = & $python --version 2>&1
Write-Host "Python encontrado: $pyVersion" -ForegroundColor Green

# ── 2. Cria o ambiente virtual ────────────────────────────────────────────────
if (-not (Test-Path ".venv")) {
    Write-Host "Criando ambiente virtual em .venv/ ..." -ForegroundColor Yellow
    & $python -m venv .venv
    Write-Host "Ambiente virtual criado." -ForegroundColor Green
} else {
    Write-Host ".venv/ ja existe — pulando criacao." -ForegroundColor Green
}

$pip    = ".\.venv\Scripts\pip.exe"
$python = ".\.venv\Scripts\python.exe"

# ── 3. Atualiza pip ───────────────────────────────────────────────────────────
Write-Host "Atualizando pip..." -ForegroundColor Yellow
& $python -m pip install --upgrade pip --quiet

# ── 4. Instala dependencias ───────────────────────────────────────────────────
Write-Host "Instalando dependencias de requirements.txt..." -ForegroundColor Yellow
& $pip install -r requirements.txt

# ── 5. Verificacao rapida ─────────────────────────────────────────────────────
Write-Host "Verificando instalacao..." -ForegroundColor Yellow
& $python -c "import google.oauth2, googleapiclient, openpyxl, requests; print('OK')"

Write-Host ""
Write-Host "=== Setup concluido com sucesso! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Como executar:" -ForegroundColor Cyan
Write-Host "  Interface grafica:  .\.venv\Scripts\python.exe app.py"
Write-Host "  CLI posicionamento: .\.venv\Scripts\python.exe posicao.py --site www.exemplo.com.br --excel"
Write-Host "  Testes:             .\.venv\Scripts\python.exe -m unittest discover"
Write-Host ""
Write-Host "Proximo passo: coloque o arquivo client_secrets.json na pasta gsc-monitor/"
Write-Host "(obtenha em: console.cloud.google.com → APIs e Servicos → Credenciais)" -ForegroundColor DarkGray
Write-Host ""
