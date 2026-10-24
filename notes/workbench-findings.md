# Trae CN (Windows) — Workbench ⇄ AI Backend: Reverse-Engineering Findings

**Target:** `d:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app\out\vs\workbench\workbench.desktop.main.js` (18,884,180 bytes)
**Companion sources (read-only, same install):**
- `resources\app\out\vs\workbench\workbench.desktop.main.solo-lite.js` (18,544,644 B) — same structure, same counts for all checked markers
- `resources\app\node_modules\@byted-icube\ai-modules-chat\dist\index.mjs` (14.4 MB) — **the chat client bundle** (where the HTTP AI API actually lives)
- `resources\app\out\main.js` (3.2 MB) — Electron main
- `resources\app\product.json` — **contains the default boot-config host map**
- `resources\app\node_modules\@byted-icube\trae-network-client-win32-x64-msvc\trae-network-node.win32-x64-msvc.node` (1.6 MB, napi-rs)

All excerpts below are verbatim (minified) unless noted. Offsets are byte offsets via `[System.IO.File]::ReadAllText` + `IndexOf`/`Regex`.

---

## 0. Architecture summary (how the pieces fit)

Trae CN has **two AI stacks**, both reachable from the workbench:

1. **V1 "Copilot" HTTP stack** (`ai-modules-chat/dist/index.mjs`): plain HTTPS `POST {baseURL}/api/ide/v1/*` with header `Authorization: Cloud-IDE-JWT <jwt>`. Services: `Chat`, `ChatCompletion`, `CodeCompletion`, `CreateAgentRun`, `FastApply`, etc. The remote endpoint host is `endpoints.remoteService` = `bootConfig.remote.domain` (from product.json: `https://trae-api-cn.mchost.guru`).
2. **V2 "agent" stack** (workbench `Ite` client + native bridge): the workbench builds `{request:{service,method,data,context,timeout}, userInfo, deviceId, payload}` and hands it to `TransportManager vOe`, which calls `sendRequest("request", packet)` on an **RPC client** obtained from `modularManagerService.getAiAgentRpcClient()`. That RPC client is backed by the native ZeroMQ module (`trae-network-node.win32-x64-msvc.node`, described as *"ZeroMQ client for Trae Network Service - Node.js bindings"* with keywords `websocket, http, sse, rust`). The Rust "Trae Network Service" is what finally speaks HTTPS/SSE to the cloud. Auth is passed *inside the payload* as `userInfo.token` (the same Cloud-IDE JWT), not as an HTTP header from JS.

Env-var trail (main.js @505687, workbench @13375626):
```js
const r=[/^ELECTRON_.+$/,/^VSCODE_(?!(PORTABLE|SHELL_LOGIN|ENV_REPLACE|ENV_APPEND|ENV_PREPEND)).+$/,/^SNAP(|_.*)$/,/^ICUBE_.+$/,
  /^TRAE_NETWORK_SERVICE_CONFIG_PATH$/,/^TRAE_NET_ZMQ_ENDPOINT$/,/^TRAE_CONFIG_CHANNEL$/,/^TRAE_LOGIN_GUIDANCE_ENDPOINTS$/,/^TRAE_CDN_PREFIXES$/];
```
and (workbench @13376xxx, `Ggs`):
```js
i.TRAE_BRAND_NAME=e.nameShort ... const r=Xt?i.USERPROFILE:i.HOME;
i.TRAE_JWT_TOKEN_PATH=`${n}${r}${e.dataFolderName}${r}trae-jwt-token`
```
→ child/native processes get the JWT via a file `%USERPROFILE%\<dataFolderName>\trae-jwt-token` and the ZMQ endpoint via `TRAE_NET_ZMQ_ENDPOINT`.

---

## 1. Gateway / AI API host construction

### 1.1 Host map — `product.json` → `bootConfig` (verbatim)

