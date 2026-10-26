# Trae CN 调用链证据矩阵与阶段计划

日期：2026-10-26

## 目标与边界

目标是依据正常 Trae CN 客户端实际支持且经证据确认的远端 LLM 协议，让代理完成指定模型的普通文本 chat。`tools`/`tool_choice`、reasoning、stream、usage 与 cancel 分别设能力门；不得把一个能力通过扩大解释为其他能力已支持。当前目标不默认包括完整 Trae agent task、workspace/worktree 操作、工具审批 UI 或 agent 副作用。

本计划只安排只读静态审查、受审查的 metadata 观察准备与独立 harness review；本阶段不 attach、不读凭据、不发网络、不触发 UI 消息、不改业务源码、不 commit。任何现场触发由主 agent 安排和验收。静态符号、route 编号、时间邻近或同一 host 都不能单独证明调用关系。

## 调用链证据矩阵

| 步骤 | 静态已知 | 运行时已知 | 未知与闭合证据 |
|---|---|---|---|
| Solo Lite 建立 session | `solo-lite` request builder 接受并沿后续请求携带 session id；状态由客户端 session store 管理。 | 既有 renderer 日志出现过 `lite.create_chat_session` request → TransportManager success。 | 本地创建成功不等于远端 LLM 成功；服务端 session 持久化、过期/跨进程生命周期、此 ID 与远端 task ID 的对应关系未知。需要同一合成 turn 的稳定脱敏关联。 |
| 模型/config 选择 | Solo Lite `ModelSelect` 从 session、agent type、policy/store 产生 `model_name`、strategy、`custom_model` 等客户端选择。V2 builder 只将同名 model/config 字段复制进 body。 | 既有日志记录过客户端选择 `deepseek-v4.1-flash`；这不是服务端采用证明。 | 正常 caller 的输入、服务端接受/改写结果、`user_selected_model_name` 与 `model_name` 的区别未知。需同 turn model/config 事件或可信响应标识。 |
| 发送用户轮 | SDK adapter 将 `chat.sendMessage` 映射为 native RPC `lite.send_message`；Solo Lite builder 形成 session/query/agent/model 配置，而非 OpenAI `messages[]`。 | 先前会话记录过 `lite.send_message` 的本地 RPC 成功；该证据只到 RPC 层。 | 具体 query content-block schema、服务端如何并入历史、该 RPC 对应哪个远端请求和最终 LLM response 未知。 |
| 订阅与事件 | `chat.subscribe` 映射到 `lite.subscribe_events`，以 session/message 标识订阅；静态事件类型包括 message、plan、model_config、usage、done/error。 | 既有会话记录过 subscribe/send RPC；早先 Cronet flows 与指定 turn 没有稳定 ID 关联。 | 目标测试的事件顺序、实际模型、terminal/error 与 usage 语义尚未建立同一 turn 证据。 |
| Renderer → native RPC | Workbench `TransportManager` 通过 `getAiAgentRpcClient()` 发送 `request`/`request_stream` packet，含 `channel_id`、连接 `session_id` 与 `params`。 | 既有日志能确认部分本地 RPC request/success。 | RPC transport 成功不等于 native handler 已调用上游或返回有效模型结果；native method 内部执行需要静态 xref/dataflow 或经批准的关联证据。 |
| CN 登录 token → native params | 安装原件静态显示普通 CN ExchangeToken 响应 `Token` 进入 `userInfo.token`；renderer session 代码将其放入 native RPC `params.user_info.token`。 | 本轮 90 秒 metadata-only observer 未命中 URL hooks；没有现场验证 token 流。 | native handler 是否验证/转发/派生 token，以及它和任一 HTTP/Cronet Authorization 的关系未知；禁止读取 token 值。需要 DLL/handler 静态 dataflow，再由主 agent决定是否做非敏感身份关联观察。 |
| route 选择与认证构造 | SDK V2 builder 静态 POST `/api/ide/v2/llm_raw_chat`；Solo Lite 静态走 `lite.send_message` RPC；Agent DLL 有 `/api/agent/v3/...` 字串。`ai_agent.dll` 初步 xref 将 V3 route-suffix 字串表置于 RVA `0x676AE0A..0x676B0EC`，V2 literal `api/ide/v2/llm_raw_chat`（文件偏移 `0xA58CBC8`/RVA `0xA58E3C8`）由 endpoint-string-array/cache 构造簇 RVA `0x676B5AF..0x676C4FC` 引用；未见通向 LiteHandler、ModelService 或 LLMAdapter 的调用边。普通 CN `GetUserToken` 只找到 USDS 旧 caller；`GenerateTempToken` 写独立文件且未证流入 SDK。 | R1/R2 metadata 曾见到 `trae-api-cn.mchost.guru` 的 AgentV3 路径形状，但脱敏动态段未恢复；没有和指定测试唯一关联。 | `/api/ide/v2/llm_raw_chat` 活动 caller、AgentV3 路由/认证、RPC token 消费和上游 route 选择均未知。所述 RVA 是 `ai_agent.dll` SHA-256 `ACAED4D3C3B9B93D4654AED3D6DDAAC884F1ACC4C7E3A8FB283C37A9CE9C516B` 上的静态候选初报，不等于活动调用。不得按 V1/V2/V3 版本号推断同链或替代关系。 |
| transport 与 remote response | `sscronet` 存在公开 Cronet URL lifecycle API；V2 默认 SDK wrapper 用 fetch JSON，未见该 wrapper 的 SSE parser。 | 90 秒 observer 在复核 PID 76788 上只装 `InitWithParams`/`Start` 两 hooks，coverage 全 0，随后 unload/detach 成功。它没有看到任何 URL event。R4 配对 observer 已独立审查、JS/Python 离线模拟各 23 项通过；但 UI 预检未能可靠识别测试输入控件，观察器未启动/attach，固定 marker 未发送。 | 90 秒窗口不能排除其他进程/其他 transport；R4 未执行，不能称作 coverage=0。请求和响应 body、status、真实 provider/model、跨 chunk stream、上游取消及错误映射仍未知。需要主 agent在 UI 可可靠操作后重新安排固定合成 turn 与窄化观察。 |
| V1 代理路径 | 当前 `gateway.py` 的 V1 实际 POST `/api/ide/v1/chat`；translator 构造 `user_input`/`chat_history`，system/developer/tool_choice 已知会被丢弃或未映射。 | 历次代理本地纯函数验证确认序列化行为，不构成原生调用证据。 | V1 与 Solo Lite RPC/AgentV3 不等价；V2 的存在也不说明 V1 上下游关系。 |
| SDK V2 raw LLM | `LLMRawChatV2` builder 固定复制 `messages`、`tools`、`tool_choice`、reasoning 等字段并调用 `/api/ide/v2/llm_raw_chat`。 | 唯一假设 V2 POST 收到 HTTP 400/0 字节；mint→V2 诊断在 mint 404 后跳过 V2。均未建立成功响应契约。 | 活动 caller、字段 requiredness、message role/schema、model/config 接受、JWT 来源、response/usage/stream 语义未知。静态 builder 不等于生产契约。 |
| AgentV3 routes | DLL/JS 字串和脱敏字典包含候选路径片段。 | 多轮 metadata 窗口出现过 AgentV3 URL 形状；没有 session/RPC ID 将对应 flow 唯一绑定到指定测试。90 秒窗口则无事件。 | 这些路径属于何种 request、是否触发 LLM、如何认证及与 Solo Lite 的关系未知。不得把静态字符串或时间相近的 POST 当作聊天 route。 |

