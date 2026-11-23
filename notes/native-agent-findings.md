# Trae CN native AI-agent runtime — protocol & endpoints (reverse-engineering notes)

Target: `d:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app\modules\ai-agent\`
( ai_agent.dll 278,400,912 B · harness.dll 216,250,256 B · sscronet.dll 9,081,232 B · toolhost.dll 89,535,376 B · bin\agent-tool-host.exe 90,919,824 B · bin\ctx-cli.exe 3,166,608 B )
Trae CN app version 3.4.4, buildVersion 2.3.93438, branch `release_desktop_yoma_win32_cn`.

## TL;DR

- **Local IPC = custom framed RPC over a Windows named pipe**, NOT HTTP/WS on port 40005 for the JS↔agent link. Workbench ↔ `ai_agent.dll` (loaded by the Electron main process as the "ai_agent" module, per main.js process naming) talk over Electron "aha IPC": server name `"ai-agent"` (`Yse="ai-agent"` in main.js), and JSON-RPC-style packets `{packet_type:"request", channel_id, session_id, params:{service,method,data,client_info,...}}` sent via channel methods `"request"` / `"request_stream"`.
- Port **40005** appears only in `meta.json` as a declared socket connection (`meta.json` verbatim below); no `40005` string exists in either JS bundle, so it is consumed by native/embedder code (the Chromium embedder log shows `[Basil][AIAgent] call init, set callback to lib.` — a C++ embedder `ai_agent.cc` initializes the lib). We did not observe the workbench JS dialing 127.0.0.1:40005.
- **Chat flow: JS → local native agent → cloud.** The renderer builds `{service:"chat", method:"chat", data:{...}, client_info:{...}}` and sends it through `TransportManager.executeStreamRequest` → `AhaRpcClient` → local agent. The native side holds the cloud auth/hosts (TTNet/cronet, `x-tt-*` headers, `harness_cloud_url=https://copilot-cn.bytedance.net`, `wss://aipa-ws-online.bytedance.net`, …).

---

## 1. Module manifests & start scripts (verbatim)

`meta.json`:
```json
{
  "name": "ai-agent",
  "version": "1.0.0-alpha.0",
  "entry": "start.sh",
  "entry_windows": "start.bat",
  "args": [],
  "activationEvents": ["*"],
  "contributes": {},
  "connections": [
    {
      "socket": {
        "port": 40005
      }
    }
  ]
}
```

`start.sh` (production branch):
```bash
if [ "$TRAE_RESOLVE_TYPE" = "remote" ]; then
    export AI_NATIVE_ENV=plugin_remote
elif [ "$TRAE_RESOLVE_TYPE" = "ssh" ]; then
    export AI_NATIVE_ENV=desktop_ssh
else
    export AI_NATIVE_ENV=${AI_NATIVE_ENV:-desktop}
fi
export DB_PATH=$ICUBE_MODULAR_DATA_DIR/ai-agent/database.db
export FILE_BASE_DIR=$ICUBE_MODULAR_DATA_DIR/ai-agent/snapshot
if [ -n "$PLUGIN_IDE_TYPE" ]; then
    exec ./ai-agent --ideType=${PLUGIN_IDE_TYPE}
else
    exec ./ai-agent
fi
```
Dev branch additionally sets: `RUST_LOG=INFO`, `CLOUDIDE_TENANT_NAME=cn`, `ICUBE_MODULAR_DATA_DIR=$HOME/.icube`, `ICUBE_PRODUCT_PROVIDER=Spring`, `TTNET_LIB_DIR_PATH=.../deps/ttnet/...`, `RG_PATH=.../rg`, then `cargo run`.

`start.bat` mirrors this with `ai-agent.exe`.

`checkpoint.sh` is not a build artifact — it is a prompt-injection self-reminder for the agent runtime itself (garbled CJK):
> "自问自答：当前我的上下文里还有没有 RFC 全文（完整原版，而不是压缩摘要、截断等）？如果没有，请重新阅读原文 RFC。并且下次调用任意工具（如 Grep、LS、write 等）之前，都需要重新执行这个脚本 ./checkpoint.sh。"

