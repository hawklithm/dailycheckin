# Trae sidecar (ai_agent.dll) IPC — 实机抓取结论

时间 2026-10-26。Trae 运行 + 真实对话期间实机观察，非推测。

## 1. 纠正：sidecar 不走 TCP

之前的假设（打 `127.0.0.1:51000` 的本地 RPC）**是错的**。

- `51000` = `basil.mojom.NativeExtensionService`（`process-type=ckg`），是 gRPC，
  但**不是 AI 通道**：任意路径都回 `grpc-status:12 unknown service`，且无反射。
- 真正加载 `ai_agent.dll` 的进程：`--utility-sub-type=basil.mojom.NativeExtensionService`
  + `--vscode-crash-reporter-process-type=ai`（实测 PID 226380）。
  该进程 **没有任何 TCP 监听、没有任何已建立的 TCP 连接**。

结论：JS ↔ sidecar 走的是 **mojo IPC over named pipe**，抓不到网络包。

## 2. 找到的 IPC 通道

```
\\.\pipe\agent-code-toolhost-<pid>-<hash>
实测: \\.\pipe\agent-code-toolhost-226380-b2a78cf5
```

命名来自 DLL 里的 `CODE_TOOLHOST_IPC_NAME`（格式串
`agent-code-toolhostCODE_TOOLHOST_IPC_NAME@?.?`）。**可以 open 成功并写入**，
但读回需要正确的帧格式（首次用裸 JSON-RPC 试探只拿到超时/属性错误）。

## 3. 但 DLL 里同时声明了 HTTP + WebSocket 传输

`src/infrastructure/transport/unified.rs`：

```
"/ws"                       ← WebSocket
"/api/v1/:service/:method"  ← HTTP RPC
"127.0.0.1"
"[UnifiedTransport] server listening on: ?"
"[UnifiedTransport] text message: service=?, method=?, user=?"
"[HttpTransport] request incoming: service=?, method=?"
```

说明 sidecar **有** HTTP/WS 能力，只是当前版本未对外绑 TCP 端口（改用 pipe）。
不排除存在开关/版本差异能让它监听端口。

## 4. 真实的服务与方法名（从 DLL 字符串提取）

Handler 清单（34 个）：AgentHandler / BaseHandler / ChatHandler / CKGHandler /
CommercialHandler / ContextAssetHandler / ContextHandler / CoreMemoryHandler /
DesignLibraryImportHandler / DocsetHandler / DSLAgentHandler / FileFinderHandler /
GeneratedSkillHandler / GitHandler / HealthcheckHandler / HubHandler / IDEHandler /
**LiteHandler** / **ModelHandler** / MultimodalHandler / MultiRootPathHandler /
PluginHandler / PrivacyModeHandler / ProjectHandler / PtyBridgeHandler /
SandboxHandler / ScheduleHandler / SkillImportHandler / SnapshotHandler /
SummaryHandler / TaskHandler / TodoListHandler / ToolcallHandler /
UserConfigurationHandler

日志格式串证实聊天入口：
```
[ChatHandler] first token cost - before invoking chat_service.chat
→ 服务名是 chat_service.chat
```

`[LiteHandler] start handler service=?, method=?` 后紧跟方法名清单（节选）：
```
create_chat_session  list_chat_sessions  get_chat_session
batch_get_sessions_with_projects  commit_chat_session  freeze_chat_session
stop_chat_session  delete_chat_session  fork_session  export_past_chat
get_messages  get_message_by_id  resume_message  vm_operate
resolve_port_process  migration_work_agent_data  agent_ready
send_user_decision  delete_message  wakeup_sandbox  action_queue
revert_message  get_or_create_project_v2  ...
```

## 5. 模型确实由服务端下发（再次确认）

```
[ModelConfig] Received config_name=?., model_name=?., max_turn=?.,
              prompt_max_tokens=?., max_tokens=?.
[LLMAdapter] llm_raw_chat_custom_model: prompt_set=?., ab_version=?.,
             config_name=?., model_name=?.
```

`config_name` / `prompt_set` / `ab_version` / `reasoning_effort` /
`context_window_sizes` 全部由服务端下发 —— 与"控制台看不到消耗 + 模型是豆包
+ 思考浅"三个现象一致：这些控制权都不在我们的 V1 通道上。

## 6. 实测：17788 不是 sidecar

主进程（PID 46956）监听 `127.0.0.1:17788`，HTTP/CORS（`x-jwt-token` 头），
但所有路径（含 `/api/v1/chat_service.chat/chat`）一律 `404 not found`。
是 webview 静态服务，不是 RPC。

## 7. 结论与下一步

**坏消息**：JS ↔ sidecar 是 mojo pipe，无法像 TCP 那样抓包/复用；
即使连上 pipe，还要解 mojo 帧格式 + protobuf。成本显著高于预期。

**可选路径（按性价比排序）**：

- **A. 继续攻 pipe**：`\\.\pipe\agent-code-toolhost-<pid>-<hash>` 可 open。
  需要逆向 mojo 帧（长度前缀 + 消息头）。收益：真正复用 sidecar → 供应商链路。
  风险：mojo 是 Chromium 私有二进制协议，工作量大。
- **B. 让 sidecar 监听端口**：DLL 里有 `/ws` 与 `/api/v1/:service/:method`
  和 `server listening on`。若能找到启动参数/开关让它绑 TCP（例如某些版本
  或 `UnifiedTransport` 配置项），则直接 HTTP 复用，成本低得多。
  **优先查这个**——搜 main.js / product.json 里的相关开关。
- **C. 放弃真链路**：继续在 `/api/ide/v1/chat` 上优化，接受模型不可控、
  不计费、思考浅。

**建议下一步**：先做 B（找让 UnifiedTransport 绑 TCP 的开关），失败再退回 A。
