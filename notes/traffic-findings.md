# Trae CN 3.4.4 → POST https://trae-api-cn.mchost.guru/api/ide/v1/chat — captured request shape

Source of truth: Trae CN install bundles + live logs from session `20261024T171939`.
No chat body was present in the logs (no chat turn fired during capture), but the exact
client-side serializer was recovered from the shipped JS bundle, and the full header set
from live request logs of sibling `/api/ide/v1/*` calls on the same client object.

## 1. Endpoint + body schema (exact, from client code)

Client: `CopilotService.Chat(e,t)` in
`D:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app\node_modules\@byted-icube\ai-modules-chat\dist\index.mjs`
(identical copy in `...\@byted-icube\solo-lite\dist\5160.0bfba5f1.mjs`):

```js
Chat(e,t){
  let r = this.genBaseURL("/api/ide/v1/chat"),
  n = {
    user_input: e.user_input,
    intent_name: e.intent_name,
    variables: e.variables,
    chat_history: e.chat_history,
    context_resolvers: e.context_resolvers,
    session_id: e.session_id,
    generate_suggested_questions: e.generate_suggested_questions,
    conversation_id: e.conversation_id,
    current_turn: e.current_turn,
    valid_turns: e.valid_turns,
    model_name: e.model_name,
    multi_media: e.multi_media,
    Request: e.Request,
    last_llm_response_info: e.last_llm_response_info,
    is_preset: e.is_preset,
    provider: e.provider
  };
  return this.request({url: r, method: "POST", data: n}, t)
}
```

→ POST body JSON keys, in order:
`user_input, intent_name, variables, chat_history, context_resolvers, session_id,
generate_suggested_questions, conversation_id, current_turn, valid_turns, model_name,
multi_media, Request, last_llm_response_info, is_preset, provider`

Sibling endpoints with same pattern (same bundle):
- `POST /api/ide/v1/intent_detect`: `intent_name, user_input, variables, chat_history, intents, context_resolvers, session_id, Request`
- `POST /api/ide/v1/context_select`: `user_input, variables, chat_history, session_id, Request`
- `GET  /api/ide/v1/chat_prompt` (params): `user_input, intent_name, variables, chat_history, context_resolvers, session_id, generate_suggested_questions, conversation_id, current_turn, valid_turns, model_name, multi_media, last_llm_response_info, is_preset, provider` + `Request` in body-slot
- `POST /api/ide/v1/chat_completion`: `model, messages, max_tokens, temperature, top_p, n, stream, stop, presence_penalty, frequency_penalty, functions, function_call, Request, tools, tool_choice, session_id, disable_antidirt`
- `GET  /api/ide/v1/llm_raw_chat_prompt` (params): `model_name, messages, session_id, message, conversation_id, is_preset, provider, user_input, metadata`

## 2. Headers (observed verbatim, live)

From `%APPDATA%\Trae CN\logs\20261024T171939\window1\exthost\trae.ai-code-completion\completion.log`
(line 89, 105; same set in window3 line 44/74, window4 line 90/103) —
client sends via `agent: TTNet, proxy: undefined`:

```json
{
  "X-App-Id": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
  "x-plugin-channel": "icube-ai",
  "x-ide-version-code": "20260212",
  "x-ide-token": "******",
  "Content-Type": "application/json",
  "Authorization": "Cloud-IDE-JWT ******",
  "X-Device-Cpu": "AMD",
  "X-Device-Id": "4333646823299987",
  "X-Machine-Id": "56cb66e60ecd32141cfe256f4e5ff76e7f8d53bc99c6a93f8ef48b7cb0068524",
  "X-Device-Brand": "MS-7B89",
  "X-Device-Type": "windows",
  "X-Os-Version": "Windows%2010%20Education"
}
```

Header-building code (extension.js, module at offset ~2408k): maps
`cpu→X-Device-Cpu, device_id→X-Device-Id, machine_id→X-Machine-Id,
device_model→X-Device-Brand, os_name→X-Device-Type, os_version→X-Os-Version`,
each value passed through `encodeURIComponent` (hence `%20`).
`x-ide-version-code` = domainConfig.xVersionCode.

