# Trae CN 原生 DLL 调用链静态审计（2026-10-26）

## 目标与边界

本报告只追踪当前安装 `ai_agent.dll` 中与 `lite.send_message`、AgentV3、`LLMRawChatV2`、认证和网络传输相关的静态证据。未读取真实凭据、私钥或对话；未调用导出函数、连接 pipe、attach 进程或发出网络请求；未修改安装文件或业务源码。

当前安装原件：

| 项目 | 值 |
|---|---|
| 路径 | `D:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app\modules\ai-agent\ai_agent.dll` |
| SHA-256 | `ACAED4D3C3B9B93D4654AED3D6DDAAC884F1ACC4C7E3A8FB283C37A9CE9C516B` |
| 大小 | 278,400,912 bytes |
| PE | x64 / AMD64，ImageBase `0x180000000` |

审计使用 PE 节区、`.pdata` 函数范围和反汇编交叉引用。当前原件未带对应 PDB，二进制也没有可用的应用级 Rust 符号；因此函数只能用 RVA 标识，不能还原源码行或可信函数名。`.pdata` 中解析出约 701,131 个函数范围。已有的全 `.text` Capstone 扫描解码约 39,268,910 条指令；结论仅限这些静态引用与函数边界，不表示对应代码在本次 UI 会话中执行。

地址换算：`.text` 的 RVA `0x1000` 对应文件偏移 `0x400`；`.rdata` 文件偏移到 RVA 加 `0x1800`。下文先写文件偏移或 RVA 时会注明单位。

## 已证调用链边界

已有动态审查记录确认 renderer 将 `lite.send_message` 交给本地 RPC，且本地 RPC 返回成功；该证据只到本机模块边界，不证明远端模型请求成功。参见 [REAL_PATH_REVIEW_2026-10-26.md](REAL_PATH_REVIEW_2026-10-26.md) 和 [NATIVE_PROTOCOL_CONTRACT_2026-10-26.md](NATIVE_PROTOCOL_CONTRACT_2026-10-26.md)。

本 DLL 中能确认的是 `LiteHandler` 的静态日志和方法名集合，以及下述序列化结构；目前没有找到从 `lite.send_message` 的 handler 函数继续到 `ModelService` / `LLMAdapter` / AgentV3/V2 route 构造器的可证函数调用链。因此不把 renderer→本地 RPC 的动态成功外推成 native→远端 LLM 的已证链路。

### RPC Request 与 user_info

静态数据区出现 `struct Request with 9 elements`：

| 文件偏移 | 同一结构附近证据 |
|---|---|
| `0xA26EBE4` | Request descriptor pointer slot 在 `0xA26EC08` |
| `0xA3EC8E4` | Request descriptor pointer slot 在 `0xA3EC908` |
| `0xA52A7A0` | Request descriptor pointer slot 在 `0xA52A7C0`，附近有源码路径 `apps\\icube_server_rs\\modules\\ai-agent\\src\\handler\\base.rs` |

字段名字符串包括 `service`, `method`, `data`, `user_info`, `client_info`, `common_params`, `streamlined_common_params`, `custom_params`, `scheduled_task_context`。这证明 DLL 带有相应 Request 序列化/反序列化 schema；不能单凭 schema 证明 `LiteHandler.send_message` 的运行时对象经过该副本，也不能证明字段随后被模型调用使用。

`user_info` 键的若干 serde/字段描述引用落在函数范围 `0x528D1A0..0x528ECED`、`0x417E58D..0x418221F`、`0x5FFB46C..0x5FFCDB9` 和 `0x5C016A3..0x5C01909`。这些是生成式字段处理的 xref，不是已确认的业务 dispatch 或 LLM caller。

`struct UserInfo with 11 elements` 见文件偏移 `0xA273145`、`0xA3F6B5D`、`0xA530088`。附近可读字段名包括 `token`, `is_internal`, `jwt_token_type`, `loginScope`, `tenant_id`, `enterprise_info`, `email`；这里只列能直接看到的字段，不推测其余字段或字段语义。

