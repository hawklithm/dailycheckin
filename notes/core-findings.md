# Trae CN 3.4.4 — 逆向核心发现笔记

目标程序: `d:\Users\marcus\AppData\Local\Programs\Trae CN\` (Electron/VSCode fork, vscodeVersion 1.107.1, packageType TRAE_CN, provider Yinli/cn)

## 1. 代码分布
- `resources\app\out\main.js` — Electron 主进程 (3.4MB): OAuth 登录、token 管理、签名
- `resources\app\out\vs\workbench\workbench.desktop.main.js` — 工作台渲染层 (18MB): UI、AI 编排
- `resources\app\modules\ai-agent\` — 原生 Rust agent (ai_agent.dll 278MB + harness.dll + sscronet.dll cronet 网络栈)，本地 socket 端口 40005，DB: `%USERPROFILE%\.icube\ai-agent\database.db`
- 模块源码路径注释保留: `out-build/vs/code/electron-main/oauth/marscode/*.js` 等

## 2. bootConfig (product.json 内嵌, CN 包)
- account(træ): `https://api.trae.cn` ← 认证主机
- agent/hub/cue/ckg/remote: `https://trae-api-cn.mchost.guru` ← AI 网关
- ws: `wss://trae-ws-cn.mchost.guru/custom_model` ← 自定义模型 WS
- consoleHost/homeUrl: `https://www.trae.cn`; soloUrl: `https://work.trae.cn`
- iCube/iCubeAgent: `https://api.trae.com.cn`
- appId (agent/ug/hub/cue): `6eefa01c-1036-4c7e-9ca5-d891f63bfcd8`
- hubConfig: appId TRAE=1030602, fpId 1458, serviceId 33555672, appKey `aa5ac4bc58edd98b3da74c30e040d3b1`
- frontier: `wss://frontier.zijieapi.com/ws/v2`

## 3. 认证流程 (main.js, out-build/vs/code/electron-main/oauth/marscode/)
### 登录 (OAuth + PKCE)
1. 本地起 HTTP 服务器 (随机端口)，监听 `/authorize`
2. 打开浏览器: `{consoleHost}/authorization?login_version=1&auth_from=trae&login_channel=native_ide&auth_type=local&client_id={ClientID}&redirect=0&login_trace_id={uuid}&auth_callback_url=http://127.0.0.1:{port}/authorize&machine_id={machineId}&device_id={deviceId}&x_device_id=...&x_machine_id=...&x_device_brand=...&x_device_type=...&x_os_version=...&x_app_version=...&x_app_type=trae&code_challenge={S256(verifier)}&code_challenge_method=S256`
3. 浏览器回调 `http://127.0.0.1:{port}/authorize` 带 AuthCode
4. `exchangeTokenByAuthCode`: POST `{host}/trae/api/v3/oauth/ExchangeToken` body={ClientID, AuthCode, CodeVerifier, DeviceInfo, IDEVersion} (无签名 DeviceProof)

### Token 刷新 (签名!)
`exchangeTokenByRefreshToken`: POST `{host}/trae/api/v3/oauth/ExchangeToken`
- body: `{ClientID, ClientSecret:"", RefreshToken, DeviceInfo, DeviceProof:{Signature,Timestamp,Nonce}, IDEVersion}`
- DeviceInfo: `{DeviceID, MachineID, PlatformCode:"IDE_PC", DeviceType:"PC", DeviceName, DeviceModel, ClientVersion, DevicePublicKey, DeviceBrand, DeviceCPU, OSInfo, OSVersion}`
- 签名 `Nxe(method,path,clientID,refreshToken,privKey)`:
  - payload = `"POST\n/trae/api/v3/oauth/ExchangeToken\n{ClientID}\n{RefreshToken}\n{unix_sec}\n{nonce_hex16}"` (join "\n")
  - ECDSA P-256 SHA256 签名, base64; nonce = 16 随机字节 hex
  - 密钥对登录时生成 (x9.62 spki/pkcs8 PEM)

### 关键接口
- `POST {api.trae.cn}/cloudide/api/v3/trae/GetUserInfo` headers: `x-cloudide-token: {JWT}`; body 含 `ReqSource:"IDE"`, IDEVersion
- `POST {api.trae.cn}/cloudide/api/v3/trae/CheckLogin` body: `{IDEVersion, ReqSource, GetAIPayHost:true}`
- 登出错误码 JM 列表 (token_expired 等) → 强制重新登录

### ClientID `Jy()`
`productJson.iCubeApp.authConfig.TRAE[region]` 默认 **`ono9krqynydwx5`** (SOLO: en1oxy7wnw8j9n)

### Token 存储
- `~/.trae-cn/trae-jwt-token` — RS256 JWT (iss=trae, data:{id,tenant_id,type:user,user_id})，~60 天有效期
- JWT 作为 `Authorization: Cloud-IDE-JWT {token}` 注入 (main 进程 WebRequest 拦截器对 consoleHost/agent 域名统一注入) + `X-User-Region: {region}`
- ppe/boe 环境时加 `x-tt-env`, `x-use-ppe:1` / `x-use-boe:1`
- 排除路径 (不注入): `/cloudide/api/v3/trae/GetUserInfo`, `/trae/api/v3/oauth/ExchangeToken`, `/cloudide/api/v3/trae/CheckLogin`
- 内部服务调用头: `x-cloudide-token: {JWT}`
- 设备 ID: `ahaDeviceService.deviceId.deviceId` (DPAPI 加密存 `%APPDATA%\Trae CN\aha\TinyStorage` 键 `aha.device.device_id`); machineId = `%APPDATA%\Trae CN\machineid` (UUID)

## 4. AI 请求路径 (待子代理确认)
- 渲染层 → 本地 ai-agent (127.0.0.1:40005, 协议待确认) → sscronet → 云端
- 自定义模型走 `wss://trae-ws-cn.mchost.guru/custom_model`
- webview 内直接调用网关: headers `Authorization: Cloud-IDE-JWT` 等

## 5. 实机证据
- 运行中进程: `Trae CN.exe` × N; ai-agent 本机端口 40005
- netstat: 本机监听 6512/6514 (语言服务?), 待确认
- 字体版本 JSON 拉取: `https://trae-api-cn.mchost.guru/api/version/fonts/main?version=17000&font_hash=` (可匿名访问)

## 6. ★ 凭据本地存储 (已破解, credential_decrypt.py)
- 存储位置: `%APPDATA%\Trae CN\User\globalStorage\storage.json` (主进程 stateService 持久化)
  - `iCubeAuthInfo://icube.cloudide` → {token, refreshToken, expiredAt, refreshExpiredAt, userId, host, userRegion, account{username,scope:marscode,loginScope:trae,...}}
  - `iCubeAuthInfo://icube-dc:{deviceId 4333646823299987}` → {privateKeyPEM, publicKeyPEM} ECDSA P-256 (DeviceProof 签名密钥)
  - `iCubeAuthInfo://usertag` → {userId: "cn"}
- 加密: 头部 `[116,99,5,16,0,0]` + 32B 随机 key, AES-128-CBC; key/iv 派生: SHA512(key)||XOR表(Gle⊕zle 64B) → 再 SHA512 → 前16B key 后16B iv; 明文前 64B = SHA512(plaintext) 校验
- window-level `state.vscdb` (ItemTable) 无凭据; RefreshToken 只在 storage.json
- Token 结构: RS256 JWT, 14 天有效期 (exp-iat=1209600), `data.source=refresh_token`, `source_id={refreshToken前半段}.{hex}`; JWT 由 `/api/v2/GetUserToken` 从 cloudide token 换出
- RefreshToken 格式: `{base64ish}.{16hex}`; RefreshExpire 至 2027-04 (6 个月)

## 7. 运行时观测 (日志)
- dynamicConfig: GET `https://api.trae.com.cn/icube/api/v1/native/config/query?mid={sha256}&did=4333646823299987&uid=3481484447459108&userRegion=CN&packageType=stable_cn&productCode=TRAE&platform=Win&branch=release_desktop_yoma_win32_cn&arch=x64&tenant=marscode&appVersion=3.4.4&buildVersion=2.3.93438&traeVersionCode=20250325` (5min 轮询, 304 缓存)
- machineId (storage.json telemetry.machineId): `56cb66e60ecd32141cfe256f4e5ff76e7f8d53bc99c6a93f8ef48b7cb0068524`
- 网络栈: TTNet/cronet ("TTNetFetch" 日志), 主进程 fetchJson 双通道 (ttnet → axios fallback)
- ai-agent 模块日志为压缩二进制 (AALG), 暂无法直读

## 8. 模型路由的最终结论 (实验确定, 2026-10-24)
- `/api/ide/v1/chat` 的 `model_name`: 省略 → 服务端默认模型 (实测自述"小豆包", Doubao 系列);
  传任何本地目录中的模型名 (Doubao-Seed-2.1-Turbo/glm-5.3-flash/deepseek-v3/...) → 4023 model unknown
- 加上完整 `Request{user_info, client_info, common_params}` (来自 ai_agent.dll serde 结构还原)
  **不改变** 4023 行为 → 模型白名单校验在网关侧, 合法 model_name 值空间未知
- `model_list` 端点: JS 只通过本地 RPC 通知 `chat/model_list` 获取; HTTP 直调
  (带/不带 Request, chat_type/usage/scene/function_type 变体) 均 4001 → 参数由 Rust 侧组装
- 真实 Trae 客户端的模型选择路径: renderer → 本地 RPC → ai-agent Rust sidecar → HTTP,
  model_name 的合法值列表与组装逻辑都在原生层 → 需 TLS 抓包 (mitmproxy + 证书信任) 才能复现
- 代理现状: 默认走服务端默认模型 (Doubao); `TRAE2API_MODEL` 可强制实验;
  `TRAE2API_PASSTHROUGH_MODEL=1` 时透传调用方 model 名 (当前会 4023, 保留给未来模型表破解)
- 注: subagent 曾推测"带 Request 后模型解锁"——经复验是探针脚本的 bug (model_name 字段被丢弃), 已修正

## 待确认
- 聊天/补全的精确端点路径与 payload 结构 (3 个子代理在挖)
- DeviceID 能否自造 (服务端是否校验)
- hub 长连接 (frontier?) 的角色
