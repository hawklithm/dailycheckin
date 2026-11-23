# 为什么走 trae2api 和走 Trae 本体效果不一样

> 结论：**不是模型不同，而是我们发给网关的请求体只有 3 个字段，Trae 本体发 20+ 个字段。**
> 服务端 `ide_prompts` 依赖这些字段决定工具集 / 系统提示词 / 工作区上下文；
> 我们发最小体，模型拿不到 IDE 场景，退化成普通聊天模型。

## 1. 证据：两边请求体对比

**trae2api 当前发送**（trace 实证，仅 3 键）：
```json
{"user_input":"请用工具在 ... 创建文件 ...","session_id":"<uuid>","chat_history":[...]}
```

**Trae 本体发送**（`aiServer_decoded.js` → `createChatRequestObject` @12801707，已解码）：
```js
{
  agent_type,            // 'chat' | 'builder' | 'BuilderWithMcp' | 'custom'  (ICubeAgentType)
  agent_id,              // 当前 agent 的 id
  agent,                 // 整个 agent 配置对象（名字/描述/工具集/模型）
  session_id,
  message_id,            // uuid
  mention_context,       // {hashWorkspace, hashFolder, hashFiles[], hashFolders[], hashSymbols[],
                         //  hashDocs[], hashRuleFiles[], onlyMention, hashWebs[], autoRuleCount,
                         //  agentsMdCount, claudeMdCount}   ← tte(parsed_query) 解析产物
  model_name,            // 具体模型名（如 Doubao-Seed-2.1-Turbo）
  custom_model,          // {provider, config_name, display_model_name, multimodal, ak,
                         //  use_remote_service, config_source, is_preset, base_url}
  message_content,       // [{type:'text', text_content}, {type:'image', image_id}]
  code_selections,       // 编辑器选区 [{file_path,start_line,end_line}]
  scene_location,        // 场景（侧边栏/编辑器内联/…）→ 决定 agent_type
  parsed_query,          // mention 数组（#工作区 / @文件 / #文件夹 / $符号 / 网页 …）
  multi_media,           // [{type, image_id}]
  active_text_editor,    // 当前编辑器 {filePath, selection, languageId}
  workspace_folders,     // [{path, ...}]  ← 工作区文件夹！
  model_auto_selection,  // {strategy}（Max 模式）
  context_window_size,
}
```

`agent_type` 的取值逻辑（`getChatRequestAgentType(sceneLocation, currentAgent)` 解码）：
```js
let agentType = currentAgent?.type ?? 'chat';
return sceneLocation === 1 ? 'chat' : agentType;
```
→ **默认 `chat`**；AI 侧边栏（Builder）走 `builder`。

## 2. 这些字段各自决定什么

| 字段 | 服务端用途（推断 + 已证实的相关性） |
|---|---|
| `agent_type` | 选择 prompt 模板族 + 工具集（chat 轻量 / builder 全工具 / BuilderWithMcp 带 MCP） |
| `agent` | 自定义 agent 的提示词与工具配置 |
| `mention_context` | #工作区/`@文件`/#文件夹 展开：把真实文件内容/目录结构注入上下文 |
| `workspace_folders` | 工作区感知：相对路径解析、git 根、monorepo 结构 |
| `active_text_editor` / `code_selections` | 编辑器上下文：当前文件、选中代码 → 模型能看到"你在看哪" |
| `message_content` 结构化 | 多模态（图片）、@提及 与文本的边界 |
| `model_name` / `custom_model` | 选模型；`is_preset`/`config_source` 影响可用特性 |
| `parsed_query` | mention 的原始解析输入，服务端可能二次处理 |

我们只发 `user_input` 自由文本 = **把上面这些维度全部压成一段自然语言**。
服务端拿不到结构化场景 → `ide_prompts` 只能按最朴素的方式拼 → 模型既不知道工作区、
也不知道有哪些工具可调、更不知道当前编辑器状态 → 表现差异巨大。

## 3. 修复方向（按性价比排序）

1. **发结构化 `message_content` + `parsed_query` + `mention_context`**：把 OpenAI 的
   `messages[]` 映射成 Trae 的结构化轮次（每条消息 = `message_content[0].text_content`，
   system → agent 提示词字段或拼入首条），`@文件/#工作区` 从用户文本中解析 mention 填入。
2. **补 `workspace_folders` / `active_text_editor` / `code_selections`**：至少发
   `workspace_folders=[{path: TRAE2API_WORKSPACE}]`，让服务端有工作区概念；
   客户端若提供文件上下文则透传。
3. **`agent_type` 显式发 `chat` 或 `builder`**：`builder` 才有完整工具集
   （这直接决定模型能不能调工具！值得优先实验）。
4. **`model_name` 发真实模型名**：现在 4023 是因为本地目录名 ≠ 网关模型名；
   拿到 `model_list` 的合法值后即可精确指定（不再依赖服务端默认）。

## 4. 验证方法

改完后对比同一 prompt 的行为（是否主动调工具、是否引用工作区文件）。
可用 `trae2api/trace/` 里落盘的请求体直接核对字段完整性。