## 当前证据状态

- V1 `/api/ide/v1/chat` 是当前代理已实现路线，但和原生 session/RPC/事件流不是一条已证明等价链。
- SDK V2 `/api/ide/v2/llm_raw_chat` 静态存在；活动 caller 和成功契约未知。一次假设 POST 为 HTTP 400/0 字节；另一次 mint 404 后未发 V2。
- 普通 CN ExchangeToken → `userInfo.token` → native RPC `params.user_info.token` 有静态证据；native handler 对该字段的消费和向远端传递仍未证。
- AgentV3 请求形状在先前 metadata 运行中出现过，但未唯一关联到指定测试；R2 route 白名单 0 命中也不能推导没有聊天请求。
- 90 秒 metadata-only observer 不是与测试 turn 配对的 R3。它在指定 NetworkService PID 上 coverage 为 0；原始 hook metadata 显示仅两个 URL hooks、body gate 关闭。driver曾错误反转 readiness 的 `body_eligible` 布尔值，已修正并通过本地 sanitizer 自测；未再次 attach。
- R4 配对观察代码已通过独立审查，JS/Python 离线模拟各 23 项通过；现场 UI 预检未找到可可靠确认的模型/输入控件，因此未 arm/attach、未发 marker、未开始观察窗。当前仍没有与指定 UI turn 关联的 native route/response 证据；不要将“未执行”解释为“无请求”。
- 随后 Trae 重启，当前安装原件已换版。新版 root `sscronet.dll` SHA 为 `288F987E64107A603CAE0E04D3282935B4017DC1C042EA579334DA49984FB79A`；`ai_agent.dll`、`harness.dll`、`main.js`、`product.json`、`ai-modules-chat` 与 Workbench bundle 的散列也与本计划中的原快照不同。针对新版的只读 spot check 仍在 ai_agent/harness 中命中 `create_agent_task`、`llm_utils_chat`、`api/ide/v2/llm_raw_chat` 静态字面量，新版 Cronet 的 R4 所需公开导出名和 Read/OnResponseStarted alias 也存在；这些只证明静态字符串/导出形状，不证明活动路径。精确同版 Cronet IDL/ABI 与完整 native 调用链尚未确认，因此旧 offset/xref 不直接代表新版。R4 当前身份常量已更新到新 PID/hash，但新 renderer session 暂无 `window3\renderer.log`，observer 未 arm/attach，固定 UI 测试暂停。