```json
"bootConfig": {
    "feedbackMail": "feedback@mail.trae.cn",
    "defaultGitEmail": "git@mail.trae.cn",
    "condition": { "website": ["www.trae.cn","trae.cn"], "bytedanceLoginPage": ["sso.bytedance.com","accounts.feishu.cn"] },
    "iCube":        { "normal": "https://api.trae.com.cn" },
    "market":       { "trae": { "normal": "https://api.trae.com.cn" }, "bytedance": { "normal": "https://ide-market.bytedance.net" } },
    "iCubeAgent":   { "normal": "https://api.trae.com.cn" },
    "frontier":     { "normal": "wss://frontier.zijieapi.com/ws/v2", "boe": "wss://frontier-boe.bytedance.net/ws/v2" },
    "asr":          { "engine": "volcengine", "domain": { "normal": "https://api.trae.com.cn" }, "appId": "4089030846",
                      "bigmodelApiUrl": "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
                      "smallmodelApiUrl": "wss://openspeech.bytedance.com/api/v2/asr", ... },
    "account":      { "trae": { "normal": "https://api.trae.cn" }, "saas": { "boe": "https://enterprise.mcdemo.show", "prod": "https://console.enterprise.trae.cn" }, ... },
    "ug":           { "trae": { "normal": "https://api.trae.cn" }, "appId": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8", ... },
    "agent":        { "trae": { "normal": "https://trae-api-cn.mchost.guru" }, "appId": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
                      "bytedance": { "normal": "", "CN": "https://copilot-cn.bytedance.net", "SG": "https://copilot-sg-og.byteintl.net", "US": "https://copilot-og.byteintl.net" },
                      "bytedanceRemote": { "normal": "", "CN": "https://copilot-cn.bytedance.net", "SG": "https://copilot-sg.byteintl.net", "US": "https://copilot.byteintl.net" } },
    "remote":       { "trae": { "normal": "https://trae-api-cn.mchost.guru" }, "bytedance": { "normal": "", "CN": "https://copilot-cn.bytedance.net", "SG": "https://copilot-sg-og.byteintl.net", "US": "https://copilot-og.byteintl.net" }, ... },
    "ckg":          { "trae": { "normal": "https://trae-api-cn.mchost.guru" }, ... },
    "cue":          { "trae": { "normal": "https://trae-api-cn.mchost.guru" }, ... },
    "hub":          { "trae": { "normal": "https://trae-api-cn.mchost.guru" }, ... },
    "ws":           { "trae": { "normal": "wss://trae-ws-cn.mchost.guru/custom_model" }, "appId": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8", ... },
    "consoleHost": "https://www.trae.cn", "homeUrl": "https://www.trae.cn", "soloUrl": "https://work.trae.cn",
    ...
}
```

**Key hosts (CN consumer build, non-Bytedance account):**

| Key | URL | Used for |
|---|---|---|
| `agent.trae.normal` / `remote.trae.normal` / `ckg` / `cue` / `hub` | `https://trae-api-cn.mchost.guru` | **AI agent/chat gateway** (`bootConfig.agent.domain`, `endpoints.remoteService`) |
| `iCubeAgent` / `iCube` | `https://api.trae.com.cn` | `/api/ide/v1/*` agent-API calls, ASR token, material/report |
| `account` / `ug` | `https://api.trae.cn` | auth/UG endpoints (`/cloudide/api/v3/...`, `/trae/api/v1/pay/...`) |
| `ws.trae.normal` | `wss://trae-ws-cn.mchost.guru/custom_model` | custom-model websocket |
| `frontier` | `wss://frontier.zijieapi.com/ws/v2` | push channel |
| Bytedance-internal variants | `copilot-cn.bytedance.net`, `copilot-sg-og.byteintl.net`, `copilot-og.byteintl.net` | selected when `authService.isBytedanceUser()` |

`appId` for agent/ug/ckg/cue/hub: `6eefa01c-1036-4c7e-9ca5-d891f63bfcd8`.

### 1.2 BootService URL builder (workbench @5489698)

```js
async getApi(i,e){const t=await this.getBootConfig();
  return i===Yh.iCubeApi     ? this.outputUrl(`${t?.iCubeApi||""}${e}`)
       : i===Yh.ugApi        ? this.outputUrl(`${t?.ugApi||""}${e}`)
       : i===Yh.iCubeAgentApi? this.outputUrl(`${t?.iCubeAgentApi||""}${e}`) : ""}
async getAgentConfig(){return(await this.getBootConfig()).agent}
async getThreePgHost(i){return(await this.getBootConfig()).threePg[i]||""}
outputUrl(i){return i.indexOf("https://")>=0?i:new URL(i).toString()}
```
with `Yh={iCubeApi:"iCubeApi",ugApi:"ugApi",iCubeAgentApi:"iCubeAgentApi"}` (workbench @5377870).

### 1.3 Consumers of `bootConfig.agent.domain` (verbatim, workbench @15186319)

```js
this.authService.isBytedanceUser()
  ? n=`${(await this.bootService.getBootConfig()).agent.domain}/trae/api/v1/pay/ide_user_ent_usage`
  : n=await this.bootService.getApi(Yh.ugApi,"/trae/api/v1/pay/ide_user_ent_usage")
```
RTC voice (ai-modules-chat @7335572): `u=`${s}/api/stream/v1/startVoiceChat`` where `s=o?.agent?.domain`.
Lark docs (workbench @18390306): `` `${r}/api/remote/v1/doc_metadata/batch` `` where `r=(await this.bootService.getBootConfig()).remote.domain`.

### 1.4 Not found in any bundle
`aigw`, `getAIGateway`, `AIGateway`, `agentHost`, `hubHost`, `monoHost`, `API_HOST`, `traffic_id(s)`, `monoverse`, `mono.cea` — **0 occurrences** in workbench.desktop.main.js, solo-lite.js, and ai-modules-chat. (Those identifiers belong to other Trae builds/agent server code, not this CN workbench.)

---

## 2. Chat request payload construction

### 2.1 V1 `/api/ide/v1/chat` — full endpoint surface (ai-modules-chat @415306, class `CopilotService`)