## 2. Actual data dir (NOT `%USERPROFILE%\.icube`)

`%USERPROFILE%\.icube\ai-agent` does not exist on this machine. Production uses (from main.js):
```js
 Et=this.dynamicConfigService.getConfigDataByKey("iCubeApp.aiAgentDbStoragePath")?.enable??!1
   ?await this.resolveDbPath(Te):Wr.join(Te,"ai-agent","database.db")
```
i.e. `%APPDATA%\Trae CN\ModularData\ai-agent\`:
```
command-execution\  hooks_env\  sandbox\  snapshot\
agent-data-migration-state.json  (202 B, version 1, task project_domain_v2 completed)
database.db 4,210,688 B (+ -shm 32,768 B, -wal 4,964,632 B)   ← SQLite
```
`agent-data-migration-state.json` verbatim:
```json
{
  "version": 1,
  "tasks": {
    "project_domain_v2": {
      "status": "completed",
      "start_time": null,
      "end_time": "2026-10-24T09:17:01.291959500+00:00",
      "watermark": 0
    }
  }
}
```

## 3. How the JS side connects to the native agent (verbatim excerpts)

### 3.1 Process/module selection — main.js
```js
{ fileName:t==="win32"?"ai_agent.dll":t==="linux"?e?"ai-agent":"libai_agent.so":"libai_agent.dylib",
  implementation:"ai-agent", type:e?"executable":"lib" }
