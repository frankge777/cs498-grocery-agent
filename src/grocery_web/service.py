"""Web-facing service layer: runs the grocery agent for one HTTP request.

Two data sources:

* ``live``: product reads go to the Kroger Public API (needs KROGER_CLIENT_ID /
  KROGER_CLIENT_SECRET).
* ``snapshot``: the frozen 722-product Kroger Mt Zion snapshot, so the app works
  without Kroger credentials.

The cart is always a local simulation here; pushing it to a real Kroger cart
(OAuth authorization-code flow, ``cart.basic:write``) is a separate step.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Mapping, Optional

from grocery_bench.data import KROGER_CATALOG_PATH, Product, Scenario, load_catalog
from grocery_bench.environment import GroceryEnv, Observation
from grocery_bench.kroger import KrogerClient, KrogerConfigurationError, KrogerLiveEnv

DEFAULT_CLARIFICATION_ANSWER = (
    "I have no further preference. Please use your best judgment and choose reasonable defaults."
)

_kroger_client: Optional[KrogerClient] = None
_snapshot_catalog: Optional[Dict[str, Product]] = None
_snapshot_location: Optional[dict] = None


class ServiceError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ----------------------------------------------------------------- resources
def kroger_configured() -> bool:
    try:
        kroger_client()
        return True
    except KrogerConfigurationError:
        return False


def deepseek_configured() -> bool:
    from grocery_agent.llm import load_dotenv

    load_dotenv()
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def kroger_client() -> KrogerClient:
    """One client per process so the OAuth token is reused across warm requests."""
    global _kroger_client
    if _kroger_client is None:
        _kroger_client = KrogerClient()
    return _kroger_client


def snapshot_catalog() -> Dict[str, Product]:
    global _snapshot_catalog, _snapshot_location
    if _snapshot_catalog is None:
        import json

        raw = json.loads(KROGER_CATALOG_PATH.read_text(encoding="utf-8"))
        _snapshot_location = dict(raw.get("source", {}).get("location") or {})
        _snapshot_catalog = load_catalog(KROGER_CATALOG_PATH)
    return _snapshot_catalog


def snapshot_location() -> dict:
    snapshot_catalog()
    return dict(_snapshot_location or {})


def resolve_source(source: Optional[str]) -> str:
    if source in (None, "", "auto"):
        return "live" if kroger_configured() else "snapshot"
    if source not in ("live", "snapshot"):
        raise ServiceError("source must be 'live', 'snapshot' or 'auto'")
    if source == "live" and not kroger_configured():
        raise ServiceError("Kroger credentials are not configured; use source='snapshot'", status=503)
    return source


def location_summary(location: Mapping[str, Any]) -> dict:
    return {
        "location_id": location.get("locationId"),
        "name": location.get("name"),
        "chain": location.get("chain"),
        "address": location.get("address"),
    }


# ----------------------------------------------------------------- locations
def find_locations(zip_code: str, source: Optional[str] = None) -> dict:
    source = resolve_source(source)
    if source == "snapshot":
        return {"data_source": source, "locations": [location_summary(snapshot_location())]}
    try:
        rows = kroger_client().search_locations(zip_code, limit=10)
    except ValueError as error:
        raise ServiceError(str(error)) from error
    return {"data_source": source, "locations": [location_summary(row) for row in rows]}


# ------------------------------------------------------------- environments
def _live_scenario(instruction: str, context: Mapping[str, Any]) -> Scenario:
    return Scenario(
        id="web-request",
        category="live",
        difficulty="live",
        title="Web shopping request",
        variants={name: instruction for name in ("high", "medium", "low")},
        context=dict(context),
        needs=[],
        extras_allowed=True,
    )


class SnapshotEnv(GroceryEnv):
    """GroceryEnv over the frozen Kroger snapshot with a free-form request."""

    def __init__(self, instruction: str, context: Mapping[str, Any],
                 clarification_handler: Optional[Callable[[str], str]] = None):
        super().__init__(dict(snapshot_catalog()), _live_scenario(instruction, context), "high")
        self.location = snapshot_location()
        self.clarification_handler = clarification_handler

    def observation(self) -> dict:
        payload = super().observation()
        payload["data_source"] = "Kroger snapshot (2026-11-16, frozen)"
        payload["location"] = location_summary(self.location)
        payload["limitations"] = [
            "prices and availability are frozen at snapshot time",
            "cart actions are local simulation only",
        ]
        return payload

    def ask_user(self, question: str) -> Observation:
        if self.clarification_handler is None:
            return super().ask_user(question)
        args = {"question": question}
        self._begin_call("ask_user", args)
        answer = str(self.clarification_handler(question))
        return self._log("ask_user", args, Observation(True, answer, {"answer": answer, "topic": "web_user"}))


def build_env(source: str, instruction: str, context: Mapping[str, Any], zip_code: Optional[str],
              location_id: Optional[str], clarification_handler: Callable[[str], str]) -> GroceryEnv:
    if source == "snapshot":
        return SnapshotEnv(instruction, context, clarification_handler)
    client = kroger_client()
    try:
        if location_id:
            location = client.get_location(location_id)
        elif zip_code:
            location = client.nearest_location(zip_code)
        else:
            raise ServiceError("zip_code or location_id is required for live Kroger data")
    except ValueError as error:
        raise ServiceError(str(error)) from error
    return KrogerLiveEnv(client, location, instruction, context, clarification_handler=clarification_handler)


# ------------------------------------------------------------------ products
def search_products(query: str, source: Optional[str] = None, zip_code: Optional[str] = None,
                    location_id: Optional[str] = None, limit: int = 10) -> dict:
    source = resolve_source(source)
    env = build_env(source, "browse", {}, zip_code, location_id, lambda q: DEFAULT_CLARIFICATION_ANSWER)
    obs = env.search_products(query, max_results=max(1, min(int(limit), 50)))
    if not obs.ok:
        raise ServiceError(obs.message)
    return {"data_source": source, "location": env.observation()["location"], **(obs.data or {})}


# --------------------------------------------------------------------- agent
def cart_payload(env: GroceryEnv) -> dict:
    items = []
    for pid, quantity in sorted(env.cart.items()):
        product = env.catalog[pid]
        items.append({
            **product.public_summary(env.stock.get(pid, 0) > 0),
            "quantity": quantity,
            "line_total_cents": product.price_cents * quantity,
        })
    return {"items": items, "total_cents": env.total_cents}


def run_agent(instruction: str, source: Optional[str] = None, zip_code: Optional[str] = None,
              location_id: Optional[str] = None, context: Optional[Mapping[str, Any]] = None,
              clarification_answer: Optional[str] = None, use_verifier: bool = True) -> dict:
    instruction = " ".join((instruction or "").split())
    if not instruction:
        raise ServiceError("instruction is required")
    if len(instruction) > 2000:
        raise ServiceError("instruction is too long (max 2000 characters)")
    if not deepseek_configured():
        raise ServiceError("DEEPSEEK_API_KEY is not configured on the server", status=503)
    source = resolve_source(source)

    from grocery_agent.llm import DeepSeekClient
    from grocery_agent.llm_agents import IntentGroundedLLMAgent

    clarifications: List[dict] = []
    answer = (clarification_answer or "").strip() or DEFAULT_CLARIFICATION_ANSWER

    def handler(question: str) -> str:
        clarifications.append({"question": question, "answer": answer})
        return answer

    env = build_env(source, instruction, dict(context or {}), zip_code, location_id, handler)
    agent = IntentGroundedLLMAgent(DeepSeekClient(), use_verifier=use_verifier)
    error: Optional[str] = None
    try:
        agent.run(env)
    except Exception as exc:  # surface agent failures to the UI with the partial cart
        error = f"{type(exc).__name__}: {exc}"

    return {
        "data_source": source,
        "location": env.observation().get("location"),
        "cart_mode": "local simulation only",
        "cart": cart_payload(env),
        "intent": agent.notes.get("intent"),
        "clarifications": clarifications,
        "verify_reports": agent.notes.get("verify_reports"),
        "trajectory": env.trajectory,
        "stats": {
            "tool_calls": env.tool_calls,
            "model_calls": env.model_calls,
            "input_tokens": env.input_tokens,
            "output_tokens": env.output_tokens,
            "elapsed_seconds": round(env.elapsed_seconds, 2),
            "termination_reason": env.termination_reason,
        },
        "error": error,
    }


# ------------------------------------------------------- product details (UI)
# Kroger's product API returns images[].sizes[].url on this CDN pattern; the
# frozen snapshot did not keep the image list, so it falls back to the pattern.
KROGER_IMAGE_URL = "https://www.kroger.com/product/images/{size}/{perspective}/{upc}"
IMAGE_PERSPECTIVES = ("front", "back", "left", "right", "top", "bottom")


def image_urls(raw_images: Optional[List[Mapping[str, Any]]], upc: str) -> List[dict]:
    """[{perspective, url, default}] preferring the API's own image list."""
    images = []
    for image in raw_images or []:
        sizes = {s.get("size"): s.get("url") for s in image.get("sizes") or [] if s.get("url")}
        url = next((sizes[s] for s in ("large", "xlarge", "medium", "small", "thumbnail") if sizes.get(s)), None)
        if url:
            images.append({"perspective": image.get("perspective") or "front", "url": url,
                           "default": bool(image.get("featured") or image.get("default"))})
    if images:
        return images
    return [{"perspective": p, "url": KROGER_IMAGE_URL.format(size="large", perspective=p, upc=upc),
             "default": p == "front"} for p in IMAGE_PERSPECTIVES[:3]]


