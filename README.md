# trae2api

TRAE CN IDE (3.4.7) 后端的 OpenAI 兼容代理。当前实现包含本地认证路径和 V1 chat upstream；历史结果曾报告文本请求成功，但远端模型选择及原生能力仍需按下方计划逐项验证。

## 当前证据状态

- 代理实现了 OpenAI 兼容 `/v1/chat/completions`，并通过 V1
  `POST /api/ide/v1/chat` 处理文本与 SSE。保存的 `_e2e_verify` 结果曾报告
  成功回复和 usage；本轮没有重跑，不能当作当前运行验收。
- `/v1/models` 来自本地模型目录/快照，不证明远端模型可用或实际选中。
- 目前没有把 Trae 正常会话的一条新输入、远端请求和响应闭合到同一 turn。
  静态 V2/V3 route、局部 HTTP 探针或 aha IPC 连接日志都不足以证明原生
  正常链路，也不足以证明 Python 独立调用不可行。
- 最近一次 45 秒 metadata-only baseline 安装了 `InitWithParams` 与 `Start`
  两个 hook，记录到 0 次调用，随后正常卸载、detach 且身份复核一致；该窗口
  没有伴随 UI 测试输入，因此只说明窗口内无可见 Cronet 请求，不说明推理路由不存在。

| 能力 | 当前代理证据范围 |
|---|---|
| 普通文本 | V1 有历史成功结果；本轮未重验，且未证明是原生会话使用的 route。 |
| 流式输出与 usage | V1 代码解析 SSE/usage；历史观察不能证明所有终止、错误或截断语义。 |
| 模型选择 | 默认 V1 请求不透传调用方模型；响应会回显输入模型。本地目录不证明上游选择。 |
| system / developer | 当前兼容修复将其作为标记文本放入普通用户内容，不等同真正 role。 |
| tools / tool_choice | V1 使用文本兼容表示和本地工具循环；没有证明上游原生结构化 tool-call 契约。 |
| reasoning、取消及其他事件 | 尚未按当前远端链路验证；未知能力不应标为已支持。 |

当前证据与阶段门槛见 [Python 客户端复现计划](notes/PYTHON_CLIENT_REPRODUCTION_PLAN_2026-10-27.md)、
[认证协议审查](notes/AUTH_PROTOCOL_REVIEW_2026-10-27.md) 和
[原生会话取证记录](notes/NATIVE_CAPTURE_SESSION_2026-10-27.md)、
[近期远端契约与 metadata 基线](notes/NATIVE_REMOTE_CONTRACT_2026-10-27.md)。历史结论保留在
[FINAL-VERDICT](notes/FINAL-VERDICT.md) 与
[HANDOFF](notes/HANDOFF-2026-10-27.md)，但其中的绝对架构结论已在文首复核说明中撤回/降级。

### 工具调用是怎么做的

当前 V1 兼容路径以普通文本传递工具说明，让模型输出
`<|FunctionCallBegin|>[{"name":...,"parameters":...}]<|FunctionCallEnd|>` 标记，
再由 `translate.py` 解析成 OpenAI `tool_calls`。

这是现有兼容实现，不证明上游结构化工具协议，也不是“唯一可行”结论。

## 快速开始

```bash
# 依赖: Python 3.10+, fastapi, uvicorn, httpx, cryptography
cd D:\workspace\trae2api

# 方式 A: 独立登录（当前设备注册实现面向 Windows x64）
python -m trae2api login          # 打开浏览器完成登录，凭据存 trae2api/trae2api.json
python -m trae2api login --no-browser --timeout 3600   # 手动复制 URL
python -m trae2api login --creds .\trae2api\trae2api.json --prepare-device  # 仅准备独立设备

# 方式 B: 复用本机 Trae 的凭据（默认，只读不干扰）
python -m trae2api                # 0.0.0.0:8080
```

登录成功后代理优先使用 `trae2api.json`；删除该文件即回到方式 B。
独立登录在凭据旁保存 `.device.secret` 设备配置，重复登录会复用注册 ID 和密钥。
设备注册/激活已经实测成功；新版独立浏览器授权、换 token 和签到仍待真实验收，详见
[独立登录实现与证据](docs/INDEPENDENT_LOGIN_2026-11-20.md)。

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
1. 读取持久化的独立设备身份；首次通过 Aha 注册/激活真实硬件，保存远端 device_id、machine_id 和 ECDSA P-256 密钥，每轮重新生成 PKCE S256 对
2. 本地起一次性 HTTP 服务器监听 `/authorize`（随机端口，30 分钟超时）
3. 打开 `https://www.trae.cn/authorization?...`（按已确认的原生字段构建；plugin_version 来自 tronBuildVersion，设备字段来自系统信息，完整线上等价尚未验收）
4. 用户在浏览器完成登录 → 重定向回 `http://127.0.0.1:{port}/authorize?authCodeInfo={"AuthCode":"..."}`
5. `POST /trae/api/v3/oauth/ExchangeToken`（AuthCode+CodeVerifier+DeviceInfo，无签名）→ Token/RefreshToken
6. `POST /cloudide/api/v3/trae/GetUserInfo` 拉取有效用户资料 → 原子替换指定的独立凭据文件

