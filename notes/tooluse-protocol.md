# Trae Tool-Use 协议分析（基于代理抓取的真实 SSE 流）

> 数据来源: trae2api/trace/20261024-210013-4452.jsonl（网关原始 SSE，未做任何转换）
> 触发对话: "列出 D:\workspace\trae2api 目录下有哪些文件，用工具查"

## 1. 结论：Trae 的 tool-use 不是 OpenAI 的 tool_calls 协议

OpenAI 风格是结构化通道：`choices[].delta.tool_calls[]`，工具调用与文本在协议层分离。
**Trae 的 tool-use 是文本内嵌协议**：工具调用以**特殊 token 标记的文本段**出现在
`output.response` 正文中，`tool_calls` 字段虽然存在但**始终为 null**。

## 2. 抓包实录（还原后的流）

```
event: progress_notice  data: {"name":"construct_prompt","content":"Building prompt: ide_prompts"}
event: progress_notice  data: {..."Completed building prompt..."}
event: prompt           data: {"name":"prompt","string":null,"messages":null}
event: metadata         data: {"model":"","session_id":"...","prompt_completion_id":0,...}

event: output  data: {"response":"","reasoning_content":"\n用户","tool_calls":null,...}
event: output  data: {"response":"","reasoning_content":"现在需要查D:\workspace\trae2api目录下的文件，首先我需要...","tool_calls":null}
event: output  data: {"response":"","reasoning_content":"用list_dir这个工具吧，参数就是那个绝对路径，对，直接调用list_dir，","tool_calls":null}
event: output  data: {"response":"","reasoning_content":"path填D:\workspace\trae2api就行。现在就写调用的格式对吧","tool_calls":null}

event: output  data: {"response":"\u003c|FunctionCallBegin|\u003e[{\"","tool_calls":null,...}
event: output  data: {"response":"name\":\"list_dir\",\"parameters\":{\"dir_path\":\"D:\\\\workspace\\\\trae2api\"}}","tool_calls":null}
event: output  data: {"response":"]\u003c|FunctionCallEnd|\u003e","tool_calls":null}

event: token_usage      data: {"name":"ide_prompts","prompt_tokens":52,"completion_tokens":110,...}
event: done             data: {"finish_reason":"stop"}
```

## 3. 协议要点

### 3.1 特殊标记（文本内嵌）
```
<|FunctionCallBegin|>[{"name": <tool>, "parameters": {<args...>}}]<|FunctionCallEnd|>
```
- `\u003c\u003e` 即 `<>`，JSON 里转义存储
- 标记内是**一个 JSON 数组**（支持并行多调用）：`[{"name":..., "parameters":...}, ...]`
- 工具名: `list_dir`（snake_case）；参数顶层键: `parameters`（不是 OpenAI 的 `arguments` 字符串，
  这里是**对象**，不需二次 JSON.parse）

### 3.2 reasoning_content（思维链）
- 模型先在 `reasoning_content` 里规划（"用list_dir这个工具吧，参数就是那个绝对路径…"）
- 再在 `response` 里输出工具调用标记
- 与 DeepSeek-R1 / OpenAI o 系的独立 reasoning 通道不同，它是在同一 SSE 事件里
  双字段并行输出，且工具决策出现在思维链之后

### 3.3 多模态/其他字段
`output` 事件完整 schema（抓包观察）:
```json
{"response": "<delta文本或工具标记>",
 "reasoning_content": "<delta思维链|null>",
 "tool_calls": null,              // 保留字段，当前未用
 "multimodal_contents": null,     // 保留字段（图片等）
 "phase": null}                   // 保留字段（阶段标记?）
```

### 3.4 与通用协议的对照

| 维度 | OpenAI | Trae (V1 chat) |
|---|---|---|
| 工具声明 | 请求体 `tools:[{type:"function",function:{name,parameters}}]` | **请求体未见 tools 字段**（服务端按场景注入 ide_prompts 工具集） |
| 调用表达 | `delta.tool_calls[].function.{name,arguments}` | 文本标记 `<|FunctionCallBegin|>[...]<|FunctionCallEnd|>` |
| 参数格式 | `arguments` 是 JSON 字符串 | `parameters` 是 JSON 对象 |
| 结果回传 | `messages:[{role:"tool", tool_call_id, content}]` | 待验证（预计工具结果也以特殊标记文本回传，如 `<|FunctionResult|>`） |
| 思维链 | `reasoning_content`（兼容层） | 同名字段，SSE output 事件内 |
| 结束信号 | `finish_reason:"tool_calls"` / `stop` | `done{finish_reason:"stop"}`（工具轮次也报 stop） |

### 3.5 对 trae2api 的翻译策略（建议）
要把 Trae 工具调用翻译成 OpenAI tool_calls：
1. 流式解析 `output.response`，用缓冲匹配 `<|FunctionCallBegin|>` ... `<|FunctionCallEnd|>`
2. 标记内 JSON 数组逐项转成 OpenAI delta.tool_calls:
   `{"index":i, "id":"call_<uuid>", "type":"function",
     "function":{"name":item.name, "arguments":json.dumps(item.parameters)}}`
   （注意 OpenAI 的 arguments 是字符串，要再序列化一次）
3. `finish_reason` 在检出 FunctionCallEnd 时应为 `"tool_calls"` 而非 `stop`
4. 反向（客户端发 tool 结果）需要确认服务端的回传格式——下一步抓包验证

## 4. 待验证项
- 工具结果如何回传（继续同一 session 的对话即可抓到）
- 多轮工具调用、并行调用的确切行为
- `phase` 字段何时非空
- 是否存在其他特殊标记（如 `<|PluginCall|>`、MCP 相关）
- 请求体能否用 `tools` 字段自定义工具集
