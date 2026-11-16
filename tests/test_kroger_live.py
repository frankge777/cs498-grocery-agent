"""Offline tests for the real Kroger adapter; no credentials or network needed."""

import os
import unittest
import urllib.parse
from unittest.mock import patch

from grocery_bench.kroger import (
    KrogerClient,
    KrogerConfigurationError,
    KrogerLiveEnv,
    normalize_kroger_product,
    parse_kroger_size,
)


MILK = {
    "productId": "0001111041700",
    "upc": "0001111041700",
    "brand": "Kroger",
    "description": "Kroger Whole Milk",
    "categories": ["Dairy"],
    "items": [{
        "size": "1 gal",
        "price": {"regular": 3.99, "promo": 3.49},
        "inventory": {"stockLevel": "HIGH"},
        "fulfillment": {"inStore": True, "curbside": True, "delivery": False, "shipToHome": False},
    }],
}


class FakeKrogerClient:
    def nearest_location(self, zip_code, chain="Kroger"):
        return {"locationId": "02100350", "name": "Kroger - Urbana", "chain": "Kroger",
                "address": {"zipCode": zip_code}}

    def search_products(self, term, location_id, limit=20, **kwargs):
        return [MILK]

    def get_product(self, product_id, location_id):
        return MILK


class FakeTransport:
    def __init__(self):
        self.requests = []

    def request(self, method, url, headers, data, timeout):
        self.requests.append({"method": method, "url": url, "headers": headers, "data": data})
        if url.endswith("/connect/oauth2/token"):
            return {"access_token": "test-token", "expires_in": 1800}
        if "/locations?" in url:
            return {"data": [{"locationId": "02100350", "name": "Kroger - Urbana"}]}
        if "/products?" in url:
            return {"data": [MILK]}
        raise AssertionError(f"unexpected request: {url}")


class KrogerAdapterTests(unittest.TestCase):
    def test_configuration_requires_credentials(self):
        with patch("grocery_bench.kroger._load_repo_dotenv"), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(KrogerConfigurationError):
                KrogerClient()

    def test_normalizes_real_product_price_size_and_availability(self):
        product = normalize_kroger_product(MILK, "whole milk")
        self.assertEqual(product.id, "0001111041700")
        self.assertEqual(product.price_cents, 349)
        self.assertEqual((product.size, product.unit), (3785, "ml"))
        self.assertEqual(product.source, "kroger_live")
        self.assertEqual(product.stock_level, "HIGH")
        self.assertTrue(product.availability["inStore"])
        self.assertEqual(product.tags, frozenset())

    def test_client_uses_store_filters_and_reuses_token(self):
        transport = FakeTransport()
        client = KrogerClient("client", "secret", transport=transport, clock=lambda: 100.0)
        locations = client.search_locations("61820")
        products = client.search_products("whole milk", "02100350", limit=7)
        self.assertEqual(locations[0]["locationId"], "02100350")
        self.assertEqual(products[0]["productId"], MILK["productId"])
        self.assertEqual(sum(r["method"] == "POST" for r in transport.requests), 1)
        location_query = urllib.parse.parse_qs(urllib.parse.urlsplit(transport.requests[1]["url"]).query)
        product_query = urllib.parse.parse_qs(urllib.parse.urlsplit(transport.requests[2]["url"]).query)
        self.assertEqual(location_query["filter.zipCode.near"], ["61820"])
        self.assertEqual(product_query["filter.locationId"], ["02100350"])
        self.assertEqual(product_query["filter.limit"], ["7"])
        self.assertEqual(transport.requests[1]["headers"]["Authorization"], "Bearer test-token")

    def test_size_parser(self):
        self.assertEqual(parse_kroger_size("12 ct"), (12, "ct"))
        self.assertEqual(parse_kroger_size("32 fl oz"), (946, "ml"))
        self.assertEqual(parse_kroger_size("16 oz"), (454, "g"))
        self.assertEqual(parse_kroger_size("unknown"), (1, "unit"))

    def test_live_environment_reads_kroger_and_keeps_cart_local(self):
        env = KrogerLiveEnv.from_zip("61820", "Buy one gallon of whole milk", client=FakeKrogerClient())
        result = env.search_products("whole milk", 5)
        self.assertTrue(result.ok)
        self.assertEqual(result.data["products"][0]["source"], "kroger_live")
        self.assertEqual(result.data["location_id"], "02100350")
        added = env.add_to_cart("0001111041700", 1)
        self.assertTrue(added.ok)
        self.assertEqual(env.total_cents, 349)
        # The public API reports availability, not an exact count. A synthetic
        # stock cap must therefore not reject a larger local quantity.
        self.assertTrue(env.update_quantity("0001111041700", 25).ok)
        self.assertEqual(env.total_cents, 349 * 25)
        self.assertEqual(env.cart, {"0001111041700": 25})
        self.assertEqual(env.observation()["data_source"], "Kroger Public API (live)")


if __name__ == "__main__":
    unittest.main()
