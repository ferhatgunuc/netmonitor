# NetMonitor kurulum / güncelleme (Windows PowerShell)
#   irm https://raw.githubusercontent.com/ferhatgunuc/netmonitor/main/install.ps1 | iex
$ErrorActionPreference = "Stop"
$Repo = "ferhatgunuc/netmonitor"
$Dest = if ($env:NETMON_DIR) { $env:NETMON_DIR } else { Join-Path $env:USERPROFILE "netmonitor" }
$Tmp = Join-Path $env:TEMP ("nm_" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $Tmp | Out-Null
Write-Host "NetMonitor indiriliyor..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest "https://github.com/$Repo/releases/latest/download/netmonitor.zip" -OutFile "$Tmp\nm.zip" -UseBasicParsing
Expand-Archive "$Tmp\nm.zip" -DestinationPath $Tmp -Force
New-Item -ItemType Directory -Path $Dest -Force | Out-Null
# Ayarlar, veritabani ve sanal ortam korunur
Copy-Item "$Tmp\netmonitor\*" $Dest -Recurse -Force
Remove-Item $Tmp -Recurse -Force
Write-Host "Kuruldu: $Dest"
Start-Process -FilePath (Join-Path $Dest "baslat.bat") -WorkingDirectory $Dest