```js
Chat(e,t){let r=this.genBaseURL("/api/ide/v1/chat"),
  n={user_input:e.user_input,intent_name:e.intent_name,variables:e.variables,chat_history:e.chat_history,
     context_resolvers:e.context_resolvers,session_id:e.session_id,generate_suggested_questions:e.generate_suggested_questions,
     conversation_id:e.conversation_id,current_turn:e.current_turn,valid_turns:e.valid_turns,model_name:e.model_name,
     multi_media:e.multi_media,Request:e.Request,last_llm_response_info:e.last_llm_response_info,is_preset:e.is_preset,provider:e.provider};
  return this.request({url:r,method:"POST",data:n},t)}
```

Other endpoints in the same class (all `POST` unless noted): `/api/ide/v1/ping` (GET), `/intent_detect`, `/context_select`, `/chat_completion`, `/code_completion`, `/code_completion_stream`, `/completion_multi_point`, `/super_completion`, `/super_completion_query`, `/fast_apply`, `/query_rewrite`, `/entity_detect`, `/entity_rerank`, `/web_search`, `/agents/runs`, `/agents/runs/${id}/tool_call_outputs`, `/knowledgebase/*`, `/get_resource_upload_url`, `/commit_resource_upload_result`, `/model_list`, `/providers`, `/get_detail_param`, `/report/clients`, `/feedback`, commercial `/api/v1/commercial/*`, `/trae/api/v1/subscribe`, `/trae/api/v1/pay/create_order`.

### 2.2 V1 `ChatCompletion` body (ai-modules-chat @420854)

```js
ChatCompletion(e,t){let r=this.genBaseURL("/api/ide/v1/chat_completion"),
  n={model:e.model,messages:e.messages,max_tokens:e.max_tokens,temperature:e.temperature,top_p:e.top_p,n:e.n,stream:e.stream,
     stop:e.stop,presence_penalty:e.presence_penalty,frequency_penalty:e.frequency_penalty,functions:e.functions,
     function_call:e.function_call,Request:e.Request,tools:e.tools,tool_choice:e.tool_choice,session_id:e.session_id,
     disable_antidirt:e.disable_antidirt};
  return this.request({url:r,method:"POST",data:n},t)}
```

### 2.3 V2 Chat body — new-style `Chat` data fields (ai-modules-chat @439507)

```js
...quest,encrypted_model_params:e.encrypted_model_params,user_input:e.user_input,request_type:e.request_type,
metadata:e.metadata,tools:e.tools,queue_id:e.queue_id,request_seq:e.request_seq,mode_type:e.mode_type,chat_mode:e.chat_mode,
config_source:e.config_source,access_type:e.access_type,image_config:e.image_config,estimate_prompt_tokens:e.estimate_prompt_tokens,
slash_command:e.slash_command,message_origin:e.message_origin,tool_choice:e.tool_choice,reasoning_effort:e.reasoning_effort,
stream:e.stream,retry_times:e.retry_times,queue_retry:e.queue_retry,video_config:e.video_config,
connect_check_param:e.connect_check_param,user_selected_model_name:e.user_selected_model_name,
reasoning_effort_level:e.reasoning_effort_level,estimated_token_usage:e.estimated_token_usage,
custom_model_uniq_id:e.custom_model_uniq_id,provider_context:e.provider_context,biz_context:e.biz_context,
extra_info:e.extra_info,use_fast_request:e.use_fast_request};
return this.request({url:r,method:"POST",data:n},t)   // url = /api/ide/v1/chat_prompt (see freq list)
```

### 2.4 V2 rust service methods (ai-modules-chat @6283380, class `e_`)

```js
class e_{static{this.SERVER_NAME="chat"}static{this.SERVER_NAME_APPLY="fast_apply"}
static{this.METHODS={Chat:"chat",ResumeChat:"resume_chat",AppendChat:"append_msg",StopChat:"stop_chat",FastApply:"fast_apply",
  GetSessions:"get_sessions",GlobalSearch:"global_search",GetChatSession:"get_chat_session",CountSessions:"count_sessions",
  CreateSession:"create_session",DeleteSession:"delete_session",PinSession:"pin_session",UnpinSession:"unpin_session",
  MarkSessionRead:"mark_session_read",CreateWorktree:"create_worktree",RemoveWorktree:"remove_worktree",
  BatchMarkWorktreesDeleted:"batch_mark_worktrees_deleted",UpdateWorktreeAfterMerge:"update_worktree_after_merge",
  RenameSession:"update_session_title",GenerateSessionTitle:"generate_session_title",DeleteMessage:"delete_message",
  RevertMessage:"revert_message",DislikeMessage:"dislike_message",GetMessages:"get_messages",
  GetMessagesByIds:"get_messages_by_message_ids",MigrateChatHistory:"chat_migrate",JumpQueueTask:"jump_queue_task",
  FixSearchReplaceBlocks:"fix_search_replace_blocks",GetSessionTokenUsage:"chat_turn_cost_detail",
  TeleportSession:"teleport_session",ExportPastChat:"export_past_chat",ForkSession:"fork_session"}}
async chat(e,t,r,n){...let i=this._sessionService.getContextVariables(e.session_id);
  e?.session_id&&(i.chat_session_id=e.session_id);
  r?.code===0&&r?.data&&(i.terminal_info=r?.data);
  i.runtime_environment_list=e.runtime_environment_list; n&&Object.assign(i,n);
  await t.requestForStream(this._aiClientManagerService.wrapRequestWithCredential(
    {service:e_.SERVER_NAME,method:e_.METHODS.Chat,data:e,context:i}))}
```

