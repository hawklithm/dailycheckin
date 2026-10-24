# MarsCode/Trae VSIX 插件 (1.7.13) 工具机制分析

> 目的：解释桌面 Trae 与本插件在 tool-use 上的协议，寻找比"prompt 声明工具"更优的方案。

## 1. 插件架构与桌面版同源：核心 AI 在原生 sidecar

VSIX 结构：
- `extension/dist/extension.js` (13.4MB) — VSCode 扩展宿主 JS，**不含任何工具协议字符串**
  （`FunctionCallBegin`/`tool_calls`/`"tools"`/`tool_choice` 全部 0 命中）
- `extension/resource/aiserver/aiServerMainV2.js` (14MB, 混淆) — 同上
- `extension/resource/aiserver/resources/binaries/win32-x64.7z` (88MB 压缩/605MB 解压) —
  **原生 sidecar，与桌面 Trae 的 `modules/ai-agent/` 完全同构**：
  `ai-agent.exe` (385MB)、`agent-tool-host.exe`、`sscronet.dll`、`vm_sdk.dll`、`ckg_server`
  —— 解包后字符串与桌面版 ai_agent.dll 逐一致（serde 结构名、ABTest 键、工具注册表全同）

结论：**市场插件 = 桌面 Trae 的轻量壳**，工具循环都在同一个 Rust sidecar (`ai-agent.exe`,
源码路径 `apps/icube_server_rs/...`) 内完成。JS 层只是 IDE 集成壳。

## 2. LLM 线协议 = 标准 OpenAI 格式（含 tools 数组！）

`ai-agent.exe` 内 llm-client crate（`crates/llm-client/src/model/raw_request.rs`）的请求结构：

```
struct LLMClientRequestRaw with 11 elements:
  model, messages, stream, max_tokens, max_completion_tokens, system,
  tools, usage, user, thinking, reasoning, inferenceConfig, anthropic_version

struct LLMClientMessageRaw: role, content, reasoning_content, tool_call_id, tool_calls, reasoning_details
struct LLMClientToolCallItemRaw: index, id, function, extra_content
struct LLMClientToolCallFunctionRaw: name, arguments       ← arguments 是字符串 (OpenAI 原样)
struct LLMClientFunctionCallRaw: name, arguments
```

Provider 分发（同 exe 内字符串）：`/models/chat/completions` (deepseek/openai/custom/xai)、
`/v1/messages` (anthropic)、`gemini`、`openrouter`、`aws/foundation-models/openai/v1/chat/completions`。

**注意**：这是 sidecar → 模型供应商的直连层（豆包/DeepSeek/Anthropic/Gemini...），
不是 sidecar → trae-api-cn 网关的层。

## 3. 两层协议的关键区别

| 层 | 协议 | tools |
|---|---|---|
| sidecar → LLM 供应商 | 标准 OpenAI/Anthropic | **请求体 tools 数组**（原生 function calling） |
| IDE(JS) ↔ sidecar | 本地 RPC `{service:"chat",method:"chat",data:ChatArgs,user_info...}` | 无 tools（工具决策在 sidecar 内部） |
| 桌面/插件 webview → trae-api-cn `/api/ide/v1/chat`（V1 HTTP 直连） | SSE 文本协议 | 无 tools；`<|FunctionCallBegin|>` 文本标记出站，工具结果以 user 文本回传 |

sidecar 的工具注册表（exe 内字符串，桌面版同名）：
`view_file(s) / edit_file(+search_replace/update_fc/fast_apply/rewrite/rename) / create_file /
write_to_file / delete_file / run_command(+check_command_status) / search_by_regex / show_diff /
apply_patch / view_folder / todo_list / MultiEdit / NotebookEdit / Write / Edit ...`
—— 工具**执行端**在 sidecar/IDE，模型只出调用。

`native_function_call` ABTest 开关 + `nfc_use_original_tool_call_id` + `parallel_tool_calling`
说明：当模型支持原生 function calling 时 sidecar 走 tools 数组；否则退化为文本标记协议
（桌面版 V1 通道看到的 `<|FunctionCallBegin|>` 正是这个退化格式）。

## 4. 对 trae2api 的启示

- `/api/ide/v1/chat` 的 4023 模型白名单 + 无 tools 字段 = V1 通道就是给
  "服务端控制工具集"的轻协议设计的；**真正的工具循环在 sidecar 的
  OpenAI 直连层，那里 tools 由 sidecar 从工具注册表组装**。
- 所以"把 tools 塞进请求体"在 V1 通道上没有官方路径；prompt 注入是
  在 V1 通道上唯一能对齐工具表的方式（我们已实现）。
- 若要"原生 tools 数组"，需要复现 sidecar → 供应商层，但那层需要
  provider 端点/凭证（从动态配置下发），等价于造一个新客户端，风险高。

## 5. 用户报告的问题："system 里给工具列表没生效，模型不下发工具指令"

可能性排序：
1. **V1 通道服务端 prompt 拼装覆盖/削峰**：`ide_prompts` 由服务端构建
   （progress_notice 事件"Building prompt: ide_prompts"），我们的 system 段
   若拼在 user_input 里且服务端把它当作普通用户文本，权重可能低于服务端工具说明；
2. system 前缀放在 user_input 首部（`【系统指令】...`），离模型"工具选择"的
   上下文位置太远；
3. 需要验证：抓 trae2api trace 里带 tools 声明请求的实际 user_input，
   确认注入文本确实到达；再对比模型行为。

下一步（按收益排序）：
a. 抓取带 prompt 声明的请求 trace，验证注入文本在线上确实存在；
b. 尝试把工具声明放到 chat_history 的 assistant 消息末尾（更接近"工具说明"位置）；
c. 尝试 `intent_name:"chat"` 之外的场景值（若有 agent/builder intent，服务端
   工具集会切换——桌面版有 `chat_mode: DEV/BUILD` 之分）；
d. 确认 `Request.common_params.chat_mode` 是否影响服务端工具集。
