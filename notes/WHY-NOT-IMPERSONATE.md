# 修正：为什么伪装成客户端仍拿不到 agent 能力

> 生成时间：2026-10-27
> 本文**修正**了 `WHY-NOT-IMPERSONATE.md` 中「Free 账号无授权」的结论——那条是错的。

---

## 0. 先认错：我上一版的结论错了

上一版我推测「agent 模式未对本账号开通」。**这个推测被数据推翻**：

| 证据 | 结果 |
|---|---|
| 真实客户端成功出字的 LLM 轮次 | **90 次**（`rs_18_llm_response_first_token` / `rs_19_llm_response_done`） |
| 额度耗尽信号 | **0 次** |
| 配额超限信号 | **0 次** |
| 升级/无权限提示 | **0 次** |
| `restrictedModelKeys` | **[]（空）** |

**Free 账号在真实客户端里是能正常用的。** 授权不是瓶颈。

（补充：`enableSoloBuilder` / `enableSoloCoder` 都是 `true`；
只有 `can_gen_solo_code: false`，那是「SOLO 生成代码」这个特定子功能，
不是 agent 对话本身。）

---

## 1. 登录流程也不是差异点

按提示查了登录链路（`auth.py` + 本地凭证 + JWT 解码）：

```
JWT header : {"alg":"RS256","typ":"JWT"}
JWT payload: data{ id, source:"refresh_token", source_id }
             exp / iat
scope / aud / role / entitlement 类 claim：一个都没有
```

- 我们发的 `Cloud-IDE-JWT` 与客户端 `completion.log` 里记录的**是同一套两个头**
  （`Authorization: Cloud-IDE-JWT` + `x-ide-token`）
- 服务端接受（`ping` 200、`chat_mode` 200、`v1/chat` 出字）
- **登录流程没有产生额外 scope 或 audience**

→ **不是登录/令牌的问题。**

---

## 2. 真正的答案：我们和客户端调的**不是同一个接口**

这是最硬的一条证据（扫了 449 个明文日志文件）：

| 字符串 | 真实客户端出现次数 |
|---|---|
| `api/agent/v3` | **0** |
| `create_agent_task` | **0** |
| `llm_utils_chat` | **0** |
| `api/ide/v1/chat` | **0** |
| `start_chat` | 117 |
| `subscribe_events` | 173 |

**真实客户端从不直接调用这两个 HTTP 端点。**

它走的是：

```
渲染层  ──mojo RPC──▶  sidecar  ──HTTPS/SSE──▶  远端
        lite.vm_operate       (sidecar 自己决定调什么)
        lite.subscribe_events
        chat.start_chat
```

**关键点：`api/ide/v1/chat` 和 `api/agent/v3/*` 都是 sidecar/ai-server
替渲染层调用的，渲染层根本不碰它们。**

---

## 3. 那为什么 sidecar 能调通、我们不能？

因为 sidecar 调的**不是 `agent/v3/llm_utils_chat`**。

从客户端日志的阶段名可以还原它真正走的服务端流程：

```
lite_01_create_session      ← 先建会话
rs_01_chat_begin
rs_02_get_session
rs_03_get_history_message
rs_04_create_message
rs_05_create_snapshot       ← 建快照
rs_06_resolvers_begin       ← 解析器群
rs_06_get_custom_model
rs_06_resolve_contexts
rs_06_resolver_websearch
rs_07_create_task           ← 建任务
rs_08_create_turn           ← 建轮次
rs_09_process_task
rs_15_before_generate_plan
rs_17_before_request_llm
rs_18_llm_response_first_token   ← 出首 token
rs_19_llm_response_done
```

注意 `rs_05_create_snapshot`、`rs_07_create_task`、`rs_08_create_turn`：
**这些是服务端的有状态写入操作**，不是「发一个 prompt 拿一个回复」。

而 `agent/v3/llm_utils_chat` 是**无状态的单次工具调用**（名字就叫
`llm_utils`，utility），它按 function 查一个「工具用模型」，
这条路本来就不是给「主对话」用的 → 所以对 `solo_agent` 返回 4011。

**我们拿一个工具调用的端点，去期望它产生主对话的 agent 能力，这是路径选错了。**

---

## 4. 结论：不是伪装失败，是**对象错了**

| 说法 | 对错 |
|---|---|
| 「伪装成客户端，服务端就会当你是客户端」 | ✅ **对，而且已经做到了**（`v1/chat` 出字就是证明） |
| 「所以能拿到 agent 能力」 | ❌ **错**，因为 agent 能力不在我们调的那个端点上 |
| 「Free 账号没授权」 | ❌ **错**（90 次成功出字） |
| 「登录流程缺 scope」 | ❌ **错**（JWT 无 scope，且客户端同款） |

**真实情况：能伪装的都伪装了，身份也通过了。但 agent 能力由 sidecar
通过一条「有状态会话链」获得，而我们调的是无状态的工具端点。**

---

## 5. 要真正拿到 agent 能力，需要做什么

按代价从低到高：

### 方案 A：走完整的会话链（推荐验证）
不是打一个 `llm_utils_chat`，而是按真实顺序：
```
create_chat_session → start_chat → subscribe_events
```
`start_chat` 在日志里出现 117 次，`subscribe_events` 173 次——
这是真实入口。需要还原它们的 HTTP 形态（目前只知道它们是 mojo RPC 方法名）。

### 方案 B：驱动本机真实客户端
不模拟 sidecar，而是让 sidecar 替我们发。代价是依赖本机 Trae 运行。

### 方案 C：接受 v1/chat
能力上限 = 7 种事件、无结构化 tool_call。这是**协议上限**。

---

## 6. 下一步该做什么（明确）

优先验证 **方案 A**：查 `start_chat` / `subscribe_events` 这两个方法
在 sidecar 里对应什么 HTTP 调用。这需要：

1. 从 `ai_agent.dll` 里找 `ChatHandler` 的 `start_chat` 实现里调了哪个 URL
2. 从明文日志里找 `start_chat` 前后是否有 URL 或 payload 记录
3. 用 `lite.create_chat_session` 建立真实会话后再试

**在此之前，不要再调 `agent/v3/llm_utils_chat` 期待 agent 能力——那条路已证否。**
