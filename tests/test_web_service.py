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
