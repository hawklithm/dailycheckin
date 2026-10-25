# DSH (DeepSeek Harness) — How Working-Directory / File / Tool Context Reaches the Model Backend

Reverse-engineered read-only from `F:\deepseek-harness` (TypeScript monorepo, `packages/`, `apps/`).
Purpose: let a third-party OpenAI-shaped proxy mine the workspace root, open files, and editor state
out of a DSH request body.

**Headline finding:** DSH does **not** use an `<environment>` block, a `Primary working directory:`
line, or an "open files" list. The workspace root reaches the model as **one prose sentence inside a
user-role "runtime context" snapshot**:

```
Current working directory: "D:\workspace\trae2api".
```

(`JSON.stringify`-quoted, trailing period). Everything else — referenced files, attachments, tool
results — is either explicit `@`-path tokens typed by the user, or XML-ish tool-result envelopes
carrying a `<path>` element.

---

## 0. Request shape overview (who writes what)

The harness is provider-neutral internally and has **two** wire serializers:

| Internal thing | Wire shape (Anthropic-style `llm-deepseek`) | Wire shape (OpenAI-style `llm-pi-ai`) |
|---|---|---|
| `SystemMessage` (role `system`) | `system` string, or in-history `system` message | leading `system`/`developer` message |
| `DeveloperMessage` (role `developer`) | `system`-role update message | `system`/`developer` message |
| `UserMessage` (role `user`) | `messages[].role='user'` | `messages[].role='user'` |
| `AssistantMessage` | `role:'assistant'`, `tool_use` blocks | `role:'assistant'`, `tool_calls[]` + `function.{name,arguments}` |
| `ToolResultMessage` (role `tool`) | `role:'user'` + `tool_result` block | `role:'tool'` + `tool_call_id` |
| tools | `tools: [{name, description, input_schema}]` | `tools: [{type:'function', function:{name, description, parameters}}]` |

Key files:
- `packages/llm/llm/src/types.ts` — provider-neutral `GenerateOptions` (`messages`, `system`, `tools`, `toolHistory`).
- `packages/llm/llm/src/message.ts` — roles `system | developer | user | assistant | tool`.
- `packages/llm/llm-deepseek/src/serialize.ts` — Anthropic-Messages-style body.
- `packages/llm/llm-pi-ai/src/context.ts` — pi-ai `Context` (`systemPrompt`, `messages`, `tools`).

---

## 1. Where the working directory / project root appears

### 1.1 The literal template (the exact string a proxy should match)

`packages/session/working-directory/src/index.ts:172-174`

```ts
  private contextText(session: Session): string {
    return `Current working directory: ${JSON.stringify(this.get(session))}.`
  }
```

`JSON.stringify` is why the path is **always double-quoted** and Windows backslashes arrive escaped:
`Current working directory: "D:\\workspace\\trae2api".` — the doubled backslashes are literal in the
model-visible text (and doubled again by the JSON transport). A proxy must JSON-unescape before
using the path.

Registered as a *dynamic context* named `working-directory:current`, ordered
`CONTEXT_ORDERS.WORKING_DIRECTORY = 100`, `required: true, interpolate: false`
(`packages/session/working-directory/src/index.ts:90-96`):

```ts
    ctx.systemPrompt.context({
      name: 'working-directory:current',
      order: ctx.systemPrompt.getContextOrder('WORKING_DIRECTORY'),
      required: true,
      interpolate: false,
      text: context => context.agent === undefined ? '' : this.contextText(context.agent.session),
    })
```

The `system-prompt/assemble` waterfall listener at `:97-110` unshifts/refreshes this entry so it is
present in every admitted assembly.

### 1.2 The envelope it rides in — a **user** message, not the system prompt

`packages/core/system-prompt/src/index.ts:302-318`

```ts
export function renderContextSnapshot(assembly: PromptAssembly): string {
  return joinContextSections(renderContextSections(assembly))
}
...
export function joinContextSections(sections: readonly ContextSnapshotSection[]): string {
  const body = sections.map(section => section.text).join('\n\n')
  if (body.length === 0) return ''
  return `Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n${body}`
}
```

So the on-the-wire user message begins with the fixed sentence
`Current runtime context. This snapshot supersedes earlier runtime-context snapshots.` followed by a
blank line, then `\n\n`-joined contributions. Contribution order is fixed by `CONTEXT_ORDERS`
(`packages/core/system-prompt/src/index.ts:170-179`):

```ts
const CONTEXT_ORDERS = {
  WORKING_DIRECTORY: 100,
  SANDBOX_POLICY: 110,
  APPROVAL_POLICY: 115,
  SUBAGENT_DELEGATION: 120,
  TEAM_IDENTITY: 125,
  HARNESS_SOURCE: 200,
  WEB_SURFACE: 210,
} as const
```

Snapshot construction / clearing — `packages/core/agent-loop/src/runtime-context.ts:19-20, 152-163`:

```ts
const SOURCE = 'runtime-context'
const CLEARED = 'Current runtime context: none. Earlier runtime-context snapshots no longer apply.'
...
  project(current: string, sections: readonly ContextSnapshotSection[]): UserMessage | undefined {
    if (this.retained === undefined && current.length === 0) return
    const snapshot = current.length === 0 ? CLEARED : current
```

