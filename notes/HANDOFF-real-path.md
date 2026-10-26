# HANDOFF：如何打通 Trae 真实调用链路（sidecar 通道）

> 目标读者：接手本任务的 agent。
> 背景：`trae2api` 已能用 Trae 账号接上后端 LLM 并跑通工具循环，但**不是真实链路**
> —— 不计费、模型不可选、思考深度不可控。本文记录已排除的路径、已确认的事实、
> 以及三条可行的攻坚路线（含具体下一步命令）。

---

## 0. 一句话现状

真链路的入口是 **本地 Rust sidecar `ai_agent.dll`**（Trae 内部叫 `ai-agent`）。
它通过 **mojo/named-pipe IPC** 与渲染层通信，**不监听任何 TCP 端口**。
我们当前打的 `https://trae-api-cn.mchost.guru/api/ide/v1/chat` 是网关的**边缘轻量通道**，
不是 sidecar 用的那条路。

---

## 1. 已验证的硬事实（都是实机测出来的，可以信任）

### 1.1 三层架构

| 层 | 实体 | 协议 | 谁决定模型 | 谁执行工具 |
|---|---|---|---|---|
| 渲染层 | `workbench.desktop.main.js` | mojo IPC（pipe） | ✗ | ✗ |
| **sidecar** | **`ai_agent.dll`** (Rust, 265MB) | **HTTP/WS → LLM 供应商** 或 → 网关 | **✓ `config_name`+`model_name`** | **✓ 原生 tools 数组** |
| 网关 | `trae-api-cn.mchost.guru` | SSE | 服务端定死 | 无 tools 字段 |

sidecar 内残留的源码路径证明它自己就是 LLM 客户端：
```
src\domain\agent\agents\{chat,builder,solo_builder,custom,reader,assistant}.rs
src\infrastructure\transport\unified.rs
src\infrastructure\toolhost\manager.rs
src\infrastructure\adapter\custom_model_proxy_client.rs
```
供应商直连端点（exe 内字符串）：`/models/chat/completions`(deepseek/openai/custom/xai)、
`/v1/messages`(anthropic)、`gemini`、`openrouter`。

### 1.2 当前链路的三个症状（已实测确认）

1. **控制台看不到 token 消耗**
   实测：body 17477 字符的请求，返回 `prompt_tokens=48`。17KB 报 48 tokens 不可能
   —— 这条通道根本没进计费埋点。

2. **模型不可控（实际是豆包）**
   ```
   探针："你是哪个模型？"
   回答："我是豆包，是由字节跳动独立开发、训练的生成式人工智能助手..."
   ```
   客户端传 `model: deepseek-v4.1-flash`，服务端照样给豆包。
   传任何本地模型目录里的名字 → `4023 model unknown`；省略 `model_name` → 服务端默认。
   **合法 model_name 白名单在原生层**，V1 通道无从得知。

3. **思考深度受限**
   sidecar 里有 `reasoning_effort` / `context_window_sizes` / `max_turn` /
   `prompt_max_tokens` / `prompt_set` / `ab_version`，全部随服务端下发的
   `ModelConfig` 一起来。V1 请求体里**没有这些字段的位置**。
   实测我们只能发这 11 个字段：
   `user_input / session_id / chat_history / workspace_folders / mention_context /
   parsed_query / agent_type / scene_location / agent / message_content / message_id`
   而 JS 层真实 body 还有：`chat_type / chat_model / call_model / chat_session_id /
   chat_message_id / operation_id / trigger_type / agent_id / agent_name`。

### 1.3 端口结论（重要，别再走弯路）

| 端口 | 归属 | 是不是 AI 通道 |
|---|---|---|
| `51000` | `NativeExtensionService`, `process-type=ckg` | **不是**。gRPC，任意路径回 `grpc-status:12 unknown service`，无反射 |
| `17788` | 主进程 | **不是**。webview 静态服务，所有路径 404 |
| `55818` | extension host (`node.mojom.NodeService`) | **不是**。debugger 端口 |
| 其它 | — | sidecar（`process-type=ai`）**没有任何 TCP 监听** |

