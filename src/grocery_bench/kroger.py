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

_DECLARATION_TAGS = {
    "gluten free": "gluten_free",
    "vegan": "vegan",
    "vegetarian": "vegetarian",
    "organic": "organic",
    "gmo free": "non_gmo",
    "kosher": "kosher",
    "dairy free": "dairy_free",
    "lactose free": "lactose_free",
    "soy free": "soy_free",
    "egg free": "egg_free",
    "fish free": "fish_free",
    "shellfish free": "shellfish_free",
    "tree nuts free": "tree_nut_free",
    "free from peanuts": "peanut_free",
    "plant-based": "plant_based",
    "paleo": "paleo",
    "halal": "halal",
    "low sodium": "low_sodium",
}


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
    inventory = item.get("inventory") if isinstance(item.get("inventory"), dict) else {}
    stock_level = str(inventory.get("stockLevel") or "").upper() or None
    inventory_available = stock_level != "TEMPORARILY_OUT_OF_STOCK"
    available = price_cents > 0 and inventory_available and (any(availability.values()) if availability else True)
    raw_size = str(item.get("size") or raw.get("size") or "").strip()
    categories = [str(value) for value in (raw.get("categories") or []) if value]
    category_source = categories[0] if categories else (search_term or "unknown")
    category = re.sub(r"[^a-z0-9]+", "_", category_source.lower()).strip("_") or "unknown"
    product_id = str(raw.get("productId") or raw.get("upc") or "")
    if not product_id:
        raise ValueError("Kroger product is missing productId and UPC")
    declarations = frozenset(str(value).strip() for value in (raw.get("manufacturerDeclarations") or []) if value)
    tags = {_DECLARATION_TAGS[value.lower()] for value in declarations if value.lower() in _DECLARATION_TAGS}
    if {"tree_nut_free", "peanut_free"}.issubset(tags):
        tags.add("nut_free")
    organic_claim = str(raw.get("organicClaimName") or "").strip()
    organic = None
    if organic_claim.upper() == "NO":
        organic = False
    elif "ORGANIC" in organic_claim.upper() or "organic" in {value.lower() for value in declarations}:
        organic = True
        tags.add("organic")
    allergen_groups = _allergen_groups(raw.get("allergens") or [])
    nutrition, serving_size, servings_per_package, ingredient_statement = _nutrition(raw.get("nutritionInformation") or [])
    serving_unit = str(serving_size.get("unit") or "").lower()
    # A serving measured in "cups" is not enough to prove that the package is
    # liquid (cereal and frozen vegetables also use cup servings).  Only an
    # explicitly fluid serving unit may disambiguate a bare "oz" package size.
    liquid_hint = any(token in serving_unit for token in ("fluid", "milliliter", "liter"))
    size, unit = parse_kroger_size(raw_size, liquid_hint=liquid_hint)
    protein = nutrition.get("protein") or nutrition.get("protein_from_plant_origin")
    protein_g = None
    if protein and protein.get("unit") == "g":
        protein_g = protein.get("quantity")
    return Product(
        id=product_id,
        name=str(raw.get("description") or product_id),
        category=category,
        brand=str(raw.get("brand") or "Unknown"),
        size=size,
        unit=unit,
        price_cents=price_cents,
        tags=frozenset(tags),
        portions={},
        protein_g=protein_g,
        stock=DEFAULT_STOCK if available else 0,
        upc=str(raw.get("upc") or "") or None,
        raw_size=raw_size or None,
        source="kroger_live",
        stock_level=stock_level,
        availability=availability,
        allergens_contains=allergen_groups["contains"],
        allergens_may_contain=allergen_groups["may_contain"],
        allergens_free_from=allergen_groups["free_from"],
        declarations=declarations,
        ingredient_statement=ingredient_statement,
        nutrition=nutrition,
        serving_size=serving_size,
        servings_per_package=servings_per_package,
        organic=organic,
        sold_by=str(item.get("soldBy") or "") or None,
    )


