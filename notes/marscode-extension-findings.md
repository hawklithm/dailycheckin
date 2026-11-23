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


## JS layer follow-up

Method: `aiServerMainV2.js` is obfuscated with a single `_0x40d6(idx)` string decoder
(35,940-entry rotated array). I recovered the array, solved the rotation offset
(253), and replaced all 22,928 `_0xNNNN(0x...)` calls → `notes/aiServer_decoded.js`.
All quotes below are from that decoded file (offsets are in it) or from
`notes/strings_aiServer.json` (the plain string table).

### 1. JS → sidecar interface (the RPC envelope)

Every JS→sidecar call is a **JSON-RPC-ish envelope `{service, method, data}`**
(plus a typed `ProtocolRequestType` with `messageDirection: clientToServer`).
Verbatim (`aiServer_decoded.js` @12115451):

```js
Js = class {
  async ["getAgents"](x) {
    let r = await this.<apiService>['request']({
      'service': Js[0x5477],                       // e.g. "agent"
      'method': Js[0x487e][0x679f],                // e.g. "agent/get_agents"
      'data': x
    });
    if (r['code'] !== Im['<Code>']['Success']) throw new Error(r['message']);
    return r['data'];
  }
```

Same shape at @12116561 (createAgent), @13173004 (handler registry:
`_0x4b65fb['onRequest'](sr['ChatSendMessageRequest']['type']['method'], async …)`),
and @13532207. Method ids are plain strings in the table, namespaced by service:

- `chat/*` (55): `chat/send_message`, `chat/create_new_session`, `chat/abort_chat_session`,
  `chat/update_run_command_tool_status_from_user` (0x376d), `chat/model_list`, `chat/…`
- `code/*` (67): `code/get_code_of_file`, `code/fast_apply`, `code/update_agentic_tool_call_status`, …
- `builder/*` (13): `builder/list_mcp_tools`, `builder/mcp_server_install`,
  `builder/get_mcp_config`, `builder/update_mcp_server_config`, `builder/listen_mcp_change`, …
- `agent/*`: `agent/get_agents`, `agent/create_agent`, `agent/update_agent`,
  **`agent/get_builtin_tool_list`**, `agent/update_mcp_agent_relations`
- `common/*`, `workspace/*`, `cueIntent/*`

Transport: the sidecar (`aiServerMainV2.js` is itself `@ai-server/tob` v1.0.5) listens on an
**AHA IPC / ZeroMQ** channel — `new VEe({serverName, runtimeDir, onConnection, …})`,
`ahaIpcRuntimeDir`, `ahaIpcServerName`, `TRAENET_ZMQ_ENDPOINT`, `rzmq` bindings
(@13675043, @11835899).

### 2. Cloud chat endpoint + body

Two distinct clouds, both baked in as host constants:

```
https://api.trae.com.cn   https://a0ai.marscode.cn   https://a0ai-api.zijieapi.com
https://a0ai-api.byteintlapi.com   https://a0ai-api-sg.byteintlapi.com
```

Endpoint constants `@10780979`:
```js
var $fr="api/ide/v1/chat", pfr="api/ide/v1/intent_detect", Yjn="api/ide/v1/context_select",
    cVn='api/ide/v1/llm_raw_chat', nVn='api/ide/v1/model_list', rVn="api/ide/v1/features", …
```
Caller `@10783942` — `chatCompletionRequestWithNoAbort`:
```js
let url = await Q.get(Qs)["getCopilotUrl"]($fr, !0, this["envId"], this["region"], this["env"], this["isIDEExternal"], this["domainUrl"]);
let jwt = await _0xe9c76d["getJwtToken"]("others");
let hdr = await _0xe9c76d["getJwtTokenHeaderObj"]("chat");
let headers = {'Content-Type':"application/json", 'X-App-Id':this["xAppId"], ...hdr, ...body["header"]};
opts = {'responseType':'stream', 'headers':headers, 'timeout':0x3c*0x3e8, 'signal':ctrl.signal};
```
So: `POST {host}/api/ide/v1/chat`, JSON, `responseType: stream`, `X-App-Id` + a JWT header, 60s timeout.

Chat request body (`createChatRequestObject`, @12795844) — **no tools key anywhere**:
```js
let req = {
  'agent_type': …, 'agent_id': agent?.['agent_id'], 'session_id': sessionId,
  'message_id': userMessage['id'], 'mention_context': mentionContext,
  'model_name': modelInfo['model_name'], 'custom_model': modelInfo,
  'message_content': [], 'code_selections': [], 'scene_location': sceneLocation,
  'parsed_query': parsedQuery, 'multi_media': multiMedia, 'agent': agent, ...modelExtra
};
req['active_text_editor'] = activeTextEditor;
req['workspace_folders']  = (await this.workspaceService.getWorkspaceFolders())['folders'].map(f=>f['uri']);
req['message_content']    = [{type: Rd['<Type>']['Text'], 'text_content': text}, ...images];
```
`custom_model` carries `{provider, config_name, display_model_name, multimodal, ak,
use_remote_service, config_source, is_preset, base_url}` (@12802395).