Auth mapping (extension.js config, verbatim):
`"chatAPI":"api/ide/v1/chat","authHeader":"x-ide-token"` and
`appId":"6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"` (CN + sg/us regions share appId;
`practiceAppId":"850edec7-b9d0-48aa-99b5-67c888e282cd"`).
Runtime domain resolution: cue-server stdout log
`[DynamicDomain] applyBootConfig: cue={"domain":"https://trae-api-cn.mchost.guru","appId":"6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"}`.

## 3. The `Request` object

- The `Request` field is attached by the **ai-agent Rust module** (`ai_agent.dll` 265 MB,
  loaded with its own `sscronet.dll` TLS stack in `%LOCALAPPDATA%\Programs\Trae CN\resources\app\modules\ai-agent\`).
  The renderer speaks local RPC ("lite" service, see renderer.log
  `[ai-chat/v2][rust] invoke ... lite.list_chat_sessions`) and the Rust side builds
  the HTTP request including `Request` + auth headers.
- `ai_agent.dll` strings confirm endpoint set: `api/ide/v1/chat`, `intent_detect`,
  `context_select`, `query_rewrite`, `agents/runs`, `chat_prompt`, `llm_raw_chat`, etc.
- Field-level contents of `Request` are not recoverable from JS (they never pass through it);
  the SQLite DB path was explicitly out of scope. Recovery options: TLS MITM of the
  sscronet/TTNet traffic (cert trust required) or DB parse — left as next step.

## 4. Observed traffic pattern (main.log, same session)

- Non-chat `/api/remote/v1/*` calls are logged as `ttnet fetch request/response` pairs in
  `%APPDATA%\Trae CN\logs\20261024T171939\main.log` (e.g. `skills?page_size=100...`,
  `plugins?page_size=200&product_name=ide&client_version=3.4.4&package_type=stable&chat_mode=code&os=windows`).
- `git/repositories` returned 403 (no repo scope) — shows status/log format.
- Chat/API `/api/ide/v1/*` requests are NOT logged with bodies anywhere in the session logs.

## 5. Related config blobs (verbatim, extension.js `JSON.parse` config, cn region)

```
"chatAPI":"api/ide/v1/chat"
"intentDetectAPI":"api/ide/v1/intent_detect"
"contextSelectionAPI":"api/ide/v1/context_select"
"queryRewriteAPI":"api/ide/v1/query_rewrite"
"agentRunAPI":"api/ide/v1/agents/runs"
"agentRunResultAPI":"api/ide/v1/agents/runs/:id/tool_call_outputs"
"agentRunDiff":"api/ide/unstable/tools/diff"
"practiceTitleAPI":"api/ide/v1/practice/generate_conversation_title"
"llmRawChatAPI":"api/ide/v1/llm_raw_chat"
"fusionRawChatAPI":"api/ide/v2/llm_raw_chat"
"fusionModelDetailAPI":"api/ide/v1/get_detail_param"
"modelListAPI":"api/ide/v1/model_list" / "fusionModelListAPI":"api/ide/v1/get_model_list"
"chatPromptAPI":"api/ide/v1/chat_prompt" / "builderPromptAPI":"api/ide/v1/llm_raw_chat_prompt"
```

## Files referenced
- `...resources\app\node_modules\@byted-icube\ai-modules-chat\dist\index.mjs` (Chat body schema)
- `...resources\app\extensions\ai-completion\dist\extension.js` (headers builder, endpoint config)
- `%APPDATA%\Trae CN\logs\20261024T171939\window{1,3,4}\exthost\trae.ai-code-completion\completion.log` (live headers)
- `%APPDATA%\Trae CN\logs\20261024T171939\Modular\cue-server_0_*.log` (domain+appId)
- `%APPDATA%\Trae CN\logs\20261024T171939\main.log` (ttnet URL patterns)