def product_summaries(env: GroceryEnv, product_ids) -> Dict[str, dict]:
    """Name/brand/size/price for products the UI shows (only ids the env has seen)."""
    rows = {}
    for pid in dict.fromkeys(str(p) for p in product_ids if p):
        product = env.catalog.get(pid)
        if product is not None:
            rows[pid] = product.public_summary(env.stock.get(pid, 0) > 0)
    return rows


def product_detail(product_id: str, source: Optional[str] = None, zip_code: Optional[str] = None,
                   location_id: Optional[str] = None) -> dict:
    if not product_id.isdigit() or len(product_id) > 20:
        raise ServiceError("product_id must be a numeric UPC")
    source = resolve_source(source)
    extra: Dict[str, Any] = {}
    if source == "snapshot":
        product = snapshot_catalog().get(product_id)
        if product is None:
            raise ServiceError("Product is not in the snapshot", status=404)
        location = location_summary(snapshot_location())
        raw_images = None
    else:
        from grocery_bench.kroger import normalize_kroger_product

        env = build_env(source, "browse", {}, zip_code, location_id, lambda q: DEFAULT_CLARIFICATION_ANSWER)
        raw = kroger_client().get_product(product_id, env.location_id)
        product = normalize_kroger_product(raw)
        location = env.observation()["location"]
        raw_images = raw.get("images")
        aisles = [a.get("description") for a in raw.get("aisleLocations") or [] if a.get("description")]
        page = raw.get("productPageURI")
        extra = {"aisles": aisles, "country_origin": raw.get("countryOrigin"),
                 "temperature": (raw.get("temperature") or {}).get("indicator"),
                 "product_page_url": f"https://www.kroger.com{page}" if page else None}
    details = product.public_details(product.stock > 0)
    upc = product.upc or product.id
    return {"data_source": source, "location": location, **details, **extra,
            "images": image_urls(raw_images, upc),
            "search_url": f"https://www.kroger.com/search?query={upc}"}
