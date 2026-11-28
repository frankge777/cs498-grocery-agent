"""Inference transport/isolation contracts. No login or model request in tests."""

import json
import os
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from grocery_agent.codex_llm import CodexCLIClient
from grocery_agent.llm import LLMProviderError, create_llm, is_provider_error


def completed(text='{"ok":true}', extra=(), returncode=0):
    events = [{"type": "thread.started", "thread_id": "fresh"}, *extra,
              {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
              {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 10,
                                                       "cached_input_tokens": 20}}]
    return SimpleNamespace(stdout="\n".join(json.dumps(e) for e in events), stderr="private diagnostics", returncode=returncode)


class CodexTransportTests(unittest.TestCase):
    def test_calls_fresh_isolated_cli_without_merchant_keys(self):
        seen = []

        def run(args, **kwargs):
            seen.append(kwargs["cwd"])
            self.assertEqual(list(Path(kwargs["cwd"]).iterdir()), [])
            self.assertNotIn("KROGER_CLIENT_SECRET", kwargs["env"])
            self.assertNotIn("DEEPSEEK_API_KEY", kwargs["env"])
            self.assertIn("--ignore-user-config", args)
            self.assertIn("--ephemeral", args)
            self.assertIn("read-only", args)
            self.assertIn("features.shell_tool=false", args)
            self.assertIn("project_doc_max_bytes=0", args)
            self.assertNotIn("--resume", args)
            self.assertFalse(kwargs.get("shell", False))
            self.assertIn('"role": "system"', kwargs["input"])
            return completed()

        client = CodexCLIClient(executable="codex")
        env = Mock()
        with patch.dict(os.environ, {"KROGER_CLIENT_SECRET": "test-merchant-secret", "DEEPSEEK_API_KEY": "test-key"}), patch("grocery_agent.codex_llm.subprocess.run", side_effect=run):
            first = client.chat([{"role": "system", "content": "JSON"}], json_mode=True, env=env)
            client.chat([{"role": "system", "content": "JSON"}], json_mode=True)
        self.assertEqual(json.loads(first.content), {"ok": True})
        env.record_model_call.assert_called_once_with(input_tokens=100, output_tokens=10, cached_input_tokens=20)
        self.assertNotEqual(seen[0], seen[1])
        self.assertTrue(all(not Path(d).exists() for d in seen))

    def test_tool_events_are_rejected(self):
        result = completed(extra=[{"type": "item.started", "item": {"type": "command_execution", "command": "read hidden data"}}])
        with self.assertRaises(LLMProviderError):
            CodexCLIClient._parse(result)

    def test_invalid_model_json_is_reasoning_failure_not_infrastructure(self):
        with self.assertRaises(ValueError) as caught:
            CodexCLIClient._parse(completed("not JSON"))
        self.assertFalse(is_provider_error(caught.exception))

    def test_cli_failure_does_not_leak_stderr(self):
        with self.assertRaises(LLMProviderError) as caught:
            CodexCLIClient._parse(completed(returncode=1))
        self.assertTrue(is_provider_error(caught.exception))
        self.assertNotIn("private diagnostics", str(caught.exception))

    def test_timeout_classified_as_provider_failure(self):
        client = CodexCLIClient(executable="codex")
        with patch("grocery_agent.codex_llm.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 1)):
            with self.assertRaises(LLMProviderError):
                client.chat([], json_mode=True)

    def test_native_function_calling_not_silently_emulated(self):
        with self.assertRaises(ValueError):
            CodexCLIClient(executable="codex").chat([], tools=[{"name": "search_products"}], json_mode=True)

    def test_description_does_not_claim_api_sampling_or_pricing(self):
        description = CodexCLIClient(executable="codex").describe()
        self.assertEqual(description["provider"], "codex-cli")
        self.assertIsNone(description["temperature"])
        self.assertIsNone(description["api_cost_usd"])

    def test_factory_rejects_unknown_provider_and_codex_thinking(self):
        for kwargs in ({"provider": "unknown"}, {"provider": "codex", "thinking": True}):
            with self.assertRaises(ValueError):
                create_llm(**kwargs)


if __name__ == "__main__":
    unittest.main()
