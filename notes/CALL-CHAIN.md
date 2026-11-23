# Trae CN 完整调用链路（静态反编译结果）

> 生成时间：2026-10-27
> 方法：**静态反编译**（不抓包）。利用 Rust 二进制里 serde 保留的明文元数据：
> 结构体字段表、`struct X with N elements` 声明、handler 分发表、日志格式串。
> 目标程序：Trae CN 3.4.7，`ai_agent.dll`(267MB) + `harness.dll`(210MB)
> 复现脚本：`tests/re_*.py`，原始产物：`logs/_discover.txt`、
> `logs/_dispatch.txt`、`logs/_rpcmethods.txt`、`logs/_sse_enum.txt`

---

## 0. 一句话结论

**本地客户端 = 渲染层(JS) + sidecar(Rust) + ai-server(Rust) 三段式**：

```
渲染层 workbench.js
   │  ① mojo RPC（service/method/data 信封）
   ▼
sidecar ai_agent.dll          ← 34 个 Handler，持有业务逻辑与会话状态
   │  ② HTTPS + SSE（api/ide/v1/... ）
   ▼
远端 trae-api-cn.mchost.guru  ← 真正的 LLM 网关，下发配置与事件流
```

**我们目前只实现了 ②，且只处理了 28 种 SSE 事件里的 7 种。**
这就是「体验差异大」的**量化解释**。

---

## 1. 三段式架构与协议

| 层 | 进程/文件 | 协议 | 证据 |
|---|---|---|---|
| 渲染层 | `workbench.desktop.main.js` | → sidecar 走 **mojo**，信封 `{service,method,data,user_info,common_params,streamlined_common_params,client_info}` | `convertReqToRustPayload` 全文 |
| sidecar | `ai_agent.dll` (`process-type=ai`) | → 远端走 **HTTPS + SSE**，`text/event-stream` | DLL 含 `text/event-stream` ×3 |
| ai-server | `harness.dll` (`process-type=ai-server`) | 持有外网连接，负责事件流与工具缓存 | 28 事件枚举在此 |

---

## 2. RPC 分发表（渲染层 → sidecar）

从 `src\handler\*.rs` 与 `[<X>Handler] unknown method` 日志串之间提取。
**共 10+ 个 handler、77+ 个方法**（完整表见 `logs/_rpcmethods.txt`）。

### 2.1 ChatHandler —— 最关键的 4 个方法

```
src\handler\chat\mod.rs 的 router match arms：
    resume_chat
    start_chat
    start_resume_chat
    query_start
```

即**一次对话只有 4 个 RPC 入口**，其余都是会话管理（`pin_session`、
`get_pinned_sessions`、`global_search`、`handle_cancel` 等）。

### 2.2 ModelHandler（11 个）

```
model_list            model_list_by_function   connect
custom_model_connectivity_check   update_custom_model
add_custom_model      providers
get_custom_model_type_config      get_model_selection_modes
fetch_for_auto        prefetch_for_auto
```

### 2.3 其他 handler 要点

| Handler | 方法数 | 关键方法 |
|---|---|---|
| ToolcallHandler | 14 | `check_result` `save_toolcall_result` `stop_toolhost_command` `query_workflow_status` `list_workflows` |
| MultimodalHandler | 12 | `read_file` `write_file` `upload_image` `check_image_content` |
| SnapshotHandler | 11 | `create_new_version` `update_snapshot` `revert_check` `get_file_list` |
| AgentHandler | 21 | `get_agents` `create_or_polish_agent_via_llm` `update_agent_mcp_servers` |
| SandboxHandler | 6 | `run_in_jail` `install_deps` `get_sandbox_status` |
| ContextHandler | 3 | `slash_list` `slash_get` `refresh_builtin_skill` |

---

## 3. 一次 LLM 请求的完整时序

从 `[PreDispatchHook] [StartChat]` 系列日志串还原（`logs/_callchain_raw.txt`）：

```
① [ChatHandler::router] starting, method:start_chat, session_id:
② [ChatHandler] validate params                    ← 参数校验
③ [ChatHandler] query parsed successfully          ← 解析 user_input
④ [PreDispatchHook] [StartChat] starting, session_id:
⑤ [PreDispatchHook] prepare_and_call_chat returned ← 进入 chat_service
⑥ [PreDispatchHook] received metadata, turn_id:    ← 拿到 turn_id
   ※ 硬性约束：Expected Metadata event as first event
⑦ [PreDispatchHook] returning response
⑧ 流式事件：... tool_call / token_usage / done
⑨ [ChatHandler::handle_cancel] stop_chat completed  ← 收尾
```

**关键约束 ⑥：`metadata` 必须是流的第一个事件**，否则服务端/客户端判错。
我们 `server.py` 已按此处理（先等 metadata 再转发）。

### 3.1 首次 token 的耗时埋点

```
first token cost - handler start timestamp:
first token cost - before invoking chat_service.chat timestamp: ; duration:
```
说明服务端把「首个 token 延迟」作为核心指标——**这也是体验差异的观感来源**。

---

## 4. ★ SSE 事件全集：28 种（我们只处理 7 种）

来源：`harness.dll @182384857` 的连续字符串表（权威枚举顺序）：

```
 1 task_created          15 compact_token_usage
 2 thought               16 chat_memory_trigger
 3 tool_call             17 queuing
 4 revoke                18 token_usage
 5 turn_completion       19 context_usage
 6 progress_notice       20 done
 7 missing_history       21 timing_cost
 8 history               22 agent_identity
 9 user_message          23 sub_agent_create
10 required_context      24 sub_agent_finish
11 obtain_context        25 agent_status
12 model_config          26 agent_resume
13 tool_cache_data       27 project_name
14 compact_finish        28 dsl_extension_log
```