### 2.5 Workbench client `Ite` — request pipeline (workbench @5433488–5447227)

```js
async request(e){
  const[t,s]=await Promise.all([this.getDeviceId(),this.createUserInfo()]);
  await this.waitForAgentReady(e,s,t);
  const n=this._dynamicConfigService?.getConfigData?.();
  e.timeout=e.timeout??n?.iCubeApp?.aiRequestTimeout??cAn;              // cAn=60*1e3
  const r={request:e,userInfo:s,deviceId:t,payload:await this.convertReqToRustPayload(e,s,t),
           onSocketError:a=>this.onSocketError(a)},o=Date.now();
  try{const a=await this._transportManager.executeRequest(r); ... return a}catch(a){...}}
requestForStream(e){const t=new E1n; return this.doRequestWithStream(t,e).catch(s=>{t.getController().error(s)}),t}
async doRequestWithStream(e,t){
  const[n,r]=await Promise.all([this.getDeviceId(),this.createUserInfo()]);
  await this.waitForAgentReady(t,r,n);
  t.timeout=t.timeout??dAn;                                            // dAn=0
  const o={request:t,userInfo:r,deviceId:n,payload:await this.convertReqToRustPayload(t,r,n),
           onSocketError:a=>this.onSocketError(a)};
  await this._transportManager.executeStreamRequest(e,o)}
```
Readiness poll before chat: `{service:"lite", method:"agent_ready", data:{}, timeout:1e3}` (`Q6i="lite"`, `Ybt="agent_ready"`), retried with exponential backoff (1s→2s… capped 5 min) up to `agent_ready_timeout`.

`getDeviceId()`: `this._icubeDeviceRegisterService.deviceId||"0"`.

`createUserInfo()` → `iCubeChatCommonSession.getUserInfoWithToken()` (workbench @5386879):

```js
async getUserInfoWithToken(){
  const[e]=await Promise.all([this._iCubeAuthService.getUserInfoFresh(),this._entitlementService.getEntitlementInfo().catch(()=>{})]),
  t=this._entitlementService.getSaaSProductType(),s=t!==void 0?{product_type:t}:void 0;
  return{name:e?.account.username||"",token:e?.token||"",is_internal:e?.account.scope===pl.BYTEDANCE,
         user_id:e?.userId||"",scope:e?.account.scope||"",loginScope:e?.account.loginScope,
         tenant_id:e?.account.tenant_id,enterprise_info:s,email:e?.account.email}}
```
→ **the Cloud-IDE JWT travels as `userInfo.token` inside the rust payload** for the V2 stack.

`convertReqToRustPayload` (workbench @5439731) injects workspace/git/env context: `workspace_folders`, `git_repos`, security rules, `runtime_environment_list`, `user_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone`, `authorized_services`, `web_fetch_strategy`, `web_fetch_ppe_env`, `web_fetch_blocked_domains`, `permission_profile_id` (`"auto_approval"|"manual_approval"` or profile id), `ckg_indexing_enabled`, `agent_run_info`, plus special-casing for `lite.create_chat_session` (`local_project_id`, `parent_session_id`, `origin:"memory_settings"`).

### 2.6 TransportManager `vOe` → RPC packet (workbench @5426280)

```js
get vOe(){this._client=e??this.modularManagerService.getAiAgentRpcClient()}
async executeRequest(e){...
  const a=this.createRequestPacket(e);
  this.logService.info(`[TransportManager] executeRequest, ${e.request.service} ${e.request.method}, ${a.channel_id}, ...`);
  s.add(this._client.onDidDisconnect(...)); s.add(this._client.onDidRequestTimeout(...)); s.add(this._client.onDidError(...));
  const l=await this._client.sendRequest("request",a); ...}
```
Connection service (workbench @11419100):
```js
ke(hy,FVt,0);  // hy = "IICubeAiChatConnectionService"
async createClient(e){return this._instantiationService.createInstance(Ite,void 0,void 0)}
async getRemoteSshClient(e){...
  const n=this._modularManagerService.createRemoteAhaRpcClient(t),      // aha IPC channel
        a=await this._modularManagerService.registerAiAgentRpcClientExchange(n),
        l=this._instantiationService.createInstance(vOe,n),             // transport over that RPC
        c=this._instantiationService.createInstance(Ite,l,e); ...}
```
So: default (local) client uses `modularManagerService.getAiAgentRpcClient()`; Remote-SSH clients tunnel through `createRemoteAhaRpcClient(ahaIpcChannel)`.

### 2.7 Legacy "V2 protocol" names in workbench (UI-side only)

`ChatSendMessageRequest.method="chat/send_message"`, `chat/session_load_session_list`, `chat/session_retry_chat_by_user_message_id`, `chat/session_revert_chat_by_agent_message_id`, `chat/switch_chat_turn_revert_confirm_visible`, `chat/session_switch_session`, `chat/session_migrate_history` (workbench @27303, @26692) — these are internal VSCode protocol request names between UI and chat module, **not** HTTP endpoints.

