# Builder 模式差距梳理 —— Trae 请求体还差什么

> 目标：让 trae2api 发的请求与 Trae 本体（AI 侧边栏 Builder）一致。
> 依据：解码后的 `aiServer_full.js`（182,425 处引用全部还原）+ 实机 trace 对比。

## 1. 当前已发送（commit cf98636 之后）

```
user_input, session_id, chat_history,
workspace_folders[{path,name}], mention_context{10 keys}, parsed_query[{type,path}],
agent_type("chat"|"builder"), message_content[{type,text_content}], message_id, scene_location
```

## 2. 还缺的字段（按影响排序）

### P0-1 `scene_location` 语义错误 ⚠️ 必须修
解码实证（`getChatRequestAgentType`）：
```js
let agentType = agent ? agent['type'] : 'chat';
return sceneLocation === 1 ? 'chat' : agentType;
```
`SceneLocation` 枚举只有两个值：**1 = InlineChat（编辑器内联，强制 chat）**，**2 = Chatview（AI 侧边栏）**。

→ **Builder 必须 `scene_location = 2`**。我们现在硬编码 `0`，等于"未知场景"，
服务端可能落到最保守的 chat 模板 → 这就是"效果和 Trae 不一样"的直接原因之一。

### P0-2 `agent` 对象整个缺失
Builder 请求带完整 agent 对象（解码实证，`'type':'builder'` 处）：
```js
{'type':'builder', 'title', 'name', 'sessionId', 'createdAt', 'updatedAt',
 'status', 'agentProcessSupport', 'worktree_data', 'worktree_branch',
 'worktree_path', ...}
```
→ 没有 `agent`，`agent_type` 就无处可来（我们只能猜），服务端也拿不到
agent 级配置（工具白名单、自定义提示词、max mode 等）。

**代理侧最小可用 agent**：
```json
{"type":"builder","name":"builder","title":"Builder"}
```

### P0-3 `active_text_editor` 缺失
Builder 会带当前编辑器状态（文件路径/选区/languageId）。
→ DSH/Cline 这类客户端不带编辑器状态（DSH 明确没有该概念），
但 Claude Code/Cursor 类客户端的 system-reminder 里有。
→ **有则发，无则不发**（不阻塞）。

### P1-1 `code_selections` 缺失
编辑器选区 `[{file_path,start_line,end_line}]`。
→ 来源：客户端消息里的 `@文件 + 选区`（Cline 的 `[edit_file for '...']`、
  Claude Code 的 `Note: ... was read before`）已能提取到文件，但**行号**要
  从消息文本里再解析（如 `:24-30` / `#L24-L30` 这类 DSH 风格的引用）。

### P1-2 `custom_model` / `model_name`
现在 `model_name` 不发（因为本地目录名 ≠ 网关模型名，发了会 4023）。
→ 需要 `model_list` 的合法值（待抓包/或从 `agent/get_builtin_tool_list` 同类接口）。
→ 在拿到之前，**保持不发**（服务端默认模型），但要允许
  `TRAE2API_MODEL` 强制指定。

### P1-3 `intent_name`
我们现在发 `"chat"`。IDE 的 Builder 请求**不带 `intent_name`**
（`createChatRequestObject` 里没有这个键）。
→ 无害，但建议改为不发，避免与服务端意图路由冲突。

### P2 `multi_media` / `message_content` 多模态
客户端带图片时（OpenAI `content:[{type:image_url}]`）应转成
`[{type:'image', image_id}]`。当前只转文本。

## 3. Builder 模式需要的完整请求体（目标态）

```json
{
  "agent_type": "builder",
  "agent": {"type": "builder", "name": "builder", "title": "Builder"},
  "session_id": "<uuid>",
  "message_id": "<uuid>",
  "scene_location": 2,
  "message_content": [{"type": "text", "text_content": "..."}],
  "parsed_query": [...],
  "mention_context": {hashWorkspace, hashFolder, hashFiles, hashFolders, ...},
  "workspace_folders": [{"path": "...", "name": "..."}],
  "active_text_editor": {...},          // 可选
  "code_selections": [],                 // 可选
  "model_name": "...",                   // 待定
  "custom_model": {...},                 // 可选
  "chat_history": [...],                 // V1 通道保留（IDE 也用）
  "user_input": "..."                    // V1 通道保留
}
```

## 4. 客户端使用模式（我们的适配矩阵）

| 客户端 | 发 tools 数组 | cwd 来源 | 文件上下文 | 编辑器状态 |
|---|---|---|---|---|
| **DSH** | ✅（`input_schema` 或 `parameters`） | `Current working directory: "..."`（user 消息） | `@path` token + 工具结果信封 | ❌ 无此概念 |
| **Claude Code** | ✅ | `Working directory:`（system） | `Note: ... was read before`、`<file path=>` | system-reminder 可能带 |
| **Cline** | ✅ | `<system-reminder> cwd:` | `[edit_file for '...']`、`file_contents` | 选区可解析 |
| **Codex CLI** | ✅ | `<environment> Working directory:` | 上下文块 | ❌ |
| **Cherry Studio 等纯聊天** | ❌ | ❌ | ❌ | ❌ |

**推论**：
- 客户端带 tools → 我们 prompt 声明 + `known_names` 过滤（已有）
- 客户端不带 tools（纯聊天）→ 模型只能用 Trae 内置工具 → bridge 本地执行（已有）
- **Builder 模式应对所有客户端生效**：`agent_type=builder` + `scene_location=2`
  让服务端给全工具集，再由上面两条路径决定谁来执行

## 5. 实施顺序

1. `scene_location=2` + 发 `agent{type:builder}`（P0-1/P0-2，几行改动）
2. `intent_name` 改为不发（P1-3）
3. `active_text_editor`/`code_selections` 从客户端消息解析（P1-1）
4. 图片多模态（P2）
5. `model_name` 合法值（需要抓包，独立任务）
