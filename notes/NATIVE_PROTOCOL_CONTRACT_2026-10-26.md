# Trae CN 原生协议契约与静态路由字典（2026-10-26）

## 范围与当前状态

本记录整理 Trae CN 3.4.4 安装原件、工作区源码审查和已有 `REAL_PATH_REVIEW_2026-10-26.md` 中可复核的证据，也记录同伴已执行的获批、单次脱敏网络诊断。此处静态复审未 attach/注入进程、调用未知 DLL 导出、发送网络请求、提交 UI 消息或读取凭据；安装目录与业务代码均未修改。

写入前确认本文件不存在。写入前的仓库状态为 `master`，只有同伴的 `notes/REAL_PATH_REVIEW_2026-10-26.md` 未跟踪；该文件未改动。仓库范围内没有找到 `AGENTS.md`。

本报告中的 DLL 偏移均为**文件字节偏移**，不是 RVA。静态字符串不证明路径在本次会话中执行。关于本次动态观测的会话关联、远端 provider/model、R2 测试是否由用户触发等仍以同伴报告中的边界为准。

配对观察 R4 已完成独立代码审查，JS 与 Python 离线模拟各 23 项通过；但现场 UI 预检未能可靠确认测试模型/输入控件，观察器没有启动或 attach，也没有发送固定 marker。因此目前没有本轮 turn 的 R4 route、model/config 接受、response、usage 或 terminal 证据；该次不是 coverage=0，而是未执行。

**安装版本边界：**随后 Trae 重启并换用了新版原件。当前根目录 `sscronet.dll` SHA-256 为 `288F987E64107A603CAE0E04D3282935B4017DC1C042EA579334DA49984FB79A`，而下方此前的 DLL/JS 散列与偏移属于重启前快照。新版 root `sscronet.dll` 中 R4 所需导出名仍齐全，Provider_Read 与 OnResponseStarted 仍为同址 alias；新版 `ai_agent.dll`/`harness.dll`/Workbench/AI modules 也仍能找到部分目标 route 字面量，但精确同版 IDL/ABI 与完整静态调用链尚未重新确认。此前静态契约不能直接当作新版安装原件的已复核结果。

## 核心结论

当前安装包中的 Solo Lite 客户端构造的是一个有状态的 agent turn：客户端按 session/agent/policy 选择模型，向内部 RPC `lite.send_message` 发送一条当前用户 query 与 session/model/agent 配置，再通过同一 session 的 `lite.subscribe_events` 接收 plan、文本、模型配置、usage、done/error 等事件。它不是一条纯无状态的 OpenAI `messages[]` 请求。

现有 V1 代理调用 `/api/ide/v1/chat`，构造 `user_input`、`chat_history` 等 body；未创建或复用原生 chat session，也未订阅原生事件流。它与原生 Solo Lite 链路之间的差异是协议和状态模型差异，不能由相同 host、DLL 字串或模型名称回显弥合。

静态代码里确实有一个通用 Workbench 命令 `workbench.action.chat.open`，它能接收 query 并在非 partial 模式自动提交。但没有找到从该命令到本次目标的 Solo Lite `ChatSessionService.sendMessage → chat.sendMessage → lite.send_message` 的注册/调用链，也没有找到可从外部受支持调用该 Solo Lite 链路的 CLI、URI handler 或本地 SDK。故它不构成本轮可用的非 UI 测试触发入口；本报告没有调用它。

## 原件与证据标识

| 安装原件（相对 `resources\app`） | 大小 | SHA-256 | 用途 |
|---|---:|---|---|
| `modules\ai-agent\ai_agent.dll` | 278,400,912 | `ACAED4D3C3B9B93D4654AED3D6DDAAC884F1ACC4C7E3A8FB283C37A9CE9C516B` | agent route 字串 |
| `modules\ai-agent\harness.dll` | 216,250,256 | `8AF3C66ABF9079E75BA8A39DC9323A67B421CA2533378ED25F4EA71434650E7A` | agent/IDE route 字串 |
| `node_modules\@byted-icube\solo-lite\dist\6645.b1c7b531.mjs` | 7,707,645 | `37C247CE0A5B527AF5044AB8D24D6B27D332D8DE67E91CCFC1E072A7B1CA9C27` | request builder、session stream、事件处理 |
| `node_modules\@byted-icube\ai-modules-chat\dist\index.mjs` | 15,126,069 | `7D198BAEDF880BBB36EEFB9AEB70AA6697B76F8C952D4D60DB1E30F609BCCC7E` | API route mapping、tool output helper、event types |
| `node_modules\@byted-icube\solo-lite\dist\7130.126f4247.mjs` | 773,477 | `3A19848D8817173F492D21BB9C41EF10E395607A2ED524FD1FDA85A6FDE6AF37` | event/usage collector |
| `node_modules\@byted-icube\solo-lite\dist\5160.0bfba5f1.mjs` | 511,751 | `B1FF50E48D1D53969B39D2640176EE2378A12C015270737FFC32CAC5E500A9AB` | IDE HTTP API 的 tool-output helper 副本 |
| `out\vs\workbench\workbench.desktop.main.js` | 18,884,180 | `6A6013B3FD12808D70C109684763EBEB299672F49EF703740AC86CC0D1633304` | 内部 RPC transport、通用 Chat 命令与 URI dispatch |
| `product.json` | 79,427 | `624918092ADE03B1D29E4F4F6909949EF1E649F4AC16F13BC88D0EBAA9F9BB68` | 安装包 URI scheme |
| `out\main.js` | 3,376,307 | `45E0C9DA688B069AF3F2E84F6AB50DDF17FE9E0B11B09CCDD4A489A37B893030` | GetUserToken 与 GenerateTempToken helper/caller 线索 |
| `out\vs\code\node\cliProcessMain.js` | 817,262 | `A38141F98F3FC888CA304ACDD2ED7A4064D08CB07E726AE4B8EA451FE9E8B603` | CLI/URL 参数解析面 |

