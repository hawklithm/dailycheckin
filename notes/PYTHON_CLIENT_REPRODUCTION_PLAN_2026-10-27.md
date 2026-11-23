# Python 独立客户端与通用协议代理：证据审查和执行方案

日期：2026-10-27\
初稿状态：代码只读审查已完成；未发远端请求、未 attach、未修改业务代码。后续 metadata-only baseline 另见文末更新。本文是新计划，不替换既有 handoff 或调用链报告。

## 目标与边界

目标是由 Python 独立完成经证实的 Trae CN 认证与远端文本推理，再把已验证的请求/响应协议接入可切换的通用代理通道。目标不包括复刻整个 IDE、workspace agent、工具执行环境或所有 UI 行为。工具、reasoning、stream、usage、取消等能力逐项取证和验收；没有证据的能力不得标为已支持。

保存的 `logs/_e2e_verify.txt` 等结果曾报告 Python V1 `/api/ide/v1/chat` 成功；handoff 记有 V1 路径与验证命令（`notes/HANDOFF-2026-10-27.md:117-123,482-488`）。本轮未重跑，因此这里只把它作为既有结果，不作为当前重验。它不证明原生正常会话也调用该端点。当前原生 `lite.send_message` 的动态证据到本地 RPC 边界为止，尚未闭合到同 turn 的远端请求及响应。没有一条同 turn 的成功远端闭环时，结论应保持“路由/认证未确定”，不能写成 Python 不可行或已经复现原生链路。

## 结论独立审查

