# Trae 原生 LLM 路线下一阶段执行计划

日期：2026-10-26

## 目标与边界

目标是让代理通过已验证为 Trae CN 客户端支持的远端 LLM 协议完成指定模型的普通文本 chat；tools、tool_choice、reasoning、stream/usage/cancel 按能力逐项验证和开放，不要求它们全部先于普通文本可用。当前目标不默认包含完整 Trae agent task、workspace/worktree 操作、工具审批 UI 或其他 agent 副作用。

当前静态证据显示 `/api/ide/v2/llm_raw_chat` builder 比 Solo Lite 的 `lite.send_message` agent/session 流更接近普通 LLM 请求，但活动调用者、完整 schema、模型配置接受行为和响应语义尚未确认。此前一条 V2 假设请求收到 HTTP 400 且零字节响应；后续 mint→条件式 V2 诊断在 GetUserToken 阶段收到 HTTP 404，故没有发送 V2 请求。两次结果原因都未知，不能据此归因于某个 body 字段、模型配置、传输或认证问题。下一步执行本计划的 A/B/C/D 证据门，不推测生产协议或自动换 host/模型重试。

## 当前状态

以下状态来自本阶段协作记录；它们不是本计划文档新运行的验收：

- 静态 V2 builder 和 R3 脱敏字典准备完成。
- 46/46 本地基线通过。
- R3 本地 harness 的 22 项核心检查与 7 项 sanitizer 检查通过；与指定 UI turn 配对的 R3 观测尚未执行，测试端就绪并经独立审查后才由主 agent安排。
- V2 假设请求已单次执行：`POST /api/ide/v2/llm_raw_chat` 返回 HTTP 400、content-type 为 other、读取 0 字节，净化结果没有 schema、marker、model 或 usage 字段，exit 1；单请求预算为 1，未重试。此结果不能确定拒绝原因，也不证明 messages 形状、模型字段或生产必填 schema。
- V2 harness 位于 ignored `logs/native_v2_probe_20261026/v2_probe.py`；14 项本地模拟通过并经独立审查。SDK builder 的字段列表是静态白名单；本次候选 body 仍是假设。
- SDK `Ping` 静态映射为 GET `/api/ide/v1/ping`。轻量对照已各发送一次 curl_cffi Chrome124 与 httpx GET；两次均 HTTP 200、content-type 为 json、HTTP/1.1，无白名单 numeric API 错误码；总预算 2、exit 0。harness 在 32 KiB 上限内读取响应体以抽取该错误码，但没有输出正文或语义值。该结果只证明两种客户端栈都收到 HTTP 200/JSON，不证明 ping 响应语义、V2 JWT 权限或 V2 可用性。
- SDK `ModelList` 静态映射为 GET `/api/ide/v1/model_list`。已有一次请求返回 HTTP 400/JSON，投影识别到 numeric API code 4001，未识别目标；请求参数、权限或其他拒绝原因未知，不据此判断模型不可用，也不进行 host/type 变体或盲重试。未保存或输出模型/账号值。
- 两个 tracked 静态快照 `trae2api/models_fallback.json` 与 `notes/model-catalog.json` 均包含目标 canonical `name` 记录（各五个上下文）。记录 schema 有 `name:string`、`provider:string`；fallback 没有 `config_name` 或 `config_source`，catalog 有 `config_name:string` 与 `config_source:integer`。两者都没有 `model_name` 或 `user_selected_model_name`。catalog 中目标记录的 `config_name` 与 canonical target 相同。此快照只说明仓库提交的静态记录，不证明当前服务端配置有效或存在活动调用。
- mint→条件式 V2 harness 仅执行一次当前配置 host 的 `POST /api/v2/GetUserToken`：HTTP 404/content-type category `other`/error category `http_4xx`，预算 1/2；`v2.request_attempted=false`, `skip_reason=mint_failed`。`valid_before/valid_after=true` 仅是旧内存 JWT 的本地 exp 检查，mint 失败、`new_equals_old=null`；不证明旧 token 无效、登录失败或上游权限。finally 的 client close 均为 true、`cleanup_complete=true`。未重试、换 host、发送 V2 或 attach R3。
- 本次诊断没有事务级 host 记录；失败后只读 auth 配置来源为 `live_storage`、host enum `api_trae_cn`，与 `api.trae.cn` 一致，这是事后配置佐证。安装 `out/main.js` 的静态 GetUserToken helper 仅找到 USDS 旧转换 caller；GenerateTempToken helper 写临时 `trae-jwt-token` 文件，但没有证据表明该 token 进入 SDK 的 `CopilotService.jwt`。
- 普通 CN 登录的静态链已补充为 `ExchangeToken` 返回 `Token` → `userInfo.token` → Workbench `GET_USER_INFO` → native RPC `params.user_info.token`；native handler 如何消费/转发仍未知。SDK 接受 `jwt` 并构造 `Cloud-IDE-JWT` header，但未找到普通 CN token 到该 SDK prop 的 caller。
- 单独的 90 秒 metadata-only observer 已运行：指定 NetworkService PID/模块身份复核通过，仅安装 Cronet `InitWithParams`/`Start` 两 hooks，不读 provider/body/header/query；coverage 全零并正常 unload/detach。driver 曾把 readiness 的 `body_eligible=false` 反转投影为 true，原始 hook metadata 与 JS 均显示 `body_api_ready=false` 且无 body hook；bug 修复后通过 6 项 sanitizer 自测，未再次 attach。该窗口不是与指定 UI 测试配对的观察，不能闭合 route/auth。
- R1/R2 metadata 曾观测到 AgentV3 URL 形状，但未与指定 UI turn 唯一关联；V1、SDK V2、AgentV3 不能按版本号推断为同一调用链。与指定 turn 配对的 R3 仍未执行。
- 配对观察 R4 的 JS/Python harness 已独立审查，离线模拟各 23 项通过。最新 UI 预检未能可靠识别目标测试窗口中的模型/输入控件，故 observer 未启动、未 attach、未发送固定 marker，也没有开始 120 秒观察窗。此状态为“未执行”，不能记录成零覆盖或任何 route/model/response 结果。
- 随后 Trae 已重启且当前原件换版；旧 R4 在换版前没有启动。B 已将观察器身份目标更新为 PID 103824/创建时间 `2026-10-26 13:36:51`/根目录 `sscronet.dll` SHA `288F987E...984FB79A`，独立静态复核确认必需导出和 Read/OnResponseStarted alias 仍匹配。该版对应的同版 generated IDL/精确原型尚未确认，且新 renderer session 目录暂缺 `window3\renderer.log`；因此 observer 仍未 arm/attach，UI marker 测试暂停。新版原件的其他 native/JS hashes 与旧证据不同，旧 RVA/偏移与调用链结论需按新 hash 重审。

