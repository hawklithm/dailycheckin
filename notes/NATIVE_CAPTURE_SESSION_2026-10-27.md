# Native capture session — 2026-10-27

## Scope and actions

This agent performed initial UI preparation and later static review of the current Trae CN installation. I did not inspect or quote chat bodies, read credentials, change settings, create a chat, or send a UI message. The only UI state change by this agent was the explicitly authorized `sky.launch_app` call for the already-installed Trae CN executable after fresh app/window enumeration returned no Trae window. Later, I added the targeted local xref helper and updated this note; a small synthetic in-memory check exercised the helper. I did not execute an installed DLL, attach a native body observer, or issue a network request. B's paired metadata observation and the user's separately reported synthetic UI test are described below; they were not performed by this agent. No process was terminated or restarted by this agent.

## Installation identity

Verified local installation root: `D:\Users\marcus\AppData\Local\Programs\Trae CN`.

- `Trae CN.exe`: ProductVersion `3.4.7`, FileVersion `2.3.96150`, app package version `1.107.1`; SHA-256 `6069AC7FB5D1E20FA08A1635CA4613957EB81F9DD670DCA5CBA844CAC1062CA4`.
- `resources\app\modules\ai-agent\ai_agent.dll`: SHA-256 `1691ABEDD6DC084F620291F27613EB5D60E77685E6D3FC137ECF2D76C4C7A362`.
- `resources\app\modules\ai-agent\harness.dll`: SHA-256 `F27F80B06B15047DC6519CCC2E04FDC9A6187D38D2EB0C6DA79FE6EC043D027C`.
- Installation-root `sscronet.dll`: SHA-256 `288F987E64107A603CAE0E04D3282935B4017DC1C042EA579334DA49984FB79A`.
- `resources\app\modules\ai-agent\sscronet.dll`: SHA-256 `22511A77155D0A98701CC517E0E62F53BA68E5744E1BEC8CB5BD76FC536DCADA`.
- `resources\app\out\vs\workbench\workbench.desktop.main.js`: SHA-256 `1925DD87B274825770AE8634AD0DE0FEB0E6463BA007F2A5F6CED6E9817FB2A0`.

The executable hash was rechecked immediately before launch. These identities are file/build evidence only; they do not prove which renderer, sidecar, or network-service module handled a request.

## Process and target window

An earlier, pre-wake CIM snapshot showed one `Trae CN.exe`: PID `168100`, parent PID `33732`, creation time `2026-10-26T15:04:37Z`. That was an isolated process observed before the UI launch; it must not be treated as the owner of the subsequently opened window. The `sky.Window` object does not expose a PID. A fresh post-launch `list_apps` returned app id `ByteDance.TraeCN` and one window:

- Window id: `254937106`
- Title: `Agent`
- App identity: `process:D:\Users\marcus\AppData\Local\Programs\Trae CN\Trae CN.exe`

`launch_app` returned without a PID. B later observed a post-launch process tree with Trae root PID `251084`, NetworkService PID `144016`, and renderer PID `232372`. This later tree is separate from the pre-wake PID `168100`. The window id `254937106` and this process tree have not been directly mapped to each other; the UI API still does not expose a PID. `list_windows` exposed ordinary desktop windows and no lock-screen window; no direct OS lock-state API was used.

## UI observation and limitations

A fresh initial `list_apps`/`list_windows` had no Trae window. After the authorized launch, the fresh app list returned the single `Agent` window above. `get_window_state` with `include_screenshot:false, include_text:true` succeeded for that returned window, but exposed no actionable controls, no focused element, and no document text. In the accessibility data available to the observer, the target model label and test marker were not observable. Because the tree did not expose the relevant controls, this is **unknown**, not evidence that the current model or chat history lacks those values.

Screenshot capture was attempted twice through the supported API with fresh target selection between attempts:

1. `computer-use request timed out: get_window_state`
2. After refreshing app/window selection, `FrameArrived timed out: timed out waiting on channel`

