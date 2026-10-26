# Trae 3.4.7 逆向：LLM 调用链路（重做）

> 上一轮基于 3.4.4，结论是"打 sidecar 的 mojo pipe 不可行"。
> 3.4.7 有变化，本轮重新逆向。**结论比上轮乐观得多**：
> 发现了 V2 端点、完整的 RPC 信封、以及计费接口。

## 0. 版本信息

| 项 | 3.4.4（旧） | 3.4.7（新） |
|---|---|---|
| appVersion | 3.4.4 | **3.4.7** |
| date | — | 2026-10-22 |
| ai_agent.dll | 265.5 MB | **267.2 MB** |
| harness.dll | — | **209.7 MB（新出现）** |
| toolhost.dll | — | **87.3 MB（新出现）** |
| sscronet.dll | — | 8.7 MB |

进程结构变化：3.4.7 除了 `process-type=ai` 的 sidecar，
**多了一个 `process-type=ai-server` 的进程**（`node.mojom.NodeService`），
它才是实际持有外网连接的进程（实测连到 Akamai CDN `23.200.231.108:443`）。

## 1. ★ 重大发现：V2 端点和计费接口

3.4.7 的 `ai_agent.dll` / `harness.dll` 里有这些端点（3.4.4 都没找到）：

```
api/ide/v2/llm_raw_chat          ← ★ 真正的 LLM 调用（V2！）
api/ide/v1/llm_raw_chat          ← V1 版本
api/ide/v1/model_list            ← 模型列表
api/ide/v1/get_model_list        ← 模型列表（另一个名字）
api/ide/v1/get_detail_param      ← 模型参数
api/ide/v1/batch_get_detail_param
api/v1/commercial/get_session_usage   ← ★ 计费/用量（解释了为什么控制台看不到）
api/v1/commercial/get_user_activity
api/v1/commercial/check_estimated_balance
api/v1/commercial/chat_mode
api/ide/v1/chat_prompt
api/ide/v1/connect
api/ide/v1/fast_apply
api/ide/v1/query_rewrite
api/ide/v1/intent_detect
api/ide/v1/context_select
api/ide/v1/web_search
api/ide/v1/web_fetch
api/ide/v1/text_to_image / tool_text_to_image / tool_text_to_image_stream
api/ide/v1/documentrag/*
api/ide/v1/wiki/*
api/ide/v1/agents/runs
api/ide/v1/agent/team_agent/*
```

**关键**：`api/ide/v2/llm_raw_chat` 就是 sidecar 自己调 LLM 的通道
（日志 `[LLMAdapter] llm_raw_chat_custom_model request: ...`），
而 `get_session_usage` 说明**用量是按 session 上报的**——
这直接解释了"我们打 `/api/ide/v1/chat` 控制台看不到消耗"：
我们既没有 session 归属，也没调用用量上报。

## 2. ★ 完整 RPC 信封（`convertReqToRustPayload`）

从 `workbench.desktop.main.js` 提取到渲染层发给 sidecar 的**完整信封**：

```js
{
  service, method, data,          // ← 业务请求
  user_info,                      // ← createUserInfo() 生成
  common_params: {
    ...icubeEventReportService.getCommonParams(),
    code_window_type,             // 窗口类型
    agent_tool_approval_type,     // manual_approval / auto_approval / full_access / custom_profile
    builtin_on_restrict,
    agent_type                     // ← data.agent_type
  },
  streamlined_common_params: { ...同上, agent_type },
  client_info: {
    ppe_env_name, connect_session_id, project_id, chat_session_id,
    version_code, workspace_folder, icube_language, confirm_config,
    device_id, workspace_id, terminal_info, is_solo_mode,
    client_type, window_type,
    git_repos, local_git_repos, git_metadata_dirs, local_svn_repos,
    security_rules, agent_task_service_strategy,
    enable_llm_utils_cloud, is_evaluation,
    is_worktree, is_workspace_folder_changed,
    workspace_folders, original_workspace_folder,
    runtime_environment_list, agent_run_info,
    web_fetch_strategy, web_fetch_ppe_env, web_fetch_blocked_domains,
    user_timezone, authorized_services, git_info, permission_profile_id,
    ckg_indexing_enabled, ckg_automatic_indexing_enabled,
    ckg_product_policy_enabled
  }
}
```

调用链：
```
UI → iCubeAgentService.request({service,method,data})
   → convertReqToRustPayload() 打成上面的信封
   → TransportManager.createRequestPacket()
   → _client.sendRequest("request", packet)   // mojo
   → sidecar → HTTP api/ide/v2/llm_raw_chat → LLM
```

