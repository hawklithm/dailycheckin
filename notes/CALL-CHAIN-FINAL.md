> ⚠️ **本文已被 `notes/FINAL-VERDICT.md` 取代（2026-10-27 末）**。
> 本文的链路描述仍然准确，但「三条路」的结论以 `FINAL-VERDICT.md` 为准
> （那里有 150 组合穷举证明 `api/v1/chat/*` 在远端不存在）。

# 最终结论：完整调用链路与「为什么伪装无效」

> 生成时间：2026-10-27
> 本文**取代** `WHY-NOT-IMPERSONATE.md` 的旧结论（含两处已证伪的推断）

---

## 0. 两处我先前判断错误，先更正

| 我的旧结论 | 实际情况 | 证据 |
|---|---|---|
| 「Free 账号未开通 agent 授权」 | ❌ **错**。Free 账号能正常用 | 真实客户端 90 次成功出字；额度/配额/升级信号 **0 次**；`restrictedModelKeys: []` |
| 「登录流程缺 scope/audience」 | ❌ **错**。令牌与客户端完全一致 | JWT payload 只有 `data{id, source:"refresh_token"}` + `exp/iat`，**无任何 scope/aud**；与 `completion.log` 记录的两个头同款 |

---

## 1. 真实调用链路（已完整还原）

```
┌─ 渲染层 workbench.js ────────────────────────────┐
│  mojo RPC：                                      │
│    lite.vm_operate              x7962            │
│    lite.super_completion_query  x64              │
│    lite.subscribe_events        x57              │
│    lite.state_notification      x13              │
└──────────────────┬───────────────────────────────┘
                   │ ① mojo（非 HTTP）
                   ▼
┌─ sidecar ai_agent.dll ───────────────────────────┐
│  ChatHandler 路由（只有 4 个）：                  │
│    resume_chat / start_chat / start_resume_chat  │
│    / query_start                                 │
│                                                  │
│  lite 模块是真正的驱动者：                        │
│    [lite][send_message] request method=start_chat│
│    → 拿到 code/message/data                      │
│    → 再 lite.subscribe_events 订阅事件流          │
└──────────────────┬───────────────────────────────┘
                   │ ② HTTP + SSE
                   ▼
┌─ 远端网关 trae-api-cn.mchost.guru ───────────────┐
│  服务端替客户端完成的阶段：                        │
│    svr_01_queue_timing                           │
│    svr_02_preprocess / gateway_preprocess        │
│    svr_06_platform_preprocess / first_token      │
│    svr_11_server_processing_time                 │
│    svr__04_postprocess_security_check            │
└──────────────────────────────────────────────────┘
```

### 1.1 传输细节（关键）

`VsockAiAgentClient`（`src/domain/lite/ai_agent_client.rs`）暴露了实际 HTTP 形态：

```
http://localhost
POST
Host: localhost
Content-Type: application/json
Connection: keep-alive
Accept: text/event-stream
traceparent
```

即 **`lite` 的 `start_chat` / `subscribe_events` 是打到 `localhost`**，
而不是直接打远端域名。远端调用由 sidecar 内部完成。

---

## 2. 我们调的两个端点，真实客户端**从不使用**

扫 449 个明文日志文件：

| 字符串 | 真实客户端 |
|---|---|
| `api/agent/v3` | **0** |
| `create_agent_task` | **0** |
| `llm_utils_chat` | **0** |
| `api/ide/v1/chat` | **0** |
| `start_chat` | 117 |
| `subscribe_events` | 173 |

**这两条 HTTP 端点都是 sidecar/ai-server 的内部实现细节，
渲染层从不直接调用。**

---

## 3. 为什么「伪装成客户端」拿不到 agent 能力

您的推理链条是：

> 伪装成客户端 → 服务端当你是客户端 → 拿到全部能力

**前两步都成立，第三步断在"接口选错"上：**

1. ✅ **身份伪装成功**：`v1/chat` 稳定出字、`ping` 200、`chat_mode` 200
2. ✅ **服务端确实把我们当正常客户端**（Free 账号也照常服务）
3. ❌ **但我们调的不是客户端调的接口**
   - 客户端：`lite.start_chat`（发到 localhost，走 sidecar 的有状态会话链）
   - 我们：`api/agent/v3/llm_utils_chat`（一个**无状态工具端点**）

### 3.1 `llm_utils_chat` 是什么

名字就叫 `llm_utils`（utility）。它按 `function` 查「工具用模型」配置：

| function | 响应 | 含义 |
|---|---|---|
| `agent` / `code` / `summary` | `no function config found` | 配置**不存在** |
| `solo_agent` / `builder` / `chat` | `4011` | 配置**存在**，但该端点不给主对话用 |

**它是一个辅助工具端点，本来就不负责主对话。** 拿它期待 agent 能力，是路径错。

### 3.2 `v1/chat` 为什么能用

`api/ide/v1/chat` 是**老链路**（`chat.legacy_chat`，与 `chat.start_chat`
并列存在于映射表中）。它无状态、单次请求-响应，所以能用；
但能力上限就是 7 种事件、无结构化 `tool_call`。

---

## 4. 逐项对照：能不能伪装

| 维度 | 能否 | 状态 |
|---|---|---|
| HTTP 头 | ✅ | 已用真实 legacy 头 |
| 请求 body | ✅ | 已用反编译 schema |
| JWT / 设备指纹 | ✅ | 与客户端同款 |
| 账号授权 | ✅ | Free 账号正常可用（已证） |
| **会话状态链** | ⚠️ | 需要 `create_session → start_chat → subscribe_events` |
| **localhost 内部通道** | ❌ | sidecar 私有 HTTP，外部无法接入 |

**结论：身份不是瓶颈，`localhost` 那条内部通道才是。**

---

## 5. 真正可行的三条路

### A. 复现完整会话链（有希望）
不是打 `llm_utils_chat`，而是：
```
lite.create_chat_session → chat.start_chat → lite.subscribe_events
```
但 `start_chat`/`subscribe_events` 是发到 **localhost** 的——
需要先搞清 sidecar 是否真的监听某个本地端口。
（注：已实测 Trae 进程**无任何 LISTEN 端口**，所以这条路可能需要
另找 sidecar 的内部 IPC 入口，而 handoff 已记录 mojo 管道不可附加。）

### B. 驱动本机真实客户端（最可靠）
让 sidecar 替我们发。代价：依赖 Trae 常驻运行。

### C. 接受 v1/chat（当前现实）
能力上限 = 7 种事件、无结构化 tool_call。这是协议上限。

---

## 6. 给接手者的硬结论

1. **不要再调 `api/agent/v3/llm_utils_chat`** 期待主对话能力——已证否。
2. **不要再怀疑账号授权或登录流程**——都已验证正常。
3. **agent 能力在 `lite.start_chat` 这条链上**，而它走 localhost 内部通道。
4. 若目标是「单进程、纯 HTTP、复现原生体验」，**这条路大概率走不通**；
   需在 A（逆向 localhost 通道）和 B（驱动真实客户端）之间选。