实测命令（可以复现）：
```powershell
Get-CimInstance Win32_Process -Filter "Name like '%Trae%'" |
  Where-Object { $_.CommandLine -match 'process-type=ai' } |
  ForEach-Object { $_.ProcessId }        # sidecar pid
Get-NetTCPConnection -State Listen | Where-Object { $_.OwningProcess -eq <pid> }   # 空
```

### 1.4 找到的 IPC 通道

```
\\.\pipe\agent-code-toolhost-<sidecar_pid>-<hash>
实测: \\.\pipe\agent-code-toolhost-230596-6cd439f4
```
命名来自 DLL 常量 `CODE_TOOLHOST_IPC_NAME`（格式串
`agent-code-toolhost` + `CODE_TOOLHOST_IPC_NAME`）。

另有 aha 通道：`aha_doctor_ipc_server_name_service_<main_pid>`，
日志显示 `[aha_ipc] server started on service: <AHA_IPC_SERVICE_NAME>`。

**实测结果**：pipe 能 open，能写入；但它是**单实例** pipe（第一次开完就拒绝后续连接），
且读回需要正确的帧格式（见 §2.3）。注意 `agent-code-toolhost` 从日志看是
**工具执行** dispatch 通道（`[ToolhostClient] Command ID: ...`），
**不是** chat 入口。

### 1.5 已确认的 RPC 服务/方法名（从 DLL 提取，可直接用）

服务名：**`chat_service.chat`**
证据：`[ChatHandler] first token cost - before invoking chat_service.chat`

传输层字符串（`unified.rs`）：
```
"/ws"                          ← WebSocket 端点
"/api/v1/:service/:method"     ← HTTP 端点
"127.0.0.1"
"[UnifiedTransport] server listening on: ?"
"[UnifiedTransport] text message: service=?, method=?, user=?"
"[HttpTransport] request incoming: service=?, method=?"
```

34 个 Handler：`ChatHandler / ModelHandler / LiteHandler / ToolcallHandler /
AgentHandler / ContextHandler / GitHandler / ProjectHandler / TaskHandler /
SnapshotHandler / TodoListHandler / SummaryHandler / SkillImportHandler /
SandboxHandler / PtyBridgeHandler / MultimodalHandler / CKGHandler / HubHandler /
IDEHandler / FileFinderHandler / DocsetHandler / DSLAgentHandler /
GeneratedSkillHandler / PluginHandler / PrivacyModeHandler / ScheduleHandler /
CommercialHandler / CoreMemoryHandler / ContextAssetHandler /
DesignLibraryImportHandler / HealthcheckHandler / MultiRootPathHandler /
UserConfigurationHandler / BaseHandler`

`LiteHandler` 方法清单（节选，全量在 DLL 里搜 `[LiteHandler] start handler`）：
```
create_chat_session  list_chat_sessions  get_chat_session
batch_get_sessions_with_projects  commit_chat_session  freeze_chat_session
stop_chat_session  delete_chat_session  fork_session  export_past_chat
get_messages  get_message_by_id  resume_message  vm_operate
resolve_port_process  migration_work_agent_data  agent_ready
send_user_decision  delete_message  wakeup_sandbox  action_queue
revert_message  get_or_create_project_v2  list_projects_v2  ...
```

### 1.6 模型配置是服务端下发的（再次确认）
```
[ModelConfig] Received config_name=?., model_name=?., max_turn=?., prompt_max_tokens=?., max_tokens=?.
[LLMAdapter] llm_raw_chat_custom_model: prompt_set=?., ab_version=?., config_name=?., model_name=?.
```
字段表（同一字符串块内）：`extra_config function_extra_config ab_versions persist_meta
raw_chat_function prompt_set context_window_sizes max_turn display_options max_tokens
application_config reasoning_effort ...`

---

## 2. 路线 A（已尝试，失败）—— 让 sidecar 监听 TCP

**思路**：DLL 里有 `/ws`、`/api/v1/:service/:method`、`server listening on`，
说明具备 HTTP/WS 能力，若有开关让它绑 TCP 就能直接复用。

