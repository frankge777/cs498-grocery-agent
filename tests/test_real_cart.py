"""OAuth and real-cart side effect boundaries; no real account writes in tests."""

import copy
import json
import os
import tempfile
import unittest
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from grocery_bench.kroger import normalize_kroger_product
from grocery_agent.quantity_interpretation import quantity_fingerprint
from grocery_web.kroger_account import AccountStore, KrogerAccount, AccountError, AccountHTTPError
from grocery_web.real_cart import RealCartBridge, completed_addition
from tests.test_kroger_live import MILK


class Transport:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.token = {"access_token": "user-token", "refresh_token": "refresh-2", "expires_in": 1800,
                      "scope": "cart.basic:write"}

    def request(self, method, url, headers, data, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "data": data})
        if method == "POST":
            return self.token
        if self.failure:
            raise self.failure
        return {}


def artifact(raw):
    p = normalize_kroger_product(raw)
    detail = p.public_details(True)
    line = {"id": p.id, "quantity": 1}
    target = {p.id: 1}
    requirement = {"requirement_id": "r1", "status": "added", "selected_product_id": p.id,
        "quantity": 1, "measure": "units", "target_min": 1, "target_max": 1,
        "active_requirement": {"description": "one milk carton", "brand": "Kroger", "constraints": [
            {"kind": "tag", "value": "gluten_free"}]},
        "quantity_interpretation": {"status": "proposal", "facts_fingerprint": quantity_fingerprint(detail)}}
    return {"steps": [{"status": "awaiting_basket_confirmation", "cart": {"items": []}, "recommendation": {
        "budget_cents": 500, "items": [{"product_id": p.id, "quantity": 1}], "operations": [
            {"action": "add", "product_id": p.id, "from_quantity": 0, "to_quantity": 1}]}},
        {"status": "complete", "schema_version": 2, "data_source": "live", "location": {"location_id": "02100946"},
         "cart": {"items": [line]}, "verification": {"ok": True, "expected_cart": target},
         "requirement_states": [requirement]}]}


class AccountFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = AccountStore(Path(self.temp.name) / "account.sqlite3")
        self.raw = copy.deepcopy(MILK)
        self.client = SimpleNamespace(client_id="client-id", client_secret="client-secret",
                                      get_product=lambda *args: self.raw)
        self.transport = Transport()
        self.now = 100.0
        self.account = KrogerAccount(self.store, self.client, self.transport, lambda: self.now)
        with self.store.transaction() as db:
            self.store.save_account({"access_token": "user-original", "refresh_token": "refresh-original",
                "expires_at": 1000, "scope": "cart.basic:write", "grant_id": "grant-1", "client_id": "client-id"}, db)

    def callback(self):
        flow = self.account.start()
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(flow["authorization_url"]).query)
        return flow["redirect_uri"] + "?" + urllib.parse.urlencode({"state": params["state"][0], "code": "auth-code"}), params


