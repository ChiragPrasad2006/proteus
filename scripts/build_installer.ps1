$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = "D:\MLops\.venv\Scripts\python.exe"
$PyInstaller = "D:\MLops\.venv\Scripts\pyinstaller.exe"

Write-Host "[1/4] Building frontend..."
Push-Location (Join-Path $Root "frontend")
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Pop-Location

Write-Host "[2/4] Generating Proteus icon & wizard bitmaps..."
& $Python (Join-Path $Root "scripts\build_icon.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/4] Building Proteus.exe with PyInstaller..."
& $PyInstaller --clean --noconfirm --onefile `
    --icon=assets/proteus.ico `
    --version-file=assets/version_info.txt `
    --distpath dist `
    --name Proteus `
    launcher.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Copy-Item -Force (Join-Path $Root "dist\Proteus.exe") (Join-Path $Root "Proteus.exe")

Write-Host "[4/4] Checking Inno Setup Compiler (ISCC.exe)..."
$Iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $Iscc) {
    $Candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $Iscc = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if ($Iscc) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "release") | Out-Null
    & $Iscc (Join-Path $Root "installer\proteus.iss")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Installer created in release\Proteus-Setup-1.0.0.exe"
} else {
    Write-Host "Inno Setup (ISCC.exe) not found. Install it with:"
    Write-Host "  winget install JRSoftware.InnoSetup"
}