The snapshot is committed as a **user-role** message with `source: { kind: 'runtime-context' }`
(same file, `:156-162`) and appended to the session surface at
`packages/core/agent-loop/src/agent.ts:428-431` and `:438-440`:

```ts
          if (message.source.kind === 'runtime-context') {
            if (context !== undefined && !contextAdmitted) {
              this.session.append('user/message', context, { surfaceOp: 'append' })
```

### 1.3 Other absolute paths in the same snapshot (easy false positives)

`packages/context/harness-dev-context/src/index.ts:147-164`

```ts
  ctx.systemPrompt.context({
    name: HARNESS_SOURCE,
    order: ctx.systemPrompt.getContextOrder('HARNESS_SOURCE'),
    interpolate: false,
    text: `Current DeepSeek Harness implementation checkout: ${JSON.stringify(SOURCE_ROOT)}.`,
  })
  ...
  ctx.systemPrompt.context({
    name: WEB_SURFACE,
    order: ctx.systemPrompt.getContextOrder('WEB_SURFACE'),
    interpolate: false,
    text: () => `Current DeepSeek Harness Web GUI URL: ${JSON.stringify(ctx.webApp.getAdvertisedUrl())}.`,
  })
```

The checkout path (`F:\deepseek-harness`) is **not** the workspace root. Prefer the
`Current working directory:` line. Note the GUI URL is also JSON-quoted.

Approval-policy sentence (`packages/interaction/user-approval/src/index.ts:73-75, 171`) — no path,
but a stable marker of the snapshot:

```ts
const NEVER_SENTENCE = 'Approval prompts are disabled in this session: actions that require approval are rejected automatically — do not request sandbox escalation (do not set `sandbox_permissions`).'
const ASK_SENTENCE = 'Approval policy: ask. Operations that require approval may ask through the configured answerers; without an available answerer, the request fails closed.'
```

### 1.4 The workspace root also appears in the sandbox-policy sentence (workspace-write only)

`packages/sandbox/sandbox-policy/src/index.ts:42-49`

```ts
function renderPolicyContext(policy: SandboxExecutionPolicy): string {
  switch (policy.mode) {
    case 'read-only':
      return 'Current DSH file policy: read-only. Any available operation enforced by the DSH file sandbox cannot modify files in the standing mode. Do not refuse a required modification from this policy alone: try an available tool normally and follow any denial and escalation guidance it returns.'
    case 'workspace-write':
      return `Current DSH file policy: workspace-write. Any available operation enforced by the DSH file sandbox may modify files under the session workspace: ${JSON.stringify(policy.workspaceRoot)}. Some platform temporary areas may also be writable.`
    case 'danger-full-access':
      return 'Current DSH file policy: danger-full-access. The DSH file sandbox does not restrict file modifications by available operations.'
```

`read-only` and `danger-full-access` emit **no path at all**, so this line is an unreliable root
source. Use `Current working directory:`.

### 1.5 Working-directory *changes* are separate injected user messages

`packages/session/working-directory/src/index.ts:193-200`

```ts
    const notice = createUserMessage({
      content: [{
        type: 'text',
        text: recovered
          ? `The working directory ${JSON.stringify(previous)} is unavailable. The working directory is now ${JSON.stringify(directory)}.`
          : `The working directory changed from ${JSON.stringify(previous)} to ${JSON.stringify(directory)}.`,
      }],
      source: { kind: 'working-directory' },
    })
```

A `cd` therefore emits **two** JSON-quoted absolute paths in one user message; the second is current.

### 1.6 Test snapshots confirming the exact rendered form

- `packages/session/working-directory/tests/working-directory.spec.ts:146`
  ```ts
  expect(renderContextSnapshot(assembly)).toContain(`Current working directory: ${JSON.stringify(f.root)}.`)
  ```
- `packages/subagent/subagent/tests/continuation-messages-adapter.spec.ts:91-92`
  ```ts
  text: 'Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n'
    + `Current working directory: ${JSON.stringify(process.cwd())}.`,
  ```
- `packages/experimental/claude-code-mods/tests/bridge.spec.ts:541` — same shape.

### 1.7 The system prompt itself carries no cwd

The system prompt is ordered *sections* joined by `\n\n` (`renderPrompt`,
`packages/core/system-prompt/src/index.ts:290-295`). The section-order table (`:131-165`) has no
environment/cwd entry; the only path-bearing sections are `HARNESS_SOURCE: 10000` and
`WEB_SURFACE: 10100`, whose *text* is deliberately path-free
(`packages/context/harness-dev-context/src/index.ts:36-51`) — their values travel only in the
runtime-context snapshot. The harness identity section is
`packages/core/system-prompt/src/index.ts:450-455`:

```ts
      this.section({
        name: 'harness:identity',
        order: this.getSectionOrder('HARNESS_IDENTITY'),
        text: 'You are an AI agent powered by DeepSeek Harness.',
      })
```

