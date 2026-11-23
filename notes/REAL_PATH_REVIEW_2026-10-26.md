# Trae CN 真实调用链审查（2026-10-26）

## 目标与范围

目标是判断 `traeproxy` 能否像正常 Trae CN 一样沿原生会话链路调用远端模型，并明确还缺哪些证据。前期采用只读静态检查与日志筛查；用户授权后，又对两个现有 Trae 进程做了短时、限定的 Frida 动态观测。全程未改代理代码、Trae 安装文件或系统/证书/代理配置；未重启或终止进程，未使用 spawn/pause/resume、未连单实例 pipe。没有采集或保存认证头、凭据、raw request/response body、私钥或原始对话内容；动态观测只保留白名单路由元数据，并仅检查固定测试标记的布尔命中。

仓库初始状态为 `master`、HEAD `837363f`，工作树干净。Trae CN 安装版本为 3.4.4。此报告初版写入时是本轮唯一非忽略新增文件；之后本阶段另有 `NATIVE_PROTOCOL_CONTRACT_2026-10-26.md` 与 `NEXT_STAGE_EXECUTION_PLAN_2026-10-26.md` 两份未跟踪报告。Frida observer、诊断 harness 与元数据输出放在 `.gitignore` 忽略的 `logs/` 下。

## 结论

在本次被观测的原生 UI 会话（当前 solo-lite 流程）中，确认其至 Trae 原生 RPC 的入口是 `lite.send_message`，会话流订阅入口是 `lite.subscribe_events`。两者由 renderer 的内部 `TransportManager` 经 `getAiAgentRpcClient()` 发送到原生模块。日志证实测试时间段内本地 `send_message` RPC 完成，并记录了客户端选中的 `deepseek-v4.1-flash` 配置；此结论不泛化到 Trae 的所有模式。

尚未证实该会话最终用了哪个模型、配置是否被 native/server 接受、真实上游 host/path/protocol、远端响应状态或 usage。`TransportManager` 的 success 只表示 Trae 本地 RPC 成功。模型配置值、产品默认 host、DLL 中的供应商 endpoint 字符串以及当前 TCP 连接快照，都不能替代同一会话的上游请求/响应证据。

因此，当前 V1 `/api/ide/v1/chat` 参数补充不等价于正常 Trae 会话链路。若目标是复用正常 Trae 的模型选择、会话和事件流，研究入口应围绕原生 `lite.send_message`/`lite.subscribe_events`；这个入口目前是应用内部 DI 服务，未找到可供外部代理直接调用的公开本地 API。

## 运行与日志证据

### 进程与端口

| 进程 | 观测 | 能说明什么 |
|---|---|---|
| Trae 主进程 PID 48180；renderer PID 52464、173544 | 正常运行 | renderer 是 UI/RPC 调用方 |
| `network.mojom.NetworkService` PID 76788 | 持有多条 443 连接 | Trae 有网络连接；不能仅凭 socket 归属判定业务请求 |
| `node.mojom.NodeService`, `process-type=ai-server` PID 197916 | 持有 `23.55.179.22:443` | 另一个 AI 进程有出站连接；当前证据未映射该 IP 到本次 chat |
| `process-type=ai` PID 230596 | 观测时无已建立 TCP | 只说明该 sidecar PID 当时没有自己的 TCP；不能推出请求未经网络服务或主进程出网 |
| `basil.mojom.NativeExtensionService`, `process-type=ckg` PID 36852 | 监听 `127.0.0.1:51000` | 与 chat 无关的 CKG 服务；本轮未探测该接口 |
| Python PID 242772，`python -m trae2api` | 监听 `0.0.0.0:8080` | 代理正在运行；Trae 无 `--proxy-server` 参数，Windows `ProxyEnable=0`，WinHTTP 为 Direct，没有证据表明本次原生请求经 8080 |

08:32:02.012 的 baseline 中，NetworkService 远端包括 `113.125.209.57:443`、`113.125.209.71:443`、`113.24.210.41:443`、`125.64.109.179:443`、`220.167.110.190:443`、`222.211.12.121:443`；NodeService `ai-server` 为 `23.55.179.22:443`。当时本地 DNS 缓存把 `125.64.109.179` 映射到 `api.trae.com.cn`，把部分 `113.125.*` 映射到 `pc-mon.zijieapi.com`。08:35:36 的后续快照仍有 NetworkService/`ai-server` 连接。它们只是各自快照，不可倒推出 08:34 chat 的 host 或请求。

当前活动日志目录：`C:\Users\marcus\AppData\Roaming\Trae CN\logs\20261026T075419`。08:32:02.012 baseline 字节偏移为：`main.log` 206246、`dynamicConfig.log` 5228、`window3\renderer.log` 1580072、`window3\exthost\trae.ai-code-completion\Trae AI Code Client.log` 17473、全局 `aha_log\aha_electron_2026.1026.log` 2682929；Modular ai-agent stdout/stderr 各为 0。对本次 08:34 对照只读取 baseline 之后新增部分，并只提取时间、service/method、模型字段、状态和 host 元数据。此前还对 baseline 之前的既有日志做过安全筛查，仅用于提取路由与运行元数据；未输出实际对话内容。

### 原生对照时间线

| 北京时间 | 新增日志中的本地行为 | 证据边界 |
|---|---|---|
| 08:34:19.409–19.574 | `lite.create_chat_session` request → TransportManager success | 本地会话创建 RPC 成功 |
| 08:34:19.868 | `lite.subscribe_events` request | 持续订阅启动；它不是普通 unary request，没有普通 success/complete 行不能据此判失败 |
| 08:34:19.943 附近 | renderer 日志出现 `model_name`/`config_name` 为 `deepseek-v4.1-flash` 的客户端配置记录 | 表示客户端所选配置；不证明 native/server/provider 已使用该模型 |
| 08:35:26.372–26.775、08:35:31.707–34.810 | 两次 `lite.send_message` request → TransportManager success | 本地 RPC 完成，不证明远端模型响应 |
| 08:35:27.060、08:35:35.251 附近 | renderer 再出现同一模型/config 字段 | 仍是客户端/会话配置证据 |

