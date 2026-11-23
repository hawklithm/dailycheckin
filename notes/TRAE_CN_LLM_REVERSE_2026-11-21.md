# Trae CN 3.4.22 LLM 调用链静态复核（2026-11-21）

## 范围和结论

本次对当前安装的 Trae CN 3.4.22 做静态分析，并参考本仓库此前的取证记录。读取的是应用安装包和项目源码；没有读取用户对话或凭据、附加进程、调用远端模型、刷新 token 或改动安装程序。旧报告研究的客户端版本和当前版本不同，不将旧偏移量和动态观察直接套用到当前程序。

当前已闭合的是本地发送链：Solo Lite 根据会话配置构造消息和模型选择 -> 本地 `lite.send_message` -> Workbench 补充 user_info、common_params、client_info -> TransportManager 的本地 request/request_stream -> native ai-agent。另有 `lite.subscribe_events` 本地事件订阅。当前还没有把一条实际 UI 输入与某一个远端 HTTP 请求、请求体、返回事件及 UI 回复一一关联，因此**真实 LLM 远端 wire contract 未闭合**。已有 Python V1 代理是历史上曾成功的另一条实现，不能等同于当前原生主对话链。

## 安装版本及本轮依据

安装根：`%LOCALAPPDATA%\Programs\Trae CN\resources\app`。`product.json` 的 `appVersion=3.4.22`，`version/vscodeVersion=1.107.1`，`commit=9f58dbd63fc8d25d766e11c5362200684b5fac56`，构建日期为 `2026-11-18T03:40:14.422Z`。1.107.1 是 VS Code 基础版本，而不是 Trae 版本。

| 文件（相对安装根） | SHA-256 |
| --- | --- |
| `node_modules/@byted-icube/solo-lite/dist/8492.cc453581.mjs` | `4f15711d65c6631df5767cd83f850bf7dc80922533301353e27783c14d7b9f7f` |
| `out/vs/workbench/workbench.desktop.main.js` | `5e1d062620d4a38cc45a1cc6618d84aa707b97f622394b3c139372de28bfe108` |
| `node_modules/@byted-icube/ai-modules-chat/dist/index.mjs` | `1fcad7588f3f6cb0629ae6dc2e2af8ded8dc5240ecaafdc7b55fdd372476353d` |
| `modules/ai-agent/ai_agent.dll` | `aaa884e34e98e543e030493b354e898e565050046bbb9ed236ab6139741741a7` |
| `modules/ai-agent/harness.dll` | `89663a4d602a661641454d930a6c21762b2424559544bcbaebd8696fcff46be1` |

下列 JS 偏移为 UTF-8 文件字节偏移，native 则区分 file offset 与 RVA。它们只适用于上述哈希。

## 当前原生侧消息链

1. `solo-lite/.../8492.cc453581.mjs` 中 `getModelRequestSelection` 位于 `0x67210d`。固定模型配置走手动选择；自动策略返回空 `modelName` 和 Auto；手动策略可读取 per-session、agent type、策略限制、Max 档及 reasoning effort，再构造 `custom_model`。这些是构造本地请求的静态分支，不表示特定账号当前可用哪个模型。
2. 同文件 `buildSendMessageRequest` 位于 `0x6730fc`，构造 `chat_session_id`、`query=JSON.stringify(...)`、`content: []`、`model_name`、`agent_type`、`agent_id`、`model_selection_strategy`、`custom_model`、`common_params`，以及可选的 session、重试、权限、来源、worktree、workspace 等字段。这是**本地 RPC payload**，并非已证实的 HTTP body。
3. 同文件 `chat.sendMessage` 映射 `service=lite, method=send_message`，`chat.subscribe` 映射 `lite.subscribe_events`（映射附近 `0x472bce`）；`subscribeStream` 在 `0x671637` 注册会话流处理器；`this.chatApi.sendMessage(...)` 调用在 `0x6771f2`。订阅与提交是两个本地方法，不应当作远端 URL。
4. Workbench `getUserInfoWithToken`（`0x480143`）调用 `getUserInfoFresh()` 并把返回 token 与用户元数据放入对象。请求封装 `0x48a9bf` 构造 `service`、`method`、`data`、`user_info`、`common_params`、`streamlined_common_params`、`client_info`。流式桥在 `0x48742b` 调用 `sendStreamRequest("request_stream", ...)`。这些是当前静态调用点；尚不能据此确定 native 侧到远端的最终字段/认证映射。

## 当前二进制中的候选后端链

