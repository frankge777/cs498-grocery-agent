"""Product-choice protocol tests; no frontend, model, or network required."""

import json
import unittest

from grocery_agent.choices import ChoiceCoordinator, RequirementChoice, SimulatedChoiceProvider


def product(product_id, name, price):
    return {"id": product_id, "name": name, "brand": "Kroger", "raw_size": "1 each",
            "price_cents": price, "in_stock": True}


class ChoiceTests(unittest.TestCase):
    def coordinator(self):
        coordinator = ChoiceCoordinator([
            RequirementChoice("r1", "Which carrot?"),
            RequirementChoice("r2", "Which yogurt?"),
        ])
        coordinator.set_candidates("r1", [product("C1", "Baby Carrots", 139),
                                          product("C2", "Daikon", 179)])
        coordinator.set_candidates("r2", [product("Y1", "Plain Yogurt", 349),
                                          product("Y2", "Greek Yogurt", 399)])
        return coordinator

    def test_batch_answers_bind_to_independent_requirements_and_retry_only_failed_one(self):
        coordinator = self.coordinator()
        simulated_user = SimulatedChoiceProvider({"r1": ["C1"], "r2": ["Y2", "Y1"]})
        request = coordinator.ask_pending(simulated_user)
        self.assertEqual([q["requirement_id"] for q in request["questions"]], ["r1", "r2"])
        self.assertEqual(coordinator.requirements["r1"].selected_product_id, "C1")
        self.assertEqual(coordinator.requirements["r2"].selected_product_id, "Y2")
        self.assertEqual(coordinator.selected_total_cents({"r1": 1, "r2": 1}), 538)

        coordinator.mark_added("r1")
        coordinator.mark_unavailable("r2", "Y2")
        retry = coordinator.ask_pending(simulated_user)
        self.assertEqual([q["requirement_id"] for q in retry["questions"]], ["r2"])
        self.assertEqual([o["product_id"] for o in retry["questions"][0]["options"]], ["Y1"])
        self.assertEqual(coordinator.requirements["r1"].status, "added")
        self.assertEqual(coordinator.requirements["r2"].selected_product_id, "Y1")
        self.assertEqual(coordinator.selected_total_cents({"r1": 1, "r2": 1}), 488)

    def test_invalid_choice_does_not_partially_apply(self):
        coordinator = self.coordinator()
        request = coordinator.prepare_batch()
        first, second = request["questions"]
        with self.assertRaises(ValueError):
            coordinator.apply_answers({"answers": [
                {"decision_id": first["decision_id"], "selected_option_id": first["options"][0]["option_id"]},
                {"decision_id": second["decision_id"], "selected_option_id": "not-offered"},
            ]})
        self.assertIsNone(coordinator.requirements["r1"].selected_product_id)
        self.assertIsNone(coordinator.requirements["r2"].selected_product_id)

    def test_frontend_can_resume_from_json_checkpoint(self):
        coordinator = self.coordinator()
        request = coordinator.prepare_batch()
        snapshot = json.loads(json.dumps(coordinator.checkpoint()))
        resumed = ChoiceCoordinator.from_checkpoint(snapshot)
        response = SimulatedChoiceProvider({"r1": "C1", "r2": "Y2"})(request)
        resumed.apply_answers(response)
        self.assertEqual(resumed.requirements["r1"].selected_product_id, "C1")
        self.assertEqual(resumed.requirements["r2"].selected_product_id, "Y2")

    def test_filters_unavailable_and_invalid_prices(self):
        coordinator = self.coordinator()
        unavailable = product("C3", "No stock", 100)
        unavailable["in_stock"] = False
        coordinator.set_candidates("r1", [unavailable, product("C1", "Baby Carrots", 139),
                                          product("C1", "Baby Carrots", 139)])
        self.assertEqual([o["product_id"] for o in coordinator.prepare_batch()["questions"][0]["options"]], ["C1"])


if __name__ == "__main__":
    unittest.main()
