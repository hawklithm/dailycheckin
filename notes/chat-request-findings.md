# Trae CN — `POST https://trae-api-cn.mchost.guru/api/ide/v1/chat` reverse engineering

Sources (all offsets are byte offsets found via `[System.IO.File]::ReadAllText`/`ReadAllBytes` + `IndexOf`):

- **A** = `D:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app\node_modules\@byted-icube\ai-modules-chat\dist\index.mjs` (14.4 MB)
- **B** = `d:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app\out\vs\workbench\workbench.desktop.main.js` (18 MB)
- **M** = `D:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app\out\main.js` (main process)
- **DLL** = `D:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app\modules\ai-agent\ai_agent.dll` (the local Rust "ai-agent" sidecar that actually performs the HTTP call)

## 1. Verbatim excerpts

### 1.1 CopilotService (module 92547, export `F2`), file A @414646 — legacy in-RPC-frontend service

```js
92547(e,t,r){r.d(t,{F2:()=>p,s9:()=>h,Be:()=>b,gJ:()=>m,Ze:()=>C,h1:()=>y});var n=r(80597),i=r(58444);class o{constructor(e){this.request=()=>{throw Error("CopilotService.request is undefined")},this.baseURL="",this.request=e?.request||this.request,this.baseURL=e?.baseURL||this.baseURL}genBaseURL(e){return"string"==typeof this.baseURL?this.baseURL+e:this.baseURL(e)}ContextSelect(e,t){let r=this.genBaseURL("/api/ide/v1/context_select"),n={user_input:e.user_input,variables:e.variables,chat_history:e.chat_history,session_id:e.session_id,Request:e.Request};return this.request({url:r,method:"POST",data:n},t)}Ping(e,t){let r=e||{},n=this.genBaseURL("/api/ide/v1/ping"),i={Request:r.Request},o={error:r.error,echo:r.echo};return this.request({url:n,method:"GET",data:i,params:o},t)}Chat(e,t){let r=this.genBaseURL("/api/ide/v1/chat"),n={user_input:e.user_input,intent_name:e.intent_name,variables:e.variables,chat_history:e.chat_history,context_resolvers:e.context_resolvers,session_id:e.session_id,generate_suggested_questions:e.generate_suggested_questions,conversation_id:e.conversation_id,current_turn:e.current_turn,valid_turns:e.valid_turns,model_name:e.model_name,multi_media:e.multi_media,Request:e.Request,last_llm_response_info:e.last_llm_response_info,is_preset:e.is_preset,provider:e.provider};return this.request({url:r,method:"POST",data:n},t)}IntentDetect(e,t){let r=this.genBaseURL("/api/ide/v1/intent_detect"),n={intent_name:e.intent_name,user_input:e.user_input,variables:e.variables,chat_history:e.chat_history,intents:e.intents,context_resolvers:e.context_resolvers,session_id:e.session_id,Request:e.Request};return this.request({url:r,method:"POST",data:n},t)}...
```

`LLMRawChat` in the same class (file A @431184):

```js
LLMRawChat(e,t){let r=this.genBaseURL("/api/ide/v1/llm_raw_chat"),n={model_name:e.model_name,messages:e.messages,session_id:e.session_id,message:e.message,conversation_id:e.conversation_id,is_preset:e.is_preset,provider:e.provider,user_input:e.user_input,metadata:e.metadata,Request:e.Request};return this.request({url:r,method:"POST",data:n},t)}
```

### 1.2 The `request` wrapper + CopilotService construction (module 55492-ish region), file A @552500–554940