## 当前取证阶段 A/B/C/D

### A：native DLL xref / dataflow

**负责人：**`real_path_investigation` 提供候选函数、模块/偏移及静态调用/数据流证据；`proxy_contract_audit` 独立核对。

**范围：**沿已静态证明的 `params.user_info.token`、`lite.send_message` handler、模型/config、候选 route builder、transport 与 response/event callback 做静态 xref/dataflow。只用安装原件，不读取 token 值、不调用未知 export、不 attach。

**产物与通过条件：**每个候选点给出文件 hash、偏移/RVA、可解释参数类型/ABI边界和“静态确证/推断/未知”标签。字符串或函数名不单独算数据流。

**失败分支：**若 DLL 无法支持进一步 dataflow，保留 native token 消费/route 为未知，不扩大到凭据、用户会话内容或任意进程内存。

### B：身份复核与配对观察准备

**负责人：**`real_path_investigation` 准备受限观察；主 agent安排现场身份复核和任何触发；`proxy_contract_audit` 不 attach。

**状态：**已有 90 秒 metadata-only observer 通过代码/本地模拟 review 后被实际运行，指定 PID 和模块身份复核匹配；只安装 `InitWithParams`/`Start` 两 hooks，body API 未安装，coverage 全零，正常 unload/detach。driver readiness sanitizer 反转 `body_eligible=false` 的投影缺陷已修正并通过本地 6-case 自测，但未重 attach。此观测不是配对 R3，不能证明指定聊天流量或 route/auth。