## 阶段与执行门

### A：native DLL xref / dataflow

**负责人：**`real_path_investigation` 提供候选函数、模块/偏移、静态调用/数据流证据；`proxy_contract_audit` 独立核对。

**范围：**沿 `params.user_info.token`、`lite.send_message` handler、model/config、候选 route builder、transport call 与响应/event callback 查静态 xref。只用已知安装原件；不读 token 值、不调用未知 export、不 attach。

**候选初报：**`native_test_ui` 提供的 `ai_agent.dll` xref 显示 V3 route-suffix 字串表在 RVA `0x676AE0A..0x676B0EC`；V2 endpoint array/cache 构造簇在 RVA `0x676B5AF..0x676C4FC` 引用 path literal。该报告尚无 route builder 到 LiteHandler/ModelService/LLMAdapter 的 callsite，WinHTTP cluster `0x9260364..0x9261F89` 也未连到该 route。以上是待独立 review 的静态候选，不证明 route 活跃或属于当前 native chat。

**通过产物：**候选点有文件 hash、偏移/RVA、可解释的参数类型/ABI边界，以及“静态确证/推断/未知”标签。仅有字符串或名字不算 dataflow。

**失败分支：**若 DLL 无可审计数据流，则把 token 消费/route 留作未知；不扩大到凭据、用户对话或任意进程内存。

### B：身份复核与配对观察准备

**负责人：**`real_path_investigation` 准备受限观察方案；主 agent安排身份复核和任何现场触发。`proxy_contract_audit` 不 attach。

**进入条件：**观察对象、进程创建时间/模块身份、固定合成标记、hook ABI与唯一关联键已预先写明；明确预算、自动停止、异常清理、可输出字段和不覆盖面。之前的 90 秒窗口 coverage=0，不能代替配对观察。

**范围：**不读凭据/header/raw body/真实文本；按当前批准范围只投影必要 metadata。若需响应体观察，须单独说明 marker gate、字节上限、跨 chunk 规则、缓冲区生命周期、拒绝条件和最小 allowlist，并经独立 review 与主 agent批准后再执行。

**通过产物：**经验证的观察身份与 harness、离线模拟结果、预期输出 schema、失败/timeout/detach 行为和 coverage 限制。此阶段“准备通过”不等于已经关联原生请求或证明 route。

### C：独立审查

**负责人：**`proxy_contract_audit`。

收到 A 候选点与 B harness 后，独立审 ABI/函数类型和对象映射、请求关联门、bytes_read/长度上限/跨 chunk 行为、隐私过滤、请求预算、超时与清理、错误/fault 覆盖。只运行本地模拟/静态检查，不 attach、不发网络、不执行业务触发。向主 agent报告阻塞项与通过数。

### D：主 agent 触发、验收与路线决策

仅由主 agent安排并批准现场固定合成 turn；记录实际执行状态、独立关联证据和未命中边界。结果经主 agent验收后，才决定选择原生协议、SDK V2 或其他已证路线并分配后续实现责任。观察准备或一次 HTTP status 不自动构成实现授权。

**普通文本最小门：**所选模型/config 确被接受或有可验证实际 model 标识；普通文本 role/schema 明确；固定合成回复、错误及 terminal 语义有同请求证据。若某字段不支持，必须有明确边界，不能静默丢弃。

**逐能力门：**tools/tool_choice 要有声明、调用、结果回传和 ID 关联；reasoning 要有受支持字段及响应语义；stream 要有真实 wire、chunk/terminal/断连行为；usage 与 cancel 分别证明精确定义。未通过的能力保持关闭或明确不支持，不阻塞已通过的普通文本路径。

**D 失败分支：**没有可安全关联的触发、目标模型/config 不能确认、认证/route 仍未知或观察器 coverage 不足时，报告未知并回到 A/B 或由主 agent决定是否停止；不盲重试、不换 host/模型、不把猜测字段写成契约。

## 后续实现边界

实现阶段待 D 验收与主 agent明确文件所有权后另行安排。先隔离新增 transport/API 适配，维持旧用户路径可回归；仅实现已证字段和能力。未知/不支持参数应明确返回 capability/error 状态；模型、usage、终止与取消不伪造。此计划不授权改业务源码、重启 8080、commit、push 或 deploy。
