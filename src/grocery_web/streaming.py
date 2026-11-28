"""Run one interactive step in a thread and stream its tool calls as NDJSON.

Each line is a JSON object: ``{"type": "tool", ...}`` for every environment
tool call as it is logged, ``{"type": "model", "model_calls": n}`` when the
model is called, then exactly one ``{"type": "result", "data": {...}}`` or
``{"type": "error", "status": int, "detail": str}``. If a proxy buffers the
response the client still receives the same lines, only later.
"""

from __future__ import annotations

import json
import threading
from typing import Callable, Iterator

from grocery_bench.kroger import KrogerAPIError

from .service import ServiceError

POLL_SECONDS = 0.2


def _line(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), default=str) + "\n"


def _tool_event(step: dict) -> dict:
    return {"type": "tool", "tool": step.get("tool") or step.get("event"), "args": step.get("args") or {},
            "ok": step.get("ok"), "message": step.get("message") or step.get("reason")}


def stream(fn: Callable, *args, **kwargs) -> Iterator[str]:
    holder: dict = {}
    done = threading.Event()

    def run():
        try:
            holder["result"] = fn(*args, on_env=lambda env: holder.setdefault("env", env), **kwargs)
        except ServiceError as error:
            holder["error"] = (error.status, str(error))
        except KrogerAPIError as error:
            holder["error"] = (502, str(error))
        except Exception as error:  # surfaced to the page instead of a dropped stream
            holder["error"] = (500, f"{type(error).__name__}: {error}")
        finally:
            done.set()

    threading.Thread(target=run, daemon=True).start()
    sent = model_calls = 0
    while True:
        finished = done.wait(POLL_SECONDS)
        env = holder.get("env")
        if env is not None:
            trajectory = env.trajectory
            while sent < len(trajectory):
                yield _line(_tool_event(trajectory[sent]))
                sent += 1
            if env.model_calls != model_calls:
                model_calls = env.model_calls
                yield _line({"type": "model", "model_calls": model_calls})
        if finished:
            break
    if "error" in holder:
        status, detail = holder["error"]
        yield _line({"type": "error", "status": status, "detail": detail})
    else:
        yield _line({"type": "result", "data": holder["result"]})
