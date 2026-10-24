# Trae 本地客户端工具清单 + 与我们工具的映射

来源：市场插件 VSIX 内的原生 sidecar `ai-agent.exe`（385MB，与桌面版 ai_agent.dll 同源）。
Rust 源码路径 `apps/icube_server_rs/modules/ai-agent/src/domain/toolcall/tools/*.rs` 在二进制里
以字符串残留形式完整保留 —— 这是最权威的工具清单。

## 1. 完整工具模块清单（115 个，按功能分组）

**文件读取**
- `view_file` / `view_files` / `view_folder` / `view_image` / `read` / `read_enoent`
- 参数（view_file 残留）：`file_path`, `start_line`, `end_line`, `content_hash`

**文件写入/编辑**
- `write` / `write_to_file` / `write_refactor_output` / `write_to_product_document`
- `edit` / `edit_file_update` / `edit_file_update_fc` / `edit_file_fast_apply`
- `edit_file_rename` / `edit_file_search_replace` / `edit_parent_dir`
- `edit_product_document_update` / `edit_product_document_update_fc` / `edit_product_document_fast_apply`
- `multi_edit` / `notebook_edit` / `apply_patch` / `show_diff` / `show_diff_fc`
- 参数残留：`file_path`, `old_str`, `new_str`, `old_string`, `new_string`, `new_source`,
  `new_content`, `old_content`, `changes`, `edit_change`, `original_file`, `updated_file`,
  `target_dir`, `rename_to`

**命令执行**
- `run_command` / `shell_tool` / `check_command_status` / `check_command_status_v3`
- `send_to_command` / `stop_command` / `monitor_command` / `monitor_stdout`
- `codex_exec_command` / `codex_write_stdin` / `windows_cmd_guard`
- 参数残留：`command`, `command_id`, `cwd`, `run_in_background`, `timeout`,
  `exit_code`, `stdout`, `status`, `timed_out_moved_to_background`
- 安全：sidecar 有 enterprise security policy 拦截（"command has been blocked by enterprise
  security policy"）、沙箱（`sandbox_restricted_paths_`, `sandbox_model_escape`）、
  `requires_approval` 类审批（`request_authorization`, `approval_check`）

**搜索**
- `search_by_regex` / `search_codebase` / `file_search` / `glob` / `grep` / `knowledge`
- 参数残留：`pattern`, `dir_path`, `query`, `num`

**任务/规划**
- `todo_write` / `task_create` / `task_get` / `task_list` / `task_update` / `task_tool`
- `list_task` / `create_goal` / `get_goal` / `update_goal` / `update_plan` / `enter_plan_mode`
- `run_agent` / `run_custom_tool` / `workflow` / `schedule` / `background_task`

**外部集成**
- `web_search` / `web_fetch` / `run_mcp` / `read_mcp_resource` / `list_mcp_resources`
  / `list_mcp_resource_templates`
- `supabase_get_project` / `supabase_get_tables` / `supabase_apply_migration`
- `deploy_to_remote` / `open_preview` / `get_preview_console_logs`
- `generate_image` / `generate_video` / `generate_video_input`
- `skill` / `skill_recommend` / `skill_sync`

**交互/收尾**
- `reply_user` / `response_to_user` / `notify_user` / `ask_user_question` / `request_user_input`
- `finish` / `agent_finish` / `complete` / `no_need_execute` / `unknown`
- `delete_file` / `safe_rm` / `get_diagnostics` / `manage_core_memory`
- `exec`（V8 沙箱，可 `await tools.<name>(args)` 链式调用，见 ALL_TOOLS 文档）

## 2. 模型侧看到的名字（来自工具注册表字符串，桌面/插件一致）

```
view_file(s) Read check_command_status edit_file_update search_by_regex show_diff show_diff_fc
create_file write_to_file edit_file edit_file_search_replace edit_file_update_fc
edit_file_fast_apply edit_file_rewrite edit_file_rename apply_patch Write Edit MultiEdit
NotebookEdit write_to_product_document edit_product_document_* delete_file DeleteFile
SearchReplace run_command run_mcp view_folder list_dir todo_list web_search
```

注意：注册表里同时有**原始名**和**OpenAI 风格别名**（`Read`/`Write`/`Edit`/`MultiEdit`/
`NotebookEdit`/`DeleteFile`）—— 说明 sidecar 会根据模型的 native_function_call 能力切换
命名风格（`Write`/`Edit` 是 Claude Code 风格别名）。

## 3. 与我们（通用 agent 客户端）工具的映射表

通用客户端（Cline / Claude Code / Cherry 等）常用工具名 → Trae 工具：

| 通用工具 (client) | Trae 工具 | 参数映射 |
|---|---|---|
| `read_file` | `view_file` / `read` | `path`→`file_path`（+`start_line`/`end_line`） |
| `list_files` / `list_dir` | `view_folder` / `ls` / `list_dir` | `path`→`dir_path` |
| `write_to_file` | `write_to_file` / `Write` | `path`→`file_path`, `content`→`new_content` |
| `replace_in_file` | `edit_file_search_replace` / `Edit` | `path`, `diff`→`old_str`/`new_str` |
| `search_files` | `search_by_regex` / `grep` | `regex`→`pattern`, `file_pattern`→`dir_path` |
| `execute_command` | `run_command` / `shell_tool` | `command`, `cwd`, `requires_approval`→审批 |
| `web_search` | `web_search` | `query` |
| `use_mcp_tool` | `run_mcp` | server/tool/args |
| `attempt_completion` | `finish` / `reply_user` | result |
| `ask_followup_question` | `ask_user_question` / `request_user_input` | question |
| （无对等） | `todo_write` / `task_*` / `create_goal` / `update_plan` | 内部规划，代理可忽略或转述 |
| （无对等） | `generate_image/video` / `supabase_*` / `deploy_to_remote` | 特殊能力 |

## 4. 对 trae2api 的落地方案（基于本清单）

两条互补路径：

**A. 出站翻译（已实现）**：模型输出的 `<|FunctionCallBegin|>` 调用 → 转成 OpenAI
`tool_calls`。若客户端声明了对应工具（如 `read_file`），按上表把 Trae 名映射成客户端名、
把 `file_path` 映射成 `path`，客户端就能执行。

**B. 代理本地执行（bridge，已开始实现 `trae2api/tools.py`）**：若调用的是
**客户端未声明**的 Trae 内置工具（这是截图报错的场景），代理按上表**自己在本地执行**
（`view_file`→读文件、`run_command`→受限 shell、`search_by_regex`→grep），
再把结果以已验证的 `工具执行结果：\n...` user 消息回传，循环直到模型给出最终答案。
这样任何客户端（包括纯聊天 UI）都能跑通完整 agent 循环。

映射实现位置建议：`trae2api/translate.py` 加
`TRAE_TO_CLIENT_TOOLS`（名映射）与 `PARAM_ALIASES`（参数别名），
出站时按客户端声明的工具集选择"映射后透传"还是"本地执行"。
