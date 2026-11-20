# Abre el dashboard en tu PC con el historial actualizado desde GitHub.
#   Uso:  click derecho > "Ejecutar con PowerShell"   o   .\iniciar.ps1
#   Opcional: .\iniciar.ps1 -SinActualizar   (no baja la base de GitHub)
param([switch]$SinActualizar)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# 1) Entorno virtual (sólo la primera vez)
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    Write-Host 'Creando entorno virtual e instalando dependencias (sólo la primera vez)...'
    python -m venv .venv
    & .venv\Scripts\python.exe -m pip install -q -r requirements.txt
    & .venv\Scripts\python.exe -m playwright install chromium
}

# 2) Base de precios: la oficial es la que commitea GitHub Actions
if (-not $SinActualizar) {
    Write-Host 'Bajando el historial de precios de GitHub...'
    git checkout -- data/prices.db 2>$null
    git pull --ff-only --quiet
    if ($LASTEXITCODE -ne 0) { Write-Warning 'No se pudo actualizar desde GitHub; sigo con la base local.' }
}

# 3) Dashboard
$port = 8000
Write-Host "Dashboard en http://127.0.0.1:$port  (Ctrl+C para cerrar)"
Start-Process "http://127.0.0.1:$port"
& .venv\Scripts\python.exe -m app.main