class AccountTests(AccountFixture, unittest.TestCase):
    def test_oauth_uses_pkce_and_user_code_not_product_credentials_grant(self):
        callback, params = self.callback()
        self.assertEqual(params["scope"], ["cart.basic:write"])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertTrue(self.account.complete(callback)["authorized"])
        fields = urllib.parse.parse_qs(self.transport.calls[0]["data"].decode())
        self.assertEqual(fields["grant_type"], ["authorization_code"])
        self.assertTrue(fields["code_verifier"])
        self.assertNotIn("access_token", self.account.status())
        self.assertNotIn("user-token", json.dumps(self.account.status()))

    def test_unknown_state_rejected_without_token_exchange(self):
        callback, params = self.callback()
        with self.assertRaises(AccountError):
            self.account.complete(callback.replace(params["state"][0], "unknown-state"))
        self.assertFalse(self.transport.calls)

    def test_callback_is_single_use(self):
        callback, _ = self.callback()
        self.account.complete(callback)
        with self.assertRaises(AccountError):
            self.account.complete(callback)
        self.assertEqual(len(self.transport.calls), 1)

    def test_wrong_callback_host_cannot_consume_valid_flow(self):
        callback, _ = self.callback()
        with self.assertRaises(AccountError):
            self.account.complete(callback.replace("127.0.0.1", "other.example"))
        self.assertTrue(self.account.complete(callback)["authorized"])

    def test_expired_oauth_state_rejected(self):
        callback, _ = self.callback()
        self.now += 601
        with self.assertRaises(AccountError):
            self.account.complete(callback)
        self.assertFalse(self.transport.calls)

    def test_denial_preserves_previous_account(self):
        callback, _ = self.callback()
        with self.assertRaises(AccountError):
            self.account.complete(callback.replace("code=auth-code", "error=access_denied"))
        self.assertEqual(self.store.account()["grant_id"], "grant-1")

    def test_product_scope_cannot_be_saved_as_cart_scope(self):
        callback, _ = self.callback()
        self.transport.token["scope"] = "product.compact"
        with self.assertRaises(AccountError):
            self.account.complete(callback)
        self.assertEqual(self.store.account()["grant_id"], "grant-1")

    def test_refresh_rotation_is_persisted_and_reused(self):
        self.now = 990
        first = self.account.access()
        self.assertEqual(first["refresh_token"], "refresh-2")
        self.assertEqual(self.account.access()["access_token"], "user-token")
        self.assertEqual(len(self.transport.calls), 1)
        fields = urllib.parse.parse_qs(self.transport.calls[0]["data"].decode())
        self.assertEqual(fields["grant_type"], ["refresh_token"])

    def test_private_storage_and_local_callback_only(self):
        self.assertEqual(os.stat(self.store.path).st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            self.account.start("http://external.example:8765/oauth/callback")


class RealCartTests(AccountFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bridge = RealCartBridge(self.account)
        self.result = artifact(self.raw)

    def prepare(self, **kwargs):
        return self.bridge.prepare(self.result, "stable-purchase", **kwargs)

    def puts(self):
        return [c for c in self.transport.calls if c["method"] == "PUT"]

    def test_preview_does_not_write_and_commit_uses_user_token(self):
        plan = self.prepare()
        self.assertEqual(plan["subtotal_cents"], 349)
        self.assertFalse(self.puts())
        with self.assertRaises(ValueError):
            self.bridge.commit(plan["plan_id"], "wrong-confirmation")
        receipt = self.bridge.commit(plan["plan_id"], plan["plan_id"])
        self.assertTrue(receipt["api_request_accepted"])
        self.assertFalse(receipt["verified_remote_cart"])
        self.assertFalse(receipt["checkout_performed"])
        call = self.puts()[0]
        self.assertEqual(call["headers"]["Authorization"], "Bearer user-original")
        self.assertEqual(json.loads(call["data"]), {"items": [{"upc": MILK["upc"], "quantity": 1, "modality": "PICKUP"}]})

    def test_same_confirmed_plan_not_sent_twice(self):
        pid = self.prepare()["plan_id"]
        self.assertEqual(self.bridge.commit(pid, pid), self.bridge.commit(pid, pid))
        self.assertEqual(len(self.puts()), 1)
        with self.assertRaises(AccountError):
            self.prepare()

    def test_concurrent_confirmations_dispatch_at_most_once(self):
        pid = self.prepare()["plan_id"]
        def commit(_):
            try:
                return self.bridge.commit(pid, pid)
            except AccountError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(commit, range(2)))
        self.assertEqual(len(self.puts()), 1)

    def test_price_change_requires_new_confirmation(self):
        pid = self.prepare()["plan_id"]
        self.raw["items"][0]["price"]["promo"] = 3.79
        changed = self.bridge.commit(pid, pid)
        self.assertEqual(changed["status"], "needs_reconfirmation")
        self.assertEqual(changed["subtotal_cents"], 379)
        self.assertFalse(self.puts())
        with self.assertRaises(AccountError):
            self.bridge.commit(pid, pid)
        self.bridge.commit(changed["plan_id"], changed["plan_id"])
        self.assertEqual(len(self.puts()), 1)

    def test_timeout_blocks_retries_including_new_previews(self):
        pid = self.prepare()["plan_id"]
        self.transport.failure = TimeoutError("ambiguous")
        for attempt in range(2):
            with self.assertRaises(AccountError):
                self.bridge.commit(pid, pid)
        with self.assertRaises(AccountError):
            self.prepare()
        self.assertEqual(len(self.puts()), 1)

    def test_signing_in_again_does_not_clear_uncertain_submission(self):
        pid = self.prepare()["plan_id"]
        self.transport.failure = TimeoutError("ambiguous")
        with self.assertRaises(AccountError):
            self.bridge.commit(pid, pid)
        callback, _ = self.callback()
        self.account.complete(callback)
        with self.assertRaises(AccountError):
            self.prepare()
        self.assertEqual(len(self.puts()), 1)

    def test_api_403_not_silently_refreshed_or_retried(self):
        pid = self.prepare()["plan_id"]
        self.transport.failure = AccountHTTPError(403)
        with self.assertRaises(AccountError):
            self.bridge.commit(pid, pid)
        with self.assertRaises(AccountError):
            self.bridge.commit(pid, pid)
        self.assertEqual(len(self.puts()), 1)

    def test_inventory_loss_before_commit_never_writes(self):
        pid = self.prepare()["plan_id"]
        self.raw["items"][0]["inventory"]["stockLevel"] = "TEMPORARILY_OUT_OF_STOCK"
        with self.assertRaises(AccountError):
            self.bridge.commit(pid, pid)
        self.assertFalse(self.puts())

    def test_missing_required_label_cannot_be_overridden_by_confirmation(self):
        pid = self.prepare()["plan_id"]
        self.raw["manufacturerDeclarations"] = []
        with self.assertRaises(AccountError):
            self.bridge.commit(pid, pid)
        self.assertFalse(self.puts())

    def test_packaging_change_requires_workflow_quantity_recheck(self):
        pid = self.prepare()["plan_id"]
        self.raw["items"][0]["size"] = "2 gal"
        with self.assertRaises(AccountError):
            self.bridge.commit(pid, pid)
        self.assertFalse(self.puts())

    def test_expired_preview_never_writes(self):
        pid = self.prepare()["plan_id"]
        self.now += 301
        with self.assertRaises(AccountError):
            self.bridge.commit(pid, pid)
        self.assertFalse(self.puts())

    def test_new_account_invalidates_previous_plan(self):
        pid = self.prepare()["plan_id"]
        callback, _ = self.callback()
        self.account.complete(callback)
        with self.assertRaises(AccountError):
            self.bridge.commit(pid, pid)
        self.assertFalse(self.puts())

    def test_snapshot_and_remove_operations_are_rejected(self):
        self.result["steps"][-1]["data_source"] = "snapshot"
        with self.assertRaises(ValueError):
            self.prepare()
        self.result = artifact(self.raw)
        self.result["steps"][0]["recommendation"]["operations"][0]["action"] = "remove"
        with self.assertRaises(ValueError):
            self.prepare()

    def test_wrong_modality_and_over_budget_do_not_write(self):
        self.raw["items"][0]["fulfillment"]["curbside"] = False
        with self.assertRaises(AccountError):
            self.prepare()
        self.raw["items"][0]["fulfillment"]["curbside"] = True
        self.raw["items"][0]["price"]["promo"] = 5.99
        with self.assertRaises(AccountError):
            self.prepare()
        self.assertFalse(self.puts())

    def test_saved_real_gpt_demo_is_importable_without_reinterpreting_intent(self):
        p = Path(__file__).resolve().parents[1] / "outputs/gpt_codex_live_20261127.json"
        target = completed_addition(json.loads(p.read_text()))
        self.assertEqual(target["quantities"], {"0001111060903": 1})
        self.assertEqual(target["budget_cents"], 500)


if __name__ == "__main__":
    unittest.main()