A `list_apps` refresh between the two attempts timed out once, then succeeded after the skill-required two-second wait and single retry. Following the second screenshot timeout, the screenshot/input path was stopped. No coordinates or stale accessibility indexes were used.

The current model, generation state, test marker/history, composer, and send control could not be reliably identified. No new test conversation was created, and `只回复 TRAE_NATIVE_20261027_A_OK` was not entered or sent. This UI is not ready for a reliable one-shot test; a manual UI step or a different supported observation path is needed before sending.

## Workspace integrity

Before writing this note, `git status --short` showed existing unrelated changes in `tests/test_translate.py`, `trae2api/gateway.py`, `trae2api/translate.py`, `notes/PYTHON_CLIENT_REPRODUCTION_PLAN_2026-10-27.md`, and `tests/test_gateway_body.py`. This agent did not edit those files or business source. It added `tools/native_xref_harness.py` and updated this note. Only the in-memory synthetic xref self-check was run locally; no app hook, native attach, installed-DLL execution, or network request was performed by this agent.

## Current JavaScript request and transport callsites (static only)

These are source and bundle observations from the installed build, not evidence that a particular route was active in the observed window. No live request, account value, message body, or credential was read.

### Raw LLM V2 SDK builder: defined, caller not found

Current `resources\app\node_modules\@byted-icube\ai-modules-chat\dist\index.mjs` is 15,617,012 bytes, SHA-256 `F6998E6C0DB6E1191B06311E6C7205D5DB6EA1E4F1963B4F9A4441604CDF8354`.

- `CopilotService.LLMRawChatV2(e,t)` at byte offset `0x728D6` forms `genBaseURL("/api/ide/v2/llm_raw_chat")`, maps these properties directly from `e` with no field transformation—`config_name`, `model_name`, `session_id`, `messages`, `message`, `conversation_id`, `is_custom_model`, `provider`, `Request`, `encrypted_model_params`, `user_input`, `request_type`, `metadata`, `tools`, `queue_id`, `request_seq`, `mode_type`, `chat_mode`, `config_source`, `access_type`, `image_config`, `estimate_prompt_tokens`, `slash_command`, `message_origin`, `tool_choice`, `reasoning_effort`, `stream`, `retry_times`, `queue_retry`, `video_config`, `connect_check_param`, `user_selected_model_name`, `reasoning_effort_level`, `estimated_token_usage`, `custom_model_uniq_id`, `provider_context`, `biz_context`, `extra_info`, `use_fast_request`—then calls `this.request({url:r,method:"POST",data:n},t)`. It has no top-level `max_tokens`, `temperature`, or `top_p` mapping.
- The adjacent `InnerLLMRawChatV2` at `0x780B1` uses `/api/ide/inner/v2/llm_raw_chat` and the same direct mapping.
- Default request wrapper `function g(e,t={},r)` at `0x91764` prefixes relative URLs with the supplied `baseURL`, adds `Authorization: Cloud-IDE-JWT ${e}` and JSON content type, serializes truthy data with `JSON.stringify`, and returns `response.json()` on success. The provider factory at `0x91D64` receives `{jwt,endpoints,getCustomizer}`, passes `endpoints.copilotService` as the copilot request `baseURL`, and constructs `CopilotService`; customizers can replace request fields or response values. Here `stream` is a JSON body field; this wrapper contains no SSE parser.
- The current SDK contains two `LLMRawChatV2` text hits, corresponding to the public and `Inner` method definitions. The selected current renderer/main/cueMain sources contain no explicit `LLMRawChatV2` callsite. The current Solo Lite route below also does not call it. The completion extension contains a repeated `fusionRawChatAPI -> api/ide/v2/llm_raw_chat` map entry at `extension.js` offset `0x38524B`, but no caller was found in the targeted review. No static edge connects `getUserInfoWithToken().token` to the SDK provider's separate `jwt` parameter. Treat V2 as a supported-looking static builder candidate, not an active/current-session route.

### Current Solo Lite path to the native request bridge

Current `resources\app\node_modules\@byted-icube\solo-lite\dist\8139.3e01fbe2.mjs` is 8,120,628 bytes, SHA-256 `C1E006710CD7C7D79AC38769E7416E541DE8A027C7C4209E54CE71BAF7F6C758`.

