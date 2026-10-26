# One-command capture of Trae's real LLM request. Run in an ADMIN PowerShell:
#   D:\workspace\trae2api\tests\start_mitm_capture.ps1
#
# Verified working: mitmdump 11.0.2 in D:\workspace\trae2api\.mitm, CA in
# D:\mitmconf, HTTPS decryption self-tested.
#
# NOTE: this file is deliberately ASCII-only. Windows PowerShell 5.1 reads .ps1
# as the system ANSI codepage without a BOM, so any non-ASCII character becomes
# invalid bytes and the script fails to parse.
$ErrorActionPreference = "Stop"

$PORT = 8081
$LOG  = "D:\workspace\trae2api\logs\mitm-requests.jsonl"
$FLOW = "D:\trae_capture.flow"
$CONF = "D:\mitmconf"

# drop the previous capture
Remove-Item $LOG -ErrorAction SilentlyContinue

# install the mitmproxy CA into the user root store (needs admin, avoids TLS
# errors inside Trae)
$caPem = Join-Path $CONF "mitmproxy-ca-cert.cer"
if (Test-Path $caPem) {
    Write-Host "== installing mitmproxy CA into the root store =="
    certutil -user -addstore Root $caPem
} else {
    Write-Host "!! CA not found: $caPem (run this script once to generate it)"
}

Write-Host ""
Write-Host "== starting mitmdump on 127.0.0.1:$PORT =="
Write-Host "   log: $LOG"
Write-Host ""
Write-Host ">>> now do these two things:"
Write-Host "    1. In Trae settings search 'http.proxy' and set it to http://127.0.0.1:$PORT"
Write-Host "    2. Restart Trae, then send any message in the AI chat (e.g. hello)"
Write-Host ""
Write-Host ">>> come back, press Ctrl+C to stop, then run:"
Write-Host "    python D:\workspace\trae2api\tests\read_mitm_log.py"
Write-Host ""

$env:PYTHONPATH = "D:\workspace\trae2api\.mitm"
$env:MITM_PORT   = "$PORT"
$env:MITM_OUT    = $LOG
$env:MITM_FLOW   = $FLOW
python D:\workspace\trae2api\tests\run_mitmdump.py
