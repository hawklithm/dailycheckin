# Authentication and V1 Request Compatibility Review

Date: 2026-10-27

## Scope

This is a source-only review of the repository authentication paths and the
OpenAI-to-V1 request builder. No credential values were read, no login was
started, no remote request or refresh was performed, and no native process was
attached.

## Authentication evidence and limits

- The project has a PKCE authorization-code login flow. `TraeLoginService`
  constructs the authorization URL in `trae2api/login.py:154-175`, exchanges
  the callback code at `/trae/api/v3/oauth/ExchangeToken` with its verifier at
  `login.py:208-224`, and orchestrates login at `login.py:237-272`.
- The login path passes `Result.Token` to `GetUserInfo`, then stores that token
  as both `creds.token` and `creds.jwt` (`login.py:257-271`). This repository
  behavior does not prove which token form the currently installed CN client
  uses for an inference request.
- The storage loader also aliases the stored Cloud-IDE token into `jwt`
  (`trae2api/auth.py:135-170,181-216`). `token_valid` checks only the parsed
  expiry and a margin (`auth.py:254-264`); it does not establish signature,
  audience, or endpoint authorization.
- `get_jwt()` calls `refresh_jwt()` when forced or when the local expiry check
  fails (`auth.py:266-270`). The default refresh posts to
  `/api/v2/GetUserToken` with `X-Cloudide-Token` (`auth.py:272-295`). If the
  Cloud-IDE token is expired, refresh-token rotation is blocked unless
  `TRAE2API_ALLOW_ROTATION=1`; the opted-in path then calls
  `/trae/api/v3/oauth/ExchangeToken` (`auth.py:275-335`). Do not infer that
  `GetUserToken` is required by ordinary CN login or remove the current alias
  before closing token provenance.
- The saved `notes/REAL_PATH_REVIEW_2026-10-26.md:243-253` records one
  `GetUserToken` request returning HTTP 404 and no subsequent V2 request. The
  later local source snapshot identifies the configured host as
  `api.trae.cn`; the report notes this was not transaction-level network
  evidence. The result does not prove that the old token was invalid, that
  login failed, or that ordinary CN exchange is unusable.
- The same report at `REAL_PATH_REVIEW_2026-10-26.md:267-271` records static
  CN mapping `ExchangeToken.Token → userInfo.token → native RPC
  params.user_info.token`, but no proven mapping from that RPC field to an
  inference HTTP authorization header. The SDK's `jwt` property producing a
  `Cloud-IDE-JWT` authorization value does not close the missing caller link.
  The report describes `GetUserToken` as an older USDS branch and
  `GenerateTempToken` as a separately gated/file-backed path with no proven
  SDK connection.

## Current proxy request path

`TraeGateway._headers()` calls `auth.get_jwt()` and builds the existing V1
header set (`trae2api/gateway.py:82-108`). `stream_chat()` sends the body to
`POST /api/ide/v1/chat` (`gateway.py:331-335`). Saved `_e2e_verify` results
report a prior successful V1 request, but it was not rerun in this task and is
not proof of the native desktop route. The static SDK V2 builder and the
single saved V2 400/empty-body result likewise do not establish a usable V2
request contract or active native caller.

## Confirmed request-construction defect and bounded repair

Before this change, `build_chat_body()` inserted tool declarations and
`tool_choice` as a system turn and called `trae_history_and_input(...,
drop_system=True)`, discarding those declarations together with caller system
messages (`gateway.py:202-228`). `normalize_messages()` did not map the
`developer` role (`translate.py:142-174`). The helper-only tests used its
default `drop_system=False` and did not exercise the final builder path.

The V1 compatibility path now preserves all system and developer messages in
source order as explicitly labeled ordinary user text on the latest user-ish
turn. Tool schemas and the text rendering of `tool_choice` use the same
compatibility block. The block is mirrored in `user_input`, the retained
`chat_history` turn, and `message_content` according to the existing V1 body
shape; it is inserted once within each representation and remains on the
current turn after the builder truncates history to 24 entries. When
instructions exist without any user/tool-result turn, the builder creates a
synthetic user turn using the existing `继续` fallback. This is a transport
compatibility representation, not native system/developer role equivalence or
proof that the V1 backend interprets tool declarations as structured tools.

The V1 route, headers, model-routing defaults, session-ID generation, and
client-side tool execution permissions were not changed. `max_tokens`,
`temperature`, `top_p`, and reasoning controls remain outside this repair.

## Offline verification

Using `D:\Users\marcus\anaconda3\python.exe` from the repository root:

```powershell
& 'D:\Users\marcus\anaconda3\python.exe' tests/test_translate.py
& 'D:\Users\marcus\anaconda3\python.exe' tests/test_gateway_body.py
```

Results: translate tests **30 passed / 0 failed**; final gateway-body tests
**6 passed / 0 failed**. The builder tests use synthetic messages only and
cover interleaved/post-user instructions, tool schema and `tool_choice` in the
final body, tool-result ending, history truncation beyond 24 entries,
instruction-only input, the empty-input fallback, and a no-instruction
multi-turn control that asserts the prior `user_input` and full history
mapping. No remote tests were run.

## Still unproven

The active CN inference route, the exact token-to-request-header mapping, V1
upstream treatment of compatibility text, and structured-tool equivalence
remain unverified. Keep the existing alias and route behavior until the
current token provenance and a same-turn remote request/response are closed
with evidence.