## 可证明的原生客户端契约

### 调用路径与边界

| 顺序 | 静态可见行为 | 证据 |
|---|---|---|
| 1 | Workbench `TransportManager` 从注入的 `modularManagerService.getAiAgentRpcClient()` 取得内部 client；普通请求使用 `sendRequest("request", packet)`，流请求使用 `sendStreamRequest("request_stream", packet, onData, onError, onComplete)`。packet 含 `packet_type`, `channel_id`, `session_id=payload.client_info.connect_session_id`, `params=payload`。 | `workbench.desktop.main.js` 文件偏移 `5,426,252` (`getAiAgentRpcClient`), `5,427,802` (`executeStreamRequest`), `5,429,114` (`sendStreamRequest`), `5,429,187` (`createRequestPacket`)；文件 hash 见证据表。 |
| 2 | 应用 API adapter 把 `chat.sendMessage` 映射为 `{service:"lite", method:"send_message"}`，`chat.subscribe` 映射为 `{service:"lite", method:"subscribe_events"}`。`chat/send_message` 是更高层类型字符串，不是这层 RPC service/method。 | `ai-modules-chat\dist\index.mjs` 偏移 `7,759,712` 与 `7,759,770`；hash 见证据表。 |
| 3 | Solo Lite `sendMessage` 调用 `buildSendMessageRequest`，经过本地 `es(e)` helper 后调用 `chatApi.sendMessage(...)`。随后从响应读取 `data.message_id` / `from_append_msg`，建本地 stream context，并以 session/message 关联启动订阅。 | `solo-lite\dist\6645.b1c7b531.mjs` 偏移 `4,396,684` (`buildSendMessageRequest`), `4,408,137` (`sendMessage`)；hash 见证据表。builder 的结构可证；helper `es(e)` 的完整作用未在本次范围内证明，所以不把它描述为字节级 identity serializer。 |

### 模型选择与请求字段

`getModelRequestSelection` 从注入的 `ModelSelect` / host context、session、agent type、model selection policy 和 model store 取客户端选择：有 `fixedModelConfig` 分支；Auto 模式可能返回空 `modelName` 与 Auto strategy；其他分支读取按 session/agent/policy 保存的 model 与 mode，并可生成 Manual/Max strategy。若 resolver 有值，可将 reasoning 写入 `custom_model.reasoning_effort` 或 `custom_model.reasoning_effort_level`。位置为 `solo-lite\dist\6645.b1c7b531.mjs` 偏移 `4,392,887`，hash 见证据表。

`buildSendMessageRequest` 的顶层对象从当前 message/session 和上面的选择构成：

- `chat_session_id` 来自 `e.sessionId`；`content` 初始化为空数组；`query` 是 `(0,h.d7)(e.query, feedback-boundary-records)` 的 JSON 字符串。
- 模型/agent 字段为 `model_name`, `agent_type`, `agent_id`, `model_selection_strategy`, `custom_model`, `common_params`。
- 可选字段含 `force_new_turn`, `session_type`, `use_fast_request`, `origin`, `permission_profile_id`；worktree 状态满足条件时附加 `is_worktree` 与 `workspace_folders`。
- `custom_model` 可包含 provider/config/model 名、`base_url`, `ak`（这里只确认字段名，未读取值）、custom model id/type、`use_remote_service`, `multimodal`, `prompt_max_tokens` 和模型支持的 reasoning 字段。

字段构造见同文件偏移 `4,397,669` 起；builder 名称位于 `4,396,684`。`prompt_max_tokens` 是 custom model 配置字段，不能据此推断为每次请求的 OpenAI `max_tokens`。这个构造没有 OpenAI `messages[]`, `system`, `developer`, `tools`, `tool_choice`, `temperature`, `top_p` 或顶层 `max_tokens` 字段。也没有证据证明代理的 `reasoning_effort` 可以直接映射为客户端自有的 resolver/custom-model 语义。

### Session、message 与 history

| 标识/状态 | 可证明语义 | 未知边界 |
|---|---|---|
| 外层 RPC `session_id` | 从 `payload.client_info.connect_session_id` 取值，是内部 RPC packet 的 connection/session 字段。 | 不等同于下面的会话 ID；与远端 agent task 的生命周期未用同一 ID 证明。 |
| `chat_session_id` | 取自客户端 `e.sessionId`；model selection 也可用 `modelSelectionSessionId ?? e.sessionId`。Session store 同时提供 `sessionType` / worktree 状态。 | 具体服务端保留策略和 session 过期策略未证。 |
| user `messageId` | 已在客户端 `userMessage` 上存在；`buildSendMessageRequest` 顶层不写 `message_id`。`send_message` 响应若返回 `data.message_id`，客户端以它覆盖/关联本地 message id。 | 是否由服务端以该 id 做幂等键未证。 |
| agent `agentMessageId` / `agent_run_id` | agent message id由本地 `commitAndStartStream`/事件上下文维护；`agent_run_id` 出现在 plan item / agent-call 数据中。 | `agent_run_id` 与 V3 `task_id` 的映射未证。request builder 没有顶层 `task_id`。 |
| history | 当前发送体显式序列化 `query`，而不是 `chat_history`；UI 通过 session store/`get_messages` 等 API 管理对话历史。 | `query` 的所有 content block schema、服务端如何合并旧 session context，需要实际受控样例才能确认。 |

`sendMessage` 主分支把响应 `message_id`（或本地 `r.messageId`）作为 `reply_to_message_id` 传给 `subscribeStream(sessionId, replyToMessageId)`；append 分支也根据 `from_append_msg` 与响应 id 调整 message/订阅状态。证据位于同文件偏移 `4,408,137`，以及 `subscribeStream` 偏移 `4,390,616`。Native client 的 session/history 是会话状态模型，不等价于每次接收任意 OpenAI `messages[]` 的无状态调用。

### Tools、decision 与完整 agent task

