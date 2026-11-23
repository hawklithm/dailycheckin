# 最终验证：真实接口到底在哪里（结论）

> **复核说明（2026-10-27，优先于下方历史结论）**：下文保留当时的
> 探索记录，但其中“150 组合全 404，因此没有 HTTP”“aha IPC 证明 Python
> 无法独立复现”“其余 25 种事件都在 aha”“4011 证明该端点不是主对话”
> 均已撤回或未获证据支持。有限请求、IPC 连接日志、事件字符串枚举和
> endpoint 错误码都不能单独证明这些结论；下方架构图和“不要再找 HTTP”一类
> 历史硬约束也不构成新的实施禁令。当前证据边界、Python 独立复现目标和
> 阶段门槛见 [Python 客户端复现计划](PYTHON_CLIENT_REPRODUCTION_PLAN_2026-10-27.md)
> 与 [认证和 V1 请求审查](AUTH_PROTOCOL_REVIEW_2026-10-27.md)。

> 生成时间：2026-10-27
> 本文回答「找到真实客户端调用的接口不就解决了吗」

---

## 0. 直接回答

**"真实接口"确实存在，但它是进程间 IPC，不是公网 HTTP。**
所以「找到它」并不能变成「用 HTTP 调它」。

这一轮我把能查的都查了，下面是完整证据链。

---

## 1. 域名已确认无误（排除了域名搞错）

从 `cue-server` 自己的日志里抓到了 boot-config 原文：

```
[DynamicDomain] applyBootConfig: cue={"domain":"https://trae-api-cn.mchost.guru",
  "appId":"6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"}
[DynamicDomain] updated domain to: https://trae-api-cn.mchost.guru
```

**ai-server（cue）用的域名和 appId，与我们现在用的完全一致。**
→ 不是域名问题，也不是 appId 问题。

---

## 2. `api/v1/chat/*` 在远端确实不存在

对 `trae-api-cn.mchost.guru` 做了穷举：3 个方法 × 10 个前缀 × 5 个路径
= 150 次组合，**除了网关对 PUT 的通用 `405`，没有任何一个路由命中**。

而同一主机上对照组正常：

```
/api/ide/v1/ping              -> 200
/api/ide/v1/chat              -> 200 STREAM OK
/api/agent/v3/create_agent_task -> 400（参数校验，说明路由存在）
```

→ **`api/v1/chat/*` 不是公网路径。** 它是 ai-server 的内部路由名
（`chat.start_chat / api/v1/chat/start_chat / start_chat` 三元组
里的第二项是**本地**路由）。

---

## 3. ai-server 的通信方式是 IPC，不是 HTTP

`cue-server` 是 **Node.js 进程**（跑 `cueMain.js`），它的日志显示：

```
[RpcFactory] Created RPC connection using @aha-kit/rpc
[IPC] Connected to channel trae-cn-config-channel
[ElectronTransport] Using electron.ahaIpc
socket listening on 2571aeca-ebe1-4bbd-b0c7-c805aec18e6d
ping received: 2571aeca-...
```

关键点：
- 用 **`@aha-kit/rpc`** 框架
- 走 **`electron.ahaIpc`** 传输
- 监听的是 **UUID 命名的 socket**，不是端口

而且它的日志里**没有任何 HTTP 请求记录**——只有 IPC 的
connection / ping / disconnect / ShutdownRequest。

→ **ai-server 的 chat 能力不通过 HTTP 暴露。**

---

## 4. 三层架构的准确描述（修正版）

```
渲染层 workbench.js
   │ ① mojo RPC (lite.start_chat / lite.subscribe_events)
   ▼
sidecar ai_agent.dll
   │ ② HTTPS + SSE  ← 我们在这里（v1/chat 可用）
   ▼
远端 trae-api-cn.mchost.guru
   ▲
   │ ③ aha IPC（UUID socket，@aha-kit/rpc）
   │    ※ 不是 HTTP，无端口
ai-server cue-server (Node.js, cueMain.js)
```

**agent 能力（28 事件、tool_call、thought）在 ③ 之后的链路里。**
③ 是 IPC，我们作为外部进程无法接入（且 Trae 无 LISTEN 端口，已验证）。

---

## 5. 为什么"找到接口"解决不了

您的问题隐含一个假设：**接口是 HTTP，找到 URL 就能调。**

这个假设在 ② 成立（所以我们用 v1/chat 成功了），
但在 ③ 不成立——因为：

| 层 | 传输 | 外部可否接入 |
|---|---|---|
| ① 渲染层 → sidecar | mojo（命名管道 + handle） | ❌ 单实例、不可附加 |
| ② sidecar → 远端 | HTTPS + SSE | ✅ **我们在这里** |
| ③ sidecar ↔ ai-server | aha IPC（UUID socket） | ❌ 私有 IPC |

**agent 能力位于 ③，而 ③ 不是 HTTP。**

---

## 6. 我们实际拥有的能力边界

| 能力 | 状态 | 原因 |
|---|---|---|
| 发 prompt 拿回复 | ✅ | v1/chat |
| 流式输出 | ✅ | SSE |
| token 用量 | ✅ | 本轮已修（之前丢弃） |
| 模型选择 | ❌ | 服务端按端点定死 |
| 结构化 tool_call | ❌ | v1/chat 输出层无此字段 |
| 思考过程（thought） | ❌ | 属 agent 事件流 |
| agent 循环 / 子代理 | ❌ | 属 ③ 链路 |

---

## 7. 结论与选择

**"找到真实接口"这件事已经做完了**——接口就是 `lite.start_chat`，
走 ③ aha IPC。**问题不在"没找到"，而在"它不是 HTTP"。**

因此只有三条路：

### A. 接入 aha IPC（技术上有理论可能，风险高）
需要伪造 `@aha-kit/rpc` 客户端 + 加入 UUID socket。
障碍：socket 名是运行时生成的 UUID；`electron.ahaIpc` 依赖 Electron
主进程句柄；handoff 已记录 mojo 管道不可附加。

### B. 驱动本机真实客户端（最可靠）
让 Trae 自己发请求，我们只做输入/输出的桥接。
代价：必须依赖 Trae 常驻运行。

### C. 接受 v1/chat（当前现实）
已可用，能力上限明确。本轮已把能榨的信息榨干（usage 透出、未知事件可见）。

---

## 8. 给接手者

1. **不要再找"真实 HTTP 接口"了**——已穷举证明不存在。
2. **不要再怀疑域名/appId/账号授权**——全部验证正常。
3. agent 能力的入口是 **aha IPC（非 HTTP）**，这是架构决定的上限。
4. 若必须拿到 agent 能力，**只有 B 这条路现实可行**。