## 逆向结论摘要（详见 notes/）

### 认证链
1. **凭据存储**: `%APPDATA%\Trae CN\User\globalStorage\storage.json`
   - `iCubeAuthInfo://icube.cloudide` → `{token, refreshToken, userId, host, userRegion, ...}`（自研 AES-128-CBC 包装，`credential_decrypt.py` 已破解并实测）
   - `iCubeAuthInfo://icube-dc:{deviceId}` → ECDSA P-256 设备密钥对
2. **RefreshToken 轮换（默认关闭）**: `POST {host}/trae/api/v3/oauth/ExchangeToken`
   - body: `{ClientID:"ono9krqynydwx5", RefreshToken, DeviceInfo, DeviceProof{ECDSA 签名}, IDEVersion}`
   - 签名串: `POST\n/trae/api/v3/oauth/ExchangeToken\n{ClientID}\n{RefreshToken}\n{ts}\n{nonce}`
3. **Token 使用/更新**: 当前 PKCE 登录保存 `ExchangeToken.Result.Token`；代理 `auth.py` 会优先复用有效凭据，并在特定过期/强制刷新路径尝试 `GetUserToken`。尚未证明普通 CN 推理请求必须先 mint 该 JWT，或该 token 与远端 LLM 授权头的对应关系。
4. **请求头**: `Authorization: Cloud-IDE-JWT {jwt}` + `X-User-Region: CN` + 设备头组
   （`X-Device-Id/X-Machine-Id/X-App-Id/x-ide-version-code` 等，来自运行日志实证）

### 聊天通道（V1 直连 HTTP）
- `POST https://trae-api-cn.mchost.guru/api/ide/v1/chat` (SSE)
- body: `{user_input, session_id, chat_history[]}`（`model_name` 省略→服务端默认模型；传未知名会 4023）
- 事件流: `progress_notice → prompt → metadata → output{response,reasoning_content} → token_usage → done`
- **必须使用 legacy 设备头**（`X-App-Id` / `X-Device-*` / `x-ide-token`）；
  改用「现代头」会得到 500 / 4001 / 2001。详见 handoff 2.4。
- 字段必须放在 body **顶层**；嵌进 `data{}` 会得到 `3003 all models failed`

### 已观察到的独立边界（不是闭合的原生请求链）

```
Python trae2api ── V1 HTTPS/SSE 请求 ──> trae-api-cn.mchost.guru

Trae renderer ── 本地 native RPC ──> ai_agent.dll / 会话处理
                                         │
                                         └── 该 turn 的远端请求/响应尚未与
                                             Python V1 或某条静态 route 关联

cue-server 的日志含 @aha-kit/rpc / electron.ahaIpc 连接信息；这是本地进程
间通道证据，不等于远端推理使用该 transport。
```

### 关键主机
| 用途 | 地址 |
|---|---|
| 认证 | `https://api.trae.cn` |
| 代理 V1 host（当前配置） | `https://trae-api-cn.mchost.guru` |
| 登录页 | `https://www.trae.cn` |
| 动态配置 | `https://api.trae.com.cn/icube/api/v1/native/config/query` |

## 文件

- `trae2api/credential_decrypt.py` — storage.json 凭据解密（已验证）
- `trae2api/auth.py` — 凭据加载 + JWT 生命周期 + ECDSA DeviceProof 签名
- `trae2api/gateway.py` — 网关 SSE 客户端（设备头 + 流式）
- `trae2api/server.py` — FastAPI OpenAI 兼容层（SSE 解析 + 工具循环 + usage 透出）
- `trae2api/translate.py` — `<|FunctionCallBegin|>` 标记 ↔ OpenAI tool_calls
- `trae2api/events.py` — SSE 事件候选、当前解析逻辑与错误码语义；不代表所有上游事件已验证
- `trae2api/trae_schema.py` — 静态结构体字段摘录，不是完整 wire schema
- `trae2api/model_catalog.py` — 模型目录（state.vscdb 缓存 → 静态快照）
- `trae2api/verify_auth.py` — 只读认证验证脚本
- `notes/` — 逆向证据；先读当前 Python 复现计划与认证审查，再把旧 verdict/handoff 当历史记录阅读

## 免责声明

仅用于学习研究协议设计。请遵守 Trae 服务条款；账号与额度归属本人，勿滥用。
