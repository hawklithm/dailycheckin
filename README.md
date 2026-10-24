# trae2api

TRAE CN IDE (3.4.4) AI 后端的 OpenAI 兼容代理。通过逆向 Trae 的认证与网关协议，把 Trae 订阅内的模型能力以 `/v1/chat/completions` 形式暴露出来。

## 状态: ✅ 可用

- 认证: 从本机 Trae 安装读取凭据（已实测 200 OK）
- 聊天: OpenAI 兼容 `/v1/chat/completions`（流式 + 非流式，已实测返回真实模型回复）
- 模型列表: `/v1/models`（来自 Trae 本地模型目录缓存）

## 快速开始

```bash
# 依赖: Python 3.10+, fastapi, uvicorn, httpx, cryptography
cd D:\workspace\trae2api

# 方式 A: 完整登录流（无需本机 Trae，支持任意账号）
python -m trae2api login          # 打开浏览器完成登录，凭据存 trae2api/trae2api.json
python -m trae2api login --no-browser --timeout 3600   # 手动复制 URL

# 方式 B: 复用本机 Trae 的凭据（默认，只读不干扰）
python -m trae2api                # 0.0.0.0:8080
```

登录成功后代理优先使用 `trae2api.json`；删除该文件即回到方式 B。

```bash
# 测试
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/v1/models
curl http://127.0.0.1:8080/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"x\",\"messages\":[{\"role\":\"user\",\"content\":\"你好\"}],\"stream\":false}"
```

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `TRAE2API_PORT` | 8080 | 监听端口 |
| `TRAE2API_API_KEY` | 空 | 可选的客户端 Bearer 鉴权 |
| `TRAE2API_GATEWAY` | `https://trae-api-cn.mchost.guru` | 网关地址 |
| `TRAE2API_MODEL` | 空 | 强制 model_name（默认省略→服务端默认模型） |
| `TRAE2API_PASSTHROUGH_MODEL` | 0 | 为 1 时透传调用方 model 名（当前网关白名单会 4023） |
| `TRAE2API_TLS_IMPERSONATE` | `chrome124` | TLS 指纹模拟（curl_cffi）；`off` 关闭用 httpx |
| `TRAE2API_ALLOW_ROTATION` | 0 | 为 1 时允许 RefreshToken 轮换（会使运行中的 Trae 登出，慎用） |
| `TRAE2API_DEV_CPU/DEV_MODEL/DEV_OS_TYPE/DEV_OS_VERSION/UA` | 本机实机值 | 设备指纹覆盖 |

### 登录流（`python -m trae2api login`）原理
1. 生成设备身份：随机 device_id（14 位）、machine_id（sha256）、ECDSA P-256 密钥对、PKCE S256 对
2. 本地起一次性 HTTP 服务器监听 `/authorize`（随机端口，30 分钟超时）
3. 打开 `https://www.trae.cn/authorization?...`（参数与 Trae 原版逐项一致：login_version/auth_from/login_channel/auth_type/client_id/redirect/login_trace_id/auth_callback_url/machine_id/device_id/x_device_*/code_challenge...）
4. 用户在浏览器完成登录 → 重定向回 `http://127.0.0.1:{port}/authorize?authCodeInfo={"AuthCode":"..."}`
5. `POST /trae/api/v3/oauth/ExchangeToken`（AuthCode+CodeVerifier+DeviceInfo，无签名）→ Token/RefreshToken
6. `POST /cloudide/api/v3/trae/GetUserInfo` 拉取资料 → 保存 `trae2api.json`

## 逆向结论摘要（详见 notes/）

### 认证链
1. **凭据存储**: `%APPDATA%\Trae CN\User\globalStorage\storage.json`
   - `iCubeAuthInfo://icube.cloudide` → `{token, refreshToken, userId, host, userRegion, ...}`（自研 AES-128-CBC 包装，`credential_decrypt.py` 已破解并实测）
   - `iCubeAuthInfo://icube-dc:{deviceId}` → ECDSA P-256 设备密钥对
2. **Token 刷新**: `POST {host}/trae/api/v3/oauth/ExchangeToken`
   - body: `{ClientID:"ono9krqynydwx5", RefreshToken, DeviceInfo, DeviceProof{ECDSA 签名}, IDEVersion}`
   - 签名串: `POST\n/trae/api/v3/oauth/ExchangeToken\n{ClientID}\n{RefreshToken}\n{ts}\n{nonce}`
3. **JWT 铸造**: `POST {host}/api/v2/GetUserToken`（`X-Cloudide-Token` 头）→ RS256 JWT（14 天）
4. **请求头**: `Authorization: Cloud-IDE-JWT {jwt}` + `X-User-Region: CN` + 设备头组
   （`X-Device-Id/X-Machine-Id/X-App-Id/x-ide-version-code` 等，来自运行日志实证）

### 聊天通道（V1 直连 HTTP）
- `POST https://trae-api-cn.mchost.guru/api/ide/v1/chat` (SSE)
- body: `{user_input, session_id, chat_history[]}`（`model_name` 省略→服务端默认模型；传未知名会 4023）
- 事件流: `progress_notice → prompt → metadata → output{response,reasoning_content} → token_usage → done`
- Trae 客户端的 V2 代理聊天走原生 Rust 桥（ZeroMQ/命名管道），HTTP V1 通道与它共用云端

### 关键主机
| 用途 | 地址 |
|---|---|
| 认证 | `https://api.trae.cn` |
| AI 网关 | `https://trae-api-cn.mchost.guru` |
| 登录页 | `https://www.trae.cn` |
| 动态配置 | `https://api.trae.com.cn/icube/api/v1/native/config/query` |

## 文件

- `trae2api/credential_decrypt.py` — storage.json 凭据解密（已验证）
- `trae2api/auth.py` — 凭据加载 + JWT 生命周期 + ECDSA DeviceProof 签名
- `trae2api/gateway.py` — 网关 SSE 客户端（设备头 + 流式）
- `trae2api/server.py` — FastAPI OpenAI 兼容层
- `trae2api/model_catalog.py` — 模型目录（state.vscdb 缓存 → 静态快照）
- `trae2api/verify_auth.py` — 只读认证验证脚本
- `notes/` — 全部逆向证据（core-findings / auth-findings / workbench-findings / native-agent-findings）

## 免责声明

仅用于学习研究协议设计。请遵守 Trae 服务条款；账号与额度归属本人，勿滥用。
