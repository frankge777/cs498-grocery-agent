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
from grocery_agent.discovery import ModelDiscovery
from grocery_agent.recommendation import ModelBasketRecommender

from . import service

TOKEN_LIFETIME_SECONDS = 1800


def _secret(override: Optional[str]) -> bytes:
    load_dotenv()
    value = override or os.environ.get("GROCERY_SESSION_SECRET")
    if not value or len(value) < 32 or value.startswith("replace_with_"):
        raise service.ServiceError("Set GROCERY_SESSION_SECRET to a random value of at least 32 characters", status=503)
    return value.encode("utf-8")


def session_configured() -> bool:
    try:
        _secret(None)
        return True
    except service.ServiceError:
        return False


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
              "selection_mode": session.selection_mode,
              "schema_version": session.intent.get("schema_version", 1),
              "location": env.observation().get("location"),
              "cart_mode": "local simulation only", "cart": service.cart_payload(env)}
    output["requirement_states"] = [
        {"requirement_id": item.requirement_id, "status": item.status,
         "selected_product_id": item.selected_product_id, "quantity": item.quantity,
         "measure": item.measure, "target_min": item.target_min, "target_max": item.target_max,
         "phase": item.phase, "active_requirement": item.active_requirement() if item.rules else None,
         "selection_revision": item.selection_revision, "quantity_interpretation": item.quantity_interpretation}
        for item in session.choices.requirements.values()
    ] if session.choices else []
    output["discovery"] = [
        {"requirement_id": item.requirement_id, "reason": item.discovery_reason,
         "search_attempts": item.search_attempts, "reviews": item.semantic_reviews,
         "errors": item.discovery_errors, "filters": item.filter_history,
         "availability_observations": item.availability_observations}
        for item in session.choices.requirements.values()
    ] if session.choices else []
    # Display-only product facts (name, size, price) for every product the UI
    # may show: reviewed candidates, options, the draft and the cart.
    shown = [pid for row in output["discovery"] for pid in
             [r.get("product_id") for r in row["reviews"] or []]]
    shown += [i.get("product_id") for i in (result.get("recommendation") or {}).get("items", [])]
    shown += [o.get("product_id") or o.get("id") for q in result.get("questions") or []
              for o in q.get("options") or []]
    shown += [s["selected_product_id"] for s in output["requirement_states"]] + list(env.cart)
    output["products"] = service.product_summaries(env, shown)
    if result["status"] != "complete":
        output["session_token"] = _encode({**metadata, "session": session.checkpoint(),
                                           "issued_at": time.time()}, secret)
    return output


def start(instruction: str, source: Optional[str] = None, zip_code: Optional[str] = None,
          location_id: Optional[str] = None, context: Optional[Mapping] = None,
          llm=None, signing_secret: Optional[str] = None, selection_mode="recommend",
          on_env=None, fallback_when_primary_empty=False) -> dict:
    """Start a recommended basket, or explicitly opt into legacy user choices."""
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
    if on_env is not None:  # lets the web layer stream tool calls while this runs
        on_env(env)
    try:
        session = InteractiveShoppingSession.from_model(env, llm or DeepSeekClient(temperature=0),
                                                         selection_mode=selection_mode)
        session.fallback_when_primary_empty = bool(fallback_when_primary_empty)
        result = session.advance()
    except (ValueError, KeyError, TypeError) as error:
        raise service.ServiceError(str(error), status=422) from error
    metadata = {"source": selected_source, "instruction": instruction, "context": dict(context or {}),
                "location_id": env.observation().get("location", {}).get("location_id"),
                "zip_code": zip_code}
    return _response(env, session, result, metadata, secret)


