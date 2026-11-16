"""Real Kroger product access and a safe, local-cart environment.

The public Kroger API supplies store-specific products, prices and fulfillment
availability.  It does not expose an exact inventory count or complete dietary
and serving metadata, so this module preserves those limitations instead of
inventing values.  Cart mutations are local to the benchmark process; this
module never calls Kroger's cart or checkout endpoints.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional, Tuple

from .data import DEFAULT_STOCK, Product, Scenario
from .environment import GroceryEnv, Observation

KROGER_API_BASE_URL = "https://api.kroger.com/v1"
KROGER_PRODUCT_SCOPE = "product.compact"


class KrogerConfigurationError(RuntimeError):
    """Raised when the API client has not been configured."""


class KrogerAPIError(RuntimeError):
    """Raised when Kroger rejects or cannot complete a request."""


class _UrllibTransport:
    def request(self, method: str, url: str, headers: Mapping[str, str], data: Optional[bytes], timeout: float) -> dict:
        request = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise KrogerAPIError(f"Kroger API HTTP {error.code}: {body[:500]}") from error
        except urllib.error.URLError as error:
            raise KrogerAPIError(f"Kroger API request failed: {error.reason}") from error
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise KrogerAPIError("Kroger API returned invalid JSON") from error


class KrogerClient:
    """Small client-credentials client for Kroger locations and products."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        base_url: str = KROGER_API_BASE_URL,
        timeout: float = 30.0,
        transport: Optional[Any] = None,
        clock: Callable[[], float] = time.time,
    ):
        _load_repo_dotenv()
        self.client_id = client_id or os.environ.get("KROGER_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("KROGER_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise KrogerConfigurationError(
                "KROGER_CLIENT_ID and KROGER_CLIENT_SECRET are required. "
                "Create a Kroger developer application and set both environment variables."
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport or _UrllibTransport()
        self.clock = clock
        self._access_token: Optional[str] = None
        self._token_expires_at = 0.0

    def _token(self) -> str:
        if self._access_token and self.clock() < self._token_expires_at:
            return self._access_token
        credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("ascii")
        body = urllib.parse.urlencode(
            {"grant_type": "client_credentials", "scope": KROGER_PRODUCT_SCOPE}
        ).encode("ascii")
        payload = self.transport.request(
            "POST",
            f"{self.base_url}/connect/oauth2/token",
            {
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            body,
            self.timeout,
        )
        token = payload.get("access_token")
        if not token:
            raise KrogerAPIError(f"Kroger token response did not contain access_token: {payload}")
        self._access_token = str(token)
        lifetime = max(1, int(payload.get("expires_in", 1800)))
        self._token_expires_at = self.clock() + max(1, lifetime - 30)
        return self._access_token

    def _get(self, path: str, params: Mapping[str, Any]) -> dict:
        clean = {key: value for key, value in params.items() if value is not None}
        query = urllib.parse.urlencode(clean)
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url += f"?{query}"
        return self.transport.request(
            "GET",
            url,
            {"Authorization": f"Bearer {self._token()}", "Accept": "application/json"},
            None,
            self.timeout,
        )

    def search_locations(
        self,
        zip_code: str,
        radius_miles: int = 100,
        chain: Optional[str] = "Kroger",
        limit: int = 20,
    ) -> List[dict]:
        if not re.fullmatch(r"\d{5}", zip_code):
            raise ValueError("zip_code must contain exactly five digits")
        payload = self._get(
            "locations",
            {
                "filter.zipCode.near": zip_code,
                "filter.radiusInMiles": max(1, min(int(radius_miles), 100)),
                "filter.chain": chain,
                "filter.limit": max(1, min(int(limit), 200)),
            },
        )
        return list(payload.get("data") or [])

    def nearest_location(self, zip_code: str, chain: Optional[str] = "Kroger") -> dict:
        locations = self.search_locations(zip_code, chain=chain)
        if not locations:
            raise KrogerAPIError(f"No {chain or 'Kroger-family'} location found near ZIP {zip_code}")
        return locations[0]

    def get_location(self, location_id: str) -> dict:
        return dict(self._get(f"locations/{location_id}", {}).get("data") or {})

    def search_products(
        self,
        term: str,
        location_id: str,
        limit: int = 20,
        fulfillment: Optional[str] = None,
        brand: Optional[str] = None,
    ) -> List[dict]:
        term = " ".join(term.split())
        if len(term) < 3:
            raise ValueError("Kroger product search terms must have at least three characters")
        payload = self._get(
            "products",
            {
                "filter.term": term,
                "filter.locationId": location_id,
                "filter.fulfillment": fulfillment,
                "filter.brand": brand,
                "filter.limit": max(1, min(int(limit), 50)),
            },
        )
        return list(payload.get("data") or [])

    def get_product(self, product_id: str, location_id: str) -> dict:
        payload = self._get(f"products/{urllib.parse.quote(product_id, safe='')}", {"filter.locationId": location_id})
        product = payload.get("data")
        if not isinstance(product, dict):
            raise KrogerAPIError(f"Kroger product {product_id} was not found at location {location_id}")
        return product


def normalize_kroger_product(raw: Mapping[str, Any], search_term: Optional[str] = None) -> Product:
    """Convert a Kroger product response into the benchmark's public product shape."""
    items = [item for item in (raw.get("items") or []) if isinstance(item, dict)]
    item = _best_item(items)
    price = item.get("price") if isinstance(item.get("price"), dict) else {}
    regular = _money_to_cents(price.get("regular"))
    promo = _money_to_cents(price.get("promo"))
    price_cents = promo if promo > 0 else regular
    fulfillment = item.get("fulfillment") if isinstance(item.get("fulfillment"), dict) else {}
    availability = {str(key): bool(value) for key, value in fulfillment.items()}
    available = price_cents > 0 and (any(availability.values()) if availability else True)
    raw_size = str(item.get("size") or raw.get("size") or "").strip()
    size, unit = parse_kroger_size(raw_size)
    categories = [str(value) for value in (raw.get("categories") or []) if value]
    category_source = categories[0] if categories else (search_term or "unknown")
    category = re.sub(r"[^a-z0-9]+", "_", category_source.lower()).strip("_") or "unknown"
    product_id = str(raw.get("productId") or raw.get("upc") or "")
    if not product_id:
        raise ValueError("Kroger product is missing productId and UPC")
    return Product(
        id=product_id,
        name=str(raw.get("description") or product_id),
        category=category,
        brand=str(raw.get("brand") or "Unknown"),
        size=size,
        unit=unit,
        price_cents=price_cents,
        tags=frozenset(),
        portions={},
        stock=DEFAULT_STOCK if available else 0,
        upc=str(raw.get("upc") or "") or None,
        raw_size=raw_size or None,
        source="kroger_live",
        availability=availability,
    )


def parse_kroger_size(raw_size: str) -> Tuple[int, str]:
    """Parse common Kroger package sizes without pretending unsupported precision."""
    text = raw_size.strip().lower().replace("fluid ounces", "fl oz").replace("fluid ounce", "fl oz")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(fl\s*oz|oz|lb|lbs|kg|g|ml|l|gal|qt|pt|ct|count|ea|each)\b", text)
    if not match:
        return 1, "unit"
    amount = float(match.group(1))
    unit = re.sub(r"\s+", " ", match.group(2))
    if unit in {"ct", "count", "ea", "each"}:
        return max(1, round(amount)), "ct"
    if unit == "ml":
        return max(1, round(amount)), "ml"
    if unit == "l":
        return max(1, round(amount * 1000)), "ml"
    if unit == "fl oz":
        return max(1, round(amount * 29.5735)), "ml"
    if unit == "gal":
        return max(1, round(amount * 3785.41)), "ml"
    if unit == "qt":
        return max(1, round(amount * 946.353)), "ml"
    if unit == "pt":
        return max(1, round(amount * 473.176)), "ml"
    if unit == "g":
        return max(1, round(amount)), "g"
    if unit == "kg":
        return max(1, round(amount * 1000)), "g"
    if unit == "oz":
        return max(1, round(amount * 28.3495)), "g"
    if unit in {"lb", "lbs"}:
        return max(1, round(amount * 453.592)), "g"
    return 1, "unit"


def _money_to_cents(value: Any) -> int:
    try:
        return max(0, round(float(value) * 100))
    except (TypeError, ValueError):
        return 0


def _best_item(items: List[dict]) -> dict:
    if not items:
        return {}
    return next((item for item in items if item.get("price")), items[0])


def _load_repo_dotenv() -> None:
    """Load Kroger credentials from an ignored repo-local .env, if present."""
    path = Path(__file__).resolve().parents[2] / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in {"KROGER_CLIENT_ID", "KROGER_CLIENT_SECRET"}:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


class KrogerLiveEnv(GroceryEnv):
    """GroceryEnv-compatible facade over live Kroger product reads.

    Product discovery and product details are live. Cart changes remain local,
    so running an agent cannot modify a user's Kroger account or place an order.
    """

    def __init__(
        self,
        client: KrogerClient,
        location: Mapping[str, Any],
        instruction: str,
        household_context: Optional[Mapping[str, Any]] = None,
        limits: Optional[dict] = None,
        clarification_handler: Optional[Callable[[str], str]] = None,
    ):
        variants = {name: instruction for name in ("high", "medium", "low")}
        scenario = Scenario(
            id="kroger-live",
            category="live",
            difficulty="live",
            title="Live Kroger shopping task",
            variants=variants,
            context=dict(household_context or {}),
            needs=[],
            extras_allowed=True,
        )
        super().__init__({}, scenario, "high", limits=limits)
        self.client = client
        self.location = dict(location)
        self.location_id = str(location.get("locationId") or "")
        if not self.location_id:
            raise ValueError("Kroger location is missing locationId")
        self.clarification_handler = clarification_handler

    @classmethod
    def from_zip(
        cls,
        zip_code: str,
        instruction: str,
        household_context: Optional[Mapping[str, Any]] = None,
        client: Optional[KrogerClient] = None,
        **kwargs,
    ) -> "KrogerLiveEnv":
        live_client = client or KrogerClient()
        location = live_client.nearest_location(zip_code)
        return cls(live_client, location, instruction, household_context, **kwargs)

    def observation(self) -> dict:
        payload = super().observation()
        payload["data_source"] = "Kroger Public API (live)"
        payload["location"] = {
            "location_id": self.location_id,
            "name": self.location.get("name"),
            "chain": self.location.get("chain"),
            "address": self.location.get("address"),
        }
        payload["limitations"] = [
            "availability is boolean; exact inventory count is not provided",
            "dietary tags and portions are unknown unless supplied by Kroger",
            "cart actions are local simulation only",
        ]
        return payload

    def search_products(self, query: str, max_results: int = 10) -> Observation:
        args = {"query": query, "max_results": max_results}
        self._begin_call("search_products", args)
        try:
            rows = self.client.search_products(query, self.location_id, limit=max_results)
            products = [self._register(normalize_kroger_product(row, query)) for row in rows]
            obs = Observation(True, f"{len(products)} live Kroger results", {
                "products": [product.public_summary(self._in_stock(product.id)) for product in products],
                "location_id": self.location_id,
            })
        except (KrogerAPIError, ValueError) as error:
            obs = Observation(False, str(error))
        return self._log("search_products", args, obs)

    def get_product(self, product_id: str) -> Observation:
        args = {"product_id": product_id}
        self._begin_call("get_product", args)
        try:
            raw = self.client.get_product(product_id, self.location_id)
            product = self._register(normalize_kroger_product(raw))
            obs = Observation(True, "Live Kroger product details", product.public_details(self._in_stock(product.id)))
        except (KrogerAPIError, ValueError) as error:
            obs = Observation(False, str(error))
        return self._log("get_product", args, obs)

    def ask_user(self, question: str) -> Observation:
        if self.clarification_handler is None:
            return super().ask_user(question)
        args = {"question": question}
        self._begin_call("ask_user", args)
        answer = str(self.clarification_handler(question))
        return self._log("ask_user", args, Observation(True, answer, {"answer": answer, "topic": "live_user"}))

    def _register(self, product: Product) -> Product:
        self.catalog[product.id] = product
        self.stock[product.id] = product.stock
        return product

    def _validate_increase(self, product_id: str, quantity: Any, positive: bool) -> Optional[str]:
        """Check boolean availability without inventing an exact inventory count."""
        if not isinstance(quantity, int) or isinstance(quantity, bool) or (positive and quantity <= 0):
            return "Quantity must be a positive integer"
        if product_id not in self.catalog:
            return f"Unknown product: {product_id}"
        if self.stock.get(product_id, 0) <= 0:
            return f"Unavailable at Kroger location {self.location_id}: {product_id}"
        return None


def product_to_snapshot_row(product: Product) -> dict:
    """Serialize the normalized, agent-visible portion of a Kroger product."""
    return {
        "id": product.id,
        "upc": product.upc,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "size": product.size,
        "unit": product.unit,
        "raw_size": product.raw_size,
        "price_cents": product.price_cents,
        "tags": sorted(product.tags),
        "portions": dict(product.portions),
        "stock": product.stock,
        "source": product.source,
        "availability": dict(product.availability),
    }


__all__ = [
    "KrogerAPIError",
    "KrogerClient",
    "KrogerConfigurationError",
    "KrogerLiveEnv",
    "normalize_kroger_product",
    "parse_kroger_size",
    "product_to_snapshot_row",
]
