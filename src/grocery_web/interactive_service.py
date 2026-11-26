"""Stateless HTTP boundary for the opt-in interactive shopping session."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from typing import Mapping, Optional, Sequence

from grocery_agent.interactive import InteractiveShoppingSession
from grocery_agent.llm import DeepSeekClient, load_dotenv

from . import service

TOKEN_LIFETIME_SECONDS = 1800


def _secret(override: Optional[str]) -> bytes:
    load_dotenv()
    value = override or os.environ.get("GROCERY_SESSION_SECRET")
    if not value or len(value) < 32 or value.startswith("replace_with_"):
        raise service.ServiceError("Set GROCERY_SESSION_SECRET to a random value of at least 32 characters", status=503)
    return value.encode("utf-8")


def _encode(payload: dict, secret: bytes) -> str:
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(secret, data, hashlib.sha256).digest()
    return ".".join(base64.urlsafe_b64encode(part).decode("ascii").rstrip("=")
                    for part in (data, signature))


def _decode(token: str, secret: bytes) -> dict:
    try:
        encoded_data, encoded_signature = token.split(".", 1)
        data = base64.urlsafe_b64decode(encoded_data + "=" * (-len(encoded_data) % 4))
        signature = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
        expected = hmac.new(secret, data, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Signature mismatch")
        payload = json.loads(data)
        age = time.time() - payload["issued_at"]
        if age > TOKEN_LIFETIME_SECONDS or age < -60:
            raise ValueError("Session expired")
        return payload
    except (ValueError, KeyError, TypeError, binascii.Error) as error:
        raise service.ServiceError("Invalid or expired interactive session", status=400) from error


def _response(env, session, result, metadata, secret):
    output = {**result, "data_source": metadata["source"],
              "location": env.observation().get("location"),
              "cart_mode": "local simulation only", "cart": service.cart_payload(env)}
    if result["status"] != "complete":
        output["session_token"] = _encode({**metadata, "session": session.checkpoint(),
                                           "issued_at": time.time()}, secret)
    return output


def start(instruction: str, source: Optional[str] = None, zip_code: Optional[str] = None,
          location_id: Optional[str] = None, context: Optional[Mapping] = None,
          llm=None, signing_secret: Optional[str] = None) -> dict:
    """Extract intent once, search candidates, then stop at the first choice."""
    secret = _secret(signing_secret)
    if not instruction.strip():
        raise service.ServiceError("instruction is required")
    if len(instruction) > 2000:
        raise service.ServiceError("instruction is too long")
    selected_source = service.resolve_source(source)
    if llm is None and not service.deepseek_configured():
        raise service.ServiceError("DEEPSEEK_API_KEY is not configured on the server", status=503)
    env = service.build_env(selected_source, instruction, dict(context or {}), zip_code,
                            location_id, lambda q: service.DEFAULT_CLARIFICATION_ANSWER)
    try:
        session = InteractiveShoppingSession.from_model(env, llm or DeepSeekClient(temperature=0))
        result = session.advance()
    except (ValueError, KeyError, TypeError) as error:
        raise service.ServiceError(str(error), status=422) from error
    metadata = {"source": selected_source, "instruction": instruction, "context": dict(context or {}),
                "location_id": env.observation().get("location", {}).get("location_id"),
                "zip_code": zip_code}
    return _response(env, session, result, metadata, secret)


def resume(session_token: str, answers: Optional[Mapping] = None,
           reconsider_requirement_ids: Optional[Sequence[str]] = None,
           signing_secret: Optional[str] = None) -> dict:
    """Continue a saved session after choices, or reopen budget-conflicting needs."""
    secret = _secret(signing_secret)
    payload = _decode(session_token, secret)
    if answers is not None and reconsider_requirement_ids:
        raise service.ServiceError("Provide answers or reconsider_requirement_ids, not both")
    env = service.build_env(payload["source"], payload["instruction"], payload["context"],
                            payload.get("zip_code"), payload.get("location_id"),
                            lambda q: service.DEFAULT_CLARIFICATION_ANSWER)
    try:
        session = InteractiveShoppingSession.from_checkpoint(env, payload["session"])
        result = (session.reconsider(reconsider_requirement_ids)
                  if reconsider_requirement_ids else session.advance(answers))
    except (ValueError, KeyError, TypeError) as error:
        raise service.ServiceError(str(error), status=422) from error
    metadata = {key: payload.get(key) for key in ("source", "instruction", "context", "location_id", "zip_code")}
    return _response(env, session, result, metadata, secret)