| 主张 | 直接证据与界限 | 审查结论 |
|---|---|---|
| “150 个 HTTP 组合都 404，因此远端没有 HTTP 接口” | `tests/probe_v1chat_sweep.py:39-44` 仅定义 10 前缀×5 尾缀×3 方法；`83-103` 遇到第 41 个非 404 即退出（`hits > 40`）。保存输出 `logs/_v1chat_sweep.txt` 可见 40 个通用 TLB `405`；记录中 405 本身也不是 404。正控制只证明列出的 `/api/ide/v1/ping`、`/api/ide/v1/chat` 与特定 `create_agent_task` 请求可响应，见 `notes/FINAL-VERDICT.md:32-47`、`tests/probe_v1chat_sweep.py:106-120`。另有 36 项 POST 矩阵，不是全接口穷举：`tests/probe_url_matrix.py:31-36,70-93`。 | **错误/过度外推。** 实验排除的只是实际发出的有限 method/path/host/body 组合；150 是理论笛卡尔积，因提前 break 未执行完。它不能证明不存在其他 HTTP endpoint、动态路由、其他 host、body 或 transport。 |
| “aha IPC 说明 Python 独立复现不可能” | `notes/FINAL-VERDICT.md:53-71` 记录 cue-server 的 `@aha-kit/rpc` / `electron.ahaIpc` 连接日志，但无同 turn 的 RPC 内容与远端请求关联；`71` 将“日志没记 HTTP”推到“不通过 HTTP”属于从日志缺席推断。其 `77-92` 架构图把 remote host 与 aha IPC 箭头混在同一处，不能作为 transport 证据。`notes/sidecar-ipc-findings.md:11-42` 观察到特定 sidecar 没有 TCP listener/连接并记录 toolhost named pipe；`tests/probe_sidecar_ipc.py:46-67,73-125` 只向 toolhost 命名管道尝试了 guessed JSON envelopes/framing，不是对所有 Mojo/aha/local entry 的穷尽。 | **不成立。** aha 是当前某条本地进程间通道的证据，既不否定 Python 对已知远端 HTTP 的独立调用，也不证明远端调用只能经 aha。它可能意味着完整 IDE session/state 复刻需要额外协议，但本计划目标只要求经证实的远端推理。 |
| “`llm_utils_chat` 返回 4011，因此它不是主对话端点” | `tests/probe_4011_scope.py:47-58` 将含 “exceeded the rate limit” 的文本归为 `4011-limit`，并将含 “no function config found” 的文本分另一类；`107-140` 对该函数改若干字段，并与同一时刻的 V1 chat 对照。记录显示 V1 200/SSE 而 `llm_utils_chat` 仍被归类为 4011。 | **未证。** 这支持限制与此 endpoint/function/request family 有关、而非当时全部账户请求都失效；不证明服务端的 4011 规则，也不能证明另一个 native caller 不会使用此路由。`llm_utils` 这个名字以及 4011 都不是“非主对话”的调用图证据。 |
| “28 种 SSE 事件中只有 3 可达，其余 25 在 aha IPC” | `tests/re_sse_enum.py:45-54,57-90` 预置 28 个词，再从 `harness.dll` 查连续字符串 `task_createdthought` 及邻接字节；没有解析出 serializer/callsite 或证明它们全是 SSE wire enum。`tests/probe_reachable_events.py:34-42,53-105` 只向 V1 `/api/ide/v1/chat` 发四种请求形状。保存结果 `logs/_reachable_events.txt` 的 distinct wire labels 为 `done, metadata, output, progress_notice, prompt, token_usage`：其中仅 3 个在 28 词表中，另 3 个不在词表。handoff 把这组窄范围结果外推为 25 个位于 aha，见 `notes/HANDOFF-2026-10-27.md:190-216`。 | **层级混淆。** 28 是 DLL 中静态字符串候选；四种 V1 请求只说明这次窄测试观察到哪些 `event:` 标签。没有证据把未观察的 25 个逐个归属到 aha，也没有证明它们都可从某个 SSE endpoint 收到。handoff 所说的额外 `error` 来自其他观察，不在上述四形状输出里。 |
| “`api/v1/chat/*` 是可确定的 HTTP 本地路由表” | `tests/re_rpc_http_map.py:46-49,61-81` 用相邻明文字符串正则配对 RPC 名与路径。其输出 `logs/_rpc_http_map.txt:24,27` 有 `start_chatstart_chat`、`subscribe_eventssubscribe_events` 拼接，边界不可靠。`notes/CALL-CHAIN.md:1-8` 自述只做静态反编译；`CALL-CHAIN-FINAL.md:1-3` 又明确被 FINAL-VERDICT 取代，正文仍作“localhost”调用结论。 | **候选而非契约。** 相邻字符串不是 route 注册、活动 callsite 或 serializer 证据。`VsockAiAgentClient` 字符串/代码也不能自动套用于桌面正常分支：`tests/re_lite_transport.py:18-25` 将其描述为 VM/remote runtime 候选。 |
| “结构体字段表是完整、权威 wire schema” | handoff `notes/HANDOFF-2026-10-27.md:152-179` 声称 Request=9、ChatArgs=61、CustomModel=31、ChatMessageData=46；`trae2api/trae_schema.py:29-38,41-104,128-138` 的字段数组实际分别为 8、49、32、26。即使字段名来自 serde 字符串，也不含完整类型、optional/default 语义或活动 endpoint 绑定。 | **矛盾且不完整。** 把该文件当字段摘录/静态线索；不能用于宣称完整 wire schema。 |
| “普通 CN 登录与代理的 GetUserToken mint 是一条已证链” | 当前代理 `trae2api/auth.py:266-295` 在 JWT 过期时调用 `/api/v2/GetUserToken`；`308-335` 才调用会影响 RefreshToken 的 `ExchangeToken`。项目已有 PKCE OAuth 登录：`trae2api/login.py:1-24,208-223,253-271`，它把 `ExchangeToken.Result.Token` 保存到 `creds.token` 与 `creds.jwt`。实证报告 `notes/REAL_PATH_REVIEW_2026-10-26.md:243-253` 记录一次固定 `api.trae.cn` GetUserToken 返回 404、未继续 V2，原因未知。安装原件静态 CN 登录链为 `ExchangeToken.Token → userInfo.token → native RPC params.user_info.token`，但没有证据继续映射至 LLM HTTP auth；SDK 接受 `jwt` 并构造 Authorization，但普通 CN `userInfo.token` 到该 prop 的 caller 未找到：同报告 `267-271`。 | **认证断点仍开。** GetUserToken 404 只否定此次具体请求，不证明旧 token 无效/登录失败，也不证明 ExchangeToken.Token 不能直接用。首轮 PoC 先复用已有、未过期凭据，不改现有 `token`/`jwt` alias、不触发刷新；若需独立登录，先追当前 CN token provenance 和目标远端 header 映射。项目的 PKCE 流程可按现有代码使用；GetUserToken 是代理当前 mint/fallback 路径，是否为当前 CN 正常登录所需仍未知。避免与正在运行的 Trae 并发轮换。 |
| “模型列表/响应 model 字段证明远端选中了所请求模型” | `/v1/models` 返回本地 `ModelCatalog` 名称：`trae2api/server.py:76-86`、`trae2api/model_catalog.py:8-23,64-86`；来源优先本机 state DB，缺失时用仓库 fallback JSON。聊天响应 `server.py:471,631` 使用调用者传入的 `model`；`gateway.py:274-285` 默认不把调用者 model_name 发到 V1 上游，除非显式 passthrough 或固定覆盖。 | **伪回显/目录不是可用性证明。** 不能据响应 model 或 fallback catalog 宣称选中了该模型；需要从成功远端响应/原生选择元数据确认实际路由。 |
| “静态 V2/V3 字符串证明当前会话用该路由” | `notes/REVERSE_NATIVE_CALL_CHAIN_2026-10-26.md:22-24,44-55` 记录 renderer→本地 RPC 的动态成功只到本机边界；AgentV3 和 V2 都在静态 endpoint table/cache 构造里，没找到到 `LiteHandler.send_message`/LLM caller 的可证链。`notes/REAL_PATH_REVIEW_2026-10-26.md:217-225` 记录 V2 一次假设 POST 得 400/0 字节，未确认 response schema/marker/model；`273-281` 记录 R4 未开始/未 attach/未发送，后续进程版本更新也没有 R4 数据。 | **未证。** route 存在不等于被调用；一次 400/空响应也不判定 route 不可用或 body/权限根因。R4 失败是测试未启动，不是未命中。 |

