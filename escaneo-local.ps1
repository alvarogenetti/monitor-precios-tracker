# Escanea desde tu PC los links que GitHub Actions no puede leer ("ci": false: Frávega, Venex)
# y publica la base en la rama "data" de GitHub, así queda en el mismo historial.
#   Uso manual:     .\escaneo-local.ps1
#   Programado:     tarea "MonitorPrecios-local" (ver README > "Escaneo local programado")
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
$py = '.venv\Scripts\python.exe'
$log = 'data\escaneo-local.log'
function Write-Log($m) { "$(Get-Date -Format s)  $m" | Out-File $log -Append -Encoding utf8 }

# Código al día (sólo si no hay cambios propios sin commitear)
if (-not (git status --porcelain)) { git pull --ff-only --quiet }

& $py -m services.datastore pull 2>&1 | Out-File $log -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { Write-Log 'Cancelado: no se pudo bajar la base de GitHub'; exit 1 }

& $py scan.py --once --only-local 2>&1 | Out-File $log -Append -Encoding utf8

# Publica; si GitHub Actions publicó en el medio, fusiona las filas y reintenta solo
& $py -m services.datastore push 2>&1 | Out-File $log -Append -Encoding utf8
if ($LASTEXITCODE -eq 0) { Write-Log 'Base publicada en GitHub' } else { Write-Log 'Falló la publicación'; exit 1 }