`ai_agent.dll` 当前镜像含候选字面量（无前导 `/`）：`api/agent/v3/create_agent_task` file offset `0xa4ce750`，`api/agent/v3/llm_utils_chat` `0xa4ce841`，`api/agent/v3/workflow/start` `0xa4ce85c`，`api/ide/v2/llm_raw_chat` `0xa4cec00`。这些只证明字符串存在。

进一步对该文件做同样的定向交叉引用，完整结果见 `notes/trae_cn_3422_ai_agent_xref_2026-11-21.json`。`create_agent_task`、`llm_utils_chat`、`workflow/start` 的字面量都被同一 PE runtime function `[0x6538fd2, 0x65392b4)` 引用；机器码依次把指针和明确长度传给 `0x63e4cc3`。按每次指令给出的指针及长度解码，可得到 16 个路径：

```text
api/agent/v3/create_agent_task
api/agent/v3/commit_toolcall_result
api/agent/v3/interrupt
api/agent/v3/resume_agent_task
api/agent/v3/get_resume_agent_task_status
api/agent/v3/query_history_state
api/agent/v3/sync_history_state
api/agent/v3/compact
api/agent/v3/llm_utils_chat
api/agent/v3/workflow/start
api/agent/v3/workflow/commit_toolcall
api/agent/v3/use_fast_request
api/agent/v3/generate_summary
api/agent/v3/dsl/logs/subscribe
api/agent/v3/dsl/templates
api/agent/v3/dsl/render/resources
```

这比依据相邻字符串拆分更可靠：本轮边界取自每个调用的显式长度，而非推测分隔符。不过它仅建立这些名字被同一函数构造，不能据此认定 HTTP 方法、请求字段、远端响应或当前活动路径。`api/ide/v2/llm_raw_chat` 的静态引用位于另一函数 `[0x6539804, 0x653a758)`；本轮没有确认两者的调用关系。

本轮对当前 `harness.dll` 做了 PE/Rust 字符串与 Capstone 验证的定向交叉引用，机器可读结果见 `notes/trae_cn_3422_native_xref_2026-11-21.json`：

- `/api/agent/v3/llm_utils_chat` 位于文件 `0xec8aad9` / RVA `0xec8bcd9`，有一个指向字符串起始地址的 RIP-relative `lea`，指令 RVA `0x90bb1a4`，所在 PE runtime function 为 `[0x90bb120, 0x90bb20b)`。
- 该函数把字符串指针与长度 `0x1c` 放入结构后调用 RVA `0x90d48d0`；这支持“函数使用该路由字面量”，**不单独证明是 HTTP 发送、请求成功或主对话**。
- 对 `.text` 的相对直接调用字节模式做候选扫描后，从 PE runtime function `[0x2aa19d0, 0x2aa2d29)` 的起点反汇编，确认 RVA `0x2aa2c50` 是边界有效的 `call 0x90bb120`。同一 runtime function 还引用静态字符串 `[CodeReviewJudge] auxiliary request failed; proceeding` 和包含 `model_policy/strategies/code_review_judge/client.rs` 的源码路径字符串。**推断**：这至少是一条与 CodeReviewJudge 辅助逻辑相关的调用线索；这些字符串和调用同处一个函数不证明它在当前 UI 轮次触发，也不能排除别的直接、间接或动态调用者。同一字节模式扫描未发现指向 `0x2aa19d0` 起始地址的直接相对 call；这不排除函数指针、间接跳转或其他入口。
- 同一 xref 工具对所选 `api/agent/v3/create_agent_task`、`api/agent/v3/workflow/start`、`api/ide/v2/llm_raw_chat` 字面量没有找到精确 fat-string 对或受工具范围约束的 RIP-relative 引用。该结果不能排除其他编码、字符串拼接、表索引或间接引用，也不能证明路由不可达。

`ai-modules-chat/dist/index.mjs` 中 `LLMRawChatV2`（`0x780f0`）静态构造 POST `/api/ide/v2/llm_raw_chat`，映射 `config_name`、`model_name`、`session_id`、`messages`、`tools`、`stream`、`reasoning_effort`、`provider_context` 等。SDK wrapper 在 `0x97332` 能构造 `Authorization: Cloud-IDE-JWT …`。这是存在的 SDK builder；本轮没有证明 Solo Lite 的 `send_message` 调用该 builder，也没有证明它与当前桌面流式响应是同一机制。

## 历史运行时证据（旧版本）