Tool-related flags do exist but only as **opaque feature strings**, e.g.
```
{"apply_file_path":true,"is_new_pe":true,"native_function_call":true,"parallel_tool_calling":false,"use_v2_process":true}
{"apply_file_path":true,"enable_invalid_json_hint":true,"is_new_pe":true,"native_function_call":true,"parallel_tool_calling":false,"use_v2_process":true}
```
— these are server-side experiment/AB payloads, not per-request tool schemas.

### 3. extension.js / package.json

`package.json` `contributes.commands` = 30 commands, **all UI only** — no tool ids:
`trae.chat`, `trae.explainCode`, `trae.docGeneration`, `trae.buildEditRequest`,
`trae.acceptAllEdits/WordEdits/LineEdits`, `trae.selectNextEditRecommend`, `trae.loginTrae`, … .

extension.js: `ide_command` = **0 hits**; `registerTool` = 0; `executeCommand` = 34
(all VSCode UI, e.g. `vscode.diff`); `run_command` = 2 (one is the RPC method
`chat/update_run_command_tool_status_from_user`); `tool_call` = 2 (telemetry +
`code/update_agentic_tool_call_status`). No tool registration path.

### 4. Where tool NAMES do appear in JS (as display/telemetry constants only)

`aiServer_decoded.js` @9082112 — `ToolCallName` enum (the agent's canonical tool ids):
`run_command, open_preview, open_preview_and_wait_for_error, open_folder, create_file,
view_file, view_files, view_folder, edit_file_search_replace, write_to_file, show_diff,
search_by_reference, search_by_definition, search_by_regex, file_search, check_command_status,
delete_file, update_shallow_memento, condense_shallow_memento, run_mcp, finish, web_search,
response_to_user, search_codebase, todo_write, create_requirement, deploy_to_remote,
supabase_apply_migration, supabase_get_project, get_llm_config, stripe_get_config,
get_preview_console_logs, init_env, agent_finish`.

Also @10086517 (a *different*, older retrieval-agent config):
`AVAILABLE_TOOLS:["get_code_of_class","get_code_of_class_function","get_code_of_file_function","get_code_of_file","grep","get_symbol_reference","get_similar_code","exit"]`,
`MAX_TOOL_CALL_COUNT:10`, `TOOLCALL_DISPATCH_TIMEOUT:3000`.

MCP is real and JS-side: `mcpServers` config, `builder/list_mcp_tools`,
`builder/mcp_server_install`, `callTool`/`listTools` over the standard MCP stdio protocol
(zod schemas for `tools/list`, `tools/call`, `notifications/tools/list_changed` @12270389),
and MCP tool schemas ARE returned to JS as `{name, description, inputSchema}` (@12618885).

Agent creation does send a **tool whitelist**, but only names, no JSON schema
(@12116561):
```js
'mcp_list': (agent['mcp_list']||[]).map(n => ({'name': n, 'type_': Im['MCPServerType']['Whitelist'], 'disabled_tools': []}))
…
'built_in_tool_list': r['data'][0x215e],   // array of tool NAMES
```

### 5. VERDICT

- **No tool JSON schema ever crosses JS→sidecar or JS→cloud.** `input_schema`,
  `tool_schema`, `tool_definition`, `json_schema`, `RegisterTool`, `registerTool`,
  `ide_command`, `tool_choice`, `tools` in the *chat* request: all 0 hits.
  The only `tools` key in the whole file is the MCP protocol zod schema
  (`{'tools': z.array(toolSchema)}` for the `tools/list` *response*).
- The sidecar→LLM `tools` array is built **natively** (matches the Rust registry already
  found in `ai-agent.exe`). JS supplies only: `{service, method, data}` envelopes,
  `model_name`/`custom_model`, `agent_type`, `built_in_tool_list` (names),
  `mcp_list` (names + `disabled_tools`), and boolean feature flags
  (`native_function_call`, `parallel_tool_calling`, `use_v2_process`).
- **Client-injectable surface is therefore limited to:**
  1. `custom_model` (`base_url`, `provider`, `ak`, `config_name`) — a BYO-model path;
  2. `mcp_list` / `disabled_tools` — enable/disable MCP servers by name;
  3. `built_in_tool_list` — a name whitelist.
  You cannot add a new tool or change a tool's parameter schema from the JS/client side.
  To do that you must (a) register a local MCP server (fully supported, and its
  `inputSchema` IS forwarded, so MCP is the one real extension point), or
  (b) patch the native sidecar / intercept `api/ide/v1/chat` upstream.
