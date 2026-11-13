"""Thin LLM client layer (DeepSeek via its OpenAI-compatible API).

Every call is reported to the benchmark environment with
``env.record_model_call`` so model-call caps, token counts and cost are
logged per trial. ``ScriptedLLM`` replays canned responses for offline tests.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

ROOT = Path(__file__).resolve().parents[2]
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"

# USD per 1M tokens (DeepSeek pricing page, peak rates; off-peak is half).
PRICES_PER_M = {
    "deepseek-flash": {"cache_hit": 0.006, "cache_miss": 0.3, "output": 1.2},
    "deepseek-v4-pro": {"cache_hit": 0.044, "cache_miss": 1.32, "output": 3.96},
}


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines); never overrides existing variables."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def estimate_cost_usd(model: str, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> float:
    price = PRICES_PER_M.get(model, PRICES_PER_M[DEFAULT_MODEL])
    miss = max(0, input_tokens - cached_input_tokens)
    return (cached_input_tokens * price["cache_hit"] + miss * price["cache_miss"] + output_tokens * price["output"]) / 1e6


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Optional[dict]
    raw_arguments: str


@dataclass
class LLMResponse:
    content: str
    tool_calls: List[ToolCall]
    message: dict  # assistant message to append to the history verbatim
    usage: dict = field(default_factory=dict)


def openai_tools(specs: List[dict]) -> List[dict]:
    return [{"type": "function", "function": spec} for spec in specs]


def _parse_tool_calls(raw_calls) -> List[ToolCall]:
    calls = []
    for call in raw_calls or []:
        raw = call["function"].get("arguments") or "{}"
        try:
            args = json.loads(raw)
            if not isinstance(args, dict):
                args = None
        except json.JSONDecodeError:
            args = None
        calls.append(ToolCall(call["id"], call["function"]["name"], args, raw))
    return calls


class DeepSeekClient:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        thinking: bool = False,
        reasoning_effort: str = "high",
        timeout: float = 180.0,
    ):
        from openai import OpenAI

        load_dotenv()
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set (put it in .env at the repo root)")
        self.client = OpenAI(api_key=key, base_url=DEEPSEEK_BASE_URL, timeout=timeout, max_retries=5)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort

    def describe(self) -> dict:
        return {
            "provider": "deepseek",
            "model": self.model,
            "thinking": self.thinking,
            "temperature": None if self.thinking else self.temperature,
            "max_tokens": self.max_tokens,
        }

    def chat(self, messages: List[dict], tools: Optional[List[dict]] = None, json_mode: bool = False, env=None) -> LLMResponse:
        kwargs = {"model": self.model, "messages": messages, "max_tokens": self.max_tokens}
        if self.thinking:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}, "reasoning_effort": self.reasoning_effort}
        else:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            kwargs["temperature"] = self.temperature
        if tools:
            kwargs["tools"] = openai_tools(tools)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(3):
            response = self.client.chat.completions.create(**kwargs)
            usage = response.usage
            usage_dict = {
                "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "cached_input_tokens": getattr(usage, "prompt_cache_hit_tokens", 0) or 0,
            }
            if env is not None:
                env.record_model_call(**usage_dict)
            message = response.choices[0].message.model_dump(exclude_none=True)
            content = message.get("content") or ""
            # JSON mode can return blank content; retry (each attempt is logged as a model call).
            if json_mode and not content.strip() and attempt < 2:
                time.sleep(1)
                continue
            break
        message.setdefault("content", content)
        return LLMResponse(content, _parse_tool_calls(message.get("tool_calls")), message, usage_dict)


class ScriptedLLM:
    """Offline stand-in: ``responder(messages, tools, json_mode)`` returns {"content", "tool_calls"}."""

    def __init__(self, responder: Callable[[List[dict], Optional[List[dict]], bool], dict]):
        self.responder = responder
        self.model = "scripted"
        self.calls = 0

    def describe(self) -> dict:
        return {"provider": "scripted", "model": "scripted"}

    def chat(self, messages, tools=None, json_mode=False, env=None) -> LLMResponse:
        self.calls += 1
        reply = self.responder(messages, tools, json_mode)
        if env is not None:
            env.record_model_call(10, 5, 0)
        raw_calls = []
        for index, call in enumerate(reply.get("tool_calls", [])):
            raw_calls.append(
                {
                    "id": f"call_{self.calls}_{index}",
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call.get("arguments", {}))},
                }
            )
        message = {"role": "assistant", "content": reply.get("content", "")}
        if raw_calls:
            message["tool_calls"] = raw_calls
        return LLMResponse(reply.get("content", ""), _parse_tool_calls(raw_calls), message, {})
