# Restart Trae with the sidecar proxy env vars, then capture its LLM traffic.
#
# Why this exists
# ---------------
# A full mitmproxy capture (admin + CA + http.proxy) got 76 requests from the
# renderer but ZERO from the sidecar: trae-api-cn.mchost.guru never appeared.
# The sidecar runs its own TTNet/cronet stack and ignores VSCode's http.proxy.
#
# main.js does set a sidecar-specific pair:
#     process.env.ICUBE_PROXY_HOST = ...
#     process.env.ICUBE_PROXY_PORT = ...
# so those are the knobs that may actually reach the sidecar.
#
# Run in an ADMIN PowerShell. It restarts Trae with those vars set.
$ErrorActionPreference = "Continue"

$TRAE = "D:\Users\marcus\AppData\Local\Programs\Trae CN\Trae CN.exe"
$PORT = 8081

Write-Host "== stopping Trae =="
Get-Process -Name "Trae CN" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 4
Get-Process -Name "Trae CN" -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

Write-Host "== relaunching Trae with the sidecar proxy env =="
$env:ICUBE_PROXY_HOST = "127.0.0.1"
$env:ICUBE_PROXY_PORT = "$PORT"
Write-Host "   ICUBE_PROXY_HOST=$env:ICUBE_PROXY_HOST"
Write-Host "   ICUBE_PROXY_PORT=$env:ICUBE_PROXY_PORT"

Start-Process -FilePath $TRAE -ArgumentList "--preserve-env"

Write-Host ""
Write-Host "== Trae relaunched =="
Write-Host ""
Write-Host ">>> Now, while mitmdump is running on 127.0.0.1:${PORT}:"
Write-Host "    1. wait for Trae to finish loading"
Write-Host "    2. send a message in the AI chat"
Write-Host "    3. then run:"
Write-Host "         python D:\workspace\trae2api\tests\read_mitm_paths.py"
Write-Host ""
Write-Host "    If trae-api-cn.mchost.guru shows up, the capture worked."
