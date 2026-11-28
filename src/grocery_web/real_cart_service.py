"""HTTP wrapper for the local, single-account real Kroger cart bridge.

The bridge stores one shopper's OAuth tokens in .kroger-account/ on this
machine (see docs/real-kroger-cart.md), so these endpoints only run on a local
server. A hosted deployment (Vercel sets VERCEL=1) reports them unavailable
instead of sharing one person's Kroger account with every visitor.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, List, Mapping

from . import service

CONNECT_COMMAND = ".venv/bin/python scripts/kroger_account.py connect"


def available() -> bool:
    return not os.environ.get("VERCEL") and os.environ.get("GROCERY_REAL_CART", "1") != "0"


def _bridge():
    if not available():
        raise service.ServiceError(
            "Real Kroger cart submission only runs on a local server (single-account bridge)", status=501)
    if not service.kroger_configured():
        raise service.ServiceError("Kroger credentials are not configured", status=503)
    from .kroger_account import KrogerAccount
    from .real_cart import RealCartBridge

    return RealCartBridge(KrogerAccount())


def _guard(fn):
    from .kroger_account import AccountError

    try:
        return fn()
    except AccountError as error:
        raise service.ServiceError(str(error), status=409) from error
    except ValueError as error:
        raise service.ServiceError(str(error), status=422) from error


def status() -> dict:
    base = {"available": available(), "connect_command": CONNECT_COMMAND}
    if not available():
        return {**base, "authorized": False,
                "reason": "Hosted deployment: real cart submission is local-only"}
    if not service.kroger_configured():
        return {**base, "authorized": False, "reason": "Kroger credentials are not configured"}
    return {**base, **_guard(lambda: _bridge().account.status())}


def _clean_steps(steps: List[Mapping[str, Any]]) -> List[dict]:
    if not isinstance(steps, list) or not steps or len(steps) > 60:
        raise service.ServiceError("steps must be the list of interactive responses (1..60)")
    return [{k: v for k, v in dict(step).items() if k not in ("session_token", "products")} for step in steps]


def prepare(steps: List[Mapping[str, Any]], modality: str = "PICKUP") -> dict:
    cleaned = _clean_steps(steps)
    purchase_id = hashlib.sha256(json.dumps(cleaned, sort_keys=True).encode()).hexdigest()
    bridge = _bridge()
    return _guard(lambda: bridge.prepare({"steps": cleaned}, purchase_id, modality))


def commit(plan_id: str, confirm: str) -> dict:
    bridge = _bridge()
    return _guard(lambda: bridge.commit(plan_id, confirm))