def resume(session_token: str, answers: Optional[Mapping] = None,
           clarification_answers: Optional[Mapping] = None,
           candidate_review_answers: Optional[Mapping] = None,
           reconsider_requirement_ids: Optional[Sequence[str]] = None,
           signing_secret: Optional[str] = None, llm=None,
           recommendation_answer: Optional[Mapping] = None,
           substitution_answers: Optional[Mapping] = None,
           quantity_review_answers: Optional[Mapping] = None, on_env=None) -> dict:
    """Continue a saved session after choices, or reopen budget-conflicting needs."""
    secret = _secret(signing_secret)
    payload = _decode(session_token, secret)
    if sum(value is not None for value in (answers, clarification_answers, candidate_review_answers,
                                           reconsider_requirement_ids, recommendation_answer,
                                           substitution_answers, quantity_review_answers)) > 1:
        raise service.ServiceError("Provide only one kind of answer per request")
    env = service.build_env(payload["source"], payload["instruction"], payload["context"],
                            payload.get("zip_code"), payload.get("location_id"),
                            lambda q: service.DEFAULT_CLARIFICATION_ANSWER)
    if on_env is not None:
        on_env(env)
    try:
        semantic = payload["session"].get("semantic_discovery", False)
        if (semantic or payload["session"].get("selection_mode") == "recommend") and llm is None:
            if not service.deepseek_configured():
                raise service.ServiceError("DEEPSEEK_API_KEY is not configured on the server", status=503)
            llm = DeepSeekClient(temperature=0)
        session = InteractiveShoppingSession.from_checkpoint(env, payload["session"],
            ModelDiscovery(llm) if semantic else None,
            ModelBasketRecommender(llm) if payload["session"].get("selection_mode") == "recommend" else None)
        if session.pending_substitution_questions and substitution_answers is None:
            if any(v is not None for v in (answers, clarification_answers, candidate_review_answers,
                                           reconsider_requirement_ids, recommendation_answer, quantity_review_answers)):
                raise ValueError("Answer the pending substitution permission first")
        if session.pending_quantity_reviews and quantity_review_answers is None:
            if any(v is not None for v in (answers, clarification_answers, candidate_review_answers,
                                           reconsider_requirement_ids, recommendation_answer, substitution_answers)):
                raise ValueError("Answer the pending quantity interpretation first")
        if substitution_answers is not None:
            session.answer_substitutions(substitution_answers)
        if quantity_review_answers is not None:
            session.answer_quantity_reviews(quantity_review_answers)
        if recommendation_answer is not None:
            if session.pending_candidate_reviews or session.pending_clarifications or session.choices._pending:
                raise ValueError("Answer the pending question first")
            session.answer_recommendation(recommendation_answer)
        elif session.pending_recommendation and any(value is not None for value in
                (answers, clarification_answers, candidate_review_answers, reconsider_requirement_ids,
                 substitution_answers, quantity_review_answers)):
            raise ValueError("Accept or request replacement for the pending recommendation first")
        if session.pending_candidate_reviews:
            if answers is not None or clarification_answers is not None or reconsider_requirement_ids:
                raise ValueError("Answer the pending candidate review first")
        if candidate_review_answers is not None:
            session.answer_candidate_reviews(candidate_review_answers)
        if clarification_answers is not None:
            if not session.pending_clarifications:
                raise ValueError("No clarification is pending")
            needs_model = any(q["kind"] == "free_text" for q in session.pending_clarifications)
            if needs_model and llm is None and not service.deepseek_configured():
                raise service.ServiceError("DEEPSEEK_API_KEY is not configured on the server", status=503)
            session.answer_clarifications(clarification_answers,
                                          llm or (DeepSeekClient(temperature=0) if needs_model else None))
        elif session.pending_clarifications and (answers is not None or reconsider_requirement_ids):
            raise ValueError("Answer the pending clarification first")
        result = (session.reconsider(reconsider_requirement_ids)
                  if reconsider_requirement_ids else session.advance(answers))
    except (ValueError, KeyError, TypeError) as error:
        raise service.ServiceError(str(error), status=422) from error
    metadata = {key: payload.get(key) for key in ("source", "instruction", "context", "location_id", "zip_code")}
    return _response(env, session, result, metadata, secret)
