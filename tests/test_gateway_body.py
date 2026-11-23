"""Offline tests for the final V1 request body compatibility mapping."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trae2api.gateway import TraeGateway


class GatewayBodyCompatibilityTests(unittest.TestCase):
    def build(self, messages, *, tools=None, tool_choice=None):
        # Keep tests independent of operator model-routing environment flags.
        with patch.dict(os.environ, {
            "TRAE2API_MODEL": "",
            "TRAE2API_PASSTHROUGH_MODEL": "0",
        }):
            return TraeGateway.build_chat_body(
                "test-model", messages, session_id="synthetic-session",
                tools=tools, tool_choice=tool_choice,
            )

    def assert_instruction_once(self, text, *sentinels):
        for sentinel in sentinels:
            self.assertEqual(text.count(sentinel), 1, (sentinel, text))

    def test_interleaved_instructions_and_tool_contract_reach_final_body(self):
        messages = [
            {"role": "system", "content": "FIRST_SYS_MARKER"},
            {"role": "user", "content": "first user"},
            {"role": "developer", "content": "DEVELOPER_SENTINEL"},
            {"role": "assistant", "content": "intermediate"},
            {"role": "system", "content": "SECOND_SYS_MARKER"},
            {"role": "user", "content": "final user"},
            {"role": "developer", "content": "POST_USER_DEVELOPER_MARKER"},
        ]
        tools = [{
            "type": "function",
            "function": {
                "name": "lookup_weather",
                "description": "Look up synthetic weather data.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }]
        body = self.build(
            messages, tools=tools,
            tool_choice={"type": "function", "function": {"name": "lookup_weather"}},
        )

        user_text = body["user_input"]
        self.assert_instruction_once(
            user_text, "FIRST_SYS_MARKER", "DEVELOPER_SENTINEL", "SECOND_SYS_MARKER",
            "POST_USER_DEVELOPER_MARKER",
        )
        self.assertIn("lookup_weather", user_text)
        self.assertIn('"city"', user_text)
        self.assertEqual(user_text.count("本轮必须调用工具 lookup_weather。"), 1)
        self.assertIn("【系统指令】", user_text)
        self.assertIn("【开发者指令】", user_text)
        self.assertIn("final user", user_text)
        self.assertEqual(body["message_content"], [{"type": "text", "text_content": user_text}])
        self.assertEqual(body["chat_history"][-1]["content"], user_text)
        self.assertEqual(len(body["chat_history"]), 3)
        self.assertTrue(all(item["role"] not in ("system", "developer")
                            for item in body["chat_history"]))
        self.assertNotIn("model_name", body)

    def test_long_history_truncation_keeps_current_compatibility_block(self):
        messages = [
            {"role": "system", "content": "EARLY_SYS_MARKER"},
            {"role": "user", "content": "turn 0"},
            {"role": "developer", "content": "LATE_DEVELOPER_SENTINEL"},
        ]
        for index in range(1, 31):
            messages.extend([
                {"role": "assistant", "content": f"answer {index}"},
                {"role": "user", "content": f"question {index}"},
            ])
        body = self.build(messages)

        self.assertEqual(len(body["chat_history"]), 24)
        self.assertIn("EARLY_SYS_MARKER", body["user_input"])
        self.assertIn("LATE_DEVELOPER_SENTINEL", body["user_input"])
        self.assert_instruction_once(
            body["user_input"], "EARLY_SYS_MARKER", "LATE_DEVELOPER_SENTINEL"
        )
        self.assertEqual(body["chat_history"][-1]["content"], body["user_input"])
        self.assertIn("question 30", body["chat_history"][-1]["content"])

    def test_tool_result_ending_keeps_instructions_and_schema(self):
        messages = [
            {"role": "system", "content": "TOOL_TURN_SYSTEM_SENTINEL"},
            {"role": "user", "content": "run the synthetic lookup"},
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call_synthetic",
                "type": "function",
                "function": {"name": "lookup_weather", "arguments": "{\"city\":\"Oslo\"}"},
            }]},
            {"role": "tool", "tool_call_id": "call_synthetic", "name": "lookup_weather",
             "content": "SYNTHETIC_TOOL_RESULT"},
        ]
        tools = [{
            "type": "function",
            "function": {"name": "lookup_weather", "parameters": {
                "type": "object", "properties": {"city": {"type": "string"}},
            }},
        }]
        body = self.build(messages, tools=tools, tool_choice="required")
        user_text = body["user_input"]

        self.assertIn("TOOL_TURN_SYSTEM_SENTINEL", user_text)
        self.assertIn("本轮必须调用上述某一个工具。", user_text)
        self.assertIn("SYNTHETIC_TOOL_RESULT", user_text)
        self.assertIn("工具执行结果：", user_text)
        self.assertEqual(body["chat_history"][-1]["content"], user_text)
        self.assert_instruction_once(user_text, "TOOL_TURN_SYSTEM_SENTINEL", "SYNTHETIC_TOOL_RESULT")

    def test_instruction_only_input_gets_user_compatibility_turn(self):
        body = self.build([
            {"role": "system", "content": "ONLY_SYSTEM_SENTINEL"},
            {"role": "assistant", "content": "prior assistant turn"},
            {"role": "developer", "content": "ONLY_DEVELOPER_SENTINEL"},
        ])

        self.assertIn("ONLY_SYSTEM_SENTINEL", body["user_input"])
        self.assertIn("ONLY_DEVELOPER_SENTINEL", body["user_input"])
        self.assertTrue(body["user_input"].endswith("继续"))
        self.assertEqual(body["chat_history"][-1]["role"], "user")
        self.assertEqual(body["chat_history"][-2]["content"], "prior assistant turn")
        self.assertEqual(body["chat_history"][-1]["content"], body["user_input"])
        self.assert_instruction_once(body["user_input"], "ONLY_SYSTEM_SENTINEL", "ONLY_DEVELOPER_SENTINEL")

    def test_empty_input_keeps_existing_fallback(self):
        body = self.build([])
        self.assertEqual(body["user_input"], "继续")
        self.assertEqual(body["chat_history"], [])

    def test_plain_multiturn_request_keeps_existing_mapping(self):
        body = self.build([
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "current question"},
        ])

        self.assertEqual(body["user_input"], "current question")
        self.assertEqual(body["chat_history"], [
            {"role": "user", "content": "first question", "type": "user"},
            {"role": "assistant", "content": "first answer", "type": "assistant"},
            {"role": "user", "content": "current question", "type": "user"},
        ])


if __name__ == "__main__":
    unittest.main()