**认证数据流断点：** schema 中存在 `user_info.token`，但静态审计未证明它从 handler 传入 AI 服务，也未证明它被映射为 `Authorization`、`x-ide-token`、`Cloud-IDE-JWT` 或 provider key。字段名相同不构成 token 等价或流向证据。

### AgentV3 与 LLM route 字符串

DLL 中路由字符串位于静态 endpoint 数组，而非当前已证请求的 callsite：

| 字符串/数组 | 文件偏移 | 反汇编证据 | 能说明什么 |
|---|---:|---|---|
| `api/agent/v3/...` 列表起点 | `0xA58C788` | 构造器 RVA `0x676AE0A..0x676B0EC` 对各字符串生成 16-byte 字符串描述并复制数组 | 存在静态 AgentV3 endpoint 列表 |
| `api/ide/v2/llm_raw_chat` | `0xA58CBC8`（RVA `0xA58E3C8`） | 构造器 RVA `0x676B5AF..0x676C4FC` 生成静态 endpoint 描述并复制数组 | 存在 V2 路径字面量及表构造，不证明它被本会话调用 |
| `api/ide/v1/llm_raw_chat` 变体 | `0xA58CBF2`, `0xA58CCE6` | 同一 endpoint 数组构造器 | 静态 V1 路径字面量 |

进一步的静态构造关系：RVA `0x676D726..0x676DF6C` 调用 IDE endpoint 表构造器（调用点约 `0x676D76A`）；缓存访问函数 RVA `0x676B42F..0x676B51E` 在 `[r14+0x10]` 为空时，于 `0x676B4DD` 调用 `0x676D726` 构建约 `0xBE8` 字节结构并保存。它把 endpoint 表连接到一个延迟构造/缓存结构，但没有证明该结构被 `LiteHandler.send_message` 或 LLM caller 消费。

**重要区分：** `api/agent/v3/*` 与 V2 route 目前是“静态路径表候选”，不是活动路由证据。没有捕获到本次测试会话中对应的 outbound request，也没有从表访问函数走到网络调用的已证 xref。

### LLMAdapter / ModelService 线索

静态日志字符串包含：

- `[LLMAdapter] llm_raw_chat_custom_model:`（文件偏移 `0x99C13E1`, `0xA3A6E31`）
- `[LLMAdapter] llm_raw_chat_custom_model request:`（`0x99C14E1`, `0xA3A6F39`）；格式占位字段包括 `model_info`、`token`，本报告不包含运行时值
- `[ModelService] llm_raw_chat error:`（`0x99E6549`, `0xA3C3DB1`）
- `[create_agent_task] request body:`（`0x99BBE91`, `0x9AD0939`, `0xA1CFBE1`, `0xA447B39`）
- DTO 类型名如 `LLMRawChatMessage`, `LLMRawChatImageURL`, `LLMRawFunctionCall`, `LLMRawMultiContent`, `LLMRawToolcallItem`, `ModelCustomConfig`, `ModelPromptConfig`

这些 DTO 名称位于文件偏移 `0xA4CFA44`、`0xA4CFB2E` 一带。它们证明 DLL 包含相应日志格式与 DTO 名称，不证明 `LLMRawChatV2` 具体 schema、该路径被当前会话选中，或 `token` 格式字段就是 Request 的 `user_info.token`。目前没有可报告的 LLMAdapter→route builder→transport 确证 caller。

## 认证线索与边界

静态字串 `Cloud-IDE-JWT` 出现在文件偏移 `0x99CB13D`, `0x9BAAE86`, `0xA294FAD`, `0xA4E51A8`, `0xA500FB1`。可定位上下文分别与 CKG refresh 日志、Skill Import handler（包含源码路径 `skill_import.rs:548`）及 Design Library handler 相关；这些上下文不能证明该 header 用于 LLM 请求。

`Authorization` 和 `x-ide-token` 也出现在 DLL 的其他静态区/服务中，但未找到它们与 `LiteHandler`、`LLMAdapter` 或上面的 V2 endpoint 表之间的调用链。当前能证明 `Request.user_info` schema 有 `token` 字段；不能证明 token 如何被处理、签名、交换或写入请求头。

## 网络桥接线索

