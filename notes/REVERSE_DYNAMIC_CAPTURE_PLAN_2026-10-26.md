# Trae CN 原生会话与网络配对观察准备

日期：2026-10-26

## 本轮状态

本文件与 `logs/paired_observer_20261026_r4/` 是本阶段新增产物。R4 已完成独立审查和本地模拟。2026-10-26T06:28:10Z 重新核对进程、模块、日志目录创建时间和输出路径后，UI owner 尝试确认目标窗口，但 screenshot capture 超时且无可识别输入控件；没有发测试消息。因此本轮没有 attach、发远端请求、读取凭据或对话日志内容，也没有改 Trae 安装文件、代理业务源码或运行中的服务。R4 observer 未启动，等待 UI 可可靠操作后再执行一次。

之后用户已表示可手工配合，但 2026-10-26T13:40:33Z 重新枚举发现 Trae 已重启：根 PID 为 196288，唯一匹配的 Chromium NetworkService 为 PID 103824，创建于 13:36:51Z。它加载同安装根目录的 `sscronet.dll`/`aha_net.dll`，当前 `sscronet.dll` SHA-256 为 `288F987E64107A603CAE0E04D3282935B4017DC1C042EA579334DA49984FB79A`。A 的静态复核确认 DLL 为 9,094,032 B、x64 PE32+、1127 named exports，R4 目标导出名仍在 `.text`，`Read` 与 `OnResponseStarted` 仍共享 RVA `0x2E6D0`；R4 按导出名动态解析。C 又确认新 `ai_agent.dll`/`harness.dll` 仍含这三条候选路由字面量，但这只证明字符串存在，不证明活跃调用。上述结果不构成新 DLL 函数运行时 ABI/调用路径验证。13:41:16Z 新 session `20261026T213651` 的 `main.log` 创建于 13:36:51.862Z，但 `window3\renderer.log` 尚未出现。根据授权，我只更新了 R4 PID/创建时间/module hash 身份常量，所有内容门控保持不变。C 已独立复核常量和导出名路径一致、旧 hash 会 fail closed、shared dispatcher 仍覆盖 alias，JS/Python 编译及 23+23 本地模拟通过；但当前安装没有同版本 generated IDL/header，不能称新 build ABI 已同版确认。R4 仍未 arm/attach；新 renderer log 未生成，是否要求额外同版 ABI corroboration 等主 agent裁定。

## 新鲜运行基线

进程快照时间为 `2026-10-26T05:07:59Z`，即北京时间 13:07:59：

| 角色 | PID | 创建时间 UTC | 父进程 | 交叉证据 |
|---|---:|---|---:|---|
| Trae 主进程 | 48180 | 2026-10-25T23:54:16Z | 19780 | `Trae CN.exe` |
| Chromium NetworkService | 76788 | 2026-10-25T23:54:19Z | 48180 | `network.mojom.NetworkService`，加载安装根目录 `sscronet.dll`、`aha_net.dll` |
| NativeExtensionService | 230596 | 2026-10-25T23:54:21Z | 48180 | `basil.mojom.NativeExtensionService`，加载 `resources\app\modules\ai-agent\ai_agent.dll` |
| BDMSSDKService | 74056 | 2026-10-25T23:54:19Z | 48180 | 也加载安装根目录 `sscronet.dll`，但本轮不纳入 attach 范围 |
| Renderer | 173544、52464 | 2026-10-25T23:54:21Z、23:58:13Z | 48180 | 两个 renderer 仍在进程树中 |

与以往快照相比，本轮重新按进程名、父子关系、utility subtype、创建时间和模块路径核验；运行器仍会在每次运行前复核 PID 创建时间及 `sscronet.dll` SHA-256，不匹配即停止。旧 PID 不被当作当前身份的充分证据。

活动日志目录为 `C:\Users\marcus\AppData\Roaming\Trae CN\logs\20261026T075419`。2026-10-26T05:08:11Z 只读取了目录项元数据：