- event type 中有 `plan_item`；流消息 schema 中有 `tool_call_info`，包含 tool name/params/result 等对象。Solo Lite 将这些计划项转为 agent plan UI 数据。证据：`ai-modules-chat\dist\index.mjs` 偏移 `39,510` (`PlanItem`/`plan_item`)；`solo-lite\dist\6645.b1c7b531.mjs` 偏移 `4,555,495` (`transformPlanItem`)。
- API adapter 单独映射 `chat.sendUserDecision` 到 `lite.send_user_decision`。这是用户决策/确认通道；不能当作工具输出回传。
- chat module 有静态 HTTP helper `SubmitToolCallOutputs(e,t)`：POST `/api/ide/v1/agents/runs/${e.id}/tool_call_outputs`，body 含 `tool_call_outputs`, `Request`, `debug_options`。位置 `ai-modules-chat\dist\index.mjs` 偏移 `420,451`；同一 helper 在 `solo-lite\dist\5160.0bfba5f1.mjs` 也有副本。限定搜索只在这两个包中找到该符号，未找到它与本次 `lite.send_message` stream 的直接调用链。
- DLL 另有 `/api/agent/v3/commit_toolcall_result`、`workflow/commit_toolcall`、`create_agent_task` 等字串；它们可能对应原生 agent/workflow 操作，但只证明二进制静态字串存在。

因此可以确认原生 agent 有结构化 tool/plan/result 通道；不能确认 OpenAI `tools` JSON Schema 到原生工具注册、参数、审批、结果对象的转换。V1 代理把工具定义拼入 system turn 后又在 translator 丢弃 system turn，纯函数复核确认 tool name/schema/tool_choice 均未到上游 body。当前没有证据可以将 OpenAI `tool_choice` 或任意用户工具直接映射到原生 agent 工具。

完整 Trae agent turn 可以包括 agent selection、持久化 session、工具/计划事件、用户授权、消息/事件回传和 workspace/worktree 权限上下文。普通 LLM chat completion 只是 message/control/tool 请求及生成结果。即使都能导致某处远端模型被调用，两者也不是同一语义单元；把代理改成 native agent transport 会改变 side effect/审批/状态行为，需要先确定期望支持的是“纯 LLM 调用”还是“完整 agent task”。

### 候选的 raw LLM JSON API（静态可见，活动调用未知）

安装包还包含比 Solo Lite `lite.send_message` 更接近普通 chat completion 的 V2 builder。`ai-modules-chat\dist\index.mjs`（15,126,069 bytes，SHA-256 `7D198BAEDF880BBB36EEFB9AEB70AA6697B76F8C952D4D60DB1E30F609BCCC7E`）的 `CopilotService.LLMRawChatV2(e,t)` 位于文件偏移 `0x6B424`：调用 `genBaseURL("/api/ide/v2/llm_raw_chat")`，再用 POST 和 `data:n` 调 request。`n` 由同名属性直接复制，不做字段转换；固定白名单为 `config_name`, `model_name`, `session_id`, `messages`, `message`, `conversation_id`, `is_custom_model`, `provider`, `Request`, `encrypted_model_params`, `user_input`, `request_type`, `metadata`, `tools`, `queue_id`, `request_seq`, `mode_type`, `chat_mode`, `config_source`, `access_type`, `image_config`, `estimate_prompt_tokens`, `slash_command`, `message_origin`, `tool_choice`, `reasoning_effort`, `stream`, `retry_times`, `queue_retry`, `video_config`, `connect_check_param`, `user_selected_model_name`, `reasoning_effort_level`, `estimated_token_usage`, `custom_model_uniq_id`, `provider_context`, `biz_context`, `extra_info`, `use_fast_request`。源码中没有顶层 `max_tokens`, `temperature` 或 `top_p` 字段。`messages`、`tools`、`tool_choice` 和 reasoning 字段被透传，仍不能证明服务端接受的 message role/schema、工具定义或 reasoning 语义。

同一 builder 副本位于 `solo-lite\dist\5160.0bfba5f1.mjs`（511,751 bytes，SHA-256 `B1FF50E48D1D53969B39D2640176EE2378A12C015270737FFC32CAC5E500A9AB`），`LLMRawChatV2` 偏移 `0x584EE`；其 `InnerLLMRawChatV2` 偏移 `0x5DCC9` 指向 `/api/ide/inner/v2/llm_raw_chat`。另一份同样的路径字符串存在 `ai_agent.dll` 偏移 `0xA58CBC8`、`harness.dll` 偏移 `0xAAD63B7`。静态 route 字符串与 builder 定义均不证明此接口当前有流量或本次 Solo Lite 会话调用它。

默认 Copilot service 工厂位于 `ai-modules-chat\dist\index.mjs` 的 `function g` 偏移 `0x8A2B2`；ServiceProvider 的 `createServices` 在偏移 `0x8A9DE` 把 `endpoints.copilotService` 作为 base URL 传给该 request factory，再注入 `CopilotService`。默认 wrapper 把 truthy `data` 用 `JSON.stringify` 编码后 `fetch`，非 2xx 尝试读取 JSON 错误体，成功则调用 `response.json()`。因此 builder 的 `stream` 是请求 body 字段，不是此 wrapper 中的 SSE/chunk 解析证据。`onBeforeRequest` 和 `onAfterResponse` customizer 可改请求或替换响应，所以这只是默认实现，不证明当前运行时没有定制行为；实际 body/response schema 仍待正常受控调用确认。

`extensions\ai-completion\dist\extension.js`（3,793,678 bytes，SHA-256 `7725E2CC61DDFC3617EF6A5CDB0E4BCEC030D633C1BD96F546A117FEBC1952A9`）有 `fusionRawChatAPI: "api/ide/v2/llm_raw_chat"` route-map 常量（例如偏移 `0x38524B`），但本次静态搜索只在该 map 看到路径，在两个 package 文件看到方法定义；未找到明文 `LLMRawChatV2` 外部调用点。可能的动态/间接调度仍属未知。没有证据确认 V2 必填字段、response DTO、session 保留语义、可用 model/config 命名或当前选择该路线的调用者；不能仅凭 route、builder 或 map 构造并发送请求。