`renderer.log` 增量中测试固定响应标记命中布尔值为 true；未能从同一记录识别 `role=assistant`，所以不能作为 assistant 回复命中或模型响应证明。观察到 `get_chat_session`、`get_messages`、`wakeup_sandbox` 等本地会话操作；它们只是编排线索。没有在本次增量中找到可关联的 `ChatHandler`、`ModelConfig`、`LLMAdapter`、上游 URL/path、usage 或远端成功状态。`dynamicConfig.log` 增量有 6 行，安全提取到 `api.trae.com.cn` 与 `url` 字段名，但没有把它关联到本次 chat 的证据。

## r1 限定动态观测（北京时间）

用户授权后，Frida 只附加到现有 PID 230596（`process-type=ai`）和 PID 76788（NetworkService），没有生成新进程或触发 UI/网络动作。observer 在 08:58:30.399 启动，运行 5 分钟，于 09:03:30.399 自动超时；对 PID 230596 安装 5 个 WinHTTP API hooks，对 PID 76788 安装 5 个 WinHTTP 与 6 个已确认 Cronet public C API hooks，共 16 个。只记录 host/port/method、符合域名白名单的脱敏 path、HTTP 状态和数值长度/时间；不读取 headers、query、body 或回调 buffer。WinHTTP 只覆盖 attach 后新建的 Connect/OpenRequest handle，不能把未命中事件解释为没有流量。

进程归属在同一采样中复核：PID 230596（父 PID 48180，创建于 07:54:21.338）加载 `ai_agent.dll` 和 `WINHTTP.dll`；PID 197916（父 PID 48180，创建于 07:54:20.810）是 `ai-server`/NodeService，未加载 `ai_agent.dll`。此前工作消息曾把 DLL 归属写反，已按这次逐 PID 模块枚举纠正。动态观测结束时，230596 和 76788 仍以相同创建时间运行；observer 记录了两个脚本卸载、两个 session detach 和最终 detach 标记，退出码为 0。

用户在 UI 选择 DeepSeek v4.1 Flash 并发送固定测试后，renderer 增量显示：

| 北京时间 | 本地日志证据 | 边界 |
|---|---|---|
| 08:59:46.190、08:59:46.356–.357 | 4 条 `lite.send_message` 日志 | renderer/native RPC 证据；不代表远端请求完成 |
| 08:59:46.422、.534、.536 | 3 条 `lite.subscribe_events` 日志 | 持续订阅相关日志；没有恢复事件载荷 |
| 08:59:46.613 | 固定标记命中布尔值为 true，`model_name`/`config_name` 均为 `deepseek-v4.1-flash` | 用户确认 UI 收到固定回复；模型字段仍是客户端配置，日志未确认 assistant role、实际 provider 或模型 |

NetworkService 的 Cronet hooks 在这条本地 send_message 首次日志之后约 23–795 毫秒看到四个 HTTPS flow：

| Flow | 北京时间 | 目标和 route | 结果 |
|---:|---|---|---|
| 28 | 08:59:46.213 | `api.trae.cn:443 POST`；path 按策略省略 | status 200，读取到 199 字节 |
| 29 | 08:59:46.709 | `trae-api-cn.mchost.guru:443 POST /api/agent/v3/<segment>` | status 200，读取到 16,541 字节 |
| 30 | 08:59:46.938 | `trae-api-cn.mchost.guru:443 POST /api/agent/v3/<segment>/<segment>` | status 200，读取到 640 字节 |
| 31 | 08:59:46.985 | `trae-api-cn.mchost.guru:443 POST /api/<segment>/v1/<segment>/<segment>/<segment>` | status 200，读取到 85 字节 |

这一轮共记录 71 个 Cronet `Start` flow 和 141 个 Cronet 响应回调事件；回调中的 status 200 出现 137 次、403 出现 4 次。该统计按回调事件计数，同一 flow 可能分别触发 `response_started` 与 `succeeded`，不是唯一 HTTP 请求数；截至自动超时时也有请求尚无完成回调。flow 28–31 与测试时间邻近，但没有 session/RPC ID 将它们和该 `lite.send_message` 唯一关联；不能据 200、响应长度或 path 形状认定其为 LLM 响应。测试日志中没有可关联的 `model_config` 事件或 token usage 数值，实际 provider/model 及 usage 仍未证实。

## r2 受控观测执行（固定路由候选与结果）

### 固定 route 候选

对安装原件的定向扫描在 `ai_agent.dll` 与 `harness.dll` 中各命中 22 个 `api/agent/v3/` 前缀字符串；两份 DLL 中精确带前导斜杠的 `/api/agent/v3/` 字符串均为 0。以下为 17 个主要后缀候选及文件字节偏移（AI / harness）：

| 静态后缀候选 | `ai_agent.dll` 偏移 | `harness.dll` 偏移 |
|---|---:|---:|
| `create_agent_task` | `0xA58C788` | `0xAAD5F98` |
| `commit_toolcall_result` | `0xA58C7A6` | `0xAAD5FB6` |
| `interrupt` | `0xA58C7C9` | `0xAAD5FD9` |
| `resume_agent_task` | `0xA58C7DF` | `0xAAD5FEF` |
| `get_resume_agent_task_status` | `0xA58C7FD` | `0xAAD600D` |
| `query_history_state` | `0xA58C826` | `0xAAD6036` |
| `sync_history_state` | `0xA58C846` | `0xAAD6056` |
| `compact` | `0xA58C865` | `0xAAD6075` |
| `llm_utils_chat` | `0xA58C879` | `0xAAD6089` |
| `workflow/start` | `0xA58C894` | `0xAAD60A4` |
| `workflow/commit_toolcall` | `0xA58C8AF` | `0xAAD60BF` |
| `use_fast_request` | `0xA58C8D4` | `0xAAD60E4` |
| `generate_summary` | `0xA58C8F1` | `0xAAD6101` |
| `dsl/logs/subscribe` | `0xA58C90E` | `0xAAD611E` |
| `dsl/templates` | `0xA58C92D` | `0xAAD613D` |
| `dsl/render/resources` | `0xA58C947` | `0xAAD6157` |
| `custom_model_connectivity_check` | `0xA58D1FA` | `0x92277A2`, `0xAAD69C0` |

