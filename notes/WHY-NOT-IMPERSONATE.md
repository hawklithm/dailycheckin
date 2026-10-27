# 为什么「完全伪装成客户端」拿不到 agent 能力

> 生成时间：2026-10-27
> 结论依据：449 个明文日志文件 + 实时 A/B 对照实验 + 静态反编译

---

## 0. 直接回答

您的推理**在前提上是对的，但前提本身不成立**：

> 「服务端会把我们当成正常客户端」

——**服务端确实把我们当成正常客户端了。** `v1/chat` 稳定出字、有
`token_usage`、有 `session_id`，服务端从未拒绝过我们的身份。

真正的问题是：**"客户端"不是一个调用者，而是三个进程**，而 agent 能力的
钥匙握在其中一个我们**无法伪装**的进程手里。

---

## 1. 决定性证据：真实客户端根本不走这两条 HTTP 路

扫了 449 个明文日志文件，统计各字符串出现次数：

| 字符串 | 出现次数 |
|---|---|
| `api/agent/v3` | **0** |
| `create_agent_task` | **0** |
| `llm_utils_chat` | **0** |
| `api/ide/v1/chat` | **0** |
| `start_chat` | 117 |
| `subscribe_events` | 173 |

**真实客户端一次都没调用过 `api/agent/v3/*`，也没调用过
`api/ide/v1/chat`。** 这两条都是我们自己在用的路。

### 1.1 它真正走的是什么

渲染层实际发出的 RPC（`service.method`）：

```
lite.vm_operate              x7962
lite.super_completion_query  x64
lite.subscribe_events        x57
lite.state_notification      x13
```

即 **mojo RPC 到本地 sidecar**，不是 HTTP 到远端。

---

## 2. 服务端替客户端做了哪些事（关键）

客户端日志里记录了**每一轮对话的完整阶段耗时**，这些阶段名暴露了
「哪些事不是客户端做的」：

```
rs_01_chat_begin              rs_11_runner_dispatch_entered
rs_02_get_session             rs_12_turn_start_hooks_done
rs_03_get_history_message     rs_13_context_resolve_done / render_user_prompt
rs_04_create_message          rs_15_before_generate_plan
rs_05_create_snapshot         rs_16_llm_generate_plain_item
rs_06_resolvers_begin         rs_17_before_request_llm
rs_06_get_custom_model        rs_18_llm_response_first_token
rs_06_resolve_contexts        rs_19_llm_response_done
rs_06_resolver_websearch      rs_07_create_task / rs_08_create_turn
rs_09_process_task
```

其中 **`svr_*` 前缀的是服务端侧阶段**：

```
svr_01_queue_timing                      ← 服务端排队
svr_02_preprocess / svr__02_preprocess_*
svr_06_platform_preprocess
svr_06_platform_first_token_timing       ← 首个 token 由平台产出
svr_11_server_processing_time
svr__04_postprocess_security_check       ← 安全审核
```

**`rs_06_get_custom_model`、`rs_06_resolve_contexts`、
`rs_15_before_generate_plan`、`svr_01_queue_timing` 这些步骤，
都不是"拼一个 HTTP body"能完成的**——它们是 sidecar / ai-server 与远端之间
有状态协作的结果。

---

## 3. 为什么伪装身份不管用（核心逻辑）

### 3.1 身份这一关我们早就过了

同一秒、同一账号、同一 token、同一套头：

```
/api/ide/v1/chat              -> 200 STREAM OK     ← 身份没问题
/api/agent/v3/llm_utils_chat  -> 200 4011 限流     ← 但被拦
```

**如果 4011 是"识别出你不是客户端"，那 v1/chat 也该失败。它没有。**

### 3.2 `4011` 的真实含义

`llm_utils_chat` 按 function 区分两种情况：

| function | 响应 | 含义 |
|---|---|---|
| `agent` / `code` / `summary` | `no function config found` | 配置**不存在** |
| `solo_agent` / `builder` / `chat` | `4011` | 配置**存在**，但被限 |

**配置存在**（否则会像 `agent` 一样报 no config）。
所以 4011 是**该 function 的额度/授权闸门**，不是身份闸门。

### 3.3 三进程模型才是根因

```
渲染层 workbench.js
   │ ① mojo RPC（lite.* / chat.*）
   ▼
sidecar ai_agent.dll          ← 持有会话状态、快照、上下文解析
   │ ② HTTPS + SSE
   ▼
远端网关
   ▲
   │ ③ 自己的凭据与授权
ai-server harness.dll         ← agent 模式 / 28 种事件 / tool_call
```

- 我们伪装的是**①里的渲染层请求形状**
- 但 agent 能力（28 事件、`tool_call`、`thought`）属于**③ ai-server**
- ai-server 的授权是**服务端按账号开通的**，不是请求里能声明的

**伪装渲染层，拿不到 ai-server 的权利。**

---

## 4. 那"完全一样"到底差在哪

| 维度 | 我们能否伪装 | 说明 |
|---|---|---|
| HTTP 请求头 | ✅ 可以 | 已用真实 legacy 头，服务端接受 |
| 请求 body 结构 | ✅ 可以 | 已用反编译还原的 schema |
| JWT / 设备指纹 | ✅ 可以 | 从本机 storage.json 解出 |
| 会话状态机 | ⚠️ 部分 | 需要 `create_session → start_chat → subscribe` 时序 |
| **服务端下发的配置** | ❌ **不行** | `ApplicationConfig` 的 agent 开关按账号下发 |
| **ai-server 的授权** | ❌ **不行** | 独立进程独立凭据，服务端按账号开通 |
| **排队/安全审核阶段** | ❌ **不行** | `svr_01_queue_timing` 等由服务端执行 |

**结论：能伪装的都伪装了，剩下的三项不在请求侧。**

---

## 5. 一个反直觉但重要的事实

`api/agent/v3/*` 这些端点**真实客户端从不调用**，但我们能打通（返回 200 + SSE）。
这说明它们是**给 ai-server 用的内部 API**，不是给渲染层用的。

也就是说：**我们在调用一个"连客户端自己都不直接调用"的接口**，
然后期望它给出与客户端相同的行为。这本身就说明路径选错了。

---

## 6. 可执行的结论

1. **身份伪装已经完成**，不是瓶颈。别再在请求头/body 上找原因。
2. **瓶颈是账号级授权**（agent 模式未开通 / 额度受限），这需要：
   - 换一个**已开通 agent 模式**的账号验证，或
   - 等当前账号的授权放开
3. **v1/chat 是当前唯一可用的推理路径**，其能力上限是 7 种事件、
   无结构化 `tool_call`。这是**协议上限**，不是我们实现不足。
4. 若必须在单账号下突破，唯一剩下的技术手段是**让 ai-server 替我们发**
   （即驱动本机真实客户端），而不是外部模拟它——这与"纯反编译重写"是
   两条不同的路。