**Conclusion for Q1:** the cwd lives in the **first user message** of a turn, inside the
runtime-context snapshot, as `Current working directory: "<abs path>".`

---

## 2. How file contents / open files / editor state are embedded

### 2.1 There is no "open files" / active-editor payload

Grepping `packages/` for `openFile`, `activeEditor`, "open file", "editor state" finds **only
client-side UI concepts**: `packages/api/workspace-files/src/client/provider.ts:22` ("One
`ChangeFeed` serves every open file of the Client" — a file-watch feed, not prompt content) and
`openFileApplication` in `packages/api/session-controller/src/types.ts`. Nothing pushes an active
editor buffer, cursor, or selection into the LLM request. **A proxy will not find "currently open
file" state in a DSH request.**

### 2.2 User-referenced files: `@`-tokens in plain user text

`packages/context/file-reference/src/index.ts:17`

```ts
export const FILE_REFERENCE_PROMPT = 'Tokens prefixed with @ are paths the user explicitly referenced. Relative paths resolve from the workspace root; absolute paths identify files or directories on the host. A trailing slash marks a directory: list it when its contents matter. Anything else is a file: use the read tool when its contents are needed, and do not claim to have inspected it before reading. @"..." quotes a path containing spaces.'
```

Registered as system-prompt section `context:file-reference`
(`packages/context/file-reference-local/src/index.ts:71-75`). Mention grammar
(`packages/context/file-reference/src/grammar.ts:45-54`):

```ts
export function formatFileMention(
  candidate: FileReferenceCandidate,
  preserveQuote: boolean,
): string | undefined {
  const path = candidate.kind === 'directory' ? `${candidate.path}/` : candidate.path
  if (/[\u0000-\u001f\u007f-\u009f"]/u.test(path)) return undefined
  const quoted = preserveQuote || /\s/u.test(path)
  if (!quoted) return `@${path}`
  if (candidate.kind === 'directory') return `@"${path}`
  return `@"${path}"`
}
```

A referenced file is therefore just `@path` / `@"path with spaces"` inside the user's message text;
trailing `/` means directory.

### 2.3 Uploaded file attachments: handle text, never content

`packages/llm/llm/src/types.ts:91-102`

```ts
/**
 * A durable verbatim file reference, valid in user content. Files never reach
 * a provider natively: request assembly projects every occurrence to
 * deterministic handle text (name, byte size, and the read-only saved path),
 * so adapters and providers see text in its place while the durable log keeps
 * the structured reference for presentation and authorization.
 */
export interface FileBlock {
  type: 'file'
  attachment: FileAttachmentRef
}
```

`packages/llm/llm/src/content.ts:151-158`

```ts
export function fileHandleText(ref: FileAttachmentRef, readonlyPath: string | undefined): string {
  const digest = String(ref.attachmentId).slice('sha256:'.length, 'sha256:'.length + 8)
  const identity = `File ${quoted(ref.name)} (${ref.bytes} bytes, sha256:${digest})`
  if (readonlyPath === undefined) {
    return `[${identity} was uploaded, but the current execution environment cannot access a readable path. Report that limitation if its contents are needed; do not claim to have read it.]`
  }
  return `[${identity}: verbatim read-only copy saved at ${quoted(readonlyPath)}. Read that path with your file tools when its contents are needed; copy it to a writable location before modifying it. When delegating file work, include this saved path in the delegation prompt; only subagents sharing this execution environment can read it.]`
}
```

Images ship pixels plus a text prefix (`packages/llm/llm/src/content.ts:91-100, 65-69`):

```ts
  const preview = `Image ${imageIdentity(ref)}; request preview ${version.width}x${version.height}px.`
...
  return ` Normalized copy (read-only; may be resized or re-encoded): ${quoted(access.readonlyPath)} (${ref.width}x${ref.height}px, ${ref.mediaType}).`
    + ' Source dimensions, format, and byte size may differ.'
    + ` Copy to a writable path ending in ${extension(ref.mediaType)} before editing.`
```

Omitted variants: `[image omitted to fit request image limits; …]` (`content.ts:108-116`) and
`[image omitted because this model accepts text only; attachment sha256:xxxxxxxx]` (`content.ts:76-79`).
File projection is unconditional on every request (`projectFilesToText`, `content.ts:185-208`, wired
at `packages/llm/llm/src/index.ts:1097-1099`).

### 2.4 Tool results carrying file content: the `<path>` / `<type>` / `<content>` envelope

This is the dominant way real file contents reach the model. `read`
(`packages/fs/tool-fs/src/read-render.ts:152-170`):

```ts
export function formatReadOutput(displayPath: string, outcome: FileReadOutcome): string {
  ...
  const body = outcome.lines.length > 0
    ? `${outcome.lines.map(line => `${line.number}: ${line.text}`).join('\n')}\n\n${footer}`
    : footer
  return `<path>${displayPath}</path>
<type>file</type>
<content>
 ${body}
</content>`
}
```

Literal footers (`read-render.ts:154-161`):
`(Output capped. Showing lines A-B. Use offset=B+1 to continue.)`,
`(Showing lines A-B of N. Use offset=B+1 to continue.)`,
`(End of file - total N lines)`. Each line is `N: <text>`; over-long lines end
`... (line truncated to 2000 chars)` (`read-render.ts:70`).

`write` (`packages/fs/tool-fs/src/write.ts:36-43`):

```ts
  return `<path>${displayPath}</path>
<type>file</type>
<content>
 ${verb} file
</content>`
```

`edit` (`packages/fs/tool-fs/src/edit.ts:65-69`) — plain prose, no XML:

```ts
  return replaceAll
    ? `The file ${displayPath} has been updated. All occurrences were successfully replaced.`
    : `The file ${displayPath} has been updated successfully.`