- `getModelRequestSelection` at `0x254637` reads fixed config from `ModelSelect` host context or the per-session selected model/mode from `modelStore`; `buildSendMessageRequest` at `0x255317` constructs `{chat_session_id, content:[], query:JSON.stringify(contentBlocks), model_name, agent_type, agent_id, model_selection_strategy, custom_model, common_params, ...optional turn/session/origin/permission fields}`. Optional worktree fields are added only when the session has active worktree data.
- The ordinary send call at `0x258628` invokes `this.chatApi.sendMessage(em(p))`. The API map at `0xF95B8` maps `chat.sendMessage` to `{service:"lite",method:"send_message"}` and `chat.subscribe` to `{service:"lite",method:"subscribe_events"}`. `subscribeStream` at `0x253D37` calls `chatApi.subscribe(...)` and registers event handlers. This is a local native-agent request/event route, not an HTTP URL or proof of V2 use.
- Current renderer `workbench.desktop.main.js` is 18,985,288 bytes, SHA-256 `1925DD87B274825770AE8634AD0DE0FEB0E6463BA007F2A5F6CED6E9817FB2A0`. `createUserInfo` at `0x52F8CB` calls `_icubeChatCommonSession.getUserInfoWithToken()`. Its implementation at `0x5238C4` calls `_iCubeAuthService.getUserInfoFresh()` and returns `token:e?.token||""` with account metadata. `convertReqToRustPayload` at `0x52E54E` places that result in `user_info:t` and constructs `common_params`, `streamlined_common_params`, and `client_info`.
- For non-stream requests, renderer `request(e)` at `0x52D3F8` obtains the device id and user info, builds the payload, and invokes `TransportManager.executeRequest`. For stream requests, `requestForStream` / `doRequestWithStream` at `0x52D670` builds the same payload and invokes `executeStreamRequest`. `TransportManager` obtains `modularManagerService.getAiAgentRpcClient()` at `0x52B1C1`, builds a packet in `createRequestPacket` at `0x52B256`, then calls `sendRequest("request", packet)` at `0x52B5E5` or `sendStreamRequest("request_stream", packet, ...)` at `0x52BE17`.

This closes a static renderer-to-native RPC edge and the origin of the outer `user_info.token` field. It does not close native Rust serialization, outbound URL/header/body construction, or prove what token type the sidecar uses. It also does not prove a specific call occurred in the current UI session.

### cueMain TTNet/ZMQ HTTP path: generic and independent in this evidence

Current `resources\app\extensions\ai-completion\resource\aiserver\cueMain.js` is 3,534,916 bytes, SHA-256 `C1EC979C919A1B1D430EC91A0EE5ABCE3E317E0A74570308EAD01CD440FF60F1`.