**已查到的东西**：
- sidecar 认识的 env var：`ICUBE_RPC_SERVER_PORT`（有校验
  `"ICUBE_RPC_SERVER_PORT is not a valid port"`）、`ICUBE_DEFAULT_HOST`、
  `ICUBE_USE_IPV6`、`ENABLE_IPC_SERVER`、`HOST0/PORT0`
- `main.js` 里 sidecar 启动 env（`AIAgentProcessManager`）：
  ```js
  ENABLE_IPC_SERVER:"true", CKG_PORT:`${r}`, CKG_USE_AHA_IPC:...,
  TRAE_RUNTIME:"local", TOOLHOST_TRANSPORT:"ipc", TOOLHOST_IPC_SERVICE_NAME:"toolhost"
  ```
  注意：**只设 `TOOLHOST_TRANSPORT:"ipc"`，从不设 `ICUBE_RPC_SERVER_PORT`**
- Remote SSH 模式下才切成 TCP：`qt.TOOLHOST_TRANSPORT="tcp"` + 需要
  `HARNESS_TOOLHOST_ENDPOINT` 和 `TRAE_NET_ZMQ_ENDPOINT`
- 注入 env 的入口：CLI 参数 `--preserve-env`（把父进程 env 带进 sidecar），
  见 `main.js`: `userEnv: e["preserve-env"] ? i : void 0`

**实测**：`ICUBE_RPC_SERVER_PORT=45678 ENABLE_IPC_SERVER=true` +
`Trae CN.exe --preserve-env --new-window` 启动 → **45678 没有监听**，
sidecar 仍然只用 pipe。结论：**这个版本 sidecar 不理会该 env，A 走不通**。

**残留可能性（给接手者）**：
- Remote SSH 那条 `TOOLHOST_TRANSPORT="tcp"` 分支是真的会开 TCP，
  但需要 `HARNESS_TOOLHOST_ENDPOINT` / `TRAE_NET_ZMQ_ENDPOINT`，
  且是 **toolhost**（工具执行）而非 chat。若目标只是"借 sidecar 执行工具"，
  这条路可能可用；若目标是 chat/模型选择，走不通。
- 可能存在未发现的配置项（`overrideDefaultConfigurations`、dynamicConfig）。
  搜 `product.json` → `iCubeApp.overrideDefaultConfigurations` 和
  `ICUBE_APP_SETTINGS_HOME` 下的动态配置缓存。

---

## 3. 路线 B（已尝试，未打通）—— 直接解 pipe 协议

**目标**：自己当客户端，通过 pipe 对 sidecar 发 `{service, method, data}`，
复用真正的 `chat_service.chat`。

### 3.0 实测结果（重要，先看这个）

用 pywin32 建了双工客户端（`tests/probe_sidecar_ipc.py`），对
`\\.\pipe\agent-code-toolhost-230596-6cd439f4` 依次试了 5 种帧格式
（u32le/u32be/u64le 长度前缀 + json+换行 + 裸 json）× 3 种信封：

```
sidecar pids: [197916, 230596]
pipe: \\.\pipe\agent-code-toolhost-230596-6cd439f4
=== request: {"service": "lite", "method": "agent_ready", "data": {}}
(第一种帧格式写入后，读取永久阻塞，无任何回包)
```

**结论：这个 pipe 不是 RPC 入口。** 依据：
1. 写入成功但**永远没有回包**（不是解析失败，是根本不读）
2. DLL 里该 pipe 的日志全是 `[ToolhostClient] Command ID: ...`，
   证明它是 **sidecar → toolhost 子进程**的单向命令下发通道
3. **关键**：sidecar 是用
   `--mojo-platform-channel-handle=5768`
   启动的（Chromium utility process）。它和 renderer 之间的
   `TransportManager` 通道是 **mojo message pipe（由 handle 传递）**，
   **没有名字**，因此**无法从外部按名字连接**。

> 这意味着 B 路线的难度比原估计高一个量级：
> 不是"解一个帧格式"，而是要**注入 Chromium 进程**或者**伪造一个 mojo
> peer** 并让它接受我们的 handle。这不是纯逆向能解决的问题。

### 3.1 已确认的协议事实