**进入条件：**指定目标测试端身份/创建时间/module SHA、固定合成标记、hook ABI/唯一关联键、预算/自动停止/cleanup 和可输出字段均事先写明。若将来申请 body 观察，先说明 marker gate、字节上限、跨 chunk、对象生命周期和 allowlist，再由主 agent审批。

**通过产物：**独立审查的 harness 与离线测试通过，输出 schema 和 coverage 限制清楚；“准备通过”不表示已关联原生消息或证明 route。

### C：proxy_contract_audit 独立审查

收到 A 候选点与 B harness 后，核验 ABI/类型及对象映射、请求关联门、真实字节长度和跨 chunk 处理、隐私输出、请求预算、timeout/cleanup、fault coverage。只做静态 review 与本地检查，不 attach、不发网络、不触发业务请求；报告阻断项和通过数。

### D：主 agent 触发与验收

只有主 agent安排并批准后才触发固定合成 turn。结果需将 UI/RPC/native/upstream 证据稳定关联，并列出未命中覆盖。经主 agent验收后再决定协议路线和实现责任；观察脚本准备、静态 route 或孤立 HTTP status 都不授权业务实现。

### 后续业务实现门

普通文本最小门只需证明选定协议/认证路径、目标模型配置被接受、message role/schema 或明确拒绝策略、合成固定回复，以及基本错误/terminal 语义。tools/tool_choice、reasoning、stream/usage/cancel 分别设独立通过门；某项未证就对该项显式不支持，不静默丢弃或伪造成功，也不因此把其他已证的普通文本能力一并阻塞。任何业务代码仍需主 agent重新分配文件所有权与实施授权。

## S1–S4 后续产品/实现与验收蓝图

以下 S1–S4 是后续执行模板，不代表当前阶段或自动授权。当前只按上面的 A/B/C/D 做静态核查、准备、独立审查与主 agent 现场验收。S1 中的一次性 V2 假设请求已经执行且未建立成功契约；不得按模板重复请求、换模型或换 host。只有 D 验收后，主 agent 才决定是否进入实现阶段并另行分配文件所有权。

## S1：确认所选路线的最小普通文本契约（候选路线未预设为 V2）

**负责人**

- `real_path_investigation`：准备一次性的 V2 最小假设诊断 harness，列出唯一请求所需的模型/config、固定合成 prompt、预计 wire 字段、观测与清理边界。
- `proxy_contract_audit`：独立审查 harness、字段假设、R3关联/脱敏与结果解释；不与 runtime owner 同时 attach。
- `native_test_ui`：追踪 model/config metadata builder，并维护现有 46/46 本地基线；本阶段不改回归测试文件。
- 主 agent：审阅 harness 和精确的一次请求参数，明确授权后才运行诊断。

**进入条件**

1. 候选路线有安装原件与静态结构证据；当前目标模型/config 的静态记录不算服务端已接受，也不证明 caller 活动。
2. harness 有固定、短小、无用户数据的合成请求和可识别的固定回复；展示会发送的字段、目标 model/config、观察字段和清理方式。
3. R3 观察端已就绪；仅当目标测试端与关联条件可用时 arm。观察过程不保存 raw URL/body、headers、认证材料或真实对话。
4. 主 agent 明确批准该次假设 body。批准只覆盖这一项诊断，不授权自动重试、换模型、扩字段或提交其他消息。

**执行与产物**

1. 从已发现的 SDK builder 和 config metadata 证据构造一份最小假设请求；逐项标记“静态已知”“本次假设”“未知”。不得把假设字段写成 SDK 必填契约。
2. 只在批准后发送一次固定合成请求；不盲重试、不自动降级或切换模型。
3. 记录无敏感内容的请求字段名/类型、实际 route/method、目标配置是否被接受、固定回复是否符合预期、错误类别、usage 语义、stream wire 行为和 terminal 状态。真实值仅按已审查的 allowlist 处理。
4. 同一请求必须通过稳定关联证据对应到目标 Trae 操作及远端请求；时间相近或相同 host 不足以证明调用关系。