- `ApiManager.request(e,r,n,s)` at `0x2D8C59` resolves a URL through `BaseDomain.getCopilotUrl(e.path,...)` or an explicit `n.domain`, obtains auth headers through `this.user.getJwtTokenHeaderObj("others")`, applies `e.transformRequest(r)`, merges the API/auth/caller/common header objects, and dispatches to the TTNet agent's `post` or `get`. For `e.isStream`, its response callback wraps `d.stream` with `$He` at `0x2D7769`, feeds decoded chunks to the SSE parser, and yields parsed `{event,id,data,retry}` records through `f.source`.
- The separate `Authenticator.getJwtTokenHeaderObj` at `0x2DCDCB` returns `{Authorization: jwtTokenType + " " + getJwtToken(...)}`. `getLastedJwtToken` at `0x2DCB25` obtains a token over the local `AuthorizeRequest` RPC. This is not a demonstrated mapping from renderer `user_info.token`.
- `TraeNetworkClientAdapter` begins at `0x2D47B7`. Its `init` conditionally reads `TRAE_NET_ZMQ_ENDPOINT`, imports `@byted-icube/trae-network-client`, and constructs `ZmqClient`; its `fetch` forwards method, URL, headers, signal, and converted body. `TTNetAdapterRegistry.detectEnvironment` selects this adapter only when that process environment variable is truthy. The bundle's `CueBootstrap` invokes shared HTTP initialization at `0x35CFE0`, but this static code does not prove the current process selected this branch or that the route handles `lite.send_message`.
- The installed `@byted-icube/trae-network-client` is version `0.5.0-dev.1351818`; `fetch.js` SHA-256 `50E01BA95A7BF7C030F932EB8AB70E8D7C02C2B321224D4DA7710A5565C18EBF`, `undici-dispatcher.js` SHA-256 `EEFC94C7F14B52CBDFE09B8DB009E78E3DD7EF2DA268DF8C8989EFDB0F08C0CD`, and Windows native binding SHA-256 `5CDBE71D2CADAC5AF02140E7AC77D5995BE7ADD6B400BC648130F5BBBE55812B`. `ZmqDispatcher.dispatch` at `undici-dispatcher.js` byte offset `0x6D7` builds `url=origin+path`, buffers body, and calls `_client.stream({method,url,headers,body,timeout_ms})` at `0xDD5`; it forwards `response_started` status/headers, `data` chunks, and `error`/`complete` events to Undici. This is the last JavaScript request/response boundary before the native ZMQ client, if this conditional path is active. The installed package has no `.d.ts` declaration; exact native method ABI is not established by this wrapper.
- In current cueMain, `llm_raw_chat` occurs only as the `ModelScene.Agent` enum value (`0x8F2A5`); no `LLMRawChatV2` symbol or `/api/ide/v2/llm_raw_chat` path was found. Thus cueMain's generic cloud API builder/SSE parser is a useful conditional observation point, not a proven callsite for either the V2 route or the current Solo Lite send route.

### Current static limits

The best proven caller chain in these JS sources ends at `lite.send_message` / `request_stream` over the local native RPC. The V2 SDK method is present but has no explicit caller in the reviewed current sources and no proven CN login-token wiring. The cueMain TTNet/ZMQ code exposes a full generic HTTP/SSE boundary but remains unlinked to that native RPC request. This was the boundary after the metadata-only baseline. The later paired run below matched observed route hashes to AgentV3 path candidates, but still does not identify a serialized body or correlate one route request to the UI turn.

## Current harness.dll route xref check (static only)

The currently installed `resources\app\modules\ai-agent\harness.dll` was re-hashed before and after the targeted scan: SHA-256 `F27F80B06B15047DC6519CCC2E04FDC9A6187D38D2EB0C6DA79FE6EC043D027C`, size 219,872,656 bytes, PE image base `0x180000000`. The `.rdata` raw offset/RVA mapping used was raw `0x9460E00` to RVA `0x9462000`; all reported RVAs below use the PE section mapping, not raw-offset guesses.

Exact route bytes occur in a contiguous `.rdata` string cluster. Current file offsets and RVAs are:

| Exact UTF-8 literal | File offset | RVA |
|---|---:|---:|
| `api/agent/v3/create_agent_task` | `0xADD0E30` | `0xADD2030` |
| `api/agent/v3/commit_toolcall_result` | `0xADD0E4E` | `0xADD204E` |
| `api/agent/v3/llm_utils_chat` | `0xADD0F21` | `0xADD2121` |
| `api/agent/v3/workflow/commit_toolcall` | `0xADD0F57` | `0xADD2157` |
| `api/ide/v2/llm_raw_chat` | `0xADD12B7` | `0xADD24B7` |

These literals have no leading slash. The neighboring route bytes are not NUL-delimited, so the scan did not infer a route's length from the next string. The prior exact `api/agent/v3/...` path offsets in `REAL_PATH_REVIEW_2026-10-26.md` describe an earlier installed image and must not be substituted for these current-image offsets.

