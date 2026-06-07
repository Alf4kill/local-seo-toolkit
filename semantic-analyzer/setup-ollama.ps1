# setup-ollama.ps1 — Configura o Ollama para rodar na GPU AMD (RX 6750 XT) via
# Vulkan e baixa o modelo escolhido. Rode uma vez (PowerShell).
#
#   .\setup-ollama.ps1                      # qwen2.5:7b-instruct (rápido, padrão)
#   .\setup-ollama.ps1 qwen2.5:14b-instruct # 14B (review mais fino; ~9GB; cabe na GPU)
#
# 7B  = rápido; ótimo para clusters pequenos e coesos.
# 14B = discrimina melhor grupos grandes/heterogêneos (menos "fundir tudo"); mais lento.
#
# Por que Vulkan: a 6750 XT (gfx1031) NÃO é suportada pelo ROCm do Ollama no
# Windows — com ROCm ele cai para CPU. Com OLLAMA_VULKAN=1 o Ollama enxerga a
# placa via Vulkan (12 GiB) e roda 100% na GPU.

param([string]$Model = "qwen2.5:7b-instruct")

$ErrorActionPreference = "Stop"
$exe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"

if (-not (Test-Path $exe)) {
    Write-Host "Ollama nao encontrado. Instale com:" -ForegroundColor Yellow
    Write-Host "  winget install --id Ollama.Ollama"
    exit 1
}

Write-Host "1) Habilitando GPU via Vulkan (OLLAMA_VULKAN=1, persistente)..."
[Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
$env:OLLAMA_VULKAN = "1"

Write-Host "1b) Janela de contexto (OLLAMA_CONTEXT_LENGTH=8192 tokens)..."
# 8192 cabe folgado nos prompts deste analisador (~4k tokens) E mantém o 14B
# 100% na GPU: ~9GB (pesos Q4) + ~1.5GB (KV de 8k) + overhead < 12GB. Com 16k o
# KV do 14B passa de 3GB e estoura os 12GB -> parte cai pra CPU e fica lento.
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH", "8192", "User")
$env:OLLAMA_CONTEXT_LENGTH = "8192"

Write-Host "2) Reiniciando o servidor Ollama para aplicar a config..."
Get-Process -Name "ollama app", "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 4

try {
    Invoke-WebRequest "http://localhost:11434/api/version" -TimeoutSec 5 -UseBasicParsing | Out-Null
    Write-Host "   Servidor no ar em http://localhost:11434" -ForegroundColor Green
} catch {
    Write-Host "   Servidor nao respondeu — verifique a instalacao." -ForegroundColor Red
    exit 1
}

Write-Host "3) Baixando o modelo $Model (pode demorar na 1a vez)..."
& $exe pull $Model
& $exe list

Write-Host ""
Write-Host "Pronto. Confirme a GPU com:  ollama ps   (deve mostrar 100% GPU)" -ForegroundColor Green
Write-Host "No analisador (caminhos reais em COMANDOS.md):" -ForegroundColor Green
Write-Host "  py analisar.py --primeweb `"<pasta-do-site>`" --gsc `"<pasta-gsc>`" --llm --llm-model $Model"