```

`read_image` (`packages/fs/tool-fs/src/read-image.ts:169-186`):
`<path>…</path>\n<type>image</type>\n<content>\n <mediaType> image, WxH px, N bytes…\n</content>`.

`grep` (`packages/fs/tool-fs-search/src/grep.ts:191-225`) — grouped, no XML:

```ts
  const sections: string[] = []
  for (const [path, group] of byFile) {
    sections.push(`${path}\n${group.map(m => `Line ${m.lineNumber}: ${m.line}`).join('\n')}`)
  }
  ...
  const header = retained.truncated
    ? `Found ${retained.kept} of ${retained.seen} matches`
    : `Found ${retained.seen} ${matchNoun(retained.seen)}`
```

### 2.5 AGENTS.md / instruction files: `<system-reminder>` frames in user messages

`packages/context/agent-instructions/src/render.ts:16-17, 304-316`

```ts
const SYSTEM_REMINDER_OPEN = '<system-reminder>'
const SYSTEM_REMINDER_CLOSE = '</system-reminder>'
...
function buildInstructionText(...): string {
  const marker = markerText(maxBytes, omitted, truncated)
  const body = [marker, style.intro, ...files.map(file => style.section(file))].filter(block => block.length > 0)
  // This producer owns the complete <system-reminder> frame. Session adds no
  // wrapper; see Derived history in packages/core/session/README.md.
  return [SYSTEM_REMINDER_OPEN, escapeInstructionFrameBody(body.join('\n\n')), SYSTEM_REMINDER_CLOSE].join('\n')
}
```

Inner literals: `Instructions from: <displayPath>` (`render.ts:91-93`),
`Additional instructions from: <displayPath>` plus
`These instructions apply to work under \`<scope>\`.` (`render.ts:220-234`),
`Updated instructions from: <path>` (`render.ts:254-260`), `Instructions removed: <path>` (`:252`),
and the budget marker
`Workspace instruction budget N bytes: omitted a.md, b.md; truncated c.md from X to Y bytes`
(`:292-302`). A literal `</system-reminder>` inside content is escaped to `<\/system-reminder>`
(`render.ts:87-89`).

### 2.6 Skill catalogs and loaded skills

`packages/skill/tool-skill/src/index.ts:256-279` (update variant at `:281-313`):

```ts
      text: [
        '<system-reminder>',
        'A skill is a reusable set of task-specific instructions. The following skills are available in this session:',
        '',
        '<available_skills>',
        ...renderCatalogEntries(entries),
        '</available_skills>',
        ...
        '</system-reminder>',
      ].join('\n'),
```

Loaded skill body (`packages/skill/skill/src/index.ts:170-183`):
`<skill_content name="…">`, `<skill_resources>`, `Base directory for this skill: <path>`,
`<skill_instructions>…</skill_instructions></skill_content>`.

### 2.7 Spilled / oversized tool-output locators

`packages/spill/spill-policy/src/notice.ts:7, 21-24`

```ts
const LOCATION = ' Full formatted result stored at: '
...
  return `${OPEN}${describeOmitted(omitted, 'bytes')}${imageNotice}${LOCATION}${ref.locator}${GUIDANCE_SEPARATOR}${ref.retrievalHint}${CLOSE}`
```

i.e. `(<N> bytes omitted. Full formatted result stored at: <path>. <hint>)`. The grep variant
spells it `Full grep result stored at: <path>. <hint>`
(`packages/fs/tool-fs-search/src/grep.ts:222`); bash truncation spells it
`[output truncated; full output: <path>]` (`packages/shell/tool-bash/src/render.ts:14`).

### 2.8 Sandbox denial markers (no paths)

`packages/sandbox/sandbox/src/escalation.ts:71-86`

```ts
export function sandboxDenialMarker(mode: SandboxMode): string {
  return `[sandbox: file access denied under ${mode} mode]`
}
export function escalationHintMarker(subject: string): string {
  return `[sandbox: escalation available — retry this exact ${subject} once with sandbox_permissions (the narrowest wider mode that suffices) + justification; the approval prompt asks the user]`
}
```

---

## 3. Tool definitions and tool results: roles and field names

### 3.1 Internal provider-neutral model — `packages/llm/llm/src/message.ts`

Roles (`:150-196`):