```js
function g(e,t={},r){let n=function(e={}){let{baseURL:t="",headers:r={},timeout:n}=e;return async function(e,i){let o,{url:a,method:s,data:l,params:c,headers:d={}}=e,{timeout:u=n,signal:p}=i||{},m=!a.startsWith("http")&&t?`${t}${a}`:a;if(c){let e,t=(e=new URLSearchParams,Object.entries(c).forEach(([t,r])=>{null!=r&&(Array.isArray(r)?r.forEach(r=>e.append(t,String(r))):e.append(t,String(r)))}),e.toString());t&&(m+=(m.includes("?")?"&":"?")+t)}let h=new AbortController,f=p||h.signal;u&&(o=setTimeout(()=>h.abort(),u));try{let e=await fetch(m,{method:s,headers:{"Content-Type":"application/json",...r,...d},body:l?JSON.stringify(l):void 0,signal:f});if(!e.ok){let t=await e.json().catch(()=>({})),r=Error(t.message||`HTTP ${e.status}`);throw Object.assign(r,{status:e.status,statusText:e.statusText,data:t}),r}return e.json()}finally{o&&clearTimeout(o)}}}(t);return async function(t,i){let o="function"==typeof r?r():r,a={...t},s={Authorization:`Cloud-IDE-JWT ${e}`,...t.headers};if(a.headers=s,o?.onBeforeRequest){let e=o.onBeforeRequest({url:a.url,method:a.method,headers:a.headers||{},data:a.data});e&&(a={...a,url:e.url??a.url,method:e.method??a.method,headers:e.headers??a.headers,data:e.data??a.data})}try{let e=await n(a,i);if(o?.onAfterResponse){let t=o.onAfterResponse(e);if(void 0!==t)return t}return e}catch(e){if(e?.data?.code){let t,r=(t=f[e.data.code],p.t(t)||t);r?e.message=r:e?.data?.message&&(e.message=e.data.message)}throw o?.onError&&o.onError(e),e}}}
let{ServiceProvider:_,useService:y,ServiceContext:v}=(0,n.G)();function b({children:e,...t}){return(0,l.jsx)(_,{...t,createServices:({jwt:e,endpoints:t,getCustomizer:r})=>{let n=g(e,{baseURL:t.remoteService},()=>r("remoteService")),l=g(e,{baseURL:t.imagexService},()=>r("imagexService")),c=g(e,{baseURL:t.galleryService},()=>r("galleryService")),d=g(e,{baseURL:t.copilotService},()=>r("copilotService"));return{remoteService:new s({request:n}),imageXService:new i.N4({request:l}),galleryService:new a({request:c}),copilotService:new o({request:d})}},children:e})}
```

> **Key fact:** the wrapper only adds `Authorization: Cloud-IDE-JWT <jwt>` + `Content-Type: application/json`. It never injects `Request` — the caller must pass `Request` inside each method's argument object. In the shipped RPC architecture no one does this; `Request` lives on the **Rust sidecar** instead (§1.5).

### 1.3 The actual current call chain (file B)

- `IICubeAiChatConnectionService` (file B @11418388): `provideConfig(){return{}}`, `createClient(e){return this._instantiationService.createInstance(Ite,void 0,void 0)}`
- Client `Ite` (file B @5433488): every request goes through `convertReqToRustPayload` and is sent over IPC to the local **ai-agent** Rust process (`sendRequest("request", packet)` / `sendStreamRequest("request_stream", ...)`), which performs HTTPS.
- Chat service (file A @6284611): `await t.requestForStream(this._aiClientManagerService.wrapRequestWithCredential({service:"chat",method:"chat",data:e,context:i}))` — `data` is the internal ChatArgs object; `context` merges `getContextVariables()` (`chat_session_id`, `terminal_info`, `runtime_environment_list`) + `git_info`/`agent_run_info`.
- `ai_agent.dll` contains the literal route table: `api/ide/v1/web_fetch`, `api/ide/v1/intent_detect`, `api/ide/v1/context_select`, **`api/ide/v1/chat`**, `api/ide/v1/query_rewrite`, `api/ide/v1/llm_raw_chat`, `api/ide/v1/chat_prompt`, ... and the header names `Authorization`, `x-ide-token`, `User-Agent`, `X-Trae-User-Agent`, `X-Ide-Function`, `x-ide-version`, `ICUBE_APP_VERSION`, `ICUBE_QUALITY`, `x-flow-traceparent`.

### 1.4 Request-object construction sites (renderer side, file B @5435293 `convertReqToRustPayload`, verbatim tail)

```js
{service:e.service,method:e.method,data:e.data,user_info:t,
 common_params:{...this.icubeEventReportService.getCommonParams(),...I,agent_type:e.data?e.data?.agent_type:"",shell_execute_strategy:w},
 streamlined_common_params:{...this.icubeEventReportService.getStreamlinedCommonParams(),...I,agent_type:e.data?e.data?.agent_type:"",shell_execute_strategy:w},
 client_info:{ppe_env_name:this.getPPEEnvName(),connect_session_id:u,project_id:e.context?.project_id,chat_session_id:e.context?.chat_session_id,version_code:this.getVersionCode(),workspace_folder:m,icube_language:n,confirm_config:e.context?.confirm_config,device_id:s,workspace_id:o?.id,terminal_info:e.context?.terminal_info,is_solo_mode:this.isSoloMode,client_type:this.requestClientType,window_type:this.requestWindowType,git_repos:a,local_git_repos:l,git_metadata_dirs:c,...d?{local_svn_repos:d.repositories}:{},security_rules:g,agent_task_service_strategy:this.getAgentTaskServiceStrategy(),enable_llm_utils_cloud:this.getEnableLlmUtilsCloud(),is_evaluation:this.getIsEvaluation(t.is_internal),is_worktree:e?.data?.is_worktree||!1,is_workspace_folder_changed:e?.data?.is_workspace_folder_changed||!1,workspace_folders:v,original_workspace_folder:e?.data?.original_workspace_folders?.[0],runtime_environment_list:e.context?.runtime_environment_list,agent_run_info:e.context?.agent_run_info,web_fetch_strategy:this.getWebFetchStrategy(),web_fetch_ppe_env:this.getWebFetchPPEEnv(),web_fetch_blocked_domains:this.getWebFetchBlockedDomains(),user_timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,authorized_services:this.getAuthorizedServices(),git_info:e.context?.git_info,permission_profile_id:E,ckg_indexing_enabled:this.getCKGIndexingEnabled(),...y,...S}}
```