### 2.8 Fast-apply body (ai-modules-chat @6369343)

```js
_={user_input:a,editing_plan:g,code_before:m?.trim(),language:c,file_path:r,editing_logic:l?.trim(),user_message_id:s},
   ...(_.custom_model={provider:y.provider||"",config_name:y.name,display_model_name:y.display_name,multimodal:!0===y.multimodal,
       ak:y.ak,use_remote_service:!y.client_connect,config_source:y.config_source,is_preset:y.config_source===C.Lf.Trae,
       base_url:y.base_url||"",custom_model_id:y.custom_model_id})
```

---

## 3. Header injection for AI/API requests

### 3.1 The universal env-routing header builder (appears ~12× across bundles)

workbench @18366387 / @6958573 (identical in ai-modules-chat @3881629, @8298366):
```js
get envHeader(){
  const e=this.configurationService.getValue("ai_assistant.request.env"),
        t=this.configurationService.getValue("ai_assistant.request.ppe");
  return e==="ppe"&&t?{"x-use-ppe":"1","x-tt-env":t}
       : e==="boe"&&t?{"x-use-boe":"1","x-tt-env":t}:{}}
```
Extended builder (workbench @6958573, verbatim; same in ai-modules-chat @3881629):
```js
d=this.configurationService.getValue("ai_assistant.request.env"),
u=this.configurationService.getValue("ai_assistant.request.ppe"),
g=this.configurationService.getValue("ai_assistant.request.envLane"),
p=this.configurationService.getValue("ai_assistant.request.agentEnv"),
f=this.configurationService.getValue("ai_assistant.request.forceSandboxType");
d==="ppe"&&u&&(c["x-tt-env"]=u,c["x-use-ppe"]="1"),
d==="boe"&&u&&(c["x-use-boe"]="1",c["x-tt-env"]=u),
g&&(c["x-env-lane"]=g),
p&&(c["x-trae-agent-env"]=p),
f&&(c["x-trae-force-sandbox-type"]=f);
```
**Headers:** `x-tt-env`, `x-use-ppe: 1`, `x-use-boe: 1`, `x-env-lane`, `x-trae-agent-env`, `x-trae-force-sandbox-type`. Settings keys: `ai_assistant.request.{env,ppe,envLane,agentEnv,forceSandboxType}`.

### 3.2 Full AI HTTP request headers (workbench @6958573, generic API caller)

```js
const c={"Content-Type":"application/json",Authorization:`Cloud-IDE-JWT ${s.token}`};
// ...env/ppe/lane/agent/sandbox headers appended as above...
const m=await this.requestService.request({type:e,url:l,headers:c},Fe.None);
if(m.res.statusCode&&(m.res.statusCode<200||m.res.statusCode>=300))
  throw new Error(`API ${e} ${t} failed with status ${m.res.statusCode}`);
```
(and `user_id` appended to URL query: `` r=`${t}${n}user_id=${s.userId}` ``.)

### 3.3 RTC voice header set (ai-modules-chat @7335572)

```js
function c(e,t,r,n){let l=i.mc.getInstance().resolve(o.k.IProductService);
  return{"Content-Type":"application/json","X-Scene-Id":r,"X-App-Id":n,"x-conversation-id":t,
         "X-IDE-Version-Code":"20260212",Authorization:`Cloud-IDE-JWT ${e}`,
         "X-Trae-Client-Type":(0,a.getProductCode)(l)===s.q6.SOLO_Lite?"lite":"ide",
         ...function(){...same x-tt-env/x-use-ppe/x-use-boe/x-env-lane/x-trae-agent-env/x-trae-force-sandbox-type builder...}()}}
```

### 3.4 ChatSuggest trace header (ai-modules-chat @11639347)

```js
l=this.options.getHeaders();
if(e.traceId){let t=Math.random().toString(16).slice(2,18).padEnd(16,"0");
  l["x-flow-traceparent"]=`04-${e.traceId}-${t}-01`}
let c=`${s.replace(/\/$/,"")}/api/ide/v1/super_completion_query`;
let d=await fetch(c,{method:"POST",headers:{...l,"Content-Type":"application/json",Accept:"text/event-stream"},body:JSON.stringify(a),signal:r.signal});
```

### 3.5 Other token headers seen in this install
- `X-Cloudide-Token: <token>` — supabase token fetch (`/cloudide/api/v3/trae/GetUserSupabaseToken`, workbench @18366387) and enterprise audit log.
- `x-icube-token: <token>` — `/icube/api/v1/material/getToken`, `/icube/api/v1/report/*`, ASR token (`/icube/api/v2/asr/get/a`).
- `x-preferenced-language` — ConversationTips catalog fetch (workbench ai-modules @3100451).
- JWT type enum (ai-modules-chat @144635): `CloudIDEJWT="Cloud-IDE-JWT", ByteCloudJWT="Byte-Cloud-JWT", GDPRJWT="GDPR-JWT"`.
- Non-AI (marketplace): `X-Client-Name`, `X-Client-Version`, `X-Client-Commit`, `X-Machine-Id` (workbench @3788130).
- `traceparent` occurrences in the workbench are Sentry/RUM instrumentation (`"03-"+id+"-"+id.substring(16)+"-01"`), **not** AI headers.
- `x-ide-`, `apps-`, `traffic-id`, `x-request-id` — **not found** as AI-request headers in this build. (`X-Jwt-Token`, `X-Cloudide-Clientip`, `X-Cloudide-Locale`, `X-Forwarded-Host` appear in ai-modules-chat only inside the remote-sandbox/MCP proxy code, i.e., headers the *sandbox side* sets.)