### 4.1 我们当前的覆盖

`server.py` 处理：`progress_notice`、`prompt`、`metadata`、`output`、
`token_usage`、`done`、`error` —— 共 7 个。

**未处理 25 种**，其中直接对应「原生体验」的有：

| 事件 | 作用 | 我们缺失的后果 |
|---|---|---|
| **`tool_call`** | 结构化工具调用 | 只能用 prompt 注入 + 标记解析 |
| **`thought`** | 思考过程 | 思考深度不可见 |
| `turn_completion` | 一轮结束 | 无法判断真正收尾 |
| `model_config` | 模型配置下发 | 模型不可控 |
| `context_usage` | 上下文用量 | 无法感知上下文压力 |
| `queuing` | 排队状态 | 高并发时无反馈 |
| `required_context` / `obtain_context` | 上下文按需索取 | 无主动补上下文能力 |
| `compact_finish` / `compact_token_usage` | 上下文压缩 | 长对话无法压缩续命 |
| `timing_cost` | 耗时分解 | 无法定位慢在哪 |
| `agent_identity` / `sub_agent_*` / `agent_status` | 子代理体系 | 无多代理能力 |

### 4.2 ★ 决定性证据：`ide_prompts` 不在本地

| 字符串 | ai_agent | harness | workbench.js | main.js |
|---|---|---|---|---|
| `ide_prompts` | 0 | 0 | 0 | 0 |
| `construct_prompt` | 0 | 0 | 0 | 0 |
| `progress_notice` | 0 | 1 | 0 | 0 |

`ide_prompts` / `construct_prompt` 是**服务端在响应里现造的**，
本地二进制里根本不存在。→ **prompt 组装发生在远端**，不是客户端行为。

---

## 5. 请求/响应结构（已还原，见 `trae2api/trae_schema.py`）

### 5.1 信封 `Request`（9 字段）

```
service, data, user_info, client_info, common_params,
streamlined_common_params, custom_params, scheduled_task_context
```
注意：**没有 `method`**（Rust 侧从 service 推导）。

### 5.2 `ChatArgs`（61 字段，已逐字还原 49）

`message_content` `code_selections` `workspace_context` `scene_location`
`use_file_context` `workspace_folders` `agent_type` `dsl_agent`
`custom_model` `model_auto_selection` `context_window_size`
`is_in_plan_mode` `is_solo_mode` `ask_question_config` `force_tool_calls`
`turn_id` `work_mode` `preheat` `parent_session_id` …

### 5.3 其他关键结构体

| 结构体 | 字段数 | 意义 |
|---|---|---|
| `ModelExtraConfig` | **181** | 全部能力开关总表（`v2_*`/`v3_*`/`enable_*`） |
| `ChatMessageData` | 46 | 一条消息的完整元数据 |
| `CustomModel` | 31 | 模型描述 |
| `ApplicationConfig` | 7 | **agent 模式开关（服务端下发）** |
| `ToolCall` | 4 | `id` `type` `function` `index` |
| `StandardChatMessagePart` | 3 | `type` `text_content` `data` |

### 5.4 ★ `ApplicationConfig` —— agent 模式是服务端开关

```
enable_solo_next
enable_agent_process_v3
enable_upgrade_all_sessions_to_v3
enable_upgrade_session_by_solo_coder
enable_upgrade_session_by_solo_builder
agent_types_that_ignore_queue_event
chat_memory_config
```

**这解释了为什么本地"看不出" agent 逻辑**：它是服务端按账号下发的，
客户端只是被动接受。也解释了为什么我们手工拼 HTTP 请求拿不到 agent 能力。

---

## 6. 实测校验（用真实 schema 打真实端点）

| 请求形状 | 结果 |
|---|---|
| 现有 flat body（字段在顶层） | ✅ STREAM OK |
| 完整 `Request` 信封 | ❌ `3003 all models failed` |
| 信封逐项加进 flat body | ✅ 全部 OK（加什么都不坏） |
| chat 字段嵌进 `data` | ❌ `3003` |
| 嵌套 + 顶层镜像 | ✅ STREAM OK |
| 顶层补齐 `ChatArgs` 全部能力字段 | ✅ 出字，但 `tool_calls` **恒 null** |

**两条结论**：
1. `api/ide/v1/chat` 从**顶层**读 chat 字段；`data` 嵌套属于 mojo 层，不适用 HTTP。
2. **该端点的模型输出层没有结构化 tool_call 通道** → 工具只能 prompt 驱动。

---

## 7. 对「重写一套」的意义

### 7.1 已经可以精确重写的部分

- ✅ 请求结构（`trae_schema.py`，权威字段表）
- ✅ 信封与分层（`Request` / `ChatArgs` / `client_info`）
- ✅ SSE 解析（28 种事件的完整词汇表已拿到）

### 7.2 结构性受限的部分

| 限制 | 根因 | 能否绕过 |
|---|---|---|
| 无结构化 `tool_call` | HTTP 端点输出层无此通道 | 只能走 mojo RPC |
| 无 agent 循环 | `ApplicationConfig` 服务端下发 | 不可外部伪造 |
| 模型不可控 | 模型由服务端按端点定死 | 需 `model_config` 事件通道 |
| prompt 由远端组装 | `ide_prompts` 不在本地 | 不可改 |

### 7.3 最高性价比的下一步

**把 `server.py` 的事件解析从 7 种扩到 28 种**。
即使暂时拿不到结构化 `tool_call`，至少可以把
`thought`（思考）、`context_usage`（上下文）、`queuing`（排队）、
`timing_cost`（耗时）、`turn_completion`（收尾）这些**已经在流里、
我们却丢掉的信息**接出来，立刻缩小观感差距。
这是纯本地改动，不依赖任何未攻克的端点。