For these exact full literals, the targeted helper checked (1) UTF-8 literal occurrences and their PE section RVAs, (2) `.rdata`/`.data` qword pairs containing the exact image VA followed by the exact UTF-8 byte length, (3) direct image-wide absolute pointer encodings, and (4) Capstone-validated x64 RIP-relative `LEA`/`MOV` references in `.text`. It also scanned candidate target RVAs bytewise across the small prelude/table-start window `0xADD1FE0`–`0xADD2060`. Results: **no exact Rust pointer-plus-length entry, no direct absolute pointer, and no RIP-relative code reference to any route literal start or the table start was found.** Within the nearby window, the only RIP-relative hits target `0xADD1FF0` and `0xADD2018`; neither is a route address. Instruction RVA `0x68EFEE5` in function `[0x68EFD50, 0x68EFFBD)` targets `0xADD1FF0`; instruction RVA `0x68EA67B` in function `[0x68EA640, 0x68EA68D)` targets `0xADD2018`. The latter contains a pointer to the Rust source-path string at RVA `0xADD1F62` followed by its exact length `0x4c` (`/rustc/.../library\std\src\sync\once.rs`); `0xADD1FF0` is a separate zero/8-byte pair. These nearby code references do not establish a request path, caller, or serializer.

Therefore this pass confirms route bytes in the current image but did **not** identify a route caller, URL join, request DTO, serializer, auth construction, or response parser in `harness.dll`. This is a bounded negative xref result for the tested route starts and RIP-relative LEA/MOV forms; it is not proof that the DLL cannot construct or send those routes through another representation or indirect path. No remote call or native code execution was performed.

The reproducible targeted helper is `tools/native_xref_harness.py`; its full JSON result is in ignored `logs\native_xref_harness_final_20261027.json`. Static parser dependencies already available in `D:\Users\marcus\anaconda3\python.exe` are LIEF `0.12.3` and Capstone `5.0.7`; no dependency was installed. A small in-memory synthetic positive/negative RIP-LEA check passed after correcting a duplicate-prefix decode edge case. The helper only reads the specified PE and does not load it.

## Paired metadata route-hash review (sanitized output only)

For `meta-20261027-paired-a`, each path candidate below was independently checked by hashing the static candidate as `SHA-256(encodeURIComponent(path))`, matching the observer's documented projection, and verifying the safe static path-segment pattern. The observer strips query and fragment before hashing. All candidates are path matches only; they do not identify a caller or body.

| Request sequence(s) | Safe path SHA-256 | Exact static path candidate | Current source evidence |
|---|---|---|---|
| 21, 27 | `ac4781f6c4434a5142b97824be620dc13b6d020747bc32147732bdf487b1f28d` | `/api/agent/v3/llm_utils_chat` | `ai_agent.dll` SHA `1691ABEDD6DC084F620291F27613EB5D60E77685E6D3FC137ECF2D76C4C7A362`, file offset `0xA7147A1`; `harness.dll` SHA `F27F80B06B15047DC6519CCC2E04FDC9A6187D38D2EB0C6DA79FE6EC043D027C`, file offset `0xADD0F21` |
| 26 | `e83038e8075b1149396727c1454bcb882d3267826c9e114ad312969596616d88` | `/api/agent/v3/create_agent_task` | Current `ai_agent.dll` offset `0xA7146B0`; current `harness.dll` offset `0xADD0E30`; hashes as above |
| 40 | `ef8445550ec2cbd7cd1451c6bd8832bae09bea584943ba9de0c655349f4fbe34` | `/api/agent/v3/sync_history_state` | Current `ai_agent.dll` offset `0xA71476E`; current `harness.dll` offset `0xADD0EEE`; hashes as above |
| 45 | `9edde739e9e152abec7cbc6fbc1e9518ccde70c3346e2a12df09322fe3513078` | `/api/agent/v3/workflow/start` | Current `ai_agent.dll` offset `0xA7147BC`; current `harness.dll` offset `0xADD0F3C`; hashes as above |
| 2 | `4a1d2d9af87423cba8d2985ee86a53a6ab44298094741f250766170183ba440c` | `/cloudide/api/v3/trae/CheckLogin` | `ai-modules-chat/dist/index.mjs` SHA `F6998E6C0DB6E1191B06311E6C7205D5DB6EA1E4F1963B4F9A4441604CDF8354`, path offset `0x8C69D9` |
| 6, 7 | `f8e9eeac9c3eaa7814d56718df8213b29cac895115a04ee19c2b1194ca527295` | `/api/ide/v1/batch_get_detail_param` | Same `index.mjs` SHA, offset `0x7BDE3` |
| 20 | `8e09837fb893f9b4d91d39949554b6c5272e55c85bc4837819cc705c91c92ca8` | `/api/ide/v1/get_skill_detail` | Same `index.mjs` SHA, offset `0x7C387` |
| 34 | `3a68142076ea8a9201b5053aa8cded4e7045f7f41509e74d636d5f7a8268b123` | `/api/ide/v1/code_completion/model_configs` | Same `index.mjs` SHA, offset `0x6D812` |
| 35, 36 | `af9ac4b3cc9975e4172459958df0cd16b3abfb9f698e36fc20d0eb9fe5903265` | `/api/ide/v1/get_detail_param` | Same `index.mjs` SHA, offset `0x72DFA`; static SDK `GetConfigDetail` uses GET with query parameters, while both observed requests used POST, so this is only a path match, not a matching request builder |
| 44 | `224b2f345ad8562059456a860b5f2ed2561c1f4c1f890d216934b760dfe1ad39` | `/api/ide/v1/super_completion_query` | Same `index.mjs` SHA, offset `0x76AB7` |
| 59 | `249e5495c61643681e1e9bdcfee5be2d31ed6aa5785cf53528b07cd514c48355` | `/api/ide/v1/get_client_config` | Same `index.mjs` SHA, offset `0x75971` |

