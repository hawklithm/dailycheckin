# 为什么 trae2api 现在不是"真正的 Trae 链路"（实测证据）

调查时间 2026-10-26。结论基于本地反编译产物 + 实机端口 + 线上探针，不是推测。

## 1. 真正的 Trae 是三层，我们只复现了最外层

从 `ai_agent.dll`（265MB Rust sidecar，路径 `resources\app\modules\ai-agent\`）
里残留的源码路径可以还原出架构：

| 层 | 谁 | 协议 | 模型选择 | 工具 |
|---|---|---|---|---|
| 渲染层 (JS) | workbench | 本地 RPC `{service:"chat",method:"chat"}` | 不参与 | 不参与 |
| **sidecar (Rust ai_agent.dll)** | 本机进程 | **HTTP → LLM 供应商直连** | **`config_name` + `model_name`** | **原生 tools 数组** |
| 网关 `/api/ide/v1/chat` | trae-api-cn | SSE 文本 | 服务端决定（我们传什么都被 4023） | 无 tools，`<\|FunctionCallBegin\|>` 文本标记 |

sidecar 里的源码文件证明它自己就是 LLM 客户端：
`src\domain\agent\agents\{chat,builder,solo_builder,custom}.rs`、
`LLMAdapter`、`ModelConfig`、`custom_model_proxy_client.rs`。
它直连供应商的路径包括 `/models/chat/completions`（deepseek/openai/custom/xai）、
`/v1/messages`（anthropic）、`gemini`、`openrouter`。

**我们打的是第三层**（V1 网关通道），前两层完全没有。

## 2. 模型不是我们选的 —— 实测证据

```
探针: "你是哪个模型？"
回答: "我是豆包，是由字节跳动独立开发、训练的生成式人工智能助手..."
```

客户端请求 `model: deepseek-v4.1-flash`，实际应答的是 **豆包**（服务端默认）。
`core-findings.md` §8 已记录：传任何本地目录模型名 → `4023 model unknown`；
省略 `model_name` → 服务端默认模型。sidecar 日志格式串证实了模型是服务端下发的：

```
[ModelConfig] Received config_name=?., model_name=?., max_turn=?., prompt_max_tokens=?., max_tokens=?.
[LLMAdapter] llm_raw_chat_custom_model: prompt_set=?., ab_version=?., config_name=?., model_name=?.
```

`config_name` / `prompt_set` / `ab_version` 我们一个都没传 —— 这些才是决定
用哪个模型、用哪套 prompt、开不开深度思考的开关，全部在原生层组装。

## 3. 官方控制台看不到消耗 —— 确凿证据

每次请求的 `gateway_body` 是 **15–17 KB** JSON，但返回的 `token_usage`：

| body 字符数 | prompt_tokens | completion_tokens |
|---|---|---|
| 319 | 48 | 24 |
| 1358 | 259 | 22 |
| **17477** | （未计） | — |

17KB 的 payload 报 48 tokens 是不可能的。说明 **我们这条链路根本没有进入
计费/统计的埋点**，走的是网关的边缘轻量通道。真正产生消耗的是 sidecar →
供应商那层，token 由供应商侧统计并回传控制台。

## 4. 思考深度受限 —— 机制解释

sidecar 里有 `reasoning_effort` / `context_window_sizes` / `max_turn` /
`prompt_max_tokens` 这些字段，随 `ModelConfig` 一起下发。V1 通道的请求体里
**没有**这些字段的位置（我们发的字段实测只有 11 个：
user_input / session_id / chat_history / workspace_folders / mention_context /
parsed_query / agent_type / scene_location / agent / message_content / message_id）。

对比 JS 层组装的真实请求体字段：
`agent_type / chat_model / call_model / agent_id / agent_name / operation_id /
chat_session_id / chat_message_id / trigger_type / chat_type ...`
我们缺 `chat_type`、`chat_model`、`call_model`、`chat_session_id`、`chat_message_id`。

所以"思考浅"不是模型差，是 **通道本身是给轻量场景设计的**：无 tools 数组、
无 reasoning 控制位、无模型选择权。

## 5. 我们走的确实偏 chat

虽然 `agent_type=builder` + `scene_location=2` 已强制（commit 8bac8e4），但
`chat_type` 从未发送，而 sidecar 里 `chat.rs` / `builder.rs` / `solo_builder.rs`
是三套不同的 agent 实现。没有 `chat_type`，服务端无法区分，很可能仍按
默认 chat 分支处理。

## 6. 结论与可选路径

**当前状态**：能对话、能跑工具（本地桥接），但不是真链路；不计费、模型不可控、
思考深度不可控。

**要走真链路，只有两条路**：

- **A. 打 sidecar RPC**（推荐先摸清）：Trae 正在运行，本地监听 **`127.0.0.1:51000`**
  （Trae CN.exe PID 74640）。这是渲染层 ↔ sidecar 的本地 RPC 口。若能复现
  `{service:"chat",method:"chat",data:ChatArgs,user_info}` 协议，就能借道真正的
  sidecar → 供应商链路，模型/工具/计费全部对齐。需要抓本地 RPC 帧（不是 HTTPS，
  无 TLS 干扰）。
- **B. 抓包 sidecar → 供应商**：sidecar 出网是直连供应商，需要 mitmproxy + 证书。
  拿到 provider 端点与凭证即可自建，但等价于造新客户端，且凭证动态下发，风险高。

**下一步建议**：先做 A —— 在 51000 上抓一次真实对话的本地 RPC 帧（Trae 里随便
问一句），确认协议形状。这是唯一能同时解决"计费 + 模型 + 深度"三个问题的入口。