对纯 OpenAI-compatible LLM 目标，V2 结构比完整 agent task 路线更匹配 `messages` / `tools` / `tool_choice` / reasoning 子集，值得优先验证；但它还不是可直接宣称兼容的协议。尤其 system/developer role 是否能原样出现在 `messages`、工具 schema/调用结果是否采用 OpenAI 形状、`max_tokens`/`temperature`/`top_p` 如何设置、`stream:true` 的 wire response 以及 usage 语义都没有静态契约。完整 Trae agent 的 V3 task/plan/approval/context 路线不能替代这些未知点，也不应自动赋予普通 LLM 请求 workspace 或工具副作用。

### Auth helper 路由与一次失败的 mint 诊断

当前安装 `out\main.js`（SHA-256 `45E0C9DA688B069AF3F2E84F6AB50DDF17FE9E0B11B09CCDD4A489A37B893030`）包含两个不同用途的 token helper；静态存在与其属于当前正常 Trae CN V2 调用链是两件事：

| helper / 静态路径 | 静态调用线索 | 证据边界 |
|---|---|---|
| `getJwtToken` → `/api/v2/GetUserToken` | 函数文件偏移 `1,528,313`；路径偏移 `1,528,438`、`1,528,577`；POST 动态 host `${e}`、JSON `{}`、`X-Cloudide-Token`，读取 `Result.Token/ExpiredAt/UserID/TenantID`。找到的 caller `convertTokenToUserInfoOld` 在 `1,531,300`；其 `loginCredentialCallback` 仅当 `apiHost === bootConfig.account.bytedance.USDSApi` 进入旧转换分支。 | 未证明该条件分支适用于当前正常 Trae CN 账户或 V2；无当前会话调用链。 |
| `GenerateTempToken` → `/cloudide/api/v3/trae/GenerateTempToken` | 路径偏移 `1,515,385`；POST `${host}`、body `{IDEVersion: appVersion}`、`x-cloudide-token`。`TokenManager.refreshTempToken` 偏移 `1,543,025` 调用 `provider.generateTempToken` 偏移 `1,543,587`，并写 `trae-jwt-token` 临时文件偏移 `1,543,708`。 | 临时文件写入可见，但未找到该 token 到 `CopilotService.jwt` 或 raw V2 请求的传递链。 |

获批的 mint→条件式 V2 诊断只发出一次当前配置 host 的 `POST /api/v2/GetUserToken`：HTTP 404、content-type category `other`、error category `http_4xx`，该请求消耗预算 `1/2`；`v2.request_attempted=false`，`skip_reason=mint_failed`。未重试、换 host、发 V2 请求或 attach R3；finally 报告所有 client close 为 true、`cleanup_complete=true`。`valid_before=true` 和 `valid_after=true` 仅是本地对旧内存 JWT 的 exp 检查；mint 失败时 `new_equals_old=null`。这不证明旧 JWT 无效、登录失败、GetUserToken 权限问题或模型不可用。

网络结果本身没有事务级 host 投影。失败后的一次只读本地 auth 读取将来源归为 `live_storage`、host enum 归为 `api_trae_cn`，与 `api.trae.cn` 一致；这是同来源事后佐证，不是网络记录直接捕获的 host。静态 main.js 的 GetUserToken helper 存在，但找到的 caller 条件是 USDS 旧登录分支，因此不能据它把这次 404 解释为正常 Trae CN 的标准 mint 路径。此前 V2 假设请求的 HTTP 400/零字节结果是另一项诊断，也不能与本次 mint 404 合并归因。

### 普通 CN 登录到 native RPC 参数的静态链

安装原件静态显示普通 CN 登录通过 `TraeLoginService.exchangeTokenByAuthCode` 调用 `POST /trae/api/v3/oauth/ExchangeToken`，响应中的 `Token` 经 `v9` 映射到 `userInfo.token`。Workbench renderer 通过 `GET_USER_INFO` 主进程 IPC 获取 user info；`ICubeChatCommonSession.getUserInfoWithToken` 将 `userInfo.token` 放进 native RPC `params.user_info.token`。CN normal account host 的静态配置为 `https://api.trae.cn`。这些只证明静态客户端供给路径，不证明该 token 在 native handler 内如何验证、变换或用于上游认证；本轮没有读取 token 值。

`ai-modules-chat` service factory 接受 `jwt` prop，默认请求 wrapper 会构造 `Authorization: Cloud-IDE-JWT ...`，但静态检查没有找到正常 CN `userInfo.token` 到该 SDK prop 的 caller。`GenerateTempToken` 属于 Marscode/provider 特性路径，结果写入单独的临时 token 文件，默认 gate 关闭，未证该 token 会进入 Copilot SDK 或 native RPC。`GetUserToken` 仍只找到 USDS 旧转换 caller。普通 CN token → native RPC 参数已经有静态证据；native handler → 远端请求的认证链仍未知。

### 订阅、完成、取消与 usage

`subscribeStream` 对 session 注册持续订阅，若该 session 已有 active subscription，会先调用旧的 `cancel()`；随后调用 `chatApi.subscribe(sessionId, {}, replyToMessageId ? {reply_to_message_id: replyToMessageId} : undefined)`。到来的事件被规范化为 `{event:e.event || "message", data:e.data}` 并交给 stream handler。没有有效事件却正常结束时，客户端生成 `PROTOCOL_SSE_EMPTY_BODY` 错误。位置：同文件偏移 `4,390,616`。