- 库：**`aha-ipc`**（Cargo git checkout：`aha-ipc-0152e3c7ae4208d9\4805dc9\rust\src\
  {client,server,rpc,utils}.rs`）
- **载荷是 JSON**：日志 `[aha_ipc] JSON parsed successfully: `、
  `[aha_ipc] Failed to parse JSON: `、`expected RawValue`
  → 用 `serde_json::value::RawValue` 包裹
- **有长度帧**：`[aha_ipc] ServerConnectionWriter::write called, message len= `、
  `[aha_ipc] ClientConnectionSender::send called, msg len= `、
  `[aha_ipc] received <n> bytes from connection`
- 消息类型名：`aha_ipc::rpc::RpcMessage`、`FieldSet`
- 连接生命周期：`Connect` / `Send` / `Disconnect` / `RemoveAllListeners`
  （来自 `workbench` 里的 `i.Connect="connect"` 等），
  服务端会主动发 `[aha_ipc] sending Connect event for new FFI connection`
- 身份：`[aha_ipc] new FFI connection accepted, id=..., identity=...`，
  消息带 `identity` 路由

### 3.2 下一步具体命令

**步骤 1：搞到 `aha-ipc` 的真实帧格式**
这个 crate 是 git 依赖，源码可能不在本机。两条路：
```powershell
# a) 本地找 cargo 缓存
Get-ChildItem "$env:USERPROFILE\.cargo\git\checkouts" -Directory -ErrorAction SilentlyContinue
# b) 从字节码里找 Rust 符号名（bincode 字段名会留在字符串表）
```
然后在 DLL 里搜这些符号确认变体：
```python
# 搜 discriminants / 变体名
for pat in ['RpcMessage','FieldSet','Connect','Disconnect','Send',
            'BROKEN_PIPE','BrokenPipe']:
    print(pat, t.count(pat))
```

### 3.3 若仍想走 B：唯一可行的方向是 mojo 注入

因为 chat 通道是**无名 mojo pipe**，纯外部连接不可能。可行的技术手段：

1. **注入 renderer 进程，劫持 `TransportManager.executeRequest`**
   - 用 Frida（`frida -n "Trae CN.exe" -l hook.js`）挂到 renderer
   - 打印每次 `executeRequest` 的 `{service, method, data}` 与回包
   - 只读观测，不改行为 → 能拿到全部真实请求/响应结构
   - **这是最现实的下一步**：即使不接管，也能拿到合法 `model_name`
     和 chat 请求体的完整字段（直接解决第 1、3 个症状）

2. **patch main.js 的 `AIAgentProcessManager`**
   - 在 sidecar 启动 env 里注入我们自己的变量，或把
     `createRequestPacket` 的产物同时写一份到磁盘
   - 缺点：改安装目录，升级会被覆盖；但**不需要注入进程**
   - 具体位置：`resources\app\out\main.js` 搜
     `AIAgentProcessManager`、`ENABLE_IPC_SERVER`、
     `HARNESS_TOOLHOST_ENDPOINT`
   - 更简单的变体：改 `out\vs\workbench\workbench.desktop.main.js` 里
     `TransportManager` 的 `executeRequest`，加一行把 packet 写到
     `D:\tmp\trace.jsonl`。**这是捞数据的捷径，强烈建议先做这个。**

3. **放弃 sidecar，转路线 C（抓 sidecar→供应商的 HTTPS 明文）**
   - 见 §4

### 3.4 风险与成本

- 纯 pipe 直连已证明不可行（无名 mojo pipe）
- Frida 注入需要关掉进程保护，可能有反调试
- patch JS 最省事但改安装目录，且需 Trae 更新后重做
- 真正"替代"真链路（而不是观测它）需要重放 mojo conversation，
  工作量远超预期

---

## 4. 路线 C（备选）—— 绕过 sidecar，直接打供应商

sidecar 直连供应商时用的端点/凭证来自服务端下发的动态配置
（`custom_model_proxy_client.rs`、`get_custom_model_fallback_config`）。
若能拿到那次 HTTPS 请求的**明文**（mitmproxy + 安装 Trae 不校验的根证书，
或用 `sslkeylogfile`），就能直接复刻。