---

## 4. JWT attachment & refresh/retry

### 4.1 Attachment pattern (everywhere)

```js
Authorization:`Cloud-IDE-JWT ${token}`    // token = authService.userInfo.token (iCube auth)
```
Examples: workbench @6958573 (generic API), @15186607/@15190840 (usage service via `ttNetService.fetchJSON`), ai-modules-chat @553814 (fetch wrapper), @3100451 (ConversationTips).

### 4.2 Client-side wrapper for V2 (ai-modules-chat @6267320 and workbench twin)

```js
wrapRequestWithCredential(e){
  if(!this._credentialStore.getState().loggedIn)throw Error("Please login first");
  return{...e}}   // token itself is injected later into the rust payload (userInfo.token)
```

### 4.3 Refresh / 401 retry logic that IS in the JS

- Supabase 401-retry (workbench @18370507):
```js
return c.code===I3.Unauthorized&&!t?(await this.fetchAccessToken(),this.request(e,!0)):c
```
  with `fetchAccessToken(e=2)` → `POST {ugApi}/cloudide/api/v3/trae/GetUserSupabaseToken`, header `X-Cloudide-Token`, retry depth 2.
- Auth-failure error names (workbench @5378598):
```js
A6i={RefreshTokenInvalid:"RefreshTokenInvalid",TokenInvalid:"TokenInvalid",
     StoreCountryInvalid:"StoreCountryInvalid",StoreTncUpdateFailed:"StoreTncUpdateFailed"}
T6i={Success:0,NO_UserInfo:1,Handle_Login_Error:2,No_RefreshToken_Or_LoginHost:3,NO_isRedirect:4,
     Handle_Login_NetworkError:10002,Handle_Login_TimeoutError:10001,Handle_Login_DeviceLimitError:20401}
```
- Business code `CLIENT_UNAUTHORIZED_ERROR=1010002` (ai-modules-chat @53524; workbench teleport command maps it to a localized message).
- Token lifecycle: `userInfo.token` obtained by auth service (SSO). For native/V2, token file `TRAE_JWT_TOKEN_PATH` and `userInfo.token` in payload; **no JS-level 401 interceptor for the rust path** — re-auth happens via `onUserLogin`/`authService.onDidChangeUserInfo` listeners and the main-process (`SANDBOX_TO_MAIN_*` channel) login flow.
- `token_expired`, `RefreshTokenInvalid` handling code (i.e., an actual refresh HTTP call for the Cloud-IDE JWT itself) is **not present in the JS bundles** — it lives in main process/native side.

---

## 5. Response / stream parsing

### 5.1 V1 SSE — `ChatSuggestService.parseSSEStream` (ai-modules-chat @11640071)

```js
async parseSSEStream(e){let t="",r="",i=e.body?.getReader();if(!i)return{logId:t,completionText:r};
let o=new TextDecoder,a="",s="",l="";
for(;;){let{done:e,value:c}=await i.read();if(e)break;
  let d=(a+=o.decode(c,{stream:!0})).split("\n");
  for(let e of(a=d.pop()||"",d)){let i=e.replace(/\r$/,"");
    if(i.startsWith("event:"))s=i.slice(6).trim();
    else if(i.startsWith("data:"))l=i.slice(5).trim();
    else if(""===i&&s&&l){
      if(s===n.R_.Meta)      {try{let e=JSON.parse(l);t=e.id||e.log_id||""}catch{}}
      else if(s===n.R_.Output){try{let e=JSON.parse(l),t=e.choices?.[0];r+=t?.text||""}catch{}}
      else if(s===n.R_.Done)  return{logId:t,completionText:r};
      else if(s===n.R_.Error) {try{let e=JSON.parse(l);throw Error(e.error||e.message||"Unknown request error")}catch(e){throw e}}
      s="",l=""}}}
```
Request side used `Accept:"text/event-stream"` and POST to `/api/ide/v1/super_completion_query`. Event names via enum `R_` = {Meta, Output, Done, Error}. **No `[DONE]` sentinel** (the single case-insensitive `\[DONE\]` hit was `[stream-diagnostics][done]`, a log tag). `EventSource` appears only in Sentry-style instrumentation.

### 5.2 V2 stream — rust bridge subscribe (ai-modules-chat @7362069)

