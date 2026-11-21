# DailyCheckin

DailyCheckin 是一个专注活动签到的 Python 库，目前支持 Trae CN 签到及签到状态查询，按账号保存设备配置和绑定。Trae 和 WorkBuddy 的登录态获取由 `buddy-agent-auth` 的品牌 provider 提供，Trae 的独立浏览器 OAuth 登录、设备注册和账号绑定也由认证包提供。项目原名 trae2api；旧代理和研究代码保留在源码中，但不包含在 DailyCheckin 发行包中。

## 使用 uv 开发和构建

当前开发版为 `0.1.1.dev2`。发布后可通过 `uv sync --prerelease allow` 从 PyPI 安装；本地联调可先把认证包构建到本项目 `dist`：

```powershell
# 在 DailyCheckin 项目目录执行；需要相邻的 WorkBuddy2API 源码
uv build ..\workbuddy2api\packages\buddy-agent-auth --out-dir dist
uv sync --prerelease allow --find-links dist --extra workbuddy

# 启动命令；去掉 --status-only/--execute 是不会读取凭据的 dry run
uv run daily-checkin --native --device-id-source get-device-id --status-only
uv run --extra workbuddy daily-checkin workbuddy --help

# 运行测试、构建 sdist 和 wheel
uv run --extra workbuddy pytest
uv build --out-dir dist
```

生成的 `dist/buddy_agent_checkin-0.1.1.dev2-py3-none-any.whl` 可供 WorkBuddy2API 本地依赖；`dist/buddy_agent_auth-0.1.0.dev1-py3-none-any.whl` 用于当前开发环境解析 WorkBuddy 可选依赖。`dist` 中的包文件不提交到 Git，因此新检出仓库需要先构建认证 wheel，已发布版本可从包仓库解析。需要更新依赖时请增加 dev 版本号并重新构建。

## 签到快速开始

在项目目录安装依赖后，可使用新名称运行（也可通过 `pip install -e .` 安装并使用 `daily-checkin` 命令）：

```powershell
# 查询签到状态
python -m daily_checkin --native --device-id-source get-device-id --status-only

# 执行签到
python -m daily_checkin --native --device-id-source get-device-id --execute

# 指定独立凭据文件
python -m daily_checkin --creds .\trae2api\trae2api.json --status-only
```

作为 Python 库使用：

```python
import httpx
from daily_checkin import Account, checkin

account = Account.from_native(device_id_source="get-device-id")
with httpx.Client(timeout=30, trust_env=False) as client:
    result = checkin(account, client, status_only=True)
```

`--native` 读取原生账号和 token；默认的 `--device-id-source get-device-id` 使用项目中按账号保存的设备配置及绑定，不需要原生设备缓存或会话日志，默认地区为 CN（可用 `--user-region` 覆盖）。显式选择 `--device-id-source existing` 才使用并校验原生设备 ID 和日志地区。首次使用账号设备来源可能触发设备注册和激活；`--execute` 会在符合条件时请求领取。源码检出中的原有 `python -m trae2api.checkin` 入口及 `.traeapi` 账号设备数据继续沿用。发行包使用 `python -m daily_checkin`。设备激活与签到仍需真实环境验收。

## WorkBuddy 独立签到

DailyCheckin 不需要运行 WorkBuddy2API，即可通过独立的 `buddy-agent-auth` 包读取并维护 WorkBuddy 账号。源码开发时先安装 WorkBuddy2API 仓库的认证包，再安装本项目：

```powershell
python -m pip install -e D:\workspace\workbuddy2api\packages\buddy-agent-auth
python -m pip install -e ".[workbuddy]"

python -m daily_checkin workbuddy login --global
python -m daily_checkin workbuddy list
python -m daily_checkin workbuddy status --account <账号ID>
python -m daily_checkin workbuddy execute --account <账号ID>
python -m daily_checkin workbuddy schedule
```

`--accounts-dir` 位于 `workbuddy` 与子命令之间；未指定时使用 `~/.workbuddy2api/accounts`。`schedule` 会持续运行并在启动及每日按计划检查，Ctrl+C 停止。签到前先查询，结果不确定时不重复领取。WorkBuddy2API 作为宿主时调用同一活动服务；两个进程共用账号目录时，通过持久化的 `daily-checkin-attempts.sqlite3` 防止同一账号当天的未知结果被重复提交。这个记录会保守地阻止重试，不能代替上游状态确认。