**障碍**：需要管理员权限装证书；Trae 用 cronet/TTNet 网络栈，
证书信任配置要单独处理。
**收益**：能拿到合法 `model_name` + provider 凭证，一次性解决模型/计费/深度。

---

## 5. 建议的优先级（按性价比重排）

| 优先级 | 动作 | 预计收益 | 成本 |
|---|---|---|---|
| **P0** | **patch `workbench.desktop.main.js` 的 `executeRequest`，把 packet 落盘** | 拿到真实 `{service,method,data}` + 回包 + **合法 `model_name`** | 半小时 |
| **P1** | 用 P0 拿到的数据，在 V1 通道里补 `model_name` / `chat_type` / `reasoning_effort` | 立刻解决"模型是豆包""思考浅" | 1 小时 |
| **P2** | Frida 挂 renderer 观测 chat 全链路 | 确认计费字段、session 生命周期 | 半天 |
| **P3** | 路线 C：抓 sidecar→供应商的 HTTPS | 拿到 provider 凭证，可完全自建 | 1-2 天 |
| — | 路线 B 纯 pipe 直连 | **已证明不可行**，不要再投入 | — |
| — | 路线 A 让 sidecar 绑 TCP | **已证明不可行** | — |

> **核心判断**：P0 是唯一低成本的突破口。只要能在 JS 层把
> `executeRequest` 的入参打出来，就能知道真实 chat 请求长什么样，
> 然后**不接管真链路，只把缺的字段补进 V1 通道**——
> 这比"复刻真链路"便宜一个数量级，且能直接解决用户报的三个症状。

---

## 6. 现有代码/资料位置

| 路径 | 内容 |
|---|---|
| `trae2api/` | 代理实现（FastAPI，OpenAI 兼容） |
| `trae2api/gateway.py` | V1 网关客户端（当前链路） |
| `trae2api/tools.py` | 本地工具执行器（桥接用，39 个工具名） |
| `notes/core-findings.md` | 逆向总账（认证/网关/端口/env） |
| `notes/real-path-gap.md` | 为什么当前不是真链路（§1 证据） |
| `notes/sidecar-ipc-findings.md` | sidecar IPC 实测记录 |
| `notes/marscode-extension-findings.md` | 两层协议区别（关键） |
| `notes/chat-request-findings.md` | V1 请求体完整字段 |
| `notes/tooluse-protocol.md` | `<\|FunctionCallBegin\|>` 文本工具协议 |
| `tests/probe_rpc.py` | HTTP/2 / gRPC 探测脚本（51000） |
| `tests/capture_rpc.py` | 端口监听 + WS 抓帧（A 方案用，已证明无端口） |

**反编译产物**（gitignore，但本机在）：
- `notes/aiServer_full.js` (15.6MB) — aiServer 的 JS 层
- Trae 安装目录：`d:\Users\marcus\AppData\Local\Programs\Trae CN\`
  - `resources\app\out\main.js` — 主进程（含 sidecar 启动 env、CLI 参数）
  - `resources\app\out\vs\workbench\workbench.desktop.main.js` — 渲染层（TransportManager）
  - `resources\app\modules\ai-agent\ai_agent.dll` — **sidecar 本体，全部关键信息在这**
  - `resources\app\product.json` — bootConfig / nativeAppConfig / `dsc`

**DLL 字符串提取技巧**（265MB 二进制，别直接当文本读）：
```python
data = open(path,'rb').read()
txt = data.decode('latin-1')          # 比 ascii errors=ignore 更完整
i = txt.find('关键字')
print(txt[max(0,i-200):i+300])
```

---

## 7. 一句话给接手者

> **别再扫 Trae 的 TCP 端口，也别再试连那个 pipe。**
> sidecar 是 Chromium utility process（`--mojo-platform-channel-handle=N`），
> chat 通道是**无名 mojo pipe**，外部无法按名字连接。
> **直接 patch `workbench.desktop.main.js` 里的 `executeRequest`，
> 把 `{service,method,data}` 和回包写到磁盘**——这是最短路径。
> 拿到真实请求体后，把缺的字段补进现有 V1 通道即可，不必复刻整条链路。