```js
async subscribe(t){...let l=e.buildRequest(t),c=await s.requestForStream(l),d=[],u=!1,p=!1,
  m="chat"===t.service&&"subscribe"===t.method,
  h=()=>{...};                                             // reset buffers, p=!0 (done)
  return c.subscribe({
    onMessage(n){
      if(p)return;
      let i=n?.code===o.av.Success&&null==n.data;
      if(m&&i){...skip empty success acknowledgement...; return}
      j(n?.data?.payload);                                  // redact <captured_window_context>
      let a={event:n.data.event,data:n.data.payload};
      r?r(a):d.push(a)},                                    // buffer until consumer attaches
    onError(e){p||(i?(i(e),h()):a=e)},
    onComplete(){p||(n?(n(),h()):u=!0)}}), ...}
```
Wire frames: `{code, data:{event, payload}}`; the app-level callback sees `{event, data}`. Empty-stream guard (ai-modules-chat @11437483): if no non-ignorable event arrived, error `PROTOCOL_SSE_EMPTY_BODY` is raised.

### 5.3 V2 SSE event names (ai-modules-chat @11597852)

```js
{n={}.Metadata="metadata",n.TextMessage="text_message",n.PlanItem="plan_item",n.Queuing="queuing",
 n.FeeUsage="fee_usage",n.TokenUsage="token_usage",n.ContextUsage="context_usage",n.TimingEvents="timing_events",
 n.UserMessage="user_message",n.AppendInput="append_input",n.SessionTitle="session_title_message",
 n.ProjectName="project_name_message",n.StatusChanged="status_changed",n.VMProgress="vm_init_progress",
 n.AgentCall="agent_call",n.Notification="notification",n.Heartbeat="heartbeat",n.Done="done",n.Error="error",
 n.WorktreeCheckRequired="worktree_check_required",n.WorktreeCreated="worktree_created",
 n.BrowserMcpRequest="browser_mcp_request",n.FastRequestSavings="fast_request_savings",
 n.PlanItemRevoke="plan_item_revoke",n.ContextTokenUsage="context_token_usage",n.ModelConfig="model_config",
 n.ToolCallCancel="tool_call_cancel",n.TobQuotaAlert="tob_quota_alert",n.AgentWakeup="agent_wakeup",
 n.MessageContextUpdate="message_context_update"}
```
(older UI enum @39647: metadata, plan_item, queuing, fee_usage, timing_events, token_usage, done, text_message, user_message, error.)

`done` payload fields (ai-modules-chat @11990183): `status`, `reply_to_message_id`, `chat_start_time`, `chat_end_time`, `stop_info`, `user_message_context` (incl. `is_ralph_loop`, `ralph_loop_context`).

### 5.4 Transport error taxonomy (ai-modules-chat @11119668)

```js
n.SSE_CONNECTION_FAILED="P30001",n.SSE_STREAM_ERROR="P30002",n.SSE_PARSE_ERROR="P30003",n.SSE_EMPTY_BODY="P30004",
n.SSE_HEARTBEAT_TIMEOUT="P30005",n.SSE_RECONNECT_EXHAUSTED="P30006",n.SSE_UNEXPECTED_EOF="P30007",
n.SSE_TERMINATED_BY_SIGNAL="P30008",n.SSE_TOTAL_RECONNECT_EXHAUSTED="P30009",n.UNKNOWN_ROUTE="P90001",
n.TRANSPORT_NOT_CONFIGURED="P90002",n.INVALID_ROUTE="P90003"   // plus HTTP_TIMEOUT..HTTP_INTERCEPTED (P1000x), WS_* (P2000x)
```
Socket-layer error enum (workbench @5426280): `SOCKET_CLIENT_CLOSE=10, SOCKET_CLIENT_ERROR=11, SOCKET_ERROR=12, INVALID_MESSAGE=13, CONNECTION_TIMEOUT=14, BIG_MESSAGE_ERROR=1009, PASSWORD_CHANGED=1003, ABNORMAL_ACCOUNT_LIMIT=4011`.

### 5.5 Subscription API shape (ai-modules-chat @11123649)

```js
async subscribe(e,t,r){
  return Object.assign(await this.adapter.subscribe({service:"chat",method:"subscribe",
    params:{chat_session_id:e,...r},context:this.getContext(),lastEventId:t?.lastEventId}),{meta:{sessionId:e}})}
async resumeChat(e,t){...method:"resumeChat"...}
```
`subscribeStream` (workbench UI @11435998): cancels any active subscription, calls `chatApi.subscribe(sessionId, {}, replyToMessageId?{reply_to_message_id:t}:undefined)`, wires `onEvent → handlers.onMessage({event: e.event||"message", data: e.data})`.

---

## 6. Miscellaneous endpoints of interest (same install)