开发版本发布后可使用 `pip install --pre buddy-agent-checkin` 安装；本地源码联调仍可使用认证包源码或 wheel。真实 WorkBuddy 登录和签到尚未完成本次集成的线上验收。 WorkBuddy2API 的 `/v1/checkin` 和 `/v1/checkin-status` 兼容端点也由 DailyCheckin 提供，保持原有上游透传语义；其中 `/v1/checkin` 直接提交，不经过账号签到服务的状态预检或跨进程去重。管理界面和独立 `execute` 命令使用账号签到服务。

### Trae CN 自动签到

使用本机 Trae 登录态运行常驻调度器：

```powershell
uv run daily-checkin trae schedule --native --device-id-source get-device-id
```

独立登录凭据可使用 `uv run daily-checkin trae schedule --creds <凭据文件>`。启动时检查当天状态；跨日后先查状态，再在北京时间零点后的 0～10 分钟内随机安排签到。进程需要持续运行；按 `Ctrl+C` 停止。调度器固定启动时的账号，每次操作重新读取登录态；账号切换后需重启。设备已签到或签到结果未知时不会重复领取。

如果希望随 WorkBuddy2API 一起启动，在启动它之前设置 `$env:DAILYCHECKIN_TRAE_NATIVE = "1"`；或者仅设置 `$env:DAILYCHECKIN_TRAE_CREDS = "凭据文件路径"` 使用独立凭据。可选的 `DAILYCHECKIN_TRAE_DEVICE_ID_SOURCE` 支持 `get-device-id`（默认）或 `existing`（仅本机登录态）。Trae 的开关与 WorkBuddy 自动签到开关独立。

独立 Trae 登录可使用 `daily-checkin trae login`，默认凭据写入 `.traeapi/trae2api.json`；源码目录中已有旧凭据文件时继续使用旧文件，也可通过 `--creds` 指定。`TRAE2API_HOME` 仍可指定设备数据目录。

## 原有 trae2api 代理及研究记录（仅源码）

本节历史代理和研究代码不包含在 DailyCheckin 的 wheel 中；源码模式运行旧代理需要额外安装其依赖。

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
默认在启动时创建 `~/.traeapi`；如用户目录无创建权限，会依次尝试 Python 所在的同名 Windows 用户目录和项目目录下的 `.traeapi`，并提示实际位置。也可通过 `TRAE2API_HOME` 指定完整存储目录（例如 PowerShell 中 `$env:TRAE2API_HOME="D:\traeapi-data"`）；切换目录不会自动迁移已有数据。已注册的独立设备缓存保存在 `~/.traeapi/<deviceId>/TinyStorage`。
签到或查询签到状态时，以凭据中的 `auth.userId` 为账号标识，`~/.traeapi/device_pair.json` 保存账号 ID 到设备 ID 的映射，不保存 token。账号没有映射时会先注册设备，并按原生设备流程发送激活请求；HTTP 200 后保存 TinyStorage 和映射，再发送签到请求。HTTP 200 表示激活请求完成，不单独证明服务端已激活或账号有签到资格。激活请求失败时保留待处理的注册记录，下次复用该设备重试；已有映射时直接使用账号已绑定的设备 ID。凭据缺少 `userId` 时无法记录绑定，签到会报错。原生客户端的凭据和缓存仍保持只读。
设备激活时会输出 `device_activation` 结构化诊断，包括 HTTP 状态、响应类型和激活标志；不会记录响应正文、令牌或设备 ID。其他日志（例如设备快照）仍可能包含账号和设备标识。首次注册的设备与现有登录 token 的组合尚未完成真实签到验收。

设备硬件信息在进程首次读取时采集一次。签到按 `auth.userId` 在 `~/.traeapi/device_hardware.json` 中查找设备快照；首次使用的账号会生成独立 UUID、漂移后的磁盘序列号和 MAC，并保存完整设备信息，之后直接复用，包括型号和系统版本。调用方可使用 `Hardware.read_native(user_id)` 获取账号快照；不提供账号的设备读取使用进程内缓存的真实设备信息，以兼容原生设备缓存，不会生成漂移结果。设备信息写入控制台和 `logs/debug-<日期>.log`，其中包含账号与设备标识，请注意日志的访问权限和分享范围。
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