Static SDK builder definitions provide candidate shapes but no callsite for these observed native requests: `BatchGetConfigDetail` POST maps `functions`, `access_type`, `ab_force_vids`, `ab_autotest_advanced_mode`, `agent_type`, `current_config_info`, `mode_type`, `Request`; `GetSkillDetail` POST maps `build_time`, `functions`, `access_type`, `Request`, `os`; `SuperCompletionQuery` POST maps completion context including `user_query`, `history_queries`, `symbol`, `file_path_edit`, `render_context`, and `biz_context`; `GetClientConfig` POST maps `config_key`, `Request`; `CodeCompletionModelConfig` is GET with `version_code` and `channel` query fields. `CheckLogin` is POST with `GetNickNameEditStatus`, `GetAIPayHost`, `IDEVersion`, `SSO`, `Sig`, and `ReqSource`. These declarations are from the SDK bundle noted above, not captured request bodies. The `GetConfigDetail` route path is an observed POST, while this SDK method defines GET with query parameters, so its builder is specifically not an exact method match.

The current `ai_agent.dll` contains route strings for the four observed AgentV3 paths, but no matching request DTO or serializer xref was established. Current static strings include `LLMRawChatMessage` at file offsets `0xA4A65CF` and `0xA4BAA93`; targeted term search found no `LLMUtilsChatRequest` or `LLMUtilsChatResponse` names. These type-name strings do not define the observed `llm_utils_chat` body or its response event schema.

Additional exact static path matches in the paired run were `seq 11,51` `/api/remote/v1/git/repositories` (Solo Lite bundle SHA `C1E006710CD7C7D79AC38769E7416E541DE8A027C7C4209E54CE71BAF7F6C758`, offset `0x1F3974`); `seq 17,29,33,57` `/api/remote/v1/skills` (chat SDK SHA above, offset `0x8354B`); `seq 18,25,30,32,56` `/api/remote/v1/plugins` (chat SDK SHA above, offset `0x838AF`); `seq 31` `/extensions/api/-/skill/list-v3` (chat SDK SHA above, offset `0x81B48`); `seq 47` OPTIONS and `seq 48` POST `/api/v1/commercial/get_session_usage` (chat SDK SHA above, offset `0x75610`); and `seq 13,19,24,43,52,58` `/trae/api/v2/pay/ide_user_ent_usage` (workbench SHA `1925DD87B274825770AE8634AD0DE0FEB0E6463BA007F2A5F6CED6E9817FB2A0`, offset `0xE80160`). These routes are plausible configuration, completion, entitlement, or marketplace/background requests according to their static builders; timing alone does not associate them with the submitted chat turn.

