# DeepSeek Harness (DSH) 上下文标记 —— 代理适配依据

> 来源：F:\deepseek-harness 源码（read-only 分析）。下面每个结论都有 file:line。

## 1. 工作目录标记（最关键）

`packages/session/working-directory/src/index.ts:173`
```ts
private contextText(session: Session): string {
  return `Current working directory: ${JSON.stringify(this.get(session))}.`
}
```
→ 模型侧看到的确切字面量：
```
Current working directory: "D:\workspace\trae2api".
```
（`JSON.stringify` → **带双引号**，路径用 JSON 转义。）

上下文快照的包装（`packages/core/system-prompt/src/index.ts:317`）：
```ts
return `Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n${body}`
```
→ 完整形态（本会话 runtime context 就是这个格式）：
```
Current runtime context. This snapshot supersedes earlier runtime-context snapshots.

Current working directory: "F:\deepseek-harness".
Current DSH file policy: danger-full-access. ...
Approval prompts are disabled in this session: ...
Current DeepSeek Harness implementation checkout: "F:\deepseek-harness".
Current DeepSeek Harness Web GUI URL: http://127.0.0.1:3080.
```

快照被清空时的字面量（`packages/core/agent-loop/src/runtime-context.ts:20`）：
```
Current runtime context: none. Earlier runtime-context snapshots no longer apply.
```

工作目录变化时注入的 user 消息（`working-directory/src/index.ts:196-197`）：
```
The working directory "D:\old" is unavailable. The working directory is now "D:\new".
The working directory changed from "D:\old" to "D:\new".
```

## 2. 快照的注入位置

`packages/core/agent-loop/src/agent.ts:697` —— 请求体：
```ts
messages: boundaryMessages,          // 含 runtime context 快照的那条 user 消息
toolHistory: session.toolHistory(),
...header.tools !== undefined ? { tools: header.tools } : {},
sessionId, signal
```
→ 快照是**一条 user 消息**（`type:'text'`），不是 system。
→ `tools` 是 **header 里的独立字段**（即 OpenAI 风格 tools 数组，走 `GenerateOptions['tools']`）。

## 3. 工具声明与工具结果

- 工具定义（`packages/fs/tool-fs/src/read.ts:77-84`）：
```ts
ctx.tools.register(defineTool({
  name: 'read',
  description: 'Read a UTF-8 text file and return line-numbered content.',
  parameters: {
    file_path: { type: 'string', required: true, description: '...' },
    offset: { type: 'number', ... },
    limit: { type: 'number', ... },
  },
```
  → **name + description + parameters（对象，非 JSON string）**，即 OpenAI function 风格。
  → 工具名是短名：`read` / `write` / `edit` / `str_replace_editor` / `bash` / `pwsh` /
    `glob` / `grep` / `todo_write` / `web_search` / `task` …（与 Claude Code 高度一致）

- 工具结果（`packages/core/agent-loop/src/tool-calls.ts:277-281`）：
```ts
const message = createToolResultMessage({ callId: block.id, content: result.content, isError: result.isError })
```
  → `role: tool` + `tool_call_id`（OpenAI 语义），我们的 `normalize_messages` 已支持。

## 4. DSH 没有的 / 与 Claude Code 的差异

| 特性 | Claude Code | DSH |
|---|---|---|
| cwd 字面量 | `Working directory: <path>`（无引号） | `Current working directory: "<path>".`（**JSON 引号**） |
| 上下文包裹 | `<system-reminder>` 块 | `Current runtime context. ...` 前缀（快照语义，后到覆盖先到） |
| 附件文件 | `Note: <path> was read before...` / `<file path=...>` | 走工具结果（`read` 工具返回），**没有** Note/file 块 |
| 工具集位置 | 请求 `tools` 数组 + MCP | 请求 `tools` 数组（`header.tools`） |
| 路径风格 | 本机绝对路径 | 本机绝对路径（Windows 下 `D:\...`，JSON 转义） |

## 5. 给代理的正则/标记清单

```python
# cwd（DSH 专属，注意 JSON 引号 + 结尾句点）
r'Current working directory:\s*"([^"]+)"\.'

# 通用 cwd（兼容 Claude Code / Codex，无引号）
r'^Working directory:\s*(.+)$'  (MULTILINE)
r'Primary working directory:\s*(.+)$'

# 上下文快照块（DSH）
r'Current runtime context\. This snapshot supersedes[^\n]*\n\n(.*?)(?=\n\nCurrent runtime context|\Z)'  (DOTALL)

# 工具结果（OpenAI 语义，已有）
role == 'tool' 且 tool_call_id
```

**落地要点**：
1. `Current working directory: "..."` 是 DSH 的**权威** cwd 源，必须支持带引号形式
   （现有 `CWD_PATTERNS` 的无引号模式会匹配失败）。
2. DSH 的 cwd 出现在 **user 消息**里（不是 system），所以扫描范围要覆盖所有 role。
3. DSH 的 `read` 工具参数名是 `file_path`（和 Trae 的 `view_file` 一致），
   工具集用短名 `read/write/edit/bash/pwsh/glob/grep/todo_write/web_search`
   —— 与 Trae 的 `view_file/write_to_file/run_command` 不同，**需要在
   bridge 执行器里再加一组 DSH 风格别名**。
4. DSH 发 `tools` 数组 → 我们已有的 prompt 声明 + `known_names` 过滤直接适用。