### 当前可证明的程序差距

- `trae2api/gateway.py:223-227` 先把工具声明和 tool_choice 文字放进 system turn，再调用 `drop_system=True`；`trae2api/translate.py:190-193` 会丢弃所有 system turn。因此 client 的 system 和工具声明在实际上游 body 中都消失。`translate.py:150-173` 也没有处理 `developer` role。此缺陷可由当前 builder 构造顺序和 helper 代码静态复现；现有 helper 测试默认 `drop_system=False`，不足以覆盖 gateway builder 路径：`tests/test_translate.py:90-98`。
- OpenAI 入参当前主要消费 `model`, `stream`, `messages`, `tools`, `tool_choice`：`trae2api/server.py:471-509`。`max_tokens`、`temperature`、`top_p`、`reasoning_effort` 等未映射到 V1 body；unsupported 不应继续静默忽略。
- 上游 stream 无 `done` 时，`server.py:435-452` 仍补发 `finish_reason=stop` 和 `[DONE]`；非流式路径在 SSE EOF 后未要求观察到 `done`，会于 `552-555,619-633` 返回 `stop`。上游 `error` 在 streaming adapter 中也被当普通内容发出并结束为 `[DONE]`：`server.py:371-381`。需区分真实正常终止、错误与截断。
- `metadata` 仅记录 debug、没有“首事件必须是 metadata”检查，也不从中解析/核验实际 model：`server.py:421-425`。所有 chunks 与最终 JSON 都回显输入 model：`server.py:335-345,455-460,627-633`。无 usage 时非流式响应补零：`633`，这不能声称为真实 usage。
- 当前 V1 有文本内嵌工具调用协议；服务器通过本地 prompt/translator/tool loop 兼容一部分工具，但这不等于上游原生结构化 tools。不得把 prompt 注入等同于服务端工具协议已经证实。