[2026-10-27 的配对元数据复核](NATIVE_CAPTURE_SESSION_2026-10-27.md) 曾观察到 `llm_utils_chat`、`create_agent_task`、`workflow/start`、`sync_history_state` 等路由对应的请求启动，但没有同一请求的正文、响应或可靠 UI turn 关联。之后的 [paired-c 上传观察](NATIVE_REMOTE_CONTRACT_2026-10-27.md) 有三个候选路由的请求、各自的非明文认证匹配，但结构化投影被 writer 丢弃，无法恢复；用户报告 UI 返回 marker，但观察器未将其绑定到同一请求。所记录的 token 值未公开，认证匹配本身也不证明服务端接受或请求属于目标轮次。

老 handoff 中“全部 LLM 走 aha IPC”“其他事件只能在 IPC 里”“4011 已证明某路由不是主对话”“若干百个路由全不存在”等结论已被后续复核撤回或限定；字符串邻接、尝试失败和局部窗口不能证明这些结论。见 `notes/PYTHON_CLIENT_REPRODUCTION_PLAN_2026-10-27.md` 与 `notes/NATIVE_REMOTE_CONTRACT_2026-10-27.md`。

## 历史 Python 代理的真实实现和限制

`trae2api/server.py` 接收 OpenAI 兼容请求；`gateway.py` 的 `build_chat_body()` 将消息转换为 `user_input`、`session_id`、`chat_history`，并构造 workspace 和 agent 相关的兼容字段，通过 `POST /api/ide/v1/chat` 发出请求。`translate.py` 将 system/developer 指令和工具声明编码成普通用户文本，并把特定文本标记解析成 OpenAI tool calls；这不是已证实的原生结构化工具协议。

现有代理默认不传调用方模型名，除非设置 `TRAE2API_MODEL` 或显式开启实验性的 `TRAE2API_PASSTHROUGH_MODEL`。`/v1/models` 的本地列表不证明远端实际选择了该模型。历史保存结果报告 V1 曾返回有效 SSE，但本轮没有重新对上游发模型请求；它不证明当前 3.4.22 原生链、模型选择、工具行为、计费或版本兼容性。

现有网关 `_headers()` 通过认证包 `get_jwt()` 取凭据。普通 CN 登录、原生 RPC `user_info.token` 和最终 HTTP 认证头之间的对应关系，本轮未用同一新请求闭合。旧 `GetUserToken` 的一次 404 只说明当时固定请求失败，不证明普通 CN 登录无效。`gateway.py` 默认会记录请求 body 和原始 SSE 到 trace 文件（`TRAE2API_TRACE=off` 可关闭），使用历史代理做任何实验时应先考虑对话内容落盘。

## BuddySwitch 实现对照（2026-11-21 补充）

对照 BuddySwitch `origin/main`，commit `ebcaead17196c6127ed2cb85669443bfc981047f`（2026-11-18）。初次检查使用本地 `git show`；用户要求拉最新版后，于 2026-11-21 执行 `git fetch origin --prune` 并用 `git ls-remote origin HEAD refs/heads/main` 确认远端 HEAD 与 main 均为该 commit。原工作树 HEAD 是较早的 `23acf3b` 且 `package-lock.json` 有预先存在的修改；因此在 `<工作区>\buddyswitch-latest-ebcaead` 创建该 commit 的独立只读用途工作树，原工作树没有被覆盖。下面的行为是**该版本源码的实现**，不等价于我们本次已复现当前真实上游。