**通过条件**

- 已确认 SDK builder 的实际调用路径，而非只找到静态类方法或 route map。
- 目标 model/config 被服务端接受，且没有静默替换为其他模型；若响应无可验证的实际模型标识，则把接受状态留为未知。
- `messages` 的普通文本 role/schema 已明确（system/developer 若不受支持则有明确拒绝策略），指定固定合成请求得到预期固定回复。
- 选定非流式文本路径的错误与 terminal 语义足以避免伪成功；不要求该阶段证实未启用的 tools、reasoning 或 stream。
- tools/tool_choice、reasoning、stream/usage/cancel 均单独记录证据状态；只有对应能力的契约证实后才可启用。`stream:true` 本身不证明 SSE 支持，缺失 usage 语义不允许伪造 usage。

**失败或不完整分支**

- 若 model/config 被拒绝、改写或未能确认：停止请求；回到 native_test_ui 的 model/config 元数据证据，或由主 agent决定是否以错误/schema 为依据再审查唯一假设。
- 若普通文本 role/schema、目标配置或 terminal/error 语义仍不清楚：阻止普通文本实现并回到 A/B 补证。若只是不清楚 tools、reasoning、stream 或 usage，则只阻止/关闭依赖该项的能力；不得把普通文本成功扩大解释成其他能力已通过。
- 若 route/body 无法与同一操作关联：诊断不通过；修正观察准备后再由主 agent决定是否重新授权。不得从静态 V3 词表猜测实际 route。

**S1 通过后交付**

- 脱敏 harness 执行记录、精确命令、一次请求的有限结果、模型/config 证据、已确认字段和未决字段。
- 主 agent 对选用 V2 或回到配置/R3取证作路线决策。

## S2：按已证契约实现可切换的新 transport

**进入条件**

1. S1 普通文本最小门通过；每个拟开放的可选能力也通过自己的契约门。主 agent 书面选定协议路线及需支持的字段集合。
2. 主 agent 为代码阶段明确分配文件所有权和实现范围；不从当前计划自动开始实现。

**负责人**

- `real_path_investigation`：新 transport 模块及 server 接入。
- `native_test_ui`：之后负责独立回归测试；本阶段开始前不改测试。
- `proxy_contract_audit`：独立检查 request/response 契约保真、错误边界和兼容性。
- 主 agent：决定合并接口和 capability behavior，并验收实现。

**实现约束**

- 新通道先做成可配置、显式启用的路径；旧用户路径保持可回归，不与新通道混改，不重启或占用当前 8080 服务。
- 对已证的 `messages`、system/developer role、tools、tool_choice、reasoning 字段进行保真映射；若远端不支持某字段，返回清楚的 capability/error 信息，不静默丢弃或伪装成成功。
- 不推测 V2 必填字段、tool result schema、usage 或 stream 格式。只实现 S1 已证部分，其余明确返回未支持/未知。
- response 中的 `model` 必须来自可验证的上游实际模型结果；不能只回显调用方请求值来冒充已采用的模型。
- 按证据处理 usage、terminal、超时、断连与取消；不得将本地读流停止声称为上游生成已取消。
- 不记录 raw prompt/response、headers、secret 或认证数据；不旋转 refresh token。

**S2 产物与通过条件**

- 独立 transport/server 接入实现、接口说明、配置开关和可运行但未占用 8080 的验证方式。
- 代码映射与 S1 契约逐项对应；未知项有明确拒绝/标识路径。
- 通过 `proxy_contract_audit` 独立 review 后，主 agent 才批准进入 S3。

**失败分支**

- 发现 S1 契约解释错误或实现需要未证字段时，暂停相关能力，回到 S1补证；不得通过扩大隐式默认值绕过缺口。
- 若新通道会改变旧路径结果或要求重启 8080，先调整隔离方案，不继续该部署方式。

