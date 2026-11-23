"""Define the REAL Trae request schema in Python, recovered statically.

Source: ai_agent.dll serde metadata (see decompile_struct_fields.py). The
declarations are authoritative because serde writes "struct X with N elements"
plus the field names verbatim.

Two structures matter most:

1. Request  (9 elements) - the envelope the sidecar actually posts:
       service, data, user_info, client_info, common_params,
       streamlined_common_params, custom_params, scheduled_task_context

   Note what is NOT here: no "method". The real envelope is flatter than the
   convertReqToRustPayload JS object (that one is the mojo hop, and it does
   carry method - the Rust side derives it from `service`).

2. ChatArgs (61 elements) - the real chat payload. Compare with what
   gateway.build_chat_body sends today: a handful of fields, and several
   (message_content, scene_location) that do not even appear in workbench.js.

This module encodes the recovered schema as data so the gateway can build
requests against the real field set instead of guessing.
"""
from __future__ import annotations

# --- Request envelope ------------------------------------------------------
# serde run: servicedatauser_infoclient_infocommon_params
#             streamlined_common_paramscustom_paramsscheduled_task_context
REQUEST_FIELDS = [
    "service",
    "data",
    "user_info",
    "client_info",
    "common_params",
    "streamlined_common_params",
    "custom_params",
    "scheduled_task_context",
]

# --- ChatArgs: the real chat payload (61 fields, in declaration order) -----
CHAT_ARGS_FIELDS = [
    "assistant_message_id",
    "message_content",
    "code_selections",
    "active_text_editor",
    "workspace_context",
    "scene_location",
    "use_file_context",
    "use_filepath",
    "unit_test_functions",
    "workspace_folders",
    "agent_type",
    "dsl_agent",
    "custom_model",
    "code_language_environment",
    "runtime_environment_list",
    "model_auto_selection",
    "context_window_size",
    "is_in_plan_mode",
    "is_in_spec_mode",
    "is_in_code_mode",
    "command_type",
    "is_solo_mode",
    "ask_question_config",
    "window_capture_hidden_contexts",
    "attachments_dir",
    "work_path_config",
    "project_local_path",
    "deleted_message_ids",
    "next_min_message_index",
    "centralized_settings",
    "generate_project_name",
    "caller_timing_durations",
    "refactor_mode",
    "refactor_custom_preference",
    "origin",
    "is_background_wakeup",
    "force_tool_calls",
    "force_agent_run_id",
    "force_server_task_id",
    "turn_id",
    "seq_offset",
    "original_start_time",
    "work_mode",
    "use_fast_request",
    "preheat",
    "parent_session_id",
    "is_user_retry",
    "workroom_id",
    "hit_shared_artifact_and_workroom",
]

# --- CustomModel (31 elements) --------------------------------------------
CUSTOM_MODEL_FIELDS = [
    "provider", "is_preset", "config_source", "model_name",
    "display_model_name", "ak", "base_url", "custom_model_uniq_id",
    "use_remote_service", "multimodal", "support_read_image",
    "prompt_max_tokens", "toolcall_history_max_tokens",
    "encrypted_model_params", "extra_config", "function_extra_config",
    "ab_versions", "persist_meta", "raw_chat_function", "prompt_set",
    "context_window_sizes", "max_turn", "display_options", "max_tokens",
    "application_config", "sk", "auth_type", "region", "session_token",
    "custom_model_type", "reasoning_effort", "reasoning_effort_level",
]

# --- ApplicationConfig (7 elements): the v3/agent switches ---------------
APPLICATION_CONFIG_FIELDS = [
    "enable_solo_next",
    "enable_agent_process_v3",
    "enable_upgrade_all_sessions_to_v3",
    "enable_upgrade_session_by_solo_coder",
    "enable_upgrade_session_by_solo_builder",
    "agent_types_that_ignore_queue_event",
    "chat_memory_config",
]

# --- StandardChatMessagePart (3 elements) --------------------------------
MESSAGE_PART_FIELDS = ["type", "text_content", "data"]

# --- ToolCall (4 elements) ----------------------------------------------
TOOL_CALL_FIELDS = ["id", "type", "function", "index"]

# --- ModelSmartSelection (3 elements) -----------------------------------
MODEL_SMART_SELECTION_FIELDS = [
    "strategy", "fallback_to_advance_model", "entitlement_id",
]

# --- ChatMessageData (46 elements) --------------------------------------
CHAT_MESSAGE_DATA_FIELDS = [
    "message_type", "message_index", "user_message_context", "revertible",
    "context_metadata", "doc_references", "agent_is_built_in", "agent_name",
    "agent_avatar_id", "max_fee_usage", "notifications",
    "model_smart_selection_meta", "from_append_msg",
    "consumed_message_ids", "shallow_memento_type", "timing_events",
    "request_client", "chat_process_version", "ttnet_abtest", "is_worktree",
    "stop_info", "merged_commit", "context_usage", "chat_start_time",
    "chat_end_time", "version_code",
]


def describe() -> str:
    out = []
    out.append("Real Trae request schema (recovered from ai_agent.dll serde "
               "metadata)")
    out.append("")
    out.append(f"Request envelope ({len(REQUEST_FIELDS)}):")
    out.append("    " + ", ".join(REQUEST_FIELDS))
    out.append("")
    out.append(f"ChatArgs ({len(CHAT_ARGS_FIELDS)} fields):")
    for f in CHAT_ARGS_FIELDS:
        out.append(f"    {f}")
    out.append("")
    out.append(f"ApplicationConfig ({len(APPLICATION_CONFIG_FIELDS)}):")
    out.append("    " + ", ".join(APPLICATION_CONFIG_FIELDS))
    return "\n".join(out)


if __name__ == "__main__":
    print(describe())