```ts
export interface SystemMessage extends MessageBase { readonly role: 'system'; ... }
export interface DeveloperMessage extends MessageBase { readonly role: 'developer' }
export interface UserMessage extends MessageBase { readonly role: 'user' }
export interface AssistantMessage extends MessageBase { readonly role: 'assistant'; readonly source: ModelMessageSource }
export interface ToolResultMessage extends MessageBase {
  readonly role: 'tool'
  readonly source: ToolMessageSource
  readonly toolCallId: ToolCallId
  readonly isError?: boolean
}
```

Tool-call block (`packages/llm/llm/src/types.ts:104-112`):

```ts
export interface ToolCallBlock {
  type: 'tool-call'
  id: ToolCallId
  name: string
  arguments: string   // Raw JSON string as produced by the model
}
```

Tool schema (`packages/llm/llm/src/types.ts:491-502`):

```ts
export interface ToolSchema {
  deferLoading?: true
  name: string
  description: string
  parameters: Record<string, unknown>   // JSON Schema object for the arguments
}
```

Tool history (`types.ts:516-526`): `{ tools: ToolSchema[]; updates: [{ messageId, additions }] }`.

Tool results are created by the loop (`packages/core/agent-loop/src/tool-calls.ts:277-281`):

```ts
  const message = createToolResultMessage({
    callId: block.id,
    content: result.content,
    isError: result.isError,
  })
```

### 3.2 The loop builds `GenerateOptions` with a `tools` array

`packages/core/agent-loop/src/agent.ts:695-702`

```ts
    const request = markAgentLoopRequest(Object.freeze({
      ...header.config,
      messages: boundaryMessages,
      toolHistory: session.toolHistory(),
      ...header.tools !== undefined ? { tools: header.tools } : {},
      sessionId: this.session.id,
      signal,
    }))
```

Tools come from the system-prompt assembly, which collects, orders, and `structuredClone`-detaches
them (`packages/core/system-prompt/src/index.ts:638-651, 674`). DSH tool names are terse lowercase:
`read`, `write`, `edit`, `glob`, `grep`, `bash`, `pwsh`, `read_image`, `job_output`, `job_kill`,
`web_search`, `web_fetch`, `lsp`, `todo`, `create_goal`, `update_goal`, `get_goal`, `subagent`,
`workflow`, `present`, `skill`, `report`, `ask_user_question`, `schedule_*`, `interrupt_agent`,
`send_message`, `list_agents`, `pwd`/`cwd` (`packages/session/tool-working-directory/src/index.ts:22`).

Parameter naming is DSH's own JSON-Schema dialect, not raw OpenAI —
`packages/fs/tool-fs/src/read.ts:80-84`:

```ts
      file_path: { type: 'string', required: true, description: 'Path to read, resolved by the filesystem backend.' },
      offset: { type: 'number', description: '1-based first line to return. Defaults to 1.' },
      limit: { type: 'number', description: `Maximum number of lines to return. Defaults to ${caps.limit}.` },
```

`required` is a **sibling key on each property**, not a `required: [...]` array. That is the
`packages/core/tools` `defineTool` dialect.

### 3.3 Anthropic-style wire (`llm-deepseek`)

`packages/llm/llm-deepseek/src/wire-types.ts:18-41`

```ts
export type WireMessage = {
  role: 'user' | 'assistant' | 'system'
  content: WireBlock[]
}
export type WireRequest = {
  model: string
  stream: true
  max_tokens: number
  messages: WireMessage[]
  system?: string
  thinking: { type: 'enabled' | 'disabled' }
  output_config?: { effort: 'low' | 'high' | 'max' }
  temperature?: number
  stop_sequences?: string[]
  tools?: {
    name: string
    description: string
    input_schema: Record<string, unknown>
    defer_loading?: true
  }[]
}
```

`packages/llm/llm-deepseek/src/serialize.ts:160-167`

```ts
    ...options.tools === undefined ? {} : {
      tools: options.tools.map(tool => ({
        name: tool.name,
        description: tool.description,
        input_schema: tool.parameters,
        ...tool.deferLoading === true ? { defer_loading: true as const } : {},
      })),
    },
```

Tool results (`serialize.ts:118-129, 125`) — mapped onto **`role: 'user'`**:

```ts
    const content: WireBlock[] = message.role === 'assistant'
      ? assistant(message, options.model, onReplayDegrade)
      : message.role === 'tool'
        ? [{ type: 'tool_result', tool_use_id: message.toolCallId, content: input(message.content), ...message.isError === undefined ? {} : { is_error: message.isError } }]
        : message.content.flatMap((block): WireBlock[] => input([block]))
    ...
    const wireRole = message.role === 'tool' ? 'user' : message.role
```

Assistant tool call (`serialize.ts:35`):
`case 'tool-call': return { type: 'tool_use', id: block.id, name: block.name, input: toolInput(block.arguments) }`.

Developer messages become `system`-role updates carrying `tool_addition` / `tool_removal` blocks
(`serialize.ts:91-100`; `wire-types.ts:12`).

### 3.4 OpenAI-shaped wire (`llm-pi-ai` → `openai-completions`)

`packages/llm/llm-pi-ai/src/context.ts:131-137, 161-168`