## 分阶段方案与门槛

| 阶段 | 进入条件 / 动作 | 交付物与通过条件 | 失败分支 |
|---|---|---|---|
| A. 认证链闭合 | 项目已有 `trae2api/login.py` PKCE 授权码流程，可通过独立 `creds_file` 保存自有登录结果（`login.py:61-74,208-223,253-271`）；自有凭据沿现有 token exchange/refresh 流程由单一写者维护。若借用已登录 Trae 的凭据，则只读复用有效值，不在 Trae 运行时刷新/轮换。暂保留 `ExchangeToken.Result.Token` 写入 `token` 与 `jwt` 的现有 alias，追踪它是否就是目标 HTTP 认证值；不能先移除 alias 或假设 GetUserToken 必要。cue、agent、account 等是不同 boot-config 键，分别核对 host，不能把 cue log 中的域名直接当 agent 目标。 | 字段级 token 流向图：来源→本地对象→发送到哪个服务的哪种认证头。通过条件是当前 CN 正常分支与目标 inference request 的 token/header 对应被源码/同 turn 观察闭合。 | 认证来源或 token 类型仍不明时停止远端 PoC，不轮换、不猜 host、不把 HTTP 404 归因到 token。保留“认证断点未解”。 |
| B. 真实远端边界 | 对当前安装版本复核进程创建时间、模块路径/hash、renderer/native route 和日志 session；用一次固定、全新 synthetic marker 的正常客户端 turn 配对观测。静态 xref 只用于选 hook/callsite。 | 同一个 turn 至少闭合：renderer service/method 与 session/message id hash → 本地 RPC 接收/响应 → 真实 egress 的 process/transport/host/path/method → response status/SSE event/terminal 与 assistant marker。为能构造真实 synthetic 请求，必须记录经审查的 allowlist 字段名、类型、嵌套、非秘密配置值、header 名及非秘密值来源/编码转换、关联 ID；凭据只用本地安全引用，禁止输出 secret 或用户正文。host 按服务配置键分别确认。R4 没有启动或捕获同 turn response，且缺 header getter 取证，因此不应称为完整配对观测：`notes/REAL_PATH_REVIEW_2026-10-26.md:273-281`。 | 无事件/覆盖为零/身份不匹配/只见 socket 或静态 URL，结果是“窗口无可见流量/未关联”，不能写“路由不存在”。更换安装版本后旧 RVA/ABI 不复用。 |
| C. 最小 Python 直连 PoC | 只有 B 给出一个同 turn 的真实成功 remote route 和 A 给出可用的认证映射后进入。Python 在 Trae 不参与转发的情况下发起第二条全新 synthetic 输入，使用新关联 ID；按照已观察状态顺序独立构造，不重放旧请求/旧 ID，也不预设 session state 一定在远端。一个请求预算，无模型降级、endpoint 探索或盲重试。 | 首先只要求普通文本：Python 的新请求收到与新 marker 对应的新 assistant 输出，成功/终止状态可解析，并能证明实际 model/config 来源；若是 SSE，以取证确认的该 flow terminal 为准，不对所有协议强加 metadata 首事件。PoC 可以是 Python CLI，不依赖 Trae UI。 | 4xx/空响应/marker 未关联时保留净化分类，不推断是模型名、body、权限或 transport；回到 A/B 的具体断点。不得自动换模型或第二 endpoint。 |
| D. 接入通用协议代理 | C 的普通文本 PoC 通过后，由主 agent 明确文件所有权，再实现独立、可配置的新 upstream channel，不替换未经证实的原路径。 | 按证据逐项支持 OpenAI messages/system/developer/tools/tool_choice/reasoning/stream/usage/finish/cancel；保真支持项，unsupported 项返回清晰能力错误。响应 model 来自真实上游元数据或被证明的选择值；usage 缺失时标为未知，不伪造零。metadata/model config 要校验来源和顺序，不假设“第一事件必为 metadata”。 | 某能力没有远端证据就标为不支持/实验，不用 system prompt 隐式模拟成原生能力；不影响旧配置的调用路径。 |
| E. 隔离验收 | D 的离线翻译和解析检查通过后，使用独立空闲端口/实例；仅走正常账号与短合成消息，不重启现有 8080。 | 先验收最小文本；其后按能力门控验收 stream 与非流、真实 model/config、错误/超时/取消/usage，再分别验收 tools/tool_choice 往返、developer/system 和 reasoning。对照记录请求/响应投影、命令、文件清单、未验证项。 | 任一阶段失败只回退对应能力，不宣称完整原生等价；不抓取 raw body、header、credential 或用户对话，不 commit/push/deploy。 |

