import unittest

from grocery_web import service


class WebServiceTest(unittest.TestCase):
    def test_snapshot_search_returns_products_and_location(self):
        result = service.search_products("whole milk", source="snapshot", limit=3)
        self.assertEqual(result["data_source"], "snapshot")
        self.assertEqual(result["location"]["location_id"], "02100946")
        self.assertTrue(result["products"])

    def test_snapshot_env_routes_clarification_to_handler(self):
        asked = []
        env = service.SnapshotEnv("buy milk", {}, lambda q: asked.append(q) or "2% please")
        obs = env.ask_user("Which milk fat level?")
        self.assertEqual(obs.message, "2% please")
        self.assertEqual(asked, ["Which milk fat level?"])

    def test_run_agent_rejects_empty_instruction(self):
        with self.assertRaises(service.ServiceError):
            service.run_agent("   ", source="snapshot")

    def test_unknown_source_rejected(self):
        with self.assertRaises(service.ServiceError):
            service.resolve_source("bogus")


if __name__ == "__main__":
    unittest.main()


class WebUiEndpointTests(unittest.TestCase):
    def test_snapshot_product_detail_has_images(self):
        from grocery_web import service

        detail = service.product_detail("0001111085020", "snapshot")
        self.assertEqual(detail["name"], "Kroger® Thin Spaghetti")
        self.assertTrue(detail["images"][0]["url"].endswith("/front/0001111085020"))
        with self.assertRaises(service.ServiceError):
            service.product_detail("not-a-upc", "snapshot")

    def test_api_image_list_is_preferred(self):
        from grocery_web.service import image_urls

        rows = image_urls([{"perspective": "back", "sizes": [{"size": "small", "url": "s"}, {"size": "large", "url": "L"}]}], "1")
        self.assertEqual(rows, [{"perspective": "back", "url": "L", "default": False}])

    def test_stream_emits_tool_events_then_result(self):
        import json
        from grocery_web import service
        from grocery_web.streaming import stream

        def fake(on_env=None):
            env = service.SnapshotEnv("x", {})
            on_env(env)
            env.search_products("spaghetti")
            return {"status": "ok"}

        lines = [json.loads(l) for l in stream(fake)]
        self.assertEqual(lines[0]["tool"], "search_products")
        self.assertEqual(lines[-1], {"type": "result", "data": {"status": "ok"}})

        def broken(on_env=None):
            raise service.ServiceError("nope", status=422)

        self.assertEqual(list(map(json.loads, stream(broken))), [{"type": "error", "status": 422, "detail": "nope"}])

    def test_real_cart_is_unavailable_when_hosted(self):
        import os
        from unittest import mock
        from grocery_web import real_cart_service, service

        with mock.patch.dict(os.environ, {"VERCEL": "1"}):
            self.assertFalse(real_cart_service.status()["available"])
            with self.assertRaises(service.ServiceError) as ctx:
                real_cart_service.prepare([{"status": "complete"}])
            self.assertEqual(ctx.exception.status, 501)