| 文件 | 大小 | 最后写入 UTC |
|---|---:|---|
| `main.log` | 648,082 B | 05:04:22 |
| `dynamicConfig.log` | 38,939 B | 05:04:22 |
| `window3\renderer.log` | 6,330,923 B | 05:04:15 |
| `window3\exthost\trae.ai-code-completion\Trae AI Code Client.log` | 27,809 B | 05:02:23 |
| `Modular\ai_agent-0-2026-10-25.alaudalog` | 8,391,346 B | 04:09:32 |

基线未读取日志内容。`main.log` 创建时间 `2026-10-25T23:54:20.705Z` 与目标 NetworkService 创建时间 `23:54:19Z` 相差不到 2 秒。R4 现在按这两个创建时间在 120 秒容差内选择 renderer session，而不要求长期运行且空闲的 Trae 持续写 `main.log`。如果有多个 session 候选，选择时间差最近者；这是启动时间的关联启发式，不作为同一聊天/请求的关联证据。tailer 仍只在开始时记当前 `window3\renderer.log` 字节长度，之后读取追加数据；文件轮换、截断、session 关联失败或超过读取预算时 fail closed。

现场预检时间 `2026-10-26T06:28:10Z`：根 PID 48180 仍存活，NetworkService PID 76788 仍是其子进程且 subtype 为 `network.mojom.NetworkService`；创建时间仍匹配 `2026-10-25T23:54:19Z`。该进程已加载 `sscronet.dll` 与 `aha_net.dll`，安装根目录 `sscronet.dll` SHA-256 与已审值匹配；renderer log 存在，`metadata.jsonl` 输出路径不存在。Frida venv 解析为 17.24.0。UI owner 未能可靠识别可发送的模型/输入控件，故不满足触发门槛，未启动观察窗口。

## 已知客户端调用链和关联边界

静态证据来自 `notes/NATIVE_PROTOCOL_CONTRACT_2026-10-26.md` 和 `notes/REAL_PATH_REVIEW_2026-10-26.md`：

1. 当前被观测的 Solo Lite UI 调用 SDK adapter 的 `chat.sendMessage`；adapter 发给 renderer/native RPC 的方法是 `lite.send_message`。同一条会话用 `lite.subscribe_events` 订阅。Workbench `TransportManager` 通过 `getAiAgentRpcClient()` 发送 `request`/`request_stream`，外层 packet 的 `channel_id`、connection `session_id`、`params` 是不同字段层级。
2. Solo Lite request builder 将当前轮序列化为 `query`，并带 `chat_session_id`、客户端 `model_name`、`agent_type`、`agent_id`、`model_selection_strategy`、`custom_model`、`common_params` 等。客户端发出的 model/config 是选择值，不证明上游接受。
3. `send_message` 返回若含 `data.message_id`，客户端用它与 session 一起启动持续订阅；静态事件枚举含 `model_config`、`token_usage`、`context_usage`、`timing_events`、`done`、`error`。订阅是持续事件流，不要求按普通请求等待一次性 success。
4. 过去日志的 TransportManager 记录能区分 service/method 和结果类别，但不保证记录 payload 里的 `chat_session_id`/`message_id`，也不保证记录订阅事件 payload。因此 R4 tailer 只安全提取已知 RPC/event 枚举、已知 ID 的 SHA-256、目标模型白名单值与 marker 布尔；它不会从日志恢复任意文本或完整对象。
5. `ai_agent.dll` 中的 AgentV3 route 字符串池与 `/api/ide/v2/llm_raw_chat` 被静态 xref 指向不同函数簇。新增 `notes/REVERSE_NATIVE_CALL_CHAIN_2026-10-26.md` 还确认 `Request`/`UserInfo` serde schema、静态 endpoint-array 构造器与 WinHTTP 实现簇，但没有 `LiteHandler.send_message` 到 AgentV3/V2/LLMAdapter/WinHTTP 的已证调用边，也未证明 `user_info.token` 如何流入 outbound auth。因此它们是两个独立活动候选，不可说成已闭合路径。R1 曾见 `trae-api-cn.mchost.guru` 的 `/api/agent/v3/*` 请求形状，但没有唯一 session/message 关联或 suffix 明文。静态路线、同一 host、请求时间邻近均不构成同一 turn 的证据。