## 3. 模型选择：`"auto"` 是默认值

```js
// service==="chat" && method==="chat" 时：
let F = x?.model_name || N?.model_name || x?.custom_model?.config_name || "auto";
if (x?.model_auto_selection?.strategy === "auto") F = "auto";
icubeEventReportService.updateCommonParams({ ai_model_name: F });
```

模型对象结构（从 DSL agent 加载处提取）：
```js
{
  model_name, provider, config_name, provider_model_name,
  tokenizer_name, max_tokens, prompt_max_tokens, max_turn, model_hyper_params
}
```
`config_name` 是主键（`custom_model.config_name` 优先于 `model_name`）。

## 4. JS→sidecar 的 RPC 面（13 个 service）

```
[agent] create create_or_polish_agent_via_llm delete enterprise_publish
        get_agents remove_mcp_server team_agent_details team_agent_list
        update update_mcp_agent_relations
[browser] check_bridge_connection focus_tab
[commercial] get_tenant_user_config
[configuration] get_user_configuration update_user_configuration
[context] slash_list
[context_asset] cloud_memory_policy create delete detail get_config list
               read_cloud_memory set_config update
[git] generate_commit_message get_return_to_local_session_git_context
[ide] sync_builtin_skills
[lite] batch_cleanup_session_snapshots batch_get_sessions_with_projects
[plugin] scan_plugins
[skill_import] cleanup_temp_dir extract_collection_zip extract_skill_zip
              install_collection_skill
[system_diagnosis] ...
```

sidecar 侧还有 34 个 Handler（3.4.7 同样存在）：
`ChatHandler / ModelHandler / LiteHandler / ToolcallHandler / AgentHandler /
ContextHandler / GitHandler / ProjectHandler / TaskHandler / SnapshotHandler /
TodoListHandler / SummaryHandler / SkillImportHandler / SandboxHandler /
PtyBridgeHandler / MultimodalHandler / CKGHandler / HubHandler / IDEHandler /
FileFinderHandler / DocsetHandler / DSLAgentHandler / GeneratedSkillHandler /
PluginHandler / PrivacyModeHandler / ScheduleHandler / CommercialHandler /
CoreMemoryHandler / ContextAssetHandler / DesignLibraryImportHandler /
HealthcheckHandler / MultiRootPathHandler / UserConfigurationHandler /
BaseHandler`

## 5. sidecar 启动方式（3.4.7，`meta.json`）

```json
{ "name": "ai-agent", "entry": "start.sh", "entry_windows": "start.bat",
  "connections": [ { "socket": { "port": 40005 } } ] }
```

`start.bat` 关键分支：
```bat
if defined MARSCODE_DEV_MODE (
    if defined MARSCODE_DEV_AI_AGENT_MANUAL ( :loop; timeout /t 99999 )  else ( cargo run )
) else (
    if "%TRAE_RESOLVE_TYPE%"=="remote"  set "AI_NATIVE_ENV=plugin_remote"
    else if "%TRAE_RESOLVE_TYPE%"=="ssh" set "AI_NATIVE_ENV=desktop_ssh"
    else if not defined AI_NATIVE_ENV    set "AI_NATIVE_ENV=desktop"
    set "DB_PATH=%ICUBE_MODULAR_DATA_DIR%\ai-agent\database.db"
    ai-agent.exe
)
```

**注意 `meta.json` 声明了 `port: 40005`，但实测 sidecar 进程不监听该端口。**
这条声明可能是给"模块管理框架"用的约定，实际未启用（与 3.4.4 观察一致）。

## 6. 实测探针结果（用我们自己的凭证）

已重建凭证（`tests/rebuild_creds.py` + `tests/add_device_key.py`，
从 Trae 的 `storage.json` 解出 cloudide token + ECDSA 设备密钥），
JWT 刷新链路恢复正常（`get_jwt()` 成功，payload 含 `source: refresh_token`）。

| 端点 | 结果 | 判断 |
|---|---|---|
| `POST /api/ide/v1/model_list` | **400** `{"code":4001,...,"model_configs":[]}` | 端点存在，参数不对 |
| `POST /api/ide/v1/get_model_list` | **404** TLB | 这个不存在 |
| `POST /api/ide/v2/llm_raw_chat` | **200** SSE `event: error data:{"code":4001}` | **端点存在且认证通过**，参数不对 |
| `POST /api/ide/v1/llm_raw_chat` | 同上 | 同上 |
| `POST /api/v1/commercial/get_session_usage` | **200** 完整 usage 结构 | **可用** |

