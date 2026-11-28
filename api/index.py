"""FastAPI backend (Vercel Python function; also runs locally with uvicorn).

Local:  .venv/bin/uvicorn api.index:app --reload --port 8000
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional, Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from grocery_bench.kroger import KrogerAPIError  # noqa: E402
from grocery_web import service  # noqa: E402
from grocery_web import interactive_service  # noqa: E402

app = FastAPI(title="Grocery Agent API")


class AgentRequest(BaseModel):
    instruction: str = Field(..., max_length=2000)
    source: Optional[str] = "auto"
    zip_code: Optional[str] = None
    location_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    clarification_answer: Optional[str] = Field(None, max_length=1000)
    use_verifier: bool = True


class InteractiveStartRequest(BaseModel):
    instruction: str = Field(..., max_length=2000)
    source: Optional[str] = "auto"
    zip_code: Optional[str] = None
    location_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    selection_mode: Literal["recommend", "user_choice"] = "recommend"


class InteractiveResumeRequest(BaseModel):
    session_token: str
    answers: Optional[Dict[str, Any]] = None
    clarification_answers: Optional[Dict[str, Any]] = None
    candidate_review_answers: Optional[Dict[str, Any]] = None
    reconsider_requirement_ids: Optional[list[str]] = None
    recommendation_answer: Optional[Dict[str, Any]] = None
    substitution_answers: Optional[Dict[str, Any]] = None
    quantity_review_answers: Optional[Dict[str, Any]] = None


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.ServiceError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error
    except KrogerAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "kroger_configured": service.kroger_configured(),
        "deepseek_configured": service.deepseek_configured(),
        "default_source": "live" if service.kroger_configured() else "snapshot",
    }


@app.get("/api/locations")
def locations(zip_code: str = Query(..., pattern=r"^\d{5}$"), source: str = "auto") -> dict:
    return _call(service.find_locations, zip_code, source)


@app.get("/api/products")
def products(q: str = Query(..., min_length=3, max_length=100), source: str = "auto",
             zip_code: Optional[str] = None, location_id: Optional[str] = None,
             limit: int = Query(10, ge=1, le=50)) -> dict:
    return _call(service.search_products, q, source, zip_code, location_id, limit)


@app.post("/api/agent/run")
def agent_run(request: AgentRequest) -> dict:
    return _call(
        service.run_agent,
        request.instruction,
        source=request.source,
        zip_code=request.zip_code,
        location_id=request.location_id,
        context=request.context,
        clarification_answer=request.clarification_answer,
        use_verifier=request.use_verifier,
    )


@app.post("/api/agent/interactive/start")
def interactive_start(request: InteractiveStartRequest) -> dict:
    return _call(interactive_service.start, request.instruction, source=request.source,
                 zip_code=request.zip_code, location_id=request.location_id, context=request.context,
                 selection_mode=request.selection_mode)


@app.post("/api/agent/interactive/resume")
def interactive_resume(request: InteractiveResumeRequest) -> dict:
    return _call(interactive_service.resume, request.session_token,
                 answers=request.answers, clarification_answers=request.clarification_answers,
                 candidate_review_answers=request.candidate_review_answers,
                 reconsider_requirement_ids=request.reconsider_requirement_ids,
                 recommendation_answer=request.recommendation_answer,
                 substitution_answers=request.substitution_answers,
                 quantity_review_answers=request.quantity_review_answers)