```ts
function piTool(tool: NonNullable<GenerateOptions['tools']>[number]): PiTool {
  return { name: tool.name, description: tool.description, parameters: tool.parameters }
}
...
function piContext(systemPrompt: string | undefined, options: GenerateOptions, messages: PiMessage[]): PiContext {
  const tools = toolsOf(options)
  return {
    ...systemPrompt !== undefined ? { systemPrompt } : {},
    messages,
    ...tools !== undefined && tools.length > 0 ? { tools } : {},
  }
}
```

`toolsOf` **drops deferred tools** (`context.ts:135-137`):
`return options.tools?.filter(tool => !tool.deferLoading).map(piTool)`.

Tool results become pi-ai `toolResult` messages (`context.ts:31-47`):

```ts
  return {
    role: 'toolResult',
    toolCallId: message.toolCallId,
    toolName: toolNames.get(message.toolCallId) ?? 'unknown',
    content: typeof content === 'string'
      ? [{ type: 'text', text: content || '(no output)' }]
      : content,
    isError: message.isError ?? false,
    timestamp: 0,
  }
```

pi-ai then serializes into the OpenAI body
(`node_modules/.pnpm/@earendil-works+pi-ai@1.1.0_*/node_modules/@earendil-works/pi-ai/dist/api/openai-completions.js`):

```js
// 1080-1086 — tool result
const toolResultMsg = { role: "tool", content: sanitizeSurrogates(toolResultText), tool_call_id: toolMsg.toolCallId };
if (compat.requiresToolResultName && toolMsg.toolName) { toolResultMsg.name = toolMsg.toolName; }
```

```js
// 1020-1039 — assistant tool call
assistantMsg.tool_calls = toolCalls.map((tc) => ({ id: tc.id, type: "function", function: { name: tc.name, arguments: JSON.stringify(tc.arguments) } }));
```

```js
// 599-600
if (transcriptTools.requestTools.length > 0) { params.tools = convertTools(transcriptTools.requestTools, compat); }
```

```js
// 1150-1159 — tool declaration
return { type: "function", function: { name: tool.name, description: tool.description, parameters: getJsonSchemaToolParameters(tool, strict), ...(compat.supportsStrictMode !== false && { strict: strict ?? false }) } };
```

```js
// 898-921 — system / developer role
const instructionRole = model.reasoning && compat.supportsDeveloperRole ? "developer" : "system";
...
params.push({ role: instructionRole, content: sanitizeSurrogates(text) });
```

DSH→pi-ai conversion **flattens** user/tool text to a plain string when no images are present
(`context.ts:96`, `:254`), so an OpenAI-route tool result is typically
`{ "role": "tool", "content": "<plain text>", "tool_call_id": "…" }`.

Mid-conversation system updates reach history only on routes declaring
`systemPromptUpdate: 'in-history'` (`packages/llm/llm/src/types.ts:408-425`); otherwise the leading
system messages are folded into `systemPrompt` (`context.ts:148-158`).

### 3.5 Tool updates in history (deferred tools)

`packages/llm/llm/src/content.ts:424-436`

```ts
export function projectToolUpdates(
  messages, tools, toolUpdate, history,
): ProjectedToolUpdates {
  if (toolUpdate === undefined) {
    // Unsupported routes need immediately available tools and no update messages.
    let immediateTools = tools
    if (tools?.some(tool => tool.deferLoading === true)) {
      immediateTools = tools.map(({ deferLoading: _loading, ...tool }) => tool)
    }
    return { messages: withoutDeveloperMessages(messages), tools: immediateTools }
  }
```

---

## 4. Absolute-path formatting conventions (Windows vs POSIX)

DSH is **platform-native**: it does not normalise paths to POSIX for the model. What the model sees
is the filesystem provider's execution-world spelling.

### 4.1 The local fs provider

`packages/fs/fs-local/src/fsio.ts:139-151`

```ts
/**
 * Anchor a path using native drive semantics and POSIX physical parent traversal.
 * @param cwd - provider base directory for relative paths.
 * @param path - non-empty requested path.
 * @returns absolute display spelling shared by target resolution and no-follow metadata.
 */
export function localDisplayPath(cwd: string, path: string): string {
  const absoluteCwd = isAbsolute(cwd) ? cwd : `${process.cwd()}${sep}${cwd}`
  const raw = isAbsolute(path) ? path : `${absoluteCwd}${sep}${path}`
  const physicalSpelling = /(?:^|[\\/])\.\.(?:[\\/]|$)/u.test(raw) ? raw : resolve(cwd, path)
  return process.platform === 'win32' ? resolve(cwd, path) : physicalSpelling
}
```

Windows → `C:\Users\...\repo\src\index.ts`; POSIX → `/home/user/repo/src/index.ts`. `displayPath` is
the model-facing spelling; `targetKey` is the realpath identity (`fsio.ts:106-112`) and
`processPath()` returns the targetKey (`packages/fs/fs-local/src/index.ts:140-142`). Symlinks are
resolved for I/O but display keeps the requested spelling (`fsio.ts:161-166`).

### 4.2 How Windows paths get JSON-escaped