Other safe path hashes in this run had no exact literal match in the selected current SDK, Solo Lite, renderer, cueMain, `ai_agent.dll`, or `harness.dll` route corpus: `fe1857d3…` (seq 1), `eac33706…` (3), `61936c6b…` (4,16,23,53), `e2796cc2…` (5,14,15,54,55), `19f81c60…` (8), `cd6fda2c…` (9), `e66d6e68…` (10,22,49), `d7786a9c…` (12), `db2976b8…` (37,38,42,46), `0ba7cab6…` (39), and `5fd14621…` (41). They remain unresolved hashes, not decoded routes. No path hash in this paired run matched `/api/ide/v2/llm_raw_chat`.

The observed AgentV3 route hashes show that those paths were started in this paired metadata window, including two `llm_utils_chat` requests. Current binaries also contain static `LLMRawChatMessage` type-name strings (`ai_agent.dll` offsets `0xA4A65CF` and `0xA4BAA93`), but no current request DTO, serializer, or route-consumer xref connects them to `llm_utils_chat`. The only currently reviewed SDK `LLMRawChatV2` remains a separate static builder without an observed route match. The metadata observer hooks only `InitWithParams`/`Start`: it reports no response status/event or body. The user separately reported that the fixed synthetic marker appeared in the UI; that is a user report, not observer evidence linking the UI response to any one request sequence. No header value, request body, response body, or conversation text was read.

## Native upload observer offline acceptance (2026-10-27)

The upload observer and projection core now pass their offline mock contract. The Node fixture installs ten required public upload/request hooks and four manifest-checked callback hooks, drives a split UTF-8 request through callback-only GetLength/Read with non-final acknowledgements, and emits seven safe records: hook status, coverage, four callback descriptors, and one upload projection. The projection fixture uses `TRAE_NATIVE_20261027_B_OK`; `marker_hit` is a candidate field match and `marker_semantics` remains `unverified`.

The mock now represents Frida scalar arguments as hexadecimal native-pointer strings. The observer bounds these strings before numeric conversion, accepts only the signed `-1` GetLength sentinel (including `0xffffffffffffffff`), and still accepts bounded decimal UInt64 getter values. A failed required public hook is absent from the installed list and makes upload readiness false. The stop path detaches the public and dynamic mock hooks.

Only the exact allowlisted routes and typed request/provider/sink/buffer mappings can reach body projection. Upload reads remain capped at 1 MiB; no response hooks or response buffers are used. Projection fields contain only allowlisted schema paths/types, fixed per-field enum literals, one-way ID hashes, and bounded usage numbers. Marker misses retain those safe structure projections. The fixture stdout excludes the private auth digest, marker text, and secret sentinels. Auth digests are sent only through the in-memory observer IPC path; only `authorization`, `x-ide-token`, and `x-cloudide-token` values are examined, with one exact, case-sensitive `Cloud-IDE-JWT ` prefix removal.

Offline verification on Node `v24.15.0`:

```powershell
node --check tools/native_upload_observer.js
node --check tools/native_upload_projection_core.js
node --check tests/test_native_upload_observer.js
node tests/test_native_upload_observer.js
node tests/test_native_upload_observer.js --fixture-events
& 'E:/tools/frida/venv/Scripts/python.exe' -m unittest discover -s tests -p test_native_upload_observer.py -v
& 'E:/tools/frida/venv/Scripts/python.exe' tools/native_upload_observer.py --self-test
```

Results: all three Node syntax checks passed; the JS suite reported 22 cases passed; the Python sanitizer/fixture suite reported 10 tests passed; Python's observer self-test reported 12 cases passed. The fixture event round-trip also produced a synthetic Python `observer_ready` record. These results validate offline parsing, sanitization, and cleanup logic only: this JS acceptance did not attach Frida, operate the UI, send a network request, or observe a live request. The subsequent bounded live-capture result is pending and must be reported separately.
