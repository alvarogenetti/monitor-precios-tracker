# Escanea desde tu PC los links que GitHub Actions no puede leer ("ci": false: Frávega, Venex)
# y sube el resultado a GitHub, así queda en el mismo historial.
#   Uso manual:     .\escaneo-local.ps1
#   Programado:     ver README > "Escaneo local programado"
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
$py = '.venv\Scripts\python.exe'
$log = 'data\escaneo-local.log'
function Write-Log($m) { "$(Get-Date -Format s)  $m" | Out-File $log -Append -Encoding utf8 }

# No tocamos nada si tenés cambios propios sin commitear (fuera de la base de precios)
$otros = git status --porcelain | Where-Object { $_ -notmatch 'data/(prices\.db|escaneo-local\.log)$' }
if ($otros) { Write-Log "Cancelado: hay cambios sin commitear: $($otros -join '; ')"; exit 1 }

for ($intento = 1; $intento -le 2; $intento++) {
    git checkout -- data/prices.db 2>$null          # la base oficial es la de GitHub
    git pull --ff-only --quiet
    if ($LASTEXITCODE -ne 0) { Write-Log 'Cancelado: git pull --ff-only falló'; exit 1 }

    & $py scan.py --once --only-local 2>&1 | Out-File $log -Append -Encoding utf8
    git add data/prices.db
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { Write-Log 'Sin cambios en la base'; exit 0 }
    git commit --quiet -m "chore(data): snapshot local (Fravega/Venex) $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    git push --quiet
    if ($LASTEXITCODE -eq 0) { Write-Log 'Subido a GitHub'; exit 0 }

    # GitHub Actions commiteó justo en el medio: descartamos nuestro commit y reescaneamos
    Write-Log "Push rechazado (intento $intento); reintento sobre la base nueva"
    git reset --quiet --hard HEAD~1
}
exit 1
