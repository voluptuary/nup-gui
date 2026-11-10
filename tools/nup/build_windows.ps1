$ErrorActionPreference = 'Stop'

# Build the standalone Windows GUI executable.
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$projectDir = Join-Path $repoRoot 'tools/nup'
$buildDir = Join-Path $projectDir 'build-win'
$distDir = Join-Path $repoRoot 'dist'
$iconFile = Join-Path $projectDir 'launcher/assets/NUP_GUI_Packager.ico'

python -m pip install --upgrade pip
python -m pip install $projectDir pyinstaller

if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $distDir | Out-Null
foreach ($name in @('nup-gui.exe', 'nup-gui-windows-x64.zip')) {
  $oldExe = Join-Path $distDir $name
  if (Test-Path $oldExe) { Remove-Item $oldExe -Force }
}

# NUP only uses SHA-256; Python's built-in SHA implementation replaces OpenSSL.
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --noupx `
  --name nup-gui `
  --paths (Join-Path $projectDir '.') `
  --collect-all zstandard `
  --exclude-module _hashlib `
  --exclude-module _ssl `
  --exclude-module ssl `
  --exclude-module _wmi `
  --icon $iconFile `
  --add-data "$iconFile;assets" `
  --distpath $distDir `
  --workpath (Join-Path $buildDir 'gui') `
  --specpath (Join-Path $buildDir 'gui') `
  (Join-Path $projectDir 'windows_gui.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed to build nup-gui.exe.' }

Compress-Archive -LiteralPath (Join-Path $distDir 'nup-gui.exe') `
  -DestinationPath (Join-Path $distDir 'nup-gui-windows-x64.zip') `
  -CompressionLevel Optimal

Write-Host "Built $distDir/nup-gui-windows-x64.zip"