`get_session_usage` 的返回结构（证明计费是按 session 归属的）：
```json
{"user_usage_group_by_session": {
  "amount_float": 0,
  "extra_info": {"cache_read_token":0,"cache_write_token":0,
                 "input_token":0,"output_token":0},
  "mode": "", "model_name": "", "product_type_list": [], "session_id": "",
  "usage_group_details": [], "usage_time": 0, "use_max_mode": false,
  "user_input_preview": ""}}
```

### 6.1 已排除的猜测

试过都不改变 4001：
- Content-Type：`application/json` / `protobuf` / `grpc` —— 都一样
- 空 body / `{}` / 裸 protobuf 帧 —— 都一样
- `model_list` 的 7 种 body 变体（空 / 只 user_info / 只 common_params /
  service=model / data-only / full / full+data）—— 全是 4001
- `llm_raw_chat` 的 5 种 body 变体（no data / data minimal /
  +message_content / +model_name / +agent_type+scene_location+agent）—— 全是 4001

**结论**：字段名全都在 DLL 里存在（`user_input`×98、`model_name`×55、
`custom_model`×207、`agent_type`×135、`chat_session_id`×59、`channel_id`×35 …），
所以不是字段名猜错，而是**这层端点不是给外部直连的**——
它期望的请求很可能带 sidecar 内部才有的东西（`channel_id`、`request` 信封嵌套、
或者根本就是 sidecar 内部 RPC 转 HTTP 的实现，不是公网 API）。

### 6.2 试过但失败的抓包手段

- `netsh trace start` → **需要管理员权限**，未提升
- sidecar 日志 `.alaudalog`（`AalG` 魔数）→ **加密/压缩，无法解**
  （`tests/decode_alaudalog.py`，zlib 全变体失败，无明文）
- 读 log 尾部（Trae 运行时）→ 能读到 47KB 新增字节，但内容是 AALG 密文

## 7. 仍待确认 / 下一步

| 问题 | 现状 | 下一步 |
|---|---|---|
| `api/ide/v2/llm_raw_chat` 的正确请求体 | 4001，所有猜测无效 | **抓真实请求**（见下） |
| 合法 `model_name` | 仍不知 | 同上 |
| sidecar 是否仍走 mojo pipe | 是（`--mojo-platform-channel-handle`） | — |
| 计费归属 | `get_session_usage` 存在且可用 | 若打 V2，需带 `chat_session_id` |

### 7.1 抓真实请求的办法（需要管理员）

`netsh trace` 需要提权。**如果愿意用管理员身份跑一次 PowerShell**：
```powershell
netsh trace start capture=yes tracefile=D:\trae347.etl maxsize=512
# 然后在 Trae 里发一句话
netsh trace stop
# 转成可读格式
pktmon etl2txt D:\trae347.etl        # 或 etl2pcapng + Wireshark
```
抓到后过滤 `trae-api-cn.mchost.guru` 的 POST，看 `llm_raw_chat` 的真实 body。
这是目前唯一能确定正确参数的手段。

### 7.2 另一个思路：让 sidecar 自己发，我们从进程内存读

sidecar 是本地进程，`llm_raw_chat` 的请求体在它的堆里。
用 `procdump -ma <pid>` 抓内存，然后搜 `llm_raw_chat` 附近的 JSON 明文
（Rust serde 序列化时明文会在内存里短暂存在）。不需要管理员权限（同用户即可）。

## 8. 对 trae2api 的直接意义

**重大修正**：3.4.7 确实暴露了 V2 端点和计费接口，且**我们的凭证能通过认证**，
但 `llm_raw_chat` 的请求体还没拼对。这说明"复刻真链路"从"必须复刻 mojo pipe"
降级为"**只需拼对一个 HTTP 请求体**"—— 成本大幅下降，但还差最后一步。

**当前 trae2api 仍走 `/api/ide/v1/chat`，功能正常**（工具循环、builder 模式、
cwd 都在工作），只是模型不可控、不计费、思考浅。这三个问题要等请求体拼对才能解。

**注意**：凭证文件 `trae2api/trae2api.json` 之前丢失（gitignore），
现已从 Trae storage.json 重建。若以后再丢，跑：
```bash
python tests/rebuild_creds.py && python tests/add_device_key.py
```
