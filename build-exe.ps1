$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

py -3 -m pip install -r .\requirements.txt
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name XundaoLogin `
  --collect-all qrcode `
  --collect-all qfluentwidgets `
  --collect-all qframelesswindow `
  .\xundao_qt_app.py

Copy-Item -LiteralPath .\config.json -Destination .\dist\config.json -Force
Write-Host "Build complete: $PSScriptRoot\dist\XundaoLogin.exe"