流 handler 对 `plan_item` 批处理；`handleCancel` 将当前 agent message 状态改为 Canceled 并停止本地 stream；`handleComplete` 停止本地 stream并 finalize。传输层 `event === Done` 则结束 `request_stream` RPC。这个 transport 完成标记、语义 `done` event、chat session 状态是不同层次。代码能证明订阅/本地 UI 清理行为，不能证明取消一定中止上游模型生成。

静态 event names 包括 `model_config`, `plan_item`, `token_usage`, `context_usage`, `timing_events`, `done`, `error` 等；事件 schema/枚举见 `ai-modules-chat\dist\index.mjs` 偏移 `22,054` (`model_config`) 与 `39,510–39,711`（plan/usage/done/error）。Solo Lite 将消息 `token_usage` 转为 input/output/last-turn/max/completion/reasoning 等显示字段（`solo-lite\dist\6645.b1c7b531.mjs` 偏移 `4,440,171`、`4,556,742`）；usage event collector 将 `input_tokens`/`output_tokens` 记录到 tokenUsage telemetry（`solo-lite\dist\7130.126f4247.mjs` 偏移 `678,556–678,962`）。这些能证明字段与 UI 消费路径存在；不能证明它们是计费账单、某一上游工具轮次还是整 turn 累计值。

V1 代理与之对比：标准流分支不把 `token_usage`完整送入 OpenAI usage；非流式与工具循环的 usage 累加也不完整。具体 V1 行号见上一轮源码审查的 `REAL_PATH_REVIEW_2026-10-26.md`。

## 外部触发入口核对

1. `product.json` 第 39 行声明 `urlProtocol: "trae-cn"`。Workbench main 的 `$registerUriHandler` 只把外部 URI 转发给按 extensionId 注册的 extension handler（`workbench.desktop.main.js` 偏移 `4,795,783`）。静态搜索到的内置 URI handler 位于 `git`, `github-authentication`, `microsoft-authentication` 扩展；在 `@byted-icube` 与 AI/chat 扩展中未找到 `registerUriHandler`。没有发现 `trae-cn://...` 直达 Solo Lite sendMessage 的 handler。
2. CLI parser 的参数列表含通用 `open-url`（`cliProcessMain.js` 偏移 `681,789`）；本次限定检查没找到专用 prompt/send 命令或把外部 URI 参数绑定到 Solo Lite `ChatSessionService` 的代码。没有运行 CLI/URI。
3. 有个通用 Workbench 命令 `workbench.action.chat.open`（`workbench.desktop.main.js` 偏移 `9,319,428–9,319,679`）。handler 接受 string 或 object；在 `query` 存在时设置输入；当 `isPartialQuery` 为 false/未给时调用 `acceptInput()`（偏移 `9,322,119–9,322,252`）。`isPartialQuery:true` 则只预填。它运行在 generic Workbench Chat 的 `lastFocusedWidget`/Chat service 上；本次没找到该 widget/provider 到 Solo Lite `ChatSessionService.sendMessage` 的直接链。
4. `workbench.action.chat.submit` / `submitWithoutDispatching` 命令对已有 widget 输入执行 accept；没有独立 prompt 参数的目标 Solo Lite 调用证据。`workbench.action.chat.icube.send.codeReview` 是有专门 review/diff metadata 的内部工作流，也未证明连接到目标 session 或接受任意 prompt。`notebook.cellOutput.addToChat` 是笔记本内容注入 chat 的命令，不是已证自动发送的测试入口。

结论：当前确认有能在**通用 Workbench Chat UI 内**提交 query 的内部命令，但未证它调用本次目标 Solo Lite 协议，也未证它可作为受支持的进程外 API 调用。因此没有可在本轮安全确认的非 UI synthetic LLM trigger。不得仅凭命令名自动调用。

## 代理接口对照与验收矩阵

| 维度 | 原生 Solo Lite 静态契约 | 当前 V1 代理 | 要达到可验收原生等价仍需 |
|---|---|---|---|
| transport/route | 主路线是内部 `request` / `request_stream` RPC 的 `lite.send_message` / `lite.subscribe_events`；另有静态 raw LLM V2 JSON builder 候选 `/api/ide/v2/llm_raw_chat`，当前调用者/活动状态未知。 | 直接 HTTP POST `/api/ide/v1/chat`。 | 同一受控 turn 下关联 UI RPC、native request/response 与上游 HTTP flow；V2 候选须先确认活动调用、参数与返回契约。 |
| model | Solo Lite 通过 session/agent/policy 的 ModelSelect 生成 `model_name`, `model_selection_strategy`, `custom_model`；V2 builder 直接复制 `model_name`, `config_name`, `provider` 等字段，但实际选取/接受语义未证。 | 默认 builder 可不传 `model_name`；响应 `model` 是客户端原值回显。 | 观测同一 turn 的选中配置、发送 body、native/server 接受的 model_config，分开标记客户端选择与服务端采用。 |
| messages/context | Solo Lite 当前 query content blocks 序列化为 `query`，历史归于持久 chat session；V2 builder 另有直传 `messages`, `session_id`, `conversation_id` 的字段，schema/服务端保留语义未知。 | `user_input` + 最近 24 条 `chat_history`，默认无原生 session lifecycle。 | 证明 user/query、role、附件/内容块、context/history 在所选路线上的映射与边界；明确同 session 如何跨轮复用。 |
| system/developer | Solo Lite builder 没有这两个 top-level role；raw V2 的 `messages` 可承载但其 role/schema 接受性未证；服务端隐藏 prompt/agent instruction 不在静态可见范围。 | system/developer 及被渲染进 system 的 tool declaration 在 translator 处被丢弃。 | 不可声称等价。需确认纯 LLM 的受支持 messages schema 或拒绝策略；不要把完整 agent prompt/config 当作 role 等价。 |
| tools/tool_choice | Solo Lite 可见 `plan_item`/`tool_call_info`、`send_user_decision` 与静态 SubmitToolCallOutputs helper；raw V2 将 `tools`/`tool_choice` 直接复制，但没有已证调用结果映射。 | 代理工具声明被丢弃；没有保真 tool_choice。 | 对每种 tool 证明声明→调用→审批→结果回传的完整 schema/ID 关联；未知 tool/tool_choice 必须明确拒绝或降级。 |
| reasoning/max_tokens/temp | selected model 可在 custom_model 带受支持的 reasoning 字段；raw V2 直传 `reasoning_effort`/`reasoning_effort_level`，但没有顶层 max_tokens/temperature/top_p。 | 没有映射 OpenAI reasoning_effort、max_tokens、temperature、top_p。 | 分别确认 server 接受的控制字段及默认值；不能把 `prompt_max_tokens` 当成 OpenAI max_tokens。 |
| events/end/cancel | Solo Lite subscribe 关联 session/message并有 done/error 与 transport 完成；raw V2 默认 wrapper 对成功响应执行 `response.json()`，没有 SSE/chunk parser 证据。 | OpenAI SSE 通过代理自己的事件翻译输出；native 事件语义/取消未直接复用。 | 同 turn 捕获 metadata、事件顺序、terminal/error、断连和取消结果，并确认 V2 `stream` 的 wire response；证明上游取消而不只关闭本地读流。 |
| usage | token/context usage event 与 message usage 字段存在；raw V2 `response.usage` 未知。 | stream usage 漏传/工具循环累计不完整。 | 识别 token_usage 是否 per-model/per-turn/累计，验证请求/工具轮次如何合计，以及 response.usage 的准确语义。 |