- `crates/buddy-switch-gateway/src/trae/mod.rs` 定义 `https://trae-api-cn.mchost.guru` + `POST /api/agent/v3/llm_utils_chat`。源码把当前 CN Trae/合并版归到 `function=chat_v3`，TraeWork 用 `solo_work_lite`。其注释声称历史探测中同一模型的不同 function 与名称后缀会导致不同结果；这些是项目作者的历史实测记载，当前账号和当前上游未复测。与此前只测过其他 function 的 4011 观察相比，这是一条更强的独立客户端实现线索，并不证明它就是 Trae 3.4.22 的原生主对话路径。
- `payload.rs::prepare_llm_chat_body` 把入口 OpenAI 风格 body 改写为上游格式：消息字符串转 `[{type:"text",text:...}]`；历史 assistant `tool_calls[].function` 改为 `function_call`；`tools[].function.parameters` 对象序列化为 JSON 字符串；归一 `tool_choice`。它保留结构化消息/工具，而现有 `trae2api` V1 主要用用户文本及标记模拟工具。
- 该版本注入 `config_name`、`model_name`、`function`、`stream=true`、`conversation_id`、`session_id`、`user_id`、`device_id`、`machine_id`、`project_id`、`workspace_id`、`prompt_max_tokens=168000`、`mode=FunctionCall`、IDE 版本和 app ID 等。普通模型名通常派生 `config_name=<模型名>`、`model_name=<模型名>__dev`，并有历史别名表；源码明确提醒真实可用性必须按 function/模型逐项验证，不能把派生规则视为无条件保证。会话 ID 从对话标识和账号生成稳定 UUID 形态，属于 BuddySwitch 的代理策略，不等于从原生捕获的 wire 值。
- `routes.rs::send_llm_chat` 的该版本对话请求使用**裸 token**的 `x-ide-token`，没有在该函数中设置 `Authorization`；另带 app、设备、版本、区域/包类型与链路追踪头。BuddySwitch 根据用户 ID 确定性派生设备 ID 和 machine ID；这与本仓签到目前采用的真实注册/按账号绑定设备路径不同，不能据单次成功推断两者互换或注册状态等价。
- `sse.rs` 处理 `output`/`thought`、`token_usage`、`metadata`、`done`、`turn_completion` 和 `error`；对 `tool_calls` 按 index/id/最近槽位组装跨帧增量，再转换为 OpenAI SSE；非流式在本地聚合。缺少 index/id 的并行调用存在实现自身注释所述的歧义。模型清单来自客户端缓存和可选目录接口；理由及字段见 `model_list.rs`、`catalog.rs`，不应把静态兜底列表当成实时可用性证明。
- 该源码的 `probe_traecode_model_names` 标记为 `#[ignore]`，须真实账号、真实网络且会消耗积分；它以 `metadata` 或 `error` 为可否接受的判据，并非本次独立执行的完整生成证明。`tests/trae_gateway_e2e.rs` 明确使用本地 mock 上游，能验证本地路由/转换/换号，不能证明真实上游可用。本轮未运行这些在线探针，也未拿真实凭据作 HTTP 请求。
- 本仓旧的 `tests/probe_4011_scope.py` 以 `solo_agent` 为基准，测试 `model_name=config_name=deepseek-v4.1-flash`（没有 `__dev`）等变体，并使用旧版设备头和另一个 body；它没有测试 BuddySwitch 的 `chat_v3`、`__dev` 模型名及完整请求的相同组合。因此当年的 4011 不能被用作拒绝 BuddySwitch 方案的对照，反过来也不能用 BuddySwitch 注释否定当年的原始观察。
- `effort.rs` 的思考档位注入默认关闭，源码明确标注上游是否接受 `model_info.reasoning_effort_level` 尚未实测。`capture.rs` 的诊断捕获默认关闭，开启会落盘请求体与原始响应；不要把它当成脱敏观测。

因此，后续 Python PoC 的最小候选方案应优先以该 commit 的 `chat_v3` 请求构造、裸 `x-ide-token`、结构化 messages/tools 与 SOLO SSE 解析为依据，在合成 fixture 下先做逐字段比较；然后才用单账号、单次短请求检查 HTTP/SSE、返回模型和实际生成结果。可用性、计费归属、结构化工具及当前版本的原生等价性均需分别验证，不能由历史注释或 mock 测试直接推出。既有 V1 路径暂不能因此宣称已替换或已失效。

## 下一步闭环所需证据

1. 固定一个当前客户端版本、一个新会话和一条无隐私的唯一测试输入，先验证 UI 确认收到回复。
2. 重审当前 DLL 及运行时 transport、进程身份和 ABI；旧版 Frida 目标、偏移、hook 和先前 body schema 不能直接复用。
3. 对应单次 turn 先获得经过严格过滤的网络元数据与请求关联，再单独验证请求 body 的字段、所选模型配置、认证来源及响应流；避免仅凭时间相近认定匹配。记录字段和标记，不保存 token 或用户原始历史。
4. 确认请求同源和响应归属后，才据此制作单次、可控的独立客户端 PoC，并分别检验文本、模型选择、工具、流事件和计费行为。

## 验证

- 当前安装文件静态检查与上面的哈希、字节偏移；原生交叉引用结果保存在独立 JSON。
- `tests/test_translate.py` 作为脚本执行：30/30 通过；`tests/test_gateway_body.py` 作为脚本执行：6/6 通过；`node tests/test_native_body_projection_core.js`：28 个离线用例通过。这些均不能证明当前远端调用。
- 本轮未发远端请求；没有重跑历史 V1 在线结果，也没有验证真实登录或签到。
