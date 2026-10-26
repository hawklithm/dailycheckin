# 一键抓 Trae 真实 LLM 请求（在【管理员】PowerShell 里执行）
#   D:\workspace\trae2api\tests\start_mitm_capture.ps1
#
# 已验证可用：mitmdump 11.0.2 装在 D:\workspace\trae2api\.mitm，
# CA 已生成于 D:\mitmconf，HTTPS 解密链路自测通过。
$ErrorActionPreference = "Stop"

$PORT = 8081
$LOG  = "D:\workspace\trae2api\logs\mitm-requests.jsonl"
$FLOW = "D:\trae_capture.flow"
$CONF = "D:\mitmconf"

# 清掉上一次的捕获
Remove-Item $LOG -ErrorAction SilentlyContinue

# 把 mitmproxy CA 装进当前用户根存储（管理员才能写；避免 Trae 报证书错）
$caPem = Join-Path $CONF "mitmproxy-ca-cert.cer"
if (Test-Path $caPem) {
    Write-Host "== 安装 mitmproxy CA 到根存储 =="
    certutil -user -addstore Root $caPem
} else {
    Write-Host "!! 没找到 CA：$caPem （先跑一次本脚本生成）"
}

Write-Host ""
Write-Host "== 启动 mitmdump（127.0.0.1:$PORT）=="
Write-Host "   日志: $LOG"
Write-Host ""
Write-Host ">>> 请你做两步："
Write-Host "    1. Trae 设置里搜 http.proxy，填  http://127.0.0.1:$PORT"
Write-Host "    2. 重启 Trae，然后在 AI 对话里随便发一句话（比如 你好）"
Write-Host ""
Write-Host ">>> 回来按 Ctrl+C 停止，然后跑："
Write-Host "    python D:\workspace\trae2api\tests\read_mitm_log.py"
Write-Host ""

$env:PYTHONPATH = "D:\workspace\trae2api\.mitm"
$env:MITM_PORT   = "$PORT"
$env:MITM_OUT    = $LOG
$env:MITM_FLOW   = $FLOW
python D:\workspace\trae2api\tests\run_mitmdump.py