`user_info` (file B @5386879 `getUserInfoWithToken`, verbatim):

```js
async getUserInfoWithToken(){const[e]=await Promise.all([this._iCubeAuthService.getUserInfoFresh(),this._entitlementService.getEntitlementInfo().catch(()=>{})]),t=this._entitlementService.getSaaSProductType(),s=t!==void 0?{product_type:t}:void 0;return{name:e?.account.username||"",token:e?.token||"",is_internal:e?.account.scope===pl.BYTEDANCE,user_id:e?.userId||"",scope:e?.account.scope||"",loginScope:e?.account.loginScope,tenant_id:e?.account.tenant_id,enterprise_info:s,email:e?.account.email}}
```

### 1.5 The wire `Request` object as serialized by the Rust sidecar (ai_agent.dll, serde struct-name strings)

```text
struct Request with 9 elements
  service user_info client_info common_params streamlined_common_params custom_params scheduled_task_context (+2 unnamed)

struct UserInfo with 11 elements
  token is_internal jwt_token_type loginScope tenant_id enterprise_info email (+4)

struct ClientInfo with 46 elements
  rw_folders icube_language icube_ai_language user_timezone connect_session_id ppe_env_name plugin_channel workspace_id device_id
  terminal_info window_type git_repos local_git_repos git_metadata_dirs local_svn_repos security_rules agent_task_service_strategy
  enable_llm_utils_cloud is_evaluation request_traffic_type ab_force_vids ab_autotest_advanced_mode original_workspace_folder
  is_workspace_folder_changed agent_run_info client_type web_fetch_ppe_env web_fetch_blocked_domains user_real_ip
  worktree_base_branch authorized_services mobile_commit_id browser_config git_info ckg_indexing_enabled (+17 more)

struct ChatArgs with 61 elements   (the `data` payload for service="chat", method="chat")
  assistant_message_id message_content code_selections active_text_editor workspace_context scene_location use_file_context
  use_filepath unit_test_functions workspace_folders agent_type agent dsl_agent model_name custom_model code_language
  environment runtime_environment_list model_auto_selection context_window_size is_in_plan_mode is_in_spec_mode
  is_in_code_mode is_solo_mode ask_question_config window_capture_hidden_contexts attachments_dir work_path_config
  project_local_path deleted_message_ids next_min_message_index centralized_settings generate_project_name
  caller_timing_durations refactor_mode refactor_custom_preference origin is_background_wakeup force_tool_calls
  force_agent_run_id force_server_task_id seq_offset original_start_time work_mode use_fast_request preheat
  parent_session_id is_user_retry workroom_id hit_shared_artifact_and_workroom (+2 more)
```

## 2. Full field list of the wire `Request` for `/api/ide/v1/chat`

| Wire field | Source |
|---|---|
| `service` | constant `"chat"` (other values: `model`, `lite`, `fast_apply`, `snapshot`, `skill_import`, ...) |
| `method` | constant `"chat"` |
| `data` | internal ChatArgs built by `chatStreamRequestFactory.createChatRequestObject` (file A @7033000+): `agent_type` (e.g. `"chat"`), `agent_id`, `session_id`, `message_id`, `mention_context`, `model_name`, `custom_model`, `message_content:[{type:"text",text_content:...}]`, `code_selections`, `scene_location:"SideChat"`, `parsed_query`, `multi_media`, `agent`, `model_auto_selection`, `active_text_editor`, `workspace_folders`, `asr_times`, `is_solo_mode`, `is_in_plan_mode`, `command_type`, ... |
| `user_info` | `getUserInfoWithToken()` — `name`, `token` (the Cloud-IDE JWT), `is_internal`, `user_id`, `scope`, `loginScope`, `tenant_id`, `enterprise_info`, `email` (8 of 11 slots; `jwt_token_type` + 3 others are filled server-side/sidecar-side or omitted) |
| `client_info` | ~46 fields from `convertReqToRustPayload` + sidecar additions: `device_id` (`IICubeDeviceRegisterService`), `icube_language` (workbench locale), `user_timezone` (`Intl.DateTimeFormat().resolvedOptions().timeZone`), `connect_session_id` (cmd `icube.cloudide.aiSessionID`), `app/version` info, git repo lists, `client_type` (`IDE`/`LITE`), `window_type`, `is_solo_mode`, ... |
| `common_params` / `streamlined_common_params` | telemetry `commonParams` (file B @17448911/17452067): `icube_uid`, `user_id`, `device_id`, `machine_id`, `os_name`, `os_version`, `platform:"electron"`, `app_version`, `quality`, `build_time`, `window_id`, `window_type`, `language`, `app_language`, `chat_mode`, `identity`, `region`, `aiRegion`, `store_region`, `product_code`, `scope`, `tenant_id`, `organization`, `workspace_id`, `channel_name`, `process_type`, `privacy_mode`, ... |
| `custom_params` | optional per-request extras (empty in normal chat) |
| `scheduled_task_context` | only for scheduled tasks |