renderer 日志存在足够结构时，可用哈希后的 session/message/channel ID 对照。若没有共同字段，本轮只能通过“一个新 Solo Lite session、一次固定 marker 消息、network upload 的同一 marker 命中”建立受限的逻辑关联；这不等于跨层共享 ID，也不能替代任一缺失的 RPC/event 记录。即使响应侧看到 marker，也须确认 `role=assistant` 或明确事件类别；单纯响应字段 echo 不能称为模型回复。

## R3 与 meta90 边界复核

- R3 的 Cronet typed provenance、`bytes_read`、buffer capacity、异步 sink 映射、marker gate、请求/响应 chunk cap 和流终态清理仍可复用；它只在同一 Cronet request flow 上传 marker 通过后读取响应。
- R3 `parseRouteUrl()` 曾将任意 AgentV3 后缀设为 `body_eligible`，仅排除已知 non-chat 集合；未知后缀也会先进入 body marker scan。R4 收紧为精确 endpoint 路径，并由 Python sanitizer 再用 path hash 复核，不匹配时只保留路径/段 SHA-256 元数据。
- R3 driver 没有总 event 数与输出文件体积硬上限；R4 加了 120 秒窗口、4096 event、1 MiB metadata file、4 KiB output line、renderer 增量读取 2 MiB/4096 lines/64 KiB line，以及保留 detach 状态输出的预算空间。
- 先前 meta90 是另一轮仅装 `InitWithParams` 和 `Start` 两个 hook 的 URL metadata 观察；窗口里没有命中这两个 API，不能解释为没有网络请求。原始记录中的 `observer_ready.body_eligible` 被 Python sanitizer 反转，但 JS 只装了 metadata hooks，body API 根本没有加载。该 sanitizer 已做过本地修复，没有再次 attach。

## R4 观察目标与严格门控

隔离目录：`logs/paired_observer_20261026_r4/`。它复制 R3 到新路径，未修改 R1/R2/R3。R4 marker 为本轮全新 `TRAE_ROUTE_R4_OK`。

### NetworkService observer

运行时使用 `E:\tools\frida\venv\Scripts\python.exe`。只 attach 当前经 subtype、创建时间和 `sscronet.dll` 模块路径/SHA 校验的 `network.mojom.NetworkService`；不 attach 230596、74056 或其他进程。公开 Cronet ABI沿用已审固定版本 Chromium generated `cronet.idl_c.h`；该头文件声明 `Cronet_UrlRequest_InitWithParams` 返回 `Cronet_RESULT`，success 是 0（见该头第 580–586 行及 603–609 行）。此为标准公开 ABI 依据，observer 仍不会因 export 名而调用未知函数；对象不唯一、alias mapping 冲突、重试/rewind 或 typed buffer 关系不完整时跳过内容读取，不猜未知 native ABI，不读 headers。每次执行前若完整 body API hook group 未就绪，driver 在输出 `observer_ready` 前 fail closed/cleanup；不安排用户触发。

所有 route metadata 仅允许输出已知 host 的 host/port/method、固定 route family/静态 suffix 候选、完整 path hash 与未知段 hash；URL query/fragment 不读取、不输出。内容读取同时需要：

- HTTPS `trae-api-cn.mchost.guru:443`、POST；
- path 精确命中下列固定 endpoint，并通过 JS native-side exact-path gate；Python path-hash allowlist 在 Frida 输出后再次校验 route metadata，并只允许同一 flow 的 body-derived projection 继续进入输出；
- typed request/params/provider/sink/buffer provenance 唯一；真实 `bytes_read` 在 buffer capacity 以内，并通过逐 flow 与总量 cap。