## S3：隔离实例正反对照验收

**进入条件**

- S2 实现与 review 完成；有独立空闲端口和隔离配置，不影响现有 8080 实例；测试账号/model/config 和操作已获授权。
- 原生对照和代理测试使用相同指定模型/config、等价短合成输入，并能关联每次请求。

**测试负责人**

- `native_test_ui`：新增并运行独立回归测试。
- `real_path_investigation`：提供已证原生请求/事件对照和隔离 runtime 支持。
- `proxy_contract_audit`：审查测试设计及结果是否足以支持结论。
- 主 agent：批准端口、命令和任何受控客户端请求。

**覆盖矩阵**

| 场景 | 验收内容 |
|---|---|
| 普通回复 | 指定 model/config、role/schema、固定回复和实际 `model` 一致；无静默 fallback。 |
| 工具往返（按需启用） | 若声明支持，验证 tools/tool_choice、调用、结果回传与 ID 关联；未通过时该能力明确不支持，不阻断普通文本验收。 |
| 流式/非流式（按需启用） | 普通非流式按最小契约验收；若声明支持流式，再验证真实 wire、token/terminal/event 顺序与取消语义。 |
| 模型拒绝与协议失败 | 未支持模型/字段、服务端拒绝、无效响应均给出明确错误，不伪造成功。 |
| 失败/超时/取消 | 普通文本路径验证错误分类和资源清理；只有声明支持流式/取消时才验收对应上游语义。 |
| 旧路径回归 | 原有 API 的行为与基线一致，新通道默认关闭或按配置选择。 |

**安全与通过条件**

- 仅使用正常账号和短合成消息，不读取或输出真实对话、raw request/response、认证头或 secret；不旋转 refresh token。
- 观察器只输出审查过的 metadata，不留原始 body；完成后清理测试产物和临时观察器。
- 原生与代理差异可按上述矩阵逐项解释；未覆盖或无法验证的格子标为未知，不能汇总成“完整原生等价”。
- 46/46 本地基线继续通过，且新回归测试覆盖新通道与旧路由。

**失败分支**

- 任何真实模型不一致、字段静默丢失、usage/event 语义不明、工具往返不匹配或旧路径回归失败，都阻止 S3通过；回退到 S1补证或 S2修正，不在生产端口试错。

## S4：主 agent 验收与交接

**进入条件**

- S3 的对照记录、测试命令/结果、实现清单和差异说明已齐全；报告不包含 raw/secret。

**交付内容**

- 各阶段实际完成项、证据来源、未验证项与失败分支结果。
- 新增/修改文件清单、配置开关和隔离运行方法、测试命令及结果。
- 已知限制、回滚方式以及下一步建议；区分“未运行”“失败”“通过”。

主 agent 完成最终验收并更新交接材料。本计划不授权 commit、push、deploy 或在 S3后直接替代主 agent验收。

## 本计划之后的即时动作

V2 假设请求 HTTP 400/零字节与后续 mint 404 是两次独立结果，均原因未知；mint 404 后明确没有发送 V2。Ping 只证明两种客户端栈收到 HTTP 200/JSON；ModelList 单次请求为 HTTP 400/API 4001。tracked 模型快照不证明当前服务端接受配置。普通 CN `ExchangeToken → userInfo.token → params.user_info.token` 是静态客户端链，native handler 后续如何消费仍未知；GetUserToken 的 USDS caller、TempToken 文件都不能替代该链。90 秒 metadata observer 已运行但 coverage=0，readiness sanitizer bug 修复后没有再次 attach；指定 turn 的 R3 关联仍缺。R4 observer 已独立 review，JS/Python 离线模拟各 23 项通过，但 UI 预检失败后没有 arm/attach、marker 触发或 120 秒观察，因此没有 R4 route/response 证据。下一步待目标 UI 可可靠操作时由主 agent重新安排身份复核和配对观察；普通文本与各可选能力分别过门，未有主 agent触发/验收前不发新网络请求、不自动重试/换 host、不实现业务 transport。