- ASR: `POST {asr.domain=https://api.trae.com.cn}/icube/api/v2/asr/get/a` → `{jwt_token, app_id}`; then Volcengine bigmodel WSS.
- Voice chat: `POST {agent.domain}/api/stream/v1/startVoiceChat` body `{scene_id, variables:{available_slash_commands, last_reply}}`.
- Usage: `POST {ugApi=https://api.trae.cn}/trae/api/v1/pay/ide_user_ent_usage` (and `/trae/api/v2/...`), body `{require_usage:!0, req_source: PKe.IDE|PKe.Lite}`.
- Supabase: `POST {ugApi}/cloudide/api/v3/trae/GetUserSupabaseToken`.
- Report: `POST {iCubeAgentApi=https://api.trae.com.cn}/api/ide/v1/report/pre_signed_url` body `{action_type, object_keys, expires:3600}`.
- Session usage tail: `POST ...` body `{session_id}` with `Authorization: Cloud-IDE-JWT` + env headers (ai-modules-chat @3881629), response parsed as `data.user_usage_group_by_session.credits_float`.
- LLM raw passthrough endpoints exist in ai-modules-chat: `/api/ide/v1/llm_raw_chat`, `/api/ide/v2/llm_raw_chat`, `/api/ide/inner/v2/llm_raw_chat` (BYD-internal only).
- Custom-model providers (settings UI): `Ac={[CUSTOM_OPENAI_COMPATIBLE]:"/chat/completions",[CUSTOM_ANTHROPIC_COMPATIBLE]:"/v1/messages",[CUSTOM_RESPONSE_COMPATIBLE]:"/responses"}` (ai-modules-chat @4780965) — user-supplied `baseUrl` + appended path, API key `ak` sent inside `custom_model` payload.

---

## 7. Confidence & Gaps

**High confidence (verbatim-extracted):**
- Host map from product.json (`trae-api-cn.mchost.guru` for agent/remote; `api.trae.com.cn` for iCube/iCubeAgent; `api.trae.cn` for ug/account) and the `getApi()`/`outputUrl()` builder.
- V1 HTTP surface `/api/ide/v1/*` with full request-body field lists (`Chat`, `ChatCompletion`, `CreateAgentRun`, fast-apply).
- Header builders (`x-tt-env`/`x-use-ppe`/`x-use-boe`/`x-env-lane`/`x-trae-agent-env`/`x-trae-force-sandbox-type`; `Authorization: Cloud-IDE-JWT`).
- V2 request pipeline (`Ite.request/requestForStream` → `convertReqToRustPayload` → `vOe.executeRequest` → `sendRequest("request", packet)`), `userInfo` payload shape, `deviceId`, agent-ready poll (`lite.agent_ready`), chat method enum (`chat`, `resume_chat`, `append_msg`, `stop_chat`, …).
- SSE event-name enum, done-payload fields, rust stream frame shape `{code, data:{event, payload}}`, SSE/WS/HTTP error-code taxonomy.
- Native bridge identity: `@byted-icube/trae-network-client` = ZeroMQ client for "Trae Network Service" (rust; websocket/http/sse), env vars `TRAE_NETWORK_SERVICE_CONFIG_PATH`, `TRAE_NET_ZMQ_ENDPOINT`, `TRAE_JWT_TOKEN_PATH`.

**Could NOT find / not recoverable from JS:**
1. **No `aigw`/`traffic_id`/`getAIGateway`/`agentHost`/`hubHost`/`monoHost`/`API_HOST` identifiers anywhere** in workbench.desktop.main.js, solo-lite.js, or ai-modules-chat (0 hits). The "AI gateway" concept from other Trae builds is not named here.
2. **The actual HTTP wire requests for V2 chat are made by the Rust Trae Network Service**, not JS. The JS only proves an RPC hop over ZeroMQ (`sendRequest("request", packet)` → native). Exact URL paths (e.g., whether the rust service calls `https://trae-api-cn.mchost.guru/.../chat` or some `/aigw/...` path), and any additional headers the rust client injects (device-id, tt-headers, traceparent...), are inside `trae-network-node.win32-x64-msvc.node` (1.6 MB napi binary) and the separate Trae Network Service binary/config (`TRAE_NETWORK_SERVICE_CONFIG_PATH`) — the service binary is not under `resources\app` and was not located in this pass.
3. **Cloud-IDE-JWT refresh call for the main token**: no JS code refreshes it; `RefreshTokenInvalid`/`TokenInvalid` are only error-name enums; re-auth flows through main-process login channels (`vscode:sandbox::...`). The V2 path has no JS 401 interceptor; the token is validated server-side via `userInfo.token` in the payload.
4. **No OpenAI-style `[DONE]` sentinel** and no `data: [DONE]` handling in this build; SSE `done` is a named event instead.
5. `message_list`, `streamChat`, `x-ide-*` (other than `X-IDE-Version-Code: 20260212` in voice), `traffic-id`, `x-request-id`, `apps-*`: 0 hits in AI-request contexts.
6. `workbench.desktop.main.solo-lite.js` was marker-scanned (identical counts for all patterns checked, e.g. ChatRequest=66, Cloud-IDE-JWT=7) but not window-extracted separately; findings from the main workbench apply to it.
7. The `channel_id`/packet-field layout of `createRequestPacket(e)` beyond `channel_id` (window cut off mid-object), and the full tail of `convertReqToRustPayload` beyond the sections quoted, are only partially captured.

**Raw extraction windows** (for re-inspection): `D:\workspace\trae2api\notes\_raw\*.txt` (`p1`–`p7`, `n1`–`n16`, `freq_*`), produced by `notes\_raw\search.ps1`, `offset.ps1`, `freq.ps1` (read-only on the target; all writes confined to `notes\`).