body读取门由 Frida JS 在 native callback 内用原始 URL 的精确 path、host/scheme/port/method 和 typed `InitWithParams`/provider provenance 决定。Python 收到 route metadata 后独立重算 path hash；只有 `body_eligible=true` 的 flow ID 才能通过 Python 的 request/response/event projection 输出门。它不能撤销进程内已经发生的读取，因此不把 Python 层描述成 body-read gate。

精确 body 路由候选仅为：

| family | 精确路径 | 动态证据状态 |
|---|---|---|
| AgentV3 | `/api/agent/v3/create_agent_task` | 安装原件静态候选；未动态确认此 route 与当前 turn 的关系 |
| AgentV3 | `/api/agent/v3/llm_utils_chat` | 安装原件静态候选；未动态确认 |
| SDK/agent V2 | `/api/ide/v2/llm_raw_chat` | builder/DLL 静态候选；未确认 Solo Lite caller |

此白名单不包含未知尾段；候选 route 带任何附加 path segment 时不扫描 body。已知 dsl/generated_skill/workflow/control routes 和其他 V3 路径均只留下脱敏 metadata。其他 host 不读 body。静态候选的“精确”只表示 URL 字面路径精确匹配，不表示接口契约或执行语义已证。

只对上传 body 在内存里查找 marker。marker 可跨 upload chunk，并以同一 Cronet request 的内部 flow ID 关联；只有 marker gate 通过后，才允许投影该 flow 的 response JSON/SSE，响应 byte count 使用公开回调的准确 `bytes_read`。每个 upload ≤1 MiB、每个 response ≤2 MiB、全 observer ≤4 MiB。原始 buffer/chunk仅在进程内短暂使用并立即清理，不写盘或输出。

投影只允许固定字段名/类型、`deepseek-v4.1-flash` 的 model/config 选择、固定 reasoning enum、安全 session/message/task ID hash、有限 role/event enum、HTTP status、done/error 类别、usage 数值以及固定 marker 命中布尔。未知模型值省略；未知字段仅能输出受限名称/type，不输出其值。响应 marker 未能确认 assistant role 时标注 role 未确认，不当作回复命中。

### Renderer 增量观察

独立 `renderer_tail_r4.py` 通过 `main.log` 文件创建时间与目标 NetworkService 创建时间相差不超过 120 秒，选择对应 `window3\renderer.log`；它不依赖最后写入时间，所以空闲日志不会因为超过 15 分钟而误拒绝。若有多个 session 命中，按创建时间差最近者选择；这只帮助选当前运行日志目录，不证明某条 renderer event 与 Cronet flow 属于同一次请求。tailer 记开始时文件长度，从该偏移开始读取追加行。JSON/已知日志包装仅在内存里解析；每行 ≤64 KiB；只输出 `lite.create_chat_session`/`send_message`/`subscribe_events`、已知事件类别、安全 ID hash、目标模型是否匹配、usage 数值、done/error 固定类别和新 marker 布尔。未知/格式不明/超长行被计数并跳过，决不打印原始行、user text、response text 或错误消息。

这个 tailer 不是通用 logger decoder。若当前版本 renderer 日志没有结构化字段，覆盖计数会显示未解析/未投影；不再尝试未知 IPC、命名 pipe、CDP 注入或修改安装文件来补齐。

## 一次受控触发与执行次序

本次获批执行尝试未通过 UI readiness：UI owner 的窗口 capture 超时，accessibility tree 无可识别输入控件；未发送测试消息，observer 未启动。后续只有 UI owner 确认可可靠定位模型与输入区后，才重新走以下步骤：