def parse_kroger_size(raw_size: str, liquid_hint: bool = False) -> Tuple[int, str]:
    """Parse common Kroger package sizes without pretending unsupported precision."""
    text = raw_size.strip().lower().replace("fluid ounces", "fl oz").replace("fluid ounce", "fl oz")
    pack = re.search(r"\b(\d+)\s*(?:pack|pk)\b", text)
    explicit_count = re.search(r"\b(\d+)\s*(?:ct|count)\b", text)
    if pack and explicit_count is None:
        return max(1, int(pack.group(1))), "ct"
    match = re.search(
        r"((?:\d+\s+)?\d+\s*/\s*\d+|\d+(?:\.\d+)?)\s*"
        r"(fl\.?\s*oz|oz|onz|lb|lbs|lbr|kg|g|ml|l|gal|qt|pt|ct|count|ea|each)\b",
        text,
    )
    if not match:
        return 1, "unit"
    amount_text = match.group(1)
    if "/" in amount_text:
        whole_and_fraction = amount_text.split()
        fraction = whole_and_fraction[-1]
        numerator, denominator = fraction.split("/", 1)
        if float(denominator) == 0:
            return 1, "unit"
        amount = (float(whole_and_fraction[0]) if len(whole_and_fraction) == 2 else 0.0) + float(numerator) / float(denominator)
    else:
        amount = float(amount_text)
    unit = re.sub(r"[.\s]+", " ", match.group(2)).strip()
    unit = {"onz": "oz", "lbr": "lb"}.get(unit, unit)
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
    if unit == "oz" and liquid_hint:
        return max(1, round(amount * 29.5735)), "ml"
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


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _allergen_groups(rows: Any) -> Mapping[str, frozenset]:
    groups = {"contains": set(), "may_contain": set(), "free_from": set()}
    for row in rows:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        level = str(row.get("levelOfContainmentName") or "").strip().lower()
        target = {"contains": "contains", "may contain": "may_contain", "free from": "free_from"}.get(level)
        if target:
            groups[target].add(_slug(str(row["name"])))
    return {key: frozenset(values) for key, values in groups.items()}


def _nutrition(rows: Any) -> Tuple[dict, dict, Optional[float], Optional[str]]:
    if not isinstance(rows, list) or not rows:
        return {}, {}, None, None
    row = next((value for value in rows if isinstance(value, dict)), {})
    nutrition = {}
    for nutrient in row.get("nutrients") or []:
        if not isinstance(nutrient, dict) or nutrient.get("quantity") is None:
            continue
        name = _slug(str(nutrient.get("displayName") or nutrient.get("description") or nutrient.get("code") or ""))
        if not name:
            continue
        unit_data = nutrient.get("unitOfMeasure") if isinstance(nutrient.get("unitOfMeasure"), dict) else {}
        unit_name = str(unit_data.get("name") or unit_data.get("abbreviation") or "").lower()
        unit = {"gram": "g", "grams": "g", "milligram": "mg", "microgram": "mcg"}.get(unit_name, unit_name or None)
        nutrition[name] = {"quantity": nutrient["quantity"], "unit": unit}
    serving = row.get("servingSize") if isinstance(row.get("servingSize"), dict) else {}
    serving_unit = serving.get("unitOfMeasure") if isinstance(serving.get("unitOfMeasure"), dict) else {}
    serving_size = {
        "quantity": serving.get("quantity"),
        "unit": serving_unit.get("abbreviation") or serving_unit.get("name") or serving_unit.get("code"),
    }
    serving_size = {key: value for key, value in serving_size.items() if value not in (None, "")}
    per_package = row.get("servingsPerPackage") if isinstance(row.get("servingsPerPackage"), dict) else {}
    servings_value = per_package.get("value")
    try:
        servings_per_package = float(servings_value) if servings_value is not None else None
    except (TypeError, ValueError):
        servings_per_package = None
    ingredient = str(row.get("ingredientStatement") or "").strip() or None
    return nutrition, serving_size, servings_per_package, ingredient


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
        "protein_g": product.protein_g,
        "stock": product.stock,
        "source": product.source,
        "stock_level": product.stock_level,
        "availability": dict(product.availability),
        "allergens_contains": sorted(product.allergens_contains),
        "allergens_may_contain": sorted(product.allergens_may_contain),
        "allergens_free_from": sorted(product.allergens_free_from),
        "declarations": sorted(product.declarations),
        "ingredient_statement": product.ingredient_statement,
        "nutrition": dict(product.nutrition),
        "serving_size": dict(product.serving_size),
        "servings_per_package": product.servings_per_package,
        "organic": product.organic,
        "sold_by": product.sold_by,
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