### 建议的代码边界与能力矩阵

实现阶段可拆成 `auth`（凭据来源/更新策略）、`config`（host 与非秘密请求设置）、`model`（真实选择与可用性）、`session`（ID/history 生命周期）、`upstream`（HTTP/IPC transport）、`events`（流解析及终止状态）、`protocol`（OpenAI 入参与回包适配）。保持 upstream 可切换，避免把尚未证实的 native route 混入现有 V1 路径。

初始能力矩阵应明确区分：普通文本（待新 Python PoC）；system/developer/tools/tool_choice（当前构造缺陷，修复后逐项验证）；model/config（回显和本地目录不构成选择证据）；reasoning、stream、usage、finish/error/cancel（按实际远端事件/响应分别验证）。不得以完整 tools/reasoning/stream 验证作为普通文本 PoC 的前置条件，也不得把未验证格子标成支持。

## 执行状态更新

- 150-path、IPC、4011、28-event 结论已按上表降级。
- 现有 V1 `/api/ide/v1/chat` 是可调用路径的证据；它是不是当前 native 正常会话的 route 仍未证明。
- V2 静态 builder/route 存在，单次假设诊断未建立成功契约；V3/Agent route strings 和连续 28 个事件名都不是活动调用证据。
- 普通 CN `ExchangeToken` 到 native RPC `user_info.token` 有静态链；从 native RPC token 到当前成功 LLM request 的认证头/transport/path 尚无闭环。
- 后续 45 秒 metadata-only baseline 安装了 `InitWithParams` 与 `Start` 两个 hook，Init/Start 均为 0；卸载、detach 和 same-identity 检查成功。窗口内没有 UI 测试输入，因此这只说明该窗口无可见 Cronet 请求，不说明 route 不存在或 Python 不可行。详细结果见 `notes/NATIVE_REMOTE_CONTRACT_2026-10-27.md`。
- 离线 body projection helper 已通过本地合成测试，但未挂到 observer；它不能证明任何 native body 被捕获。默认未配置 request-marker contract 时会拒绝 upload read；合成 fixture 只检查约定数组的末项是否为含 marker 的 user/content。真实 wire schema 尚未确认，不能把 fixture 当 production contract。helper 已补 pending-read、identity-history 与 buffer-size 快照上限；response assistant marker 仍可能是 prompt echo，SSE marker 跨 delta frame 可能漏标。实流 schema/同请求绑定和 UI 固定回复确认前，不能把投影当成功证明。
- 最小下一步是确认 UI/model/new-turn 状态后，用一次有证据的同 turn 观察闭合远端请求与响应，然后才做独立 Python 普通文本 PoC。没有闭环时，不作“Python 不可行”或“原生协议已复现”的结论。