Because `contextText` uses `JSON.stringify`, a Windows cwd appears in the raw JSON body as
`"Current working directory: \"D:\\\\workspace\\\\trae2api\"."`; the model-visible text is
`Current working directory: "D:\\workspace\\trae2api".` — backslashes doubled **in the text** and
doubled again by JSON. This is the single most important formatting gotcha for a proxy.

### 4.3 Relative display forms

- Instruction paths are **project-root-relative using the platform separator**:
  `relativeDisplay(root, path) = escapeProjectDisplayPath(relative(root, path))`
  (`packages/context/agent-instructions/src/files.ts:291-293`), and `escapeProjectDisplayPath` uses
  `sep` (`render.ts:173-177`).
- grep/glob paths inside the workdir become **workdir-relative**; outside paths stay absolute
  (`packages/fs/tool-fs-search/src/search-core.ts:301-307`):

```ts
export function toWorkdirRelative(path: string, workdir: string): string {
  if (!isAbsolute(path)) return path
  const rel = relative(workdir, path)
  if (rel.length === 0) return '.'
  if (rel === '..' || rel.startsWith(`..${sep}`)) return path
  return rel
}
```

- LSP renders the workspace root itself as `.` (`packages/lsp/tool-lsp/tests/render.spec.ts:61`).
- UI display helpers accept both separators and abbreviate only POSIX homes to `~`
  (`packages/util/workspace-path/src/index.ts:8-10, 42-50`); `abbreviateHomePath` bails out on
  Windows-style paths, so `~` never appears for Windows paths.

### 4.4 The workspace-root "address" convention

`dsh-resource://file/session/<sessionId>/<path>` and `dsh-resource://file/absolute/<path>`, always
`/`-separated (`packages/api/workspace-files/src/client/provider.ts:6-14`,
`packages/util/workspace-path/src/file-address.ts:32`). These are Client↔Host wire addresses, not
model prompt content; `fileAddressFor` normalises `\` → `/` first
(`packages/util/workspace-path/src/index.ts:92-99`).

### 4.5 Session header cwd validation

`packages/core/session/src/index.ts:112-116` — the header cwd must be absolute per Node's
`isAbsolute`, so it is platform-native.

---

## 5. Is there a `tools` array, and are names/params OpenAI-style?

**Yes to `tools`; "OpenAI-style" only on the OpenAI route.**

- `GenerateOptions.tools?: ToolSchema[]` — "Tool schemas (adapters map to the provider's `tools`
  field)" (`packages/llm/llm/src/types.ts:547-548`). The loop always populates it when non-empty
  (`packages/core/agent-loop/src/agent.ts:629, 699`).
- **Anthropic/DeepSeek route**: `tools: [{ name, description, input_schema, defer_loading? }]`
  (`packages/llm/llm-deepseek/src/serialize.ts:160-167`) — `input_schema`, **not** `parameters`,
  and no `type: 'function'` wrapper.
- **OpenAI route**: `tools: [{ type: 'function', function: { name, description, parameters, strict } }]`
  (pi-ai `openai-completions.js:1150-1159`), plus optional `tool_choice` (`:612-614`) and
  `tool_stream` for zai (`:601-603`).
- Tool **names** are DSH's own terse snake_case (`read`/`write`/`edit`/`bash`/`pwsh`/`glob`/`grep`/
  `read_image`/`job_output`/`todo`/`goal`/`subagent`/`present`…), **not** Anthropic's
  `str_replace_editor`/`computer` naming.
- Tool **parameters** use the `defineTool` dialect (`type`/`required`/`description` per property).
  pi-ai converts that into a real JSON Schema for OpenAI
  (`getJsonSchemaToolParameters(tool, strict)`); the DeepSeek route passes `tool.parameters`
  through verbatim as `input_schema`, so a proxy sees the DSH dialect there.
- Deferred tools (`deferLoading`) are **omitted** from the OpenAI route's initial `tools`
  (`packages/llm/llm-pi-ai/src/context.ts:135-137`) and appear later as
  `{role:'system', toolsAdded:[…]}` / `toolsRemoved:[{name}]` messages (`context.ts:194-200`).
  `packages/llm/llm-pi-ai/src/adapter.ts:372-378` may prepend an
  `ANTHROPIC_TOOL_UPDATE_PLACEHOLDER` tool when every declared tool is deferred on an
  anthropic-messages in-history route.

---

## Regex / marker list for a proxy

Apply in order; run these on each message's **decoded** text (JSON-unescape first, or the Windows
backslashes will read as doubled).

### A. Workspace root (authoritative)

```
/Current working directory:\s*"([^"]+)"\./
```

Group 1 is the absolute, platform-native cwd. If several match, prefer the one inside the
runtime-context snapshot; otherwise fall back to the last `The working directory changed from "…" to "…".`
notice.

### B. Runtime-context envelope (to segment the user message)

```
/Current runtime context\. This snapshot supersedes earlier runtime-context snapshots\.\n\n/
/Current runtime context: none\. Earlier runtime-context snapshots no longer apply\./
```

The snapshot is always the **first** user message of a turn. Contributions inside it are joined by
`\n\n` in the fixed order: cwd → sandbox policy → approval policy → subagent delegation → team
identity → harness checkout → GUI URL.

### C. Secondary path sources (beware false positives)

```
/Current DSH file policy:\s*(read-only|workspace-write|danger-full-access)\./
/under the session workspace:\s*"([^"]+)"\./                       # workspace-write mode only
/Current DeepSeek Harness implementation checkout:\s*"([^"]+)"\./  # NOT the workspace
/Current DeepSeek Harness Web GUI URL:\s*"([^"]+)"\./
/The working directory (?:changed from "([^"]+)" to|is unavailable\. The working directory is now) "([^"]+)"/
/Approval prompts are disabled in this session:/
```

### D. Referenced files (user `@`-mentions)

```
/(?:^|\s)@("(?:[^"\n]*)"?|[^\s@]+)/g
```

Unquoted `@path` = file; `@"path with spaces"` = quoted file; a trailing `/` (before the closing
quote in the quoted form) = directory. These live only in `role: 'user'` message text. There is
**no** structured open-editor/selection payload — do not look for one.

### E. Attachments / saved copies

```
/\[File "([^"]+)" \((\d+) bytes, sha256:[0-9a-f]{8}\): verbatim read-only copy saved at "([^"]+)"\./
/\[Image ("[^"]+"|[^;\]]+); request preview \d+x\d+px\./
/Normalized copy \(read-only; may be resized or re-encoded\): "([^"]+)" \(/
/\[image omitted to fit request image limits;/
/\[image omitted because this model accepts text only; attachment sha256:[0-9a-f]{8}\]/
```

### F. File-content envelopes in tool results

```
/<path>([^<]+)<\/path>\s*<type>(file|image)<\/type>\s*<content>/
/<content>[\s\S]*?<\/content>/
/\(End of file - total (\d+) lines\)/
/\(Showing lines (\d+)-(\d+) of (\d+)\. Use offset=(\d+) to continue\.\)/
/\(Output capped\. Showing lines (\d+)-(\d+)\. Use offset=(\d+) to continue\.\)/
/\.\.\. \(line truncated to (\d+) chars\)/
/The file (.+?) has been updated(?: successfully|\. All occurrences were successfully replaced)\./
/^Line (\d+): (.*)$/m                       # grep body rows
/^Found (\d+)(?: of (\d+))? matches?$/m
```

### G. System-reminder frames (instructions, skill catalogs)

```
/<system-reminder>[\s\S]*?<\/system-reminder>/
/(?:Instructions|Additional instructions|Updated instructions) from:\s*(.+)/
/Instructions removed:\s*(.+)/
/These instructions apply to work under `([^`]+)`\./
/Workspace instruction budget (\d+) bytes:/
/<available_skills>[\s\S]*?<\/available_skills>/
/<skill_content name="([^"]+)">[\s\S]*?<\/skill_content>/
/Base directory for this skill:\s*(.+)/
```