另有 4 个 `generated_skill` 后缀候选：`restore_pending`（AI `0x9B63308` / harness `0xAACE06D`）、`dismiss_pending`（`0x9B63334` / `0xAACE041`）、`get_pending`（`0x9B63360` / `0xAACE019`）、`list_pending`（`0x9B63388` / `0xAACDFF0`）。`api/agent/v3/generated_skill` 仅在 AI DLL 的 `0x9B633D7` 出现，且在后缀前 NUL 结束，属于不完整前缀。静态字符串邻接有歧义：AI 的 `list_pending` 后接权限错误文本；harness 的一个 `custom_model_connectivity_check` 副本后接 `window_typebiz_context`；harness 的 `dsl/render/resources` 后接 `TTNetConfig`。这些邻接不能可靠地划分为同一路径或参数。

以上只是二进制静态字符串候选，不证明任一后缀在当前流程被调用，也不构成活动路由的穷举。r1 已观测到 `/api/agent/v3/<segment>` 形状，但其动态 path 段按策略脱敏，不能据此反向恢复 suffix。两份安装 JS bundle 对精确字串 `/api/agent/v3/` 未命中。r2 使用的 17 项 allowlist 未匹配本窗口 13 个 flow；这只表示该 observer 未找到固定 token 匹配，不能判定是静态清单遗漏、没有相关请求或用户未发送测试。

r2 observer 已仅在既有 NetworkService PID 76788 上执行 5 分钟；按安装原件固定 route token 做白名单，只输出命中 token 的 path，其他 path 不展示。13 个 Cronet flow 中没有一个命中这组固定路由，因此无法从本轮确认任何精确 Agent V3 suffix；host/method/status 汇总见文末。R1 已证实 `trae-api-cn.mchost.guru:443` 实际收到 `/api/agent/v3/<segment>` 形状请求，但动态 suffix 被脱敏，17 项静态字符串只是候选，不能说其中任何一项已由运行流量确认。

### 上传/响应内容门禁与本次覆盖