Nothing is taken from `bootConfig` directly into `Request` except indirectly through endpoints/JWT. `Request` is **not** built in the JS bundle at all in the shipped product; it is assembled by the ai-agent sidecar from the renderer's `{service, method, data, context}` envelope + `user_info` + `client_info`.

## 3. Ranked minimal viable body for `POST /api/ide/v1/chat`

Ranking rationale: the server (Go/TLint) validates the **outer** body first — the handler is the same one CopilotService's `Chat` targets, so the JSON keys it expects are exactly the keys of the legacy `n={...}` object in §1.1. `Request` carries the auth (JWT) and identity. Missing `Request` or an invalid/anonymous token yields `event: error`, `data: {"code":4001,"message":"...param is invalid..."}`.

1. **Rank 1 — required**
```json
{
  "user_input": "hi",
  "session_id": "<uuid>",
  "intent_name": "chat",
  "Request": {
    "user_info": { "token": "<Cloud-IDE JWT>", "user_id": "<uid>", "scope": "<account.scope>", "name": "<username>", "loginScope": "<loginScope>", "tenant_id": "<tenant_id>", "email": "<email>", "is_internal": false },
    "client_info": { "device_id": "<device id>", "icube_language": "zh-CN", "user_timezone": "Asia/Shanghai", "client_type": "IDE", "window_type": "<window type>", "connect_session_id": "<aiSessionID>", "workspace_id": "<workspace id>", "workspace_folder": "D:\\path\\to\\workspace", "workspace_folders": ["D:\\path\\to\\workspace"] },
    "common_params": { "device_id": "<device id>", "os_name": "Windows", "os_version": "<ver>", "platform": "electron", "app_version": "<version>", "language": "zh-CN", "chat_mode": "DEV", "window_id": "<win id>", "window_type": "<window type>", "region": "CN", "product_code": "<product code>" }
  }
}
```
   `intent_name: "chat"` is the safe default for the plain chat intent; the server routes by it. If omitted the param-validation layer can reject before intent resolution.

2. **Rank 2 — typically needed for a real model turn**
```json
  "chat_history": [],
  "variables": {},
  "context_resolvers": [],
  "generate_suggested_questions": false,
  "current_turn": 1,
  "valid_turns": 1
```

3. **Rank 3 — model pinning (optional)**
```json
  "model_name": "deepseek-v3",
  "is_preset": true,
  "provider": ""
```

4. **Rank 4 — multimodal / multi-turn extras (optional)**
```json
  "multi_media": [],
  "conversation_id": "<uuid>",
  "last_llm_response_info": null
```

**Auth header (mandatory):** `Authorization: Cloud-IDE-JWT <jwt>` — the JWT comes from login (`Cloud-IDE-JWT ${e}` in the wrapper §1.2; the same token string is `user_info.token`). Without it the server cannot resolve the user and falls into the 4001 param-invalid path. Other observed headers: `Content-Type: application/json`, `User-Agent`, `X-Trae-User-Agent`, `x-ide-version`, `ICUBE_APP_VERSION`, `ICUBE_QUALITY`, `x-flow-traceparent`, `x-ide-token`.

**Caveat:** the exact per-field server validation (which of Rank 1–3 fields are strictly required) is enforced by the server, not visible in any of the inspected artifacts; the ranking above is inferred from (a) the legacy client body shape, (b) the wire `Request` struct, and (c) the 4001 error you observed with only `user_input`+`session_id` (missing `Request`, hence no auth identity). The fastest empirical route to a definitive minimal body is to capture one real request from a live session (mitmproxy on `trae-api-cn.mchost.guru`) and diff it against Rank 1.