## 静态 endpoint suffix 词表

下表是两份 DLL 中目标前缀字串的完整命中分解与去重候选，便于 R3 对已脱敏 path token 作本地比对。`AI`=`ai_agent.dll`，`H`=`harness.dll`；offset 均为文件字节偏移。扫描只覆盖表中列出的前缀族，不声称覆盖所有动态拼接或整个产品的 API。路径候选即使在两个 DLL 重复，也不能证明本次调用。

### `api/agent/v3/`

| suffix 候选 | AI 偏移 | H 偏移 | 边界说明 |
|---|---:|---:|---|
| `create_agent_task` | `0xA58C788` | `0xAAD5F98` | 下一 `api/agent/` 分隔 |
| `commit_toolcall_result` | `0xA58C7A6` | `0xAAD5FB6` | 同上 |
| `interrupt` | `0xA58C7C9` | `0xAAD5FD9` | 同上 |
| `resume_agent_task` | `0xA58C7DF` | `0xAAD5FEF` | 同上 |
| `get_resume_agent_task_status` | `0xA58C7FD` | `0xAAD600D` | 同上 |
| `query_history_state` | `0xA58C826` | `0xAAD6036` | 同上 |
| `sync_history_state` | `0xA58C846` | `0xAAD6056` | 同上 |
| `compact` | `0xA58C865` | `0xAAD6075` | 同上 |
| `llm_utils_chat` | `0xA58C879` | `0xAAD6089` | 同上 |
| `workflow/start` | `0xA58C894` | `0xAAD60A4` | 同上 |
| `workflow/commit_toolcall` | `0xA58C8AF` | `0xAAD60BF` | 同上 |
| `use_fast_request` | `0xA58C8D4` | `0xAAD60E4` | 同上 |
| `generate_summary` | `0xA58C8F1` | `0xAAD6101` | 同上 |
| `dsl/logs/subscribe` | `0xA58C90E` | `0xAAD611E` | 同上 |
| `dsl/templates` | `0xA58C92D` | `0xAAD613D` | 同上 |
| `dsl/render/resources` | `0xA58C947` | `0xAAD6157` | H 尾接 `TTNetConfig`，AI 尾为控制/非 ASCII；后缀候选可比对，尾边界不确定 |
| `custom_model_connectivity_check` | `0xA58D1FA` | `0x92277A2`, `0xAAD69C0` | AI 及 H `0xAAD69C0` 到下一 API 前缀；H `0x92277A2` 后接 `window_typebiz_context` |
| `generated_skill/restore_pending` | `0x9B63308` | `0xAACE06D` | H 有 trailing `/`，可能是下一个路径分隔，斜线归属不确定 |
| `generated_skill/dismiss_pending` | `0x9B63334` | `0xAACE041` | H 副本下一 API 分隔 |
| `generated_skill/get_pending` | `0x9B63360` | `0xAACE019` | H 副本下一 API 分隔 |
| `generated_skill/list_pending` | `0x9B63388` | `0xAACDFF0` | AI 接 `DismissedAgent access is not permitted`，H 副本由下一 API 分隔，故保留为候选 |

每个 DLL 的 `api/agent/v3/` 原始 hit 数各为 22；精确 `/api/agent/v3/` 前缀 hit 数各为 0。另有 AI 偏移 `0x9B633D7` 的不完整 `api/agent/v3/generated_skill`，NUL 结尾，无后缀。

### `api/ide/v1/`：主要相邻常量池

每个文件的原始 hit 数：AI 77、H 55。前导斜杠形式 `/api/ide/v1/` 的命中分别为 AI 5、H 3。以下主要相邻常量池的 53 个 route suffix 候选均由下一 `api/` 前缀分隔；已在“边界注意”列出的少数尾部不同步项仍应标 uncertain。