本机 `sscronet.dll`（SHA256 `A7BED51C3D76BC4F96DD0F49CED50D589DA7F305071ECA95F802F4D541836648`）的 Cronet API 原型参照 Chromium 固定提交的[生成 C 头文件](https://chromium.googlesource.com/chromium/src/+/42bcd13e37f9b0a9efc540ae8feee9b4aae8e948/components/cronet/native/generated/cronet.idl_c.h)。observer 通过 `UrlRequest_InitWithParams` 建立 request/URL/params/provider 映射，并以 `UploadDataProvider_Read` 建立 provider/sink/buffer 映射。只有精确白名单 flow 在 `UploadDataSink_OnReadSucceeded` 提供有效 `bytes_read`，且不超过 buffer 容量及每 flow/总量上限时才可能读取；没有 body-eligible flow 时不读取 buffer。执行上限为每个 upload 1 MiB、每个 response 2 MiB、全 observer 合计 4 MiB；重试/rewind、异步顺序、对象复用或映射不唯一时放弃该 flow 的内容投影。

response 侧 `UrlRequestCallback_OnReadCompleted(callback,request,info,buffer,bytes_read)` 只会在同 request upload 至少命中新合成 token `TRAE_ROUTE_R2_OK` 后读取精确 `bytes_read`；同一 body 在 query/history 中正常重复序列化仍算命中。确认 marker 后才可在进程内按上限解析 JSON/SSE，并仅输出白名单字段：固定 route、HTTP 状态、done/error 类别、marker 命中布尔值、批准的模型/config/reasoning 选择、usage 数值、schema key/type 和关联 ID hash。本轮 `body_eligible_flow=0`，所以没有读取 upload 或 response buffer，也没有检查 marker、model/config body 字段或 usage；它只说明 observed flow 没匹配本次 host/path/method gate，不能说明 GetLength/Read ABI 失效。没有输出或落盘 raw body/header、对话内容、`custom_model.ak`、token 或私钥。

静态复核确认会影响拦截器的 `UploadDataProvider_Read` 与 `UrlRequestCallback_OnResponseStarted` 共用 RVA；r2 对该地址只装一个 dispatcher，并用 request/provider/callback typed map 区分上下文。`Buffer_GetData` 与 `Provider_Close` 同址不单独 hook；只在已映射的 Cronet buffer 上调用公开 getter。其余 getter 也不作为拦截 hook。Cronet URL 表示客户端请求目标；即使识别 Trae gateway route，也不能仅凭 URL 或客户端 `model_name` 推断服务器内部 provider/model。

marker 只有在 request body 与 response JSON/SSE 的安全投影中实际命中时才记录布尔值；response marker 若没有 `role=assistant` 上下文，只能记为角色未确认或非 assistant 命中。当前 renderer/native 日志没有足够共同 ID；即便时间接近，也不单独用来关联 RPC 与网络 flow。本轮 r2 未达到 body gate，因此没有建立这类 marker 关联，也未取得 body/model/usage。

## 已确认的原生调用与数据结构

以下静态位置来自当前安装原件；offset 是文件字节偏移，哈希用于确认文件版本。

| 原件 | 证据 |
|---|---|
| `resources\app\out\vs\workbench\workbench.desktop.main.js`，SHA256 `6A6013B3FD12808D70C109684763EBEB299672F49EF703740AC86CC0D1633304` | offset 5426280 附近：`TransportManager` 从注入的 `modularManagerService.getAiAgentRpcClient()` 取得内部 client。普通请求用 `sendRequest("request", packet)`；流请求用 `sendStreamRequest("request_stream", packet, onData, onError, onComplete)`。packet 为 `{packet_type:"request", channel_id, session_id:payload.client_info.connect_session_id, params:payload}`；`request.service/method` 是 `params` 中的 route。流数据经 controller `write(data)`，`event===Done` 时完成；错误、断连和 timeout 另走错误回调。 |
| `resources\app\node_modules\@byted-icube\ai-modules-chat\dist\index.mjs`，SHA256 `7D198BAEDF880BBB36EEFB9AEB70AA6697B76F8C952D4D60DB1E30F609BCCC7E` | offset 7351561 附近的 API 映射把 `chat.sendMessage` 映射到 `{service:"lite",method:"send_message"}`，把 `chat.subscribe` 映射到 `{service:"lite",method:"subscribe_events"}`。offset 27308 的 `chat/send_message` 是更高层协议类型字符串；运行日志和 native RPC route 证明的 wire service/method 是 `lite.send_message`，二者不可混为一谈。 |
| `resources\app\node_modules\@byted-icube\solo-lite\dist\6645.b1c7b531.mjs`，SHA256 `37C247CE0A5B527AF5044AB8D24D6B27D332D8DE67E91CCFC1E072A7B1CA9C27` | offset 4397669 附近的 `buildSendMessageRequest` 构造 `chat_session_id`、空 `content`、JSON 字符串 `query`、`model_name`、`agent_type`、`agent_id`、`model_selection_strategy`、`custom_model`、`common_params`，以及可选 `force_new_turn`、`session_type`、`use_fast_request`、`origin`、`permission_profile_id`、`is_worktree`、`workspace_folders`。`getModelRequestSelection`（offset 4392887）从客户端模型选择生成 `modelName/customModel/modelSelectionStrategy`；`custom_model` 可包含 provider/config source/base_url/ak/prompt_max_tokens 等配置字段。它们是客户端发出的选择与配置，不是上游已选模型证明。此构造中 `query` 是序列化内容块，未使用 V1 的 `user_input`/`chat_history` 形态；`chat_type` 未见于该顶层对象，可能的 `common_params` 内容本轮不作推断。 |

同一 `solo-lite` 原件 offset 4390616 的 `subscribeStream` 调用 `chatApi.subscribe(sessionId, ..., reply_to_message_id?)`，把事件转给 `streamService`；事件对象被规范为 `{event: e.event || "message", data: e.data}`。事件枚举包含 `token_usage`、`context_usage`、`timing_events`、`model_config`、`done`、`error` 等。`append_input` handler 在 offset 4935333 读取 `user_message_id`、`message_contents`、`extra_chat_params.parsed_query`、`message_index`、`reply_to_message_id` 等字段。它说明 UI 有结构化会话事件桥；本次日志没有恢复实际 stream 事件内容，也没有确认这些事件的上游语义或 usage 值。`request`/`request_stream` 是本地传输类型，不是远端 provider HTTP 路由。

## 安装配置中的 host 与实际出站的区别

Trae 3.4.4 原件 `resources\app\product.json` 的 `bootConfig.agent.trae.normal`（约第 1694 行）配置 `https://trae-api-cn.mchost.guru`；`bootConfig.ckg/cue/hub/remote.trae.normal` 也含该 host。其他条目如 `bootConfig.iCube.normal`、`iCubeAgent.normal` 使用 `https://api.trae.com.cn`。因此 `mchost.guru` 确实存在于当前安装包配置，不能只归因于本地代理或旧 MarsCode 插件样本。

本地 V1 客户端 `trae2api/gateway.py:22,37` 的默认 host 同样是 `https://trae-api-cn.mchost.guru`，但会受 `TRAE2API_GATEWAY` 覆盖；`gateway.py:289-292` 实际 POST `/api/ide/v1/chat`。产品配置能证明应用内默认 URL，不能证明 08:34 的请求走了该 URL。当前连接快照也无法判断具体 path、HTTP/WS 协议或最终 provider。

## 当前 V1 代理与原生契约差异

以下代码结论来自本仓库静态审查；同伴用纯函数 sentinel 复核了两组输入，没有访问网络或读取凭据。

| 结论 | 源码证据与边界 |
|---|---|
| 已验证构造路径确实丢弃 system、developer 及工具说明 | `gateway.py:174-178` 把 tool declarations/tool_choice 转成 system turn，随后 `translate.py:191` 在 `drop_system=True` 下跳过 system。`translate.py:156-173` 处理 system/user/assistant/tool/function，没有 developer 分支。sentinel 结果中 system/developer/tool name/schema 均不存在于上游 body，`tool_choice` 也不是 body 字段。 |
| 请求模型与响应回显不是实际模型证据 | `gateway.py:230-235` 只有设置 `TRAE2API_MODEL` 或实验开关 `TRAE2API_PASSTHROUGH_MODEL=1` 才写 `model_name`；默认省略。`server.py:579` 将客户端传入的 `model` 原样放入响应，model catalog 本地名称也不证明上游接受。 |
| 控制参数没有映射 | `gateway.py:153-154` 的 builder 参数仅含 model/messages/session/tools/tool_choice，`server.py:454-456` 也只传这些；请求 body 构造处未见 `reasoning_effort`、`max_tokens`、`temperature`、`top_p` 映射。`server.py:346` 只是转发上游给出的 reasoning 内容。 |
| V1 session/history 与原生不同 | `gateway.py:166` 在没有传入 session 时生成 UUID，`:179` 截取最后 24 条历史，`:224` 生成新 message_id；服务端调用 `gateway.stream_chat` 不传 `session_id`，见 `server.py:454-456,475-477`。sentinel 的 30 条合成消息只保留 24 条，每次 build 新 session/message id。此处不把 `user_input` 与 history 的关系单独判为错误。 |
| Usage 回传不完整 | 普通 streaming 分支 `server.py:385-388` 忽略 `token_usage`；非流式路径见 `:491-496`。工具流路径每轮重置 usage (`:189`)，遇到已知客户端工具调用即结束而未先输出 usage (`:223-228`)，内部工具循环只保留最后一轮 (`:229-234`)。因此本地响应 usage 不能作为完整上游累计账单。 |

sentinel 验证还确认：默认 body keys 是 `user_input`、`session_id`、`chat_history`、`agent_type`、`scene_location`、`agent`、`message_content`、`message_id`；默认不含 `model_name` 或 `tool_choice`。这些是本地纯函数检查，不是对当前远端请求的实测。

### 可复跑的纯函数复核

以下命令使用合成 sentinel 输入，只构造并打印本地请求 body，不访问网络或读取凭据。该命令由源码审查者提供，本轮未重跑：

```powershell
@'
import json, os, sys, types
from unittest.mock import patch
auth_stub = types.ModuleType("trae2api.auth")
auth_stub.TraeAuth = object
sys.modules["trae2api.auth"] = auth_stub
from trae2api.gateway import TraeGateway
messages = [
    {"role": "system", "content": "SENTINEL_SYSTEM"},
    {"role": "developer", "content": "SENTINEL_DEVELOPER"},
    {"role": "user", "content": "SENTINEL_USER"},
]
tools = [{"type": "function", "function": {"name": "sentinel_tool", "description": "SENTINEL_TOOL_DESC", "parameters": {"type": "object", "properties": {"arg": {"type": "string"}}}}}]
with patch.dict(os.environ, {"TRAE2API_MODEL": "", "TRAE2API_PASSTHROUGH_MODEL": "0", "TRAE2API_FORCE_CHAT": "0"}):
    body = TraeGateway.build_chat_body("sentinel-model", messages, session_id="SENTINEL_SESSION", tools=tools, tool_choice="required")
s = json.dumps(body, ensure_ascii=False)
print(json.dumps({"keys": list(body), "user_input": body.get("user_input"), "history": body.get("chat_history"), "message_content": body.get("message_content"), "contains_system_sentinel": "SENTINEL_SYSTEM" in s, "contains_developer_sentinel": "SENTINEL_DEVELOPER" in s, "contains_tool_name": "sentinel_tool" in s, "contains_tool_schema": "SENTINEL_TOOL_DESC" in s, "model_name_present": "model_name" in body, "tool_choice_present": "tool_choice" in body}, ensure_ascii=False))
'@ | python -
```

源码审查者报告的结果摘要：body keys 为 `user_input`、`session_id`、`chat_history`、`agent_type`、`scene_location`、`agent`、`message_content`、`message_id`；`user_input` 为 `SENTINEL_USER`；system/developer/tool name/schema sentinel 均未出现，`model_name` 与 `tool_choice` 均不存在。另一组 30 条合成消息结果为仅保留 24 条（`TURN_06` 至 `TURN_29`），每次构造生成新的 session/message id，传入 model 未用作 route。审查者的解释器直接导入时因缺少 `cryptography` 依赖而受阻；命令用内存中的 `trae2api.auth.TraeAuth = object` 类型 stub 绕过该导入依赖，原因是 body builder 不使用 auth。这只说明该复核解释器的依赖情况，不表示当前运行代理缺少依赖。

## 对 HANDOFF 结论的修正

1. `chat_service.chat` 来自 Rust DLL 内部日志字符串；当前 renderer runtime route 与安装 JS 映射是 `lite.send_message`。不要将 Rust 函数/日志名当作 renderer wire method。
2. `agent-code-toolhost-*` 是 toolhost/工具执行方向；本轮未碰 pipe。它不提供已证实的 chat RPC 入口。
3. sidecar `process-type=ai` 无自身 TCP socket，不等于 Trae 没有出站请求；当前 `ai-server` 和 Chromium NetworkService 都有 TCP 连接。仍未把任何一条连接映射到本次 chat。
4. DLL 含 `/ws`、`/api/v1/:service/:method`、provider path 字符串，只能证明二进制字符串/代码存在，不能证明本次运行选择了这些 transport/provider。
5. `trae-api-cn.mchost.guru` 既是本地代理默认值，也是当前 Trae 安装包 `bootConfig.agent.trae.normal` 配置值；R1 与本次 r2 都观测到该 host 的实际 Cronet 请求。尚不清楚其中哪条属于特定测试会话，也没有证明最终服务器内部 provider/model。
6. 模型自述、请求字符数与返回 token 数、OpenAI SDK 的 model 回显都不证明实际模型或计费；本轮也不以这些作为结论。

## 下一阶段观测与验收标准

下一步应沿一次正常 UI 会话建立可关联的结构化证据，不向未知接口发送请求、不连 pipe：

1. 记录 `create_chat_session`、`lite.send_message` 和持续 `lite.subscribe_events` 的时间与散列后的 session/message 关联标识；本轮日志尚未暴露可安全关联的 session ID。
2. 从该订阅事件中确认是否返回 `model_config`，并读取 `model_name`、`config_name`、reasoning 与模型选择策略。客户端选择值必须和 native/server 接收值分开记录。
3. 找到同一会话对应的上游 request 记录，确认实际 host/path/protocol 和请求状态；不能用 `product.json` 配置或时间邻近的长连接代替。
4. 找到同一会话的 `done/error`、远端响应与 token usage，说明 usage 是本轮、工具轮次还是累计值。

只有这四段能用同一关联 ID/时间链闭合，才可以宣称已走通正常远端模型链路。若现有官方日志不提供上游关联信息，下一步应先确定受支持的 native tracing/日志开关；当前没有活动的 CDP/Inspector listener，也没有可从外部直接调用的 chat API。对 renderer instrumentation 或安装文件 patch 的选择留到单独评审，本轮没有进行。

## r2 实际观测摘要（2026-10-26）

使用本机已有的 `E:\tools\frida\venv\Scripts\python.exe`（Frida 17.24.0）运行 observer；系统默认 `python` 不含 Frida，首个启动在 import 阶段退出，未 attach。显式选用该 venv 后，driver 在 attach 前复核 PID 创建时间与安装 DLL SHA256，并只 attach NetworkService PID 76788。2026-10-26 01:55:18 UTC（北京时间 09:55:18）ready，预计 02:00:18 UTC 自动结束；11 个 hooks 安装成功，`sscronet.dll` 路径匹配，`body_api_ready=true`，没有缺失项。observer 自动 timeout，脚本 unload、session detach 成功，PID 创建时间复核仍一致，记录 `observer_detached`。没有重启、暂停或终止 Trae，也没有重复 attach。

观察窗口内有 13 个 Cronet route metadata flow：`trae-api-cn.mchost.guru:443` 有 5 个 POST、1 个 GET；`api.trae.cn:443` 有 4 个 POST；`api.trae.com.cn:443` 有 3 个 GET。按 flow 计，10 个 response-start/completion 为 200，2 个为 304，另 1 个请求被取消。13 个 flow 都没有命中 r2 的 17 项固定 route token 白名单，因此 route_token/path 未输出；无法确认其中是否有 V3 路由，也不能据时间或 host 将某个 flow 归到测试消息。

最终 coverage 为 `provider_bound=6`，`body_eligible_flow=0`、`get_length=0`、`typed_read=0`、`sink_ack=0`、marker matched/rejected=0、`response_read=0`、`response_projection=0`，固定 skip reason 全为 0。这里的零值表示本轮没有 flow 命中 host/path/method body gate；observer 没读取请求或响应 buffer，也没有检查 R2 marker、model/config body 字段、done/error 或 usage。它不等于“没有 LLM 请求”，也不证明 Cronet ABI 失败。

已知的 Trae 活动日志文件没有覆盖 09:55:18–10:00:18 北京时间这一窗口的新写入：`window3\renderer.log` 最后写入时间为 09:02:48，`aha_electron_2026.1026.log` 为 09:00:01，`main.log` 为 08:35:51，`dynamicConfig.log` 为 08:39:22，ai-agent stdout/stderr 仍为空且没有新写入。因此窗口内没有可提取的 renderer/native service/method、model/config 或 R2 marker 布尔事件。该日志缺口不能证明用户没有发测试；r2 网络 metadata 本身也没有正文 marker 字段。唯一新 R2 marker 测试尚未获用户确认，是否触发及 UI 回复仍未知。

本轮结论仅为：NetworkService 在此窗口确实访问了上述 host，Cronet API metadata hooks 工作并记录了 route flow；没有任何 flow进入固定 route/body gate，因而没有建立 R2 测试请求、响应事件与模型配置的内容级关联。R1 中已观测到 mchost `/api/agent/v3/*` 形状请求，但精确 suffix 仍未从动态路径验证；17 项 suffix 仅是静态候选。R1/R2 host 观测都不单独证明某个测试会话或最终服务器内部 provider/model。

### 本地 observer 验证记录

以下为当时用于本地静态/模拟验证的命令；模拟不 attach、不触网，也不读取运行会话数据：

```powershell
node --check logs/route_observer_20261026_r2/observer_r2.js
node --check logs/route_observer_20261026_r2/simulate_r2.js
node logs/route_observer_20261026_r2/simulate_r2.js
python -m py_compile logs/route_observer_20261026_r2/observer_r2.py
```

JS 语法检查与 Python 编译检查通过；模拟覆盖 19 项：route allowlist、marker 指令/重复 history、response projection、echo role 边界、coverage summary、marker gate 前 response race、wrong sink、超限、异步 sink mapping、乱序快照、terminal flow capture、rewind、provider 复用、共享 callback 并发请求、request pointer collision cleanup、活跃 flow 上限、有界 SSE、无 secret 输出、SHA256。另有 Python sanitizer 本地自检覆盖：模型/config 只接受本次指定的 DeepSeek v4.1 Flash canonical 值、reasoning 枚举限制、dotted key 逐段白名单、受限未知 top-level schema key 与常见 secret key 排除、marker role 状态分类，以及 ready 时间窗字段。上述模拟/自检通过只证明 observer 的本地过滤与关联逻辑，不证明运行时有可观测业务 flow；本轮 body gate 未打开。

## V2 单次受控假设诊断（2026-10-26 02:54 UTC）

使用 ignored harness `logs/native_v2_probe_20261026/v2_probe.py`，从 `D:\workspace\trae2api` 通过 `D:\Users\marcus\anaconda3\python.exe` 执行。端点固定为 `POST https://trae-api-cn.mchost.guru/api/ide/v2/llm_raw_chat`。body 是一次诊断假设：`config_name`、`model_name`、`user_selected_model_name` 使用原生 ModelSelect 日志中见到的 `deepseek-v4.1-flash`，并发送随机 session、单条短合成 user message、空 tools、`tool_choice=none`、`stream=false`。其中 `messages` 的 OpenAI 形状仍未由活动调用证明；builder 的静态允许字段列表不等同于服务端必填 schema。

诊断进程设置 `TRAE2API_ALLOW_ROTATION=0`、`TRAE2API_TRACE=off`，在读取本地认证配置前即把 `refresh_jwt` 设为 fail-closed，并要求现有 JWT 剩余有效期超过一小时；无效时会在发请求前停止。请求预算为一次，固定 TLS transport 选择、无重试或 redirect、45 秒总 timeout、2 MiB 响应上限。只输出净化字段，不保存/打印认证头、body、错误原文或会话内容。

本次已使用唯一 POST 预算，结果为 HTTP 400、content type 类别 `other`、观察到的响应字节数为 0；退出码为 1。净化结果没有 schema、模型字段、marker、usage 或可提取 numeric API error code，`protocol_state=json_unverified_output_unconfirmed`，`error_category=http_4xx`。这只说明这一份假设请求未获得可解析的成功响应；响应内容不足以区分请求 shape、model/config、服务端业务拒绝、认证之外的入口行为或传输差异。没有自动重试、换模型或改 body；不能将此结果写成已验证 V2 契约或已走通 LLM。

该 harness 的本地编译检查和 14 项合成模拟通过，并由同伴用指定 Anaconda 解释器复跑通过。覆盖固定 body、刷新 fail-closed、模型/usage/schema 过滤、marker role 确认、错误文本/secret 不输出、单次请求预算、超时/redirect 参数、响应 cap、httpx `aiter_bytes` 与 curl `aiter_content` 兼容，以及 HTTP 200 业务错误和无 assistant marker 状态。模拟不访问网络或读取凭据。本次执行的 `finally` 调用了 gateway 与 auth client cleanup；cleanup 异常会被吞掉，因此不能据净化输出单独证明每个 close 调用均成功。进程已退出。

运行前后 `git status --short` 相同：只有 `NATIVE_PROTOCOL_CONTRACT_2026-10-26.md`、`NEXT_STAGE_EXECUTION_PLAN_2026-10-26.md`、本报告三份未跟踪文档；业务源码、8080 服务、Trae 进程和系统/证书/代理设置均未改动。

## 后续只读 HTTP 控制诊断（2026-10-26）

### SDK ping transport 对照

按已核实的 SDK `Ping` builder，各执行一次无参 GET `/api/ide/v1/ping`：`curl_cffi_chrome124` 与 `httpx_default` 均收到 HTTP 200、JSON content type 和 HTTP/1.1；两次合计预算为 2，退出码为 0。harness 在 32 KiB 上限内读取响应，仅尝试提取白名单 numeric API error code；未检测到数值错误码，未输出或落盘任何正文内容。该结果只证明两种客户端栈对这个 ping endpoint 收到 200/JSON，不证明 ping payload 语义，也不证明 V2 请求的 JWT 权限或 body 契约。

### SDK model_list 单次查询

按已核实的 SDK `ModelList` 无参 GET `/api/ide/v1/model_list`，在 `curl_cffi_chrome124` 上执行一次，未携带 body/query，得到 HTTP 400、JSON content type 和 numeric API error code 4001。净化投影没有识别到 `deepseek-v4.1-flash` 的明确模型字段；schema 仅留下两个 `$.*` 类型项，字段名被路径过滤器折叠。未写盘或输出错误 Message、其他模型名、账号信息或 `encrypted_model_params` 值。

该结果不能证明目标模型不可用，也不能区分 model_list 请求参数、权限或其他服务端条件；不据此尝试 `type` 变体、GetDetail、换 host 或重复请求。Ping/model_list 都是非 LLM 控制请求，不能替代原生会话请求或证明 V2 JWT 权限。两次 harness 均在 finally 中调用 client cleanup；关闭异常被吞掉，记录只确认清理路径执行且进程退出。

## 非轮换 JWT 路径单次诊断

使用 ignored harness `logs/jwt_mint_v2_control_20261026/mint_then_v2.py`，从仓库目录通过 `D:\Users\marcus\anaconda3\python.exe` 执行 `--execute-once`。来源类别为 `live_storage`；配置 host 通过 HTTPS host allowlist，cloudide expiry 可解析且超过一小时，预检标记为未过期。只执行一次当前配置 host 上的 `POST /api/v2/GetUserToken`，请求预算使用 1；收到 HTTP 404、content type 类别 `other`，分类为 `http_4xx`。未重试、未调用 ExchangeToken、未更换 host/body，也没有继续调用 V2；V2 结果为 `request_attempted=false, skip_reason=mint_failed`。本轮 HTTP 总预算使用 1/2。

返回的 `valid_before=true` 与 `valid_after=true` 仅表示内存中现存 JWT 的过期时间检查通过。mint 失败时，auth 对象仍持有原有 JWT，因此 `jwt_present_after=true` 不表示拿到了新 token；`jwt_alias_before=true`、`new_equals_old=null` 也不能用于判断新旧 token 差异。该 404 只说明此次固定 endpoint 调用未成功，不证明旧 token 无效、登录失效或原因所在；本地 exp 检查不验证签名或上游权限。

finally 结果为 `default_auth_client_closed=true`、`mint_client_closed=true`、`v2_session_closed=true`、`v2_inner_client_closed=true`、`cleanup_complete=true`。本轮没有追加请求；代理业务源码和 8080 服务未改动。R3 observer 未 attach，native 测试是否已触发仍待确认。

## Mint 404 的认证 host 补充（本地只读）

为补足原始净化输出未记录 host 的缺口，之后用同一 Anaconda Python 对 `TraeAuth` 做了一次本地只读加载。加载前在子进程内将 refresh、GetUserToken 自动路径、refresh-token exchange、签名与 save 设为 fail-closed；仅调用 `auth.load()`，不调用 `get_jwt`、`refresh_jwt`、任何 HTTP 方法或 `save`，最后清除内存私钥引用并关闭本地 client。安全输出为 `{"credential_source":"live_storage","auth_host":"api_trae_cn","load_status":"loaded","client_closed":true}`；未输出 URL、token、账户信息或日期。

该只读快照与前次 mint 运行报告的 `credential_source=live_storage` 一致，当前配置 host 被严格枚举为 `https://api.trae.cn` 对应的 `api_trae_cn`。因此可将当时的 404 诊断补充标注为配置在 `api.trae.cn` 的 GetUserToken 路径。原始网络输出未在事务级记录 host，故这属于同来源的事后本地配置佐证，而非从网络事件本身读取的 host；404 仍不说明旧 JWT 无效或登录状态失效。没有重发任何请求。

## R3 metadata-only 原生观察（2026-10-26）

为寻找背景原生认证/LLM路由，本轮使用独立 ignored observer `logs/route_observer_20261026_meta90/`，不是会话正文配对版 R3。Frida venv 预检通过：PID 76788 创建时间 `2026-10-25 23:54:19 UTC` 匹配，`sscronet.dll` 路径匹配且磁盘 SHA256 匹配已审值，解释器匹配。只安装两个 hooks：`Cronet_UrlRequest_InitWithParams`、`Cronet_UrlRequest_Start`；公开 `Params_http_method_get` 只用于读取 typed Params 的 method，不挂 hook。没有 provider getter、upload/read、response/body API。JS 将 `body_api_ready` 和每个 route 的 `body_eligible` 固定为 false；URL 字符串只在内存读到 `?`/`#` 前，输出限于三个已知 HTTPS host 的 method、path SHA256、静态 route 分类/词或动态段哈希，不输出 raw URL/query/header/body。

observer 进入 readiness 后等待设定的 90 秒并触发 timeout；最终 `script_unloaded`、`session_detached`、`observer_detached` 均记录成功，detach 后 PID 创建时间仍匹配，目标进程存活。coverage 全为零：`init_calls=0`、`known_https_candidates=0`、`started_metadata=0`，没有任何 host/path hash 或 request 事件。它只说明该 NetworkService PID 在窗口内没有经过这两个 Cronet lifecycle hook 的可见调用；不证明没有 Trae 网络请求、其他进程请求或其他 transport。

**记录投影限制：**原始 metadata 行中的 `hook_install` 明确 `hook_count=2`、仅上述 hooks、`body_api_ready=false`。但 Python driver 的 `observer_ready.body_eligible` sanitizer 有布尔反转 bug，把输入的 false 显示成了 true。原始 JSONL 保留以便审计；观测器 JS 未包含或调用任何 body/upload/read API，也没有 route 事件。该误标不是 body gate 被打开的证据。观察后已修正 sanitizer 并通过 Frida venv 本地 6-case self-test；没有再次 attach。

本地验证：`node --check observer_meta90.js` 通过；`simulate_meta90.js` 的 10 个合成 URL cases 通过（query 不影响 hash、动态段只输出哈希、未知 host/非 HTTPS/非443/userinfo 被排除、输出无 raw 路径）；Frida venv Python `py_compile` 与 `--self-test`（6 cases）通过。代理业务源码、Trae、8080及系统代理配置未改动；原配对消息 R3 未 attach。

### CN 客户端认证供给链的静态补充

安装原件静态审查显示，普通 CN 登录路径使用 `TraeLoginService.exchangeTokenByAuthCode` 调用 `POST /trae/api/v3/oauth/ExchangeToken`；响应中的 `Token` 经 `v9` 映射到 `userInfo.token`。CN normal account host 来自 `product.json` 的 `bootConfig.account.trae.normal`，值为 `https://api.trae.cn`。workbench renderer 通过 `GET_USER_INFO` 主进程 IPC 获取 user info，`ICubeChatCommonSession.getUserInfoWithToken` 将 `userInfo.token` 放入 native RPC `params.user_info.token`。这证明 token 到达 native RPC 参数，不证明 ai-agent 后续 HTTP 如何使用它。

SDK `ai-modules-chat` 的 service factory 接受 `jwt` prop，request wrapper 将它写入 `Authorization: Cloud-IDE-JWT ...`。静态检查尚未找到普通 CN `userInfo.token` 接入该 SDK `jwt` prop 的 caller。`GenerateTempToken` 位于 `/cloudide/api/v3/trae/GenerateTempToken`，由 Marscode provider/特性开关路径管理并写入独立 `trae-jwt-token` 文件；该文件进入 Copilot SDK/native RPC 的接线未证实，且默认功能开关关闭。`GetUserToken` 出现在旧 Bytedance USDS `convertTokenToUserInfoOld` 分支，静态结果称普通 CN 登录不走该方法。

因此，本地代理一次 `api.trae.cn` GetUserToken 诊断收到的 HTTP 404 仅证明该次固定 legacy-path 假设未成功；它不证明普通 CN 登录失败、旧 JWT 无效或真实原生 host/token 传递链失败。由于原始网络事件未直接记录认证来源、且静态调用路径不是同一事务证据，不能把静态差异当作 404 的确定原因。下一步应优先闭合 native RPC `user_info.token` 到活动 AgentV3/AI request 的认证映射，当前 metadata-only窗口没有提供这条证据。

## R4 配对观察执行尝试（未启动）

2026-10-26T06:28:10Z 的现场只读预检中，NetworkService PID 76788 仍在根 PID 48180 下运行，subtype 为 `network.mojom.NetworkService`，创建时间与已审目标一致；实际模块列表含安装根目录 `sscronet.dll` 和 `aha_net.dll`，`sscronet.dll` SHA-256 匹配既有审值。对应 `main.log` 创建时间为 `2026-10-25T23:54:20.705Z`，renderer log 存在，R4 输出文件尚不存在；解释器为 `E:\tools\frida\venv\Scripts\python.exe` / Frida 17.24.0。

R4 已由 `proxy_contract_audit` 独立复审，JS/Python 模拟各 23 项通过，但 UI owner 无法可靠定位 Trae 模型/输入控件：窗口截图多次超时，accessibility tree 未提供可识别输入区。没有触发 `observer_ready`，因此未 attach、未开始 120 秒观察、未发 `只回复 TRAE_ROUTE_R4_OK`、未产生 R4 网络 metadata。不能从这次 UI 失败推断任何模型路由或业务请求状态。执行器和方案见 `notes/REVERSE_DYNAMIC_CAPTURE_PLAN_2026-10-26.md`；R4 等待 UI 可可靠操作后再启动一次。

用户之后表示可手工配合，但 2026-10-26T13:40:33Z 现场重新枚举发现 Trae 已重启。新根 PID 为 196288，唯一同安装目录且 subtype 匹配的 NetworkService 为 PID 103824，已加载 `sscronet.dll` 与 `aha_net.dll`；当前 `sscronet.dll` SHA-256 为 `288F987E64107A603CAE0E04D3282935B4017DC1C042EA579334DA49984FB79A`。A 静态复核确认 R4 目标导出名称仍存在于 `.text`、Read/OnResponseStarted alias 仍共享 RVA，但仅证明导出形状和别名；当前 DLL 的函数运行时 ABI/调用路径仍未验证。13:41:16Z 元数据复查确认新日志 session `20261026T213651` 的 `main.log` 创建于 13:36:51.862Z，但当时 `window3\renderer.log` 尚未出现；旧 renderer session 的创建时间不匹配新 NetworkService 启动时间。随后只更新 R4 PID/创建时间/module hash 身份常量，门控不变，等待 C 复核及新 renderer log；未 arm/attach、未发送测试消息、没有 R4 网络数据。

C 已复核新身份常量与 JS PID/path 一致，导出名解析和共享 alias gate 可复用，JS/Python 编译及 23+23 本地模拟通过；但新安装没有同版本 generated IDL/header，不能据导出存在断言该 build 的 ABI 同版确认。新日志 session 的 `window3\renderer.log` 在 13:48:49Z 仍未出现，故当前尚无可运行的配对 tailer。是否先补新 DLL 同版 ABI 静态证据、以及新 AI/workbench 静态 route 是否需要复核，待主 agent 裁定；本报告不把新身份常量更新误写成运行时兼容性验证。