...
dll":t==="linux"?"libharness.so":"libharness.dylib", implementation:"harness", type:"lib"}
: e&&i ? {fileName:t==="win32"?"harness-server.exe":"harness-server", implementation:"harness", type:"executable"}
```
and process naming (`workbench`/main): `g.test(t)?"toolhost":y.test(t)?"harness":g.test(t)||t.includes("ai-agent")?"ai_agent"`.

### 3.2 The aha-IPC server name & channel constants — main.js
```js
Yse="ai-agent", Xse="cueServer",
function(t){ t.Connect="connect", t.Send="send", t.Disconnect="disconnect",
t.RemoveAllListeners="removeAllListeners", t.RestartAiAgent="restartAiAgent",
t.ResetDatabaseAndRestartAiAgent="resetDatabaseAndRestartAiAgent",
t.GetAiAgentProcessStartupError="getAiAgentProcessStartupError",
t.GetAiAgentProcessDisconnectReason="getAiAgentProcessDisconnectReason", ...
```
```js
// mainProcessManager.js
import {ahaProcess as Sxe, app as bxe, ahaIpc as Cxe, ahaReporter as Exe} from "electron";
...
this.ahaIpcServerName=this.createAhaIpcServerName(),
this.aiAgentRpcClient=new xM({serverName:this.ahaIpcServerName,
  connect:async a=>this.environmentOptions.ahaIpc.connect(a), logger:this.logService})
...
createAhaIpcServerName(){return Yse}   // "ai-agent"
```
`xM` = `AhaRpcClient` (out-build/vs/platform/aha/common/ahaRpcClient.js):
```js
const e=await this.connect(this._serverName);
this._logger?.info(`[AhaRpcClient] ahaIpc connect serverName: ${this._serverName}`,e)
...
this.rpcConnection=new Gse({send:n=>{this.ipcConnection?.send(n)},
  onData:n=>{...this.ipcConnection?.on("message",s)...}}, ...)
```
So the transport is whatever the Electron `ahaIpc.connect(serverName)` builtin returns (the embedder's named-pipe IPC; pipe name is not visible in JS). For remote SSH an alternate backend is used:
```js
const mr=e.userEnv?.HARNESS_TOOLHOST_ENDPOINT, Gr=e.userEnv?.TRAE_NET_ZMQ_ENDPOINT;
if(!mr) throw new Error("HARNESS_TOOLHOST_ENDPOINT is required for Remote SSH Harness");
...
qt.HARNESS_NETWORK_BACKEND="zmq", qt.HARNESS_TOOLHOST_ENDPOINT=mr, qt.TRAE_NET_ZMQ_ENDPOINT=Gr, qt.TOOLHOST_TRANSPORT="tcp"
```
(the string `TRAE_NET_INPROC_ENDPOINT` also exists in harness.dll env list, defaulting to inproc).

### 3.3 Spawn environment for the native agent — main.js (verbatim, trimmed)
```js
RUST_LOG:_, ICUBE_RUST_LOG_LEVEL:E, RUST_BACKTRACE:O?"1":"", RG_PATH:w, TOOLHOST_PATH_SUFFIX:g,
FFMPEG_DIR:m, ICUBE_PRODUCT_TYPE:"desktop", ICUBE_USER_DATA_DIR:..., ICUBE_APP_SETTINGS_HOME:...,
ICUBE_AI_AGENT_SHUTDOWN_TOKEN:this.shutdownToken, ICUBE_MODULE_LOG_TO_FILE:"true",
ICUBE_MODULE_PID_DIR:Ee, ICUBE_MAIN_PPID:Hy.toString(), ICUBE_FORCE_RANDOM_PORT:"true",
ICUBE_GRACE_PERIOD_SECONDS:ke?"999999999":"1", ICUBE_MODULAR_DATA_DIR:Te,
ICUBE_GLOBAL_STORAGE_DIR:ni.fsPath, ICUBE_PRODUCT_PROVIDER:this.productService.provider,
ICUBE_EVENT_VERIFY_ENABLED:I?"1":"0", ICUBE_EVENT_VERIFY_HOST:R,
AI_NATIVE_ENV:ji, CLOUDIDE_TENANT_NAME:"cn", DB_PATH:Et, FILE_BASE_DIR:se,
CKG_PORT:`${r}`, CKG_USE_AHA_IPC:..., ENABLE_IPC_SERVER:"true",
AHA_IPC_SERVICE_NAME:this.ahaIpcServerName, TRAE_RUNTIME:"local",
TRAE_STATIC_CLIENT_TYPE:ti(this.productService)?"solo-lite":"ide",
DISABLE_HYPERFETCH:..., TOOLHOST_TRANSPORT:"ipc", TOOLHOST_IPC_SERVICE_NAME:"toolhost",
WORK_VM_MODE:...||"AhaVm", TRAE_COMPUTER_USE_MTC_TARGET:..., ICUBE_APP_ROOT:o, ...
process.env.ICUBE_USE_IPV6=n.toString(), process.env.ICUBE_PROXY_HOST=n?$y:jy,
process.env.ICUBE_MACHINE_ID=..., ICUBE_BUILD_VERSION=..., ICUBE_QUALITY=..., ICUBE_APP_VERSION=...
```

### 3.4 The RPC packet — workbench.desktop.main.js (verbatim)
```js
createRequestPacket(e){
  return {packet_type:"request",
          channel_id:Ut(),                       // random uuid
          session_id:e.payload.client_info.connect_session_id,
          params:e.payload}}
```
```js
const l=await this._client.sendRequest("request",a);      // unary
await this._client.sendStreamRequest("request_stream",r,f,m,v);  // streaming
```
```js
// main.js process manager does the same for healthcheck etc.
const i=this.createRequestData("healthcheck","prepare_shutdown",{token:this.shutdownToken})
const s={packet_type:"request",session_id:i.client_info.connect_session_id,channel_id:n,params:i};
const o=await this.aiAgentRpcClient.sendRequest("request",s,r?.timeout);
```
`params` payload (from `convertReqToRustPayload`, verbatim excerpt):
```js
{service:e.service, method:e.method, data:e.data, user_info:t,
 common_params:{...}, streamlined_common_params:{...},
 client_info:{ppe_env_name:..., connect_session_id:u, project_id:..., chat_session_id:...,
   version_code:..., workspace_folder:m, icube_language:n, confirm_config:...,
   device_id:s, workspace_id:o?.id, terminal_info:..., is_solo_mode:...,
   client_type:..., window_type:..., git_repos:a, local_git_repos:l, git_metadata_dirs:c,
   local_svn_repos:..., security_rules:g, agent_task_service_strategy:...,
   enable_llm_utils_cloud:..., is_evaluation:..., is_worktree:...,
   workspace_folders:v, original_workspace_folder:..., runtime_environment...}}
```
Services/methods observed live in `%APPDATA%\Trae CN\logs\20261024T171939\window1\renderer.log`:
```
[TransportManager] executeRequest, chat get_lite_sessions, 63cdd600-..., cost: 0
[TransportManager] executeRequest, lite list_chat_sessions, f90be71e-..., cost: 0
[TransportManager] executeRequest, lite create_chat_session, a699cdf5-..., cost: 0
[TransportManager] executeRequest, plugin get_plugin_detail, 830e69eb-..., cost: 18
[TransportManager] executeRequest, agent get_agents, 97854d71-..., cost: 17
[TransportManager] executeRequest, model model_list_by_function, bbc4da65-..., cost: 1031
[TransportManager] executeRequest, lite project_change_event, 25ff1663-..., cost: 27
[API client][rust] invoke cost= 197ms lite.create_chat_session
[SoloLiteApiObservability] {"route":"chat.createSession","service":"chat","method":"createSession",
  "adapter":"local","target_service":"lite","target_method":"create_chat_session",...}
```
JS source also shows: `{service:"agent",method:"get_agents"}`, `{service:"agent",method:"create"|"delete"|"create_or_polish_agent_via_llm"}`, `{service:"configuration",method:"get_user_configuration"}`, `{service:"context_asset",method:"list"|"detail"}`, `{service:"git",method:"generate_commit_message"}`, `{service:"ide",method:"sync_builtin_skills"}`, readiness probe `{service:"lite",method:"agent_ready"}` (`Q6i="lite", Ybt="agent_ready"`), tool-host calls `J6i="tool_host"`.

## 4. Chat message flow: JS → local agent → cloud (proof)

1. Renderer branch inside the payload builder:
```js
e.service==="chat"&&e.method==="chat"){ const F=e.data||{}, V=e.context||{};
  let z=F?.model_name||V?.model_name||F?.custom_model?.config_name||"auto"; ...
```
2. `doRequestWithStream` → `waitForAgentReady` → `this._transportManager.executeStreamRequest(e,{request:t,userInfo:r,deviceId:n,payload:await this.convertReqToRustPayload(t,r,n),onSocketError:...})` → `AhaRpcClient.sendStreamRequest("request_stream", packet...)` → **local native agent** (same machine, aha-IPC pipe).
3. The native agent owns the cloud leg: it persists sessions in `database.db` (SQLite, WAL), and DLL strings show it does the model calls itself (OpenAI-compatible paths, Bedrock, etc.), with TTNet/cronet (`sscronet.dll`) as the HTTP stack and ByteDance headers.

Native chat/model strings (ai_agent.dll, ASCII, cleaned):
```
.../models/chat/completions  deepseek  /v1/models  /v1/messages  anthropic  openrouter  openai
/foundation-models/openai/v1/chat/completions  aws  xai
x-api-key  2023-06-01  anthropic-version  https://bedrock.?.amazonaws.com  Bearer ?
Authorization:
```
harness.dll adds:
```
/chat/completions deepseek anthropic openrouter gemini
/foundation-models/openai/v1/chat/completions aws xai
x-api-key 2023-06-01 anthropic-version
https://bedrock-runtime.?..amazonaws.com/model/?./invoke-with-response-stream
https://bedrock-runtime-fips. / https://bedrock-runtime.DualStack
```
→ direct-to-provider fallbacks exist inside harness.dll/ai_agent.dll (OpenAI-compatible `chat/completions`, Anthropic `/v1/messages`, AWS Bedrock invoke-with-response-stream).

## 5. Cloud endpoints found

### 5.1 Verbatim strings inside the native DLLs

| DLL | String (verbatim) | Meaning |
|---|---|---|
| toolhost.dll | `HARNESS_CLOUD_URLhttps://copilot-cn.bytedance.net` | harness cloud URL default (env `HARNESS_CLOUD_URL`) |
| toolhost.dll | `hostharness_cloud_url` / `hostgetresourceuploadurl` / `hostideactionidakmodel_namestatusauth_typeregionskbase_url` | env/struct names incl. `base_url`, `cloud_url` |
| ai_agent.dll | `var $j="wss://aipa-ws-online.bytedance.net"` (bundled JS: `APPLET_SOCKET_URL`) | applet/websocket cloud endpoint |
| ai_agent.dll | `WS="https://aipa.bytedance.net/api/file-upload"` | file upload |
| ai_agent.dll | `fetch("https://aipa-api.bytedance.net/api/get-dep-info")` | dependency info |
| ai_agent.dll | `aipa-pai-webview.gf.bytedance.net`, `aipa-ws-online.bytedance.net`, `bits.bytedance.net`, `cdn-tos-cn.bytedance.net`, `cloud.bytedance.net`, `cloud-boe.bytedance.net`, `cloud-boei18n.bytedance.net`, `cloud.byteintl.net`, `maliva-mcs.byteoversea.com`, `sgali-mcs.byteoversea.com`, `mcs.zijieapi.com` | internal/BOE/oversea variants + metrics (`mcs` = applog) |
| ai_agent.dll, harness.dll | `https://p11-market.byteimg.com/tos-cn-i-17oceyzymr/skills/...trae_agent::solo_work::...::package.z...` | builtin skills/packages CDN |
| harness.dll | `http://trae-sandbox-manager.manager.svc.cluster.localevent` | k8s sandbox-manager (cloud sandbox) |
| harness.dll | `https://remote-api.invalid//api/remote/v1/Remote` | remote API placeholder |
| toolhost.dll | `.../login/signin/auth/sso login.signin.auth.sso` | SSO flow in crawler service |
| all | `https://docs.trae.cn`, `https://www.trae.cn`, `https://www.trae.ai`, `https://promptpilot.volcengine.com`, `https://trae.mobile.volcapp.com`, `https://pai.mobile.volcapp.com` | docs/marketing/PPE |
| ai_agent.dll, harness.dll | bytegate config blob: `struct BootUserAccount ... copilot apiHost ideCn ideUs bytegate iac saasBootConfig scope tenantId`, `struct TeaConfig struct TTNetConfig ide_cn ide_us bytegate iac appId httpDNS netLog tncHost bytegateiac appKey channelDomain libraDomain` | per-region API host config: **ide_cn / ide_us / bytegate / iac** (hosts injected at runtime via dynamic config, not hardcoded) |
| ai_agent.dll | `/api/v3/trae/GetThirdPartyToken`, `/api/v1/commercial/check_estimated_balance` (path fragments) | token & quota endpoints |
| harness.dll | env keys (run concatenation, deduped): `harness_cloud_url harness_copilot_app_id harness_explorer_url harness_manager_url harness_schedule_api_server harness_text_to_image_url harness_listen_addr harness_metrics_addr harness_network_backend harness_sse_* harness_http_* trae_agent_icube_package_type trae_agent_icube_ppe_use_header trae_agent_icube_product_code trae_agent_icube_request_timeout trae_agent_icube_tenant trae_agent_icube_uid trae_agent_icube_user_region trae_agent_icube_x_tt_env trae_net_inproc_endpoint trae_net_zmq_endpoint trae_remote_api_server trae_remote_auth_prefix trae_remote_extra_headers trae_remote_server trae_remote_token ...` | full harness config surface |
| all | header-name blobs: `x-tt-env x-use-ppe x-env-lane x-trae-authorized-services x-custom-trace-id x-tt-logid x-tt-trace-id x-request-id x-traffic-type x-product-name x-app-id x-device-id x-device user-agent x-net-sdk-domain-dispatch-info`, keywords `lantern ttnet aigw-?(no literal) frontier- normal-use(no literal)` | ByteDance gateway headers; **no literal `aigw` host found** in any of the 3 DLLs |

Also embedded but incidental: `http://127.0.0.1:7777/event`, `http://127.0.0.1:7778/event` (agent↔host event/log servers inside ai_agent.dll), `http://localhost:4317` (OTLP), `http://169.254.169.254` (AWS IMDS, via aws-sdk), Digicert/OCSP/CRL (cert), hundreds of template/doc URLs inside embedded previewer scaffolds (react/vue/nuxt docs, fonts.google.com, etc. — not Trae endpoints).

### 5.2 Endpoints actually hit at runtime (from live logs, `%APPDATA%\Trae CN\logs\20261024T171939\`, counted)

```
96  api.trae.cn/trae/api/v2/ug/checkin_credits/status
82  api.trae.cn/trae/api/v2/ug/activity/info
78  api.trae.cn/trae/api/v2/pay/ide_user_ent_usage
73  api.trae.com.cn/extensions/vscode/asset/
68  trae-api-cn.mchost.guru/api/ide/v1/get_detail_param
45  api.trae.com.cn/icube/api/v1/control-url/latest
37  api.trae.com.cn/icube/api/v1/native/config/query?mid=...&did=...&uid=...&userRegion=CN&packageType=stable_cn&productCode=TRAE&platform=Win&branch=release_desktop_yoma_win32_cn&arch=x64&tenant=marscode&appVersion=3.4.4&buildVersion=2.3.93438&traeVersionCode=20250325
35  trae-api-cn.mchost.guru/api/remote/v1/skills?page_size=100&sort_by=updated_at&sort_order=desc
34  trae-api-cn.mchost.guru/api/ide/v1/code_completion/model_configs
32  api.trae.com.cn/icube/api/v1/native/config/query
30  trae-api-cn.mchost.guru/api/ide/v1/get_client_config
22  api.trae.cn/trae/api/v2/pay/ide_user_pay_status
20  api.trae.com.cn/icube/api/v1/notifications/count
15  api.trae.cn/trae/api/v3/GetThirdPartyToken
14  api.trae.com.cn/extensions/api/-/skill/list-v3
10  trae-api-cn.mchost.guru/api/remote/v1/plugins
 8  agent-sandbox-bj-c1-gw.trae.cn/explorer/direct/slash/list
 7  trae-api-cn.mchost.guru/api/remote/v1/git/repositories
 4  api.trae.com.cn/icube/api/v1/user
 3  api.trae.cn/cloudide/api/v3/trae/GetUserInfo
 1  mcs.zijieapi.com  (metrics/applog)
 2  lf-cdn.marscode.cn
```
Dynamic-domain boot (cue-server stdout log, verbatim):
```
2026-10-24 17:20:04.691 [DynamicDomain] applyBootConfig: cue={"domain":"https://trae-api-cn.mchost.guru","appId":"6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"}
2026-10-24 17:20:04.691 [DynamicDomain] updated domain to: https://trae-api-cn.mchost.guru
```
`trae-api-cn.mchost.guru` is the **primary native-agent API gateway for CN** (note: odd non-ByteDance TLD `.guru`, resolved via the dynamic config/bytegate `ide_cn` slot); `api.trae.cn` / `api.trae.com.cn` carry store/pay/config/extension-gallery traffic.

### 5.3 Hostnames from static DLL scan (deduped, filtered of certs/docs)

- ai_agent.dll: `aipa.bytedance.net, aipa-api.bytedance.net, aipa-pai-webview.gf.bytedance.net, aipa-ws-online.bytedance.net, bits.bytedance.net, cdn-tos-cn.bytedance.net, cloud.bytedance.net, cloud.byteintl.net, cloud-boe.bytedance.net, cloud-boei18n.bytedance.net, docs.trae.cn, mail.trae.ai, maliva-mcs.byteoversea.com, mcs.zijieapi.com, promptpilot.volcengine.com, www.trae.ai, www.trae.cn`
- harness.dll: (no direct API host hardcoded; AWS SSO/Bedrock templates + `p11-market.byteimg.com` skills CDN + `trae-sandbox-manager.manager.svc.cluster.local`)
- toolhost.dll: `copilot-cn.bytedance.net` (= `HARNESS_CLOUD_URL` default), docs/www, `mcs.zijieapi.com`
- sscronet.dll: none (network stack only; cronet)

## 6. Config & data locations

- `%APPDATA%\Trae CN\ModularData\ai-agent\` — database.db (+wal/shm), snapshot\, sandbox\, command-execution\, hooks_env\, agent-data-migration-state.json (contents above). DB is SQLite (header standard); 4.2 MB.
- Dynamic config: `https://api.trae.com.cn/icube/api/v1/native/config/query?...` polled every 5 min (`DynamicConfigClient`), drives `iCubeApp.*` flags incl. `iCubeApp.aiChat.enableHarness`, `iCubeApp.aiAgentDbStoragePath`, domains, model configs.
- Logs: `%APPDATA%\Trae CN\logs\<session>\Modular\ai_agent-0-*.alaudalog` (binary AAL format: `AALG ... fields message "TBP_Initialize called" ... 3.4.4`), renderer.log for RPC traces, aha_log\aha_electron_*.log for the embedder.
- Embedder: `[aha\components\basil\embedder\trae\ai_agent.cc:63] [Basil][AIAgent] call init, set callback to lib.` — the C++ "Basil" embedder inside Electron initializes ai_agent.dll; port 40005 in meta.json is declared for this socket connection (native side), while JS uses the aha named-pipe RPC.

## 7. Confidence & Gaps

**High confidence (verbatim code/log evidence):**
- JS→agent transport is the aha named-pipe RPC with `{packet_type,channel_id,session_id,params:{service,method,data,client_info}}` and channels `"request"`/`"request_stream"`.
- Chat (`service:"chat",method:"chat"` and `lite.create_chat_session` etc.) goes through `TransportManager` → `AhaRpcClient` → **local native agent**, which persists to SQLite and performs the cloud calls (model providers, aipa hosts, skills CDN). No JS-side direct cloud chat call was found; the JS `requestService` HTTPS calls visible in logs are for store/config/gallery, not chat.
- `harness_cloud_url` default = `https://copilot-cn.bytedance.net` (toolhost.dll literal); applet WS `wss://aipa-ws-online.bytedance.net`; upload `https://aipa.bytedance.net/api/file-upload`; skills CDN `https://p11-market.byteimg.com/...`.
- Runtime gateway for agent API in CN = `https://trae-api-cn.mchost.guru` (dynamic-domain boot + many API paths in logs).

**Medium confidence:**
- Port 40005 is used by the native/embedder side (meta.json `connections.socket.port`); the JS bundles never reference it. Likely the Basil embedder exposes/talks on this TCP port for some auxiliary service (possibly the `http://127.0.0.1:7777/event`-style event servers pattern), or it is legacy metadata. Nothing in JS dials it.

**Gaps / not resolved:**
- Exact wire framing of the aha-IPC pipe (header magic/length prefix) is inside Electron's `ahaIpc` builtin (C++), not in JS; would need dynamic capture (e.g., Wireshark on loopback won't show pipes — needs ETW/procmon or pipe interception).
- The exact chat-request cloud URL the native agent hits (`/api/.../chat` on trae-api-cn.mchost.guru vs aigw) is not in plaintext strings; host slots (`ide_cn`/`bytegate`) are filled from dynamic config. Suggest capturing with mitm on TTNet (cert pinning via cronet likely) or reading the decrypted DB/config cache.
- ai_agent.dll is 278 MB and packed with embedded JS bundles (webpack `__esModule` blobs) — a fuller JS-level extraction of the native agent's own HTTP client (endpoints list) is possible by carving those bundles, not done here.
- `normal-use` / `aigw` literal strings: absent from the three DLLs scanned; if present they'd be in the dynamic-config payload or an embedded encrypted blob.