| suffix 候选 | AI 偏移 | H 偏移 |
|---|---:|---:|
| `web_fetch` | `0xA58C9B8` | `0xAAD61C8` |
| `intent_detect` | `0xA58C9CC` | `0xAAD61DC` |
| `context_select` | `0xA58C9E4` | `0xAAD61F4` |
| `chat` | `0xA58C9FD` | — |
| `query_rewrite` | `0xA58CA0C` | `0xAAD620D` |
| `agents/runs` | `0xA58CA36` | `0xAAD6225` |
| `agents/runs/:id/tool_call_outputs` | `0xA58CA4C` | `0xAAD623B` |
| `practice/generate_conversation_title` | `0xA58CA93` | `0xAAD6282` |
| `get_resource_upload_token` | `0xA58CAC2` | `0xAAD62B1` |
| `get_resource_url` | `0xA58CAE6` | `0xAAD62D5` |
| `fast_apply` | `0xA58CB49` | `0xAAD6338` |
| `model_list` | `0xA58CB5E` | `0xAAD634D` |
| `get_model_list` | `0xA58CB73` | `0xAAD6362` |
| `get_detail_param` | `0xA58CB8C` | `0xAAD637B` |
| `batch_get_detail_param` | `0xA58CBA7` | `0xAAD6396` |
| `llm_raw_chat` | `0xA58CBF2` | `0xAAD63E1` |
| `feedback` | `0xA58CBDF` | `0xAAD63CE` |
| `get_resource_upload_url` | `0xA58CC09` | `0xAAD63F8` |
| `commit_resource_upload_result` | `0xA58CC2B` | `0xAAD641A` |
| `cancel_queue_task` | `0xA58CC53` | `0xAAD6442` |
| `connect` | `0xA58CC71` | `0xAAD645E` |
| `chat_prompt` | `0xA58CC83` | `0xAAD6470` |
| `update_custom_model` | `0xA58CC99` | `0xAAD6486` |
| `providers` | `0xA58CCB7` | `0xAAD64A4` |
| `add_custom_model` | `0xA58CCCB` | `0xAAD64B8` |
| `llm_raw_chat_prompt` | `0xA58CCE6` | `0xAAD64D3` |
| `web_search` | `0xA58CD04` | `0xAAD64F1` |
| `jump_queue_task` | `0xA58CD19` | `0xAAD6506` |
| `get_mode_info` (`api/v1/commercial`) | `0xA58CD33` | `0xAAD6520` |
| `chat_mode` (`api/v1/commercial`) | `0xA58CD52` | `0xAAD653F` |
| `save_status` (`api/v1/commercial`) | `0xA58CD6D` | `0xAAD655A` |
| `privacy/operation` | `0xA58CD8A` | `0xAAD6577` |
| `privacy/query` | `0xA58CDA6` | `0xAAD6593` |
| `check_content` | `0xA58CDBE` | `0xAAD65AB` |
| `tool_text_to_image` | `0xA58CDD6` | `0xAAD65C3` |
| `tool_text_to_image_stream` | `0xA58CDF3` | `0xAAD65E0` |
| `tool_text_to_video_stream/` | `0xA58CE17` | `0xAAD6604` |
| `check_estimated_balance` (`api/v1/commercial`) | `0xA58CE3C` | `0x9227779`, `0xAAD6629` |
| `report/multimodal` | `0xA58CE7D` | `0xAAD6652` |
| `get/multimodal` | `0xA58CE99` | `0xAAD666E` |
| `documentrag/official/check_should_update` | `0xA58CEB2` | `0xAAD6687` |
| `documentrag/official/latest_document_sets` | `0xA58CEE5` | `0xAAD66BA` |
| `documentrag/custom/index_document_set` | `0xA58CF19` | `0xAAD66EE` |
| `documentrag/custom/delete_document_set` | `0xA58CF49` | `0xAAD671E` |
| `documentrag/custom/document_sets_status` | `0xA58CF7A` | `0xAAD674F` |
| `documentrag/retrieve` | `0xA58CFAC` | `0xAAD6781` |
| `ping` | `0xA58CFCB`, `0xA4DA806` | `0x92A0EEE` |
| `get_session_usage` (`api/v1/commercial`) | `0xA58CFDA` | `0xAAD67A0` |
| `get_user_activity` (`api/v1/commercial`) | `0xA58CFFD` | `0xAAD67C3` |
| `tenant/get_tenant_user_config` | `0xA58D020` | `0xAAD67E6` |
| `agent/team_agent/create` | `0xA58D101` | `0xAAD68C7` |
| `agent/team_agent/update` | `0xA58D123` | `0xAAD68E9` |
| `agent/team_agent/remove` | `0xA58D145` | `0xAAD690B` |
| `agent/team_agent/list` | `0xA58D167` | `0xAAD692D` |
| `agent/team_agent/details` | `0xA58D187` | `0xAAD694D` |
| `agent/team_agent/change_status` | `0xA58D1AA` | `0xAAD6970` |
| `get_custom_model_type_config` | `0xA58D1D3` | `0xAAD6999` |
| `super_completion_query` | `0xA58D226` | `0xAAD69EC` |
| `skill_recommend` | `0xA58D247` | `0xAAD6A0D` |

### `api/ide/v1/`：其他命中与尾部不确定候选

| suffix 候选 | AI 偏移 | H 偏移 | 边界 |
|---|---:|---:|---|
| `get_skill_detail` | `0x9A61CC7` | `0x9225358` | NUL 结尾 |
| `ping/list` | `0xA4DA881` | — | NUL 结尾 |
| `ping/list/tunnel/{id}` | — | `0x92CF2A1` | 后接 `https://`；`:id` 是动态段，尾界不确定 |
| `tenant/report_audit_log` | `0x9A8AA9F` | `0xAACE09A` | AI NUL 结尾；H 追加 workflow/device 字段 |
| `text_to_image` | `0x99E2C7F`, `0x9AEFD37`, `0xA496A5D` | — | 追加 `enable_multi_agent_reader`、`mcp_server_list` 或 source-path 字串，suffix 边界不确定 |
| `wiki/clear_wiki` | `0x99EA747`, `0x9A9F0CF`, `0x9AF668F` | — | 后接 Rust source path；候选 suffix，不是活动 route 证明 |
| `wiki/get_wiki_status` | `0x99EA9EF`, `0x9A9F377`, `0x9AF6937` | — | 同上 |
| `wiki/get_wiki_content` | `0x99EAB35`, `0x9A9F4BD`, `0x9AF6A7D` | — | 同上 |
| `wiki/get_wiki_repo_info` | `0x99EAC80`, `0x9A9F608`, `0x9AF6BC8`, `0xA4A3270` | — | 同上 |
| `wiki/update_wiki_progress_status` | `0x99EAF56`, `0x9A9F8DE`, `0x9AF6E9E` | — | 同上 |