1. 主 agent先核对当前 Trae PID 创建时间/subtype、NetworkService 模块路径与 `sscronet.dll` SHA、renderer session 的文件创建时间关联和 output path 不存在；任何 identity/session 检查失败则不 attach。
2. 指定 Frida venv 执行 observer。它安装 hooks 后只回报 ready、实际 hook 数、body API readiness、renderer baseline size、coverage 初值与 120 秒 deadline。ready 未确认前不发送 marker。
3. ready 后只触发一次新 Solo Lite session，模型选择保持 `deepseek-v4.1-flash`，用户消息为 `只回复 TRAE_ROUTE_R4_OK`。窗口内不发其它 chat、不换 model、不请求额外 API。
4. 优先等请求/响应在同一 flow 内到 terminal；terminal 后保留 3 秒 renderer tail 窗口再自动 cleanup。若 marker 未命中或没有 terminal，最多 120 秒后停止，不因未命中而自动重试。
5. `finally` 卸载 script 并 detach，记录每个 cleanup 状态和进程仍存活/创建时间一致性。event/file cap 触发时停止业务观察，但保留 cleanup 输出空间；cleanup 失败记 `cleanup_incomplete`，不伪报 detached。

## 本地验证结果

本地命令（只在合成 fixture 上运行；不 attach、不触网）：

```powershell
node --check logs/paired_observer_20261026_r4/observer_r4.js
node --check logs/paired_observer_20261026_r4/simulate_r4.js
node logs/paired_observer_20261026_r4/simulate_r4.js
& 'E:\tools\frida\venv\Scripts\python.exe' -m py_compile logs/paired_observer_20261026_r4/observer_r4.py logs/paired_observer_20261026_r4/renderer_tail_r4.py logs/paired_observer_20261026_r4/simulate_driver_r4.py
& 'E:\tools\frida\venv\Scripts\python.exe' logs/paired_observer_20261026_r4/simulate_driver_r4.py
```

JS 输出 `result=pass`，覆盖 23 个场景组：精确 V2/V3 path gate、未知后缀 metadata-only、query 不投影、R4 marker 跨 chunk、并发 flow 隔离、重复 history、响应 projection/echo role、marker gate 前响应 race、sink/长度/超限、异步/乱序映射、terminal、rewind、provider reuse、共享 callback、pointer collision、active flow cap、SSE、secret 不输出和 SHA-256。

Python 输出 `result=pass`，覆盖 23 个场景：精确 route/path hash sanitization、Python 同 flow path-hash projection gate、terminal 可早于异步 upload marker gate 到达且延迟 response projection 仍可输出并随后清理、未命中 marker 的终态 flow 清理、未知后缀 body 关闭、query/path raw 排除、host/scheme/method/non-chat 过滤、目标模型与 ID hash 安全投影、idle renderer log session 匹配且只读取 baseline 后追加数据、renderer marker 布尔与有限 usage/done 投影、不输出 raw text/secret、event/file/line cap、cleanup reserve、cleanup 状态成功/失败/空会话、output sink failure 与 cleanup failure 分类。

这只是本地过滤、预算、关联逻辑的模拟；没有验证 observer 对当前 DLL 的运行时行为或本次测试消息。`git status` 中本轮新增的唯一非忽略文件是本计划；R4 harness 目录受 `.gitignore` 的 `logs/` 规则忽略，不 commit。

## 待主 agent 安排与验收项

- 先由 C 对 `logs/paired_observer_20261026_r4/` 的路径 gate、Cronet ABI/对象映射、renderer session 匹配、Python 同 flow projection gate、输出预算与 detach 保留空间做独立静态 review；review 不 attach、不读真实日志。
- 只有 C review 通过且主 agent对目标进程身份与 UI 窗口准备就绪后，才由主 agent通知启动。启动后 ready 先回报，之后才安排一次 synthetic UI action。
- 验收需要同一 Cronet flow 的 route/marker/request projection/response terminal/response projection；model/config 必须是允许值；usage 若未出现明确 numeric path 就保持 unknown；role 不明确时不能把 marker 当 assistant reply。
- Renderer 能提供 session/message hash 时与网络投影比较；否则明确写“唯一 marker + 单次 UI action 的逻辑关联”，不可称为跨层同 ID 证明。
- 最终仍不推断 Trae 服务端内部 provider 或权重；目标仅为验证官方客户端的 native request→AgentV3/V2 HTTP→response 这一客户端可见契约。