### H. Spill / truncation locators

```
/Full formatted result stored at:\s*(\S+)\./
/Full grep result stored at:\s*(\S+)\./
/\[output truncated; full output: ([^\]]+)\]/
```

### I. Tool-result markers (useful for classifying messages)

```
/\[exit code: (-?\d+)\]/
/\[stderr\]/
/\[sandbox: file access denied under (read-only|workspace-write|danger-full-access) mode\]/
/\[sandbox: escalation available — retry this exact (command|operation) once/
/\[timed out after (\d+)ms\]/
/\[stopped: (.+)\]/
/\[killed by signal: (.+)\]/
/\[still running after (\d+)ms; moved to background job ([^\]]+)\]/
```

### J. Tool-shape detection (which wire protocol am I looking at?)

- **OpenAI-shaped**: `tools[].type === 'function'` and `tools[].function.parameters`; tool results
  are `{role:'tool', tool_call_id}`; assistant carries `tool_calls[].function.{name,arguments}`
  with `arguments` as a **JSON string**.
- **Anthropic-shaped**: `tools[].input_schema`; tool results are `role:'user'` with
  `content[].type === 'tool_result'` and `tool_use_id`; assistant carries
  `content[].type === 'tool_use'` with `input` as an **object**.
- **DSH tells either way**: a message containing
  `You are an AI agent powered by DeepSeek Harness.`
  (`packages/core/system-prompt/src/index.ts:453`) or the `Current runtime context.` snapshot
  header; and tool names `read`/`write`/`edit`/`bash`/`pwsh`/`glob`/`grep`/`read_image`/`todo`/
  `goal`/`subagent`/`present`.

### K. Extraction algorithm (recommended)

1. Find the first `role: 'user'` message whose decoded text starts with
   `Current runtime context. This snapshot supersedes earlier runtime-context snapshots.`
2. Within it, apply pattern **A** → workspace root. Fall back to the last pattern-C cwd notice.
3. Scan all user-role messages for pattern **D** → the set of user-referenced files.
4. Scan tool-role (or `tool_result`-carrying) messages for patterns **F**/**H** → files whose
   contents were actually in context, plus any spill paths.
5. Never treat `Current DeepSeek Harness implementation checkout:` or `Web GUI URL:` values as the
   workspace root.