以下字符串也被扫描命中，但只能作为不完整/拼接线索，不应加入确定白名单：AI `0xA2E7E1A` 的 `pinghttpAhaVmDirectFallbackDirectSpawn`；AI `0xA58CA0C` 的 `query_rewritex-ide-tokendefault`（H 有明确 `query_rewrite`）；AI `0xA58CC53` 的 `cancel_queue_taskcn`（H 有明确 `cancel_queue_task`）；AI `0xA58CE3C` 的 `check_estimated_balanceseedream_5seedance2-fast`（H 有清楚 token）；AI `0xA58D247` 的 `skill_recommendsgUnfold`（H 有清楚 token）；`get_resource_url` 两 DLL 副本均接 UUID-like 常量；`tool_text_to_video_stream/` 两份均带 trailing slash。对 R3 最安全的做法是只在本地内存中比较观察到的 path token，遇到未知/不唯一/拼接不明时保留为 unknown 并跳过 body。

### `out\main.js` 中的认证路径 literal

| 静态路径 | 文件字节偏移 | 安装原件 SHA-256 | 证据类型 |
|---|---:|---|---|
| `/api/v2/GetUserToken` | `0x175276`, `0x175301` | `45E0C9DA688B069AF3F2E84F6AB50DDF17FE9E0B11B09CCDD4A489A37B893030` | exact static literal; only the USDS old conversion caller was found |
| `/cloudide/api/v3/trae/GenerateTempToken` | `0x171F79` | same | exact static literal; TokenManager writes its result to a temporary token file |

The ignored offline dictionary at `logs/native_static_dictionary_20261026/dictionary.py` now pins this `out/main.js` hash and those two exact literals alongside the prior fixed sources. It compares only `SHA256(ASCII(encodeURIComponent(value)))`; slash-containing fixtures therefore hash the encoded `%2F` form. It neither reverses arbitrary digests nor assembles a route across dynamic IDs. A match is source-backed static evidence only, not proof that a helper ran or that the path belongs to the current normal Trae CN authentication branch.

### 其他扫描到的前缀族

| 前缀 | AI hit | H hit | suffix 候选（AI / H 偏移） |
|---|---:|---:|---|
| `api/ide/v2/` | 1 | 1 | `llm_raw_chat`: `0xA58CBC8` / `0xAAD63B7` |
| `api/ide/unstable/` | 1 | 1 | `tools/diff`: `0xA58CA78` / `0xAAD6267` |
| `api/v1/commercial/` | 6 | 7 | `get_mode_info`: `0xA58CD33` / `0xAAD6520`; `chat_mode`: `0xA58CD52` / `0xAAD653F`; `save_status`: `0xA58CD6D` / `0xAAD655A`; `check_estimated_balance`: `0xA58CE3C` / `0x9227779,0xAAD6629`; `get_session_usage`: `0xA58CFDA` / `0xAAD67A0`; `get_user_activity`: `0xA58CFFD` / `0xAAD67C3` |
| `api/v1/knowledgebase/` | 4 | 4 | `teamDoc/getDocumentSetLists`: `0xA58D048` / `0xAAD680E`; `teamDoc/getDocumentSetInfo`: `0xA58D078` / `0xAAD683E`; `teamDoc/getDocumentUrl`: `0xA58D0A7` / `0xAAD686D`; `teamDoc/getDocumentSetDiff`: `0xA58D0D2` / `0xAAD6898` |

这些前缀计数来自只读二进制字符串扫描，和运行期间的 71/13 flow 计数不是同一类证据。路径去重词表不得作为 R3 body 探测白名单的完整性证明，也不得放宽 host/method/unique-marker gate。

## 下一阶段验收重点

1. 先由 `real_path_investigation` 对 DLL 做只读 xref/dataflow，尝试闭合静态已证的 `params.user_info.token` 到 native handler、认证构造和 transport 的链；`proxy_contract_audit` 独立核对类型/ABI/证据边界。不得读取 token 值或调用未知 export。
2. 90 秒 metadata-only observer 已实际运行并正常 unload/detach，但 coverage 全零：`init_calls=0`、`known_https_candidates=0`、`started_metadata=0`。它只装 Cronet `InitWithParams`/`Start` 两个 hook，不读 provider、body、header 或 query；零覆盖只说明指定 NetworkService PID 在该窗口没有经过这两个 lifecycle hook 的可见调用，不排除其他进程/transport。其 driver 曾把 readiness 的 `body_eligible=false` 错投影为 true；原始 hook metadata 及 JS 均显示只有两个 URL hooks、body API 未安装。sanitizer 已修正并本地 6-case 自测通过，未再次 attach。该窗口不是与指定 UI turn 配对的观察，不能作为路由或认证调用链证据。
3. 后续配对观察须先由主 agent安排现场身份复核、固定合成触发和请求关联设计；`proxy_contract_audit` 在不 attach 的情况下审 harness 的 ABI/对象映射、关联门、字节长度/跨 chunk、隐私输出、预算、cleanup 和 fault coverage。只有主 agent另行触发与验收后，才决定路线与实现授权。
4. 普通文本实现门只要求所选路由/认证、目标配置接受情况、文本 role/schema（或明确拒绝）、固定回复和基本错误/terminal 语义有证据；tools/tool_choice、reasoning、stream/usage/cancel 分别设独立能力门。未证项明确不支持或未知，不静默丢弃、伪回显或扩大能力结论。
5. V1 `/api/ide/v1/chat`、SDK V2 `/api/ide/v2/llm_raw_chat` 与 AgentV3 字串/观测分别属于不同证据层；版本号、同 host 或时间邻近不证明它们上下游等价。实现路线待调用链与同 turn 证据通过后由主 agent选择。