PE import table 有 `winhttp.dll` 的 `WinHttpOpen`, `WinHttpConnect`, `WinHttpOpenRequest`, `WinHttpAddRequestHeaders`, `WinHttpSendRequest`, `WinHttpReceiveResponse`, `WinHttpReadData`, `WinHttpWriteData`, `WinHttpCloseHandle`，IAT 区域约 RVA `0x97FF530..0x97FF5A8`。`.text` 中能看到 WinHTTP 实现簇：

| 操作 | 代码 RVA 范围/调用点 |
|---|---|
| `WinHttpSendRequest` | 函数范围 `0x9260364..0x9260626`，调用点 `0x92603EA` |
| `WinHttpOpen` / `WinHttpConnect` | `0x926096C..0x9260BE7`，调用点约 `0x9260A77` / `0x9260B09` |
| `WinHttpOpenRequest` / `WinHttpAddRequestHeaders` | `0x9260E1C..0x9261473` |
| `WinHttpReceiveResponse` / `WinHttpReadData` | `0x9261494..0x9261AC0` |
| `WinHttpWriteData` | `0x9261494..0x9261AC0`、`0x9261DDC..0x9261E96`、`0x9261E98..0x9261F89` |

这是 DLL 中某类 native HTTP 的明确实现证据，但没有找到它从 AgentV3/V2 endpoint 表、ModelService 或 LLMAdapter 被调用的链路。DLL 同时导入 Winsock；其引用分布在其他区域，尚未与目标 route 连接。现有动态审查观察到 Chromium NetworkService/Cronet 元数据，但没有同一 RPC 会话到某个 outbound route 的事务级对应关系。不能据此将 WinHTTP 或 Cronet 任一者指定为本次 LLM transport。

## 已证 / 候选 / 未知汇总

| 等级 | 结论 |
|---|---|
| 已证 | DLL 含本地 RPC `Request` / `UserInfo` schema；存在 `lite.send_message` 相关 handler 字符串；存在 AgentV3、V1/V2 LLM route 字符串及 endpoint 数组构造器；存在 WinHTTP 请求/响应实现簇。 |
| 候选 | 延迟缓存中的 endpoint 数组可能用于某个 AI 服务；WinHTTP 簇可能是某些 native outbound 请求的 transport；LLMAdapter 的 `token`/`model_info` 可能参与自定义模型调用。 |
| 未知 | `lite.send_message` 的确切 DLL 函数体/运行时 Request 对象；当前会话是否执行 AgentV3 或 V2；`user_info.token` 到 LLM auth 的映射；真实 host、method、header、body、response schema；目标路由实际使用 WinHTTP、Cronet 还是其他桥接。 |

## 下一步最小动态观测点

要闭合断点，优先做同一固定测试会话的元数据关联，不采集 token 或原始消息：

1. 在 Request 反序列化之后、LiteHandler dispatch 处只记 `service` / `method` 字面值和 `data` / `user_info.token` 是否存在及其类型；不记录值、长度或摘要。
2. 若进入 ModelService/LLMAdapter，只记录所选 handler 名、模型/config 字段是否存在及类型，和 outbound URL 的 scheme/host/path/method；不记录 query 内容、headers 值或 body。
3. 在 transport 出口只记录 header 名集合/授权 header 是否存在、response status/content-type/stream 标志及调用栈模块名，以线程/请求关联标记连接上一点；不输出认证值、prompt、completion 或原始响应。

可用类型来源是 DLL 中的 `Request`/`UserInfo` serde descriptors、DLL 的 `LLMRawChat*` DTO 名，以及安装 JS SDK 中 `LLMRawChatV2` builder（详见 `NATIVE_PROTOCOL_CONTRACT_2026-10-26.md`）。这些来源可以约束字段形状，但只有与一次真实调用的元数据/调用栈关联后，才能把它们称为活动调用链。

## 工作区状态

本次复核时仓库根目录为 `D:\workspace\trae2api`，分支 `master`，HEAD `837363f92e7d0cf0155cf17f8e71795f14196add`。本报告是新增的静态审计记录；未修改业务源码、Trae 安装件或既有说明，未 commit。开始时工作区已有的未跟踪计划/报告保留原状。
