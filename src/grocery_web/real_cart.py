"""Explicit, addition-only handoff from a completed local live plan to Kroger.

No real writes are installed in agent tools or benchmark environments. A stable
purchase ID, server-side preview and separate confirmation fence every request.
"""

import hashlib
import json
import re
import secrets

from grocery_agent.intent_schema import fact_violations
from grocery_agent.quantity_interpretation import quantity_fingerprint
from grocery_agent.llm_agents import amount_per_package
from grocery_agent.choices import choice_brand_matches
from grocery_bench.kroger import normalize_kroger_product
from .kroger_account import AccountError, AccountHTTPError


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def completed_addition(result):
    """Only accept an explicitly completed local live workflow, not search hits."""
    if not isinstance(result, dict):
        raise ValueError("Expected a saved live workflow object")
    steps = result.get("steps", [])
    if not isinstance(steps, list) or any(not isinstance(s, dict) for s in steps):
        raise ValueError("Expected live workflow steps")
    if len(steps) < 2 or steps[0].get("cart", {}).get("items"):
        raise ValueError("Use a live workflow starting from an empty LOCAL cart; real cart is addition-only")
    final = steps[-1]
    if (final.get("status") != "complete" or final.get("data_source") != "live"
            or final.get("verification", {}).get("ok") is not True):
        raise ValueError("A completed and verified LIVE local plan is required")
    drafts = [s["recommendation"] for s in steps[:-1] if s.get("status") == "awaiting_basket_confirmation"]
    if not drafts:
        raise ValueError("Missing reviewed local basket")
    draft = drafts[-1]
    items = final["cart"].get("items", [])
    if not items or len(items) > 20:
        raise ValueError("A local submission supports 1..20 product lines")
    targets = {}
    for item in items:
        pid, qty = item.get("id"), item.get("quantity")
        if (not isinstance(pid, str) or not re.fullmatch(r"\d{13}", pid) or pid in targets
                or isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 99):
            raise ValueError("Unique 13-digit UPCs and integer quantities 1..99 are required")
        targets[pid] = qty
    draft_targets = {i["product_id"]: i["quantity"] for i in draft["items"]}
    if targets != final["verification"].get("expected_cart") or targets != draft_targets:
        raise ValueError("Verified cart and reviewed draft do not agree")
    operations = draft.get("operations", [])
    if (len(operations) != len(targets) or any(o.get("action") != "add" or o.get("from_quantity") != 0
            or o.get("to_quantity") != targets.get(o.get("product_id")) for o in operations)
            or {o.get("product_id") for o in operations} != set(targets)):
        raise ValueError("Kroger public API cannot apply local remove/update/replace-cart operations")
    location = final.get("location", {}).get("location_id")
    if not isinstance(location, str) or not re.fullmatch(r"\d{8}", location):
        raise ValueError("Verified store location required")
    budget = draft.get("budget_cents")
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int) or budget < 0):
        raise ValueError("Invalid addition budget")
    requirements = final.get("requirement_states", [])
    if final.get("schema_version") != 2 or not requirements:
        raise ValueError("A v2 result with quantity interpretations and hard constraints is required")
    assigned = {}
    for requirement in requirements:
        pid, qty = requirement.get("selected_product_id"), requirement.get("quantity")
        if (requirement.get("status") != "added" or pid not in targets or isinstance(qty, bool)
                or not isinstance(qty, int) or qty < 1 or not requirement.get("active_requirement")):
            raise ValueError("Every requirement must be resolved and bound to the verified cart")
        assigned[pid] = assigned.get(pid, 0) + qty
    if assigned != targets:
        raise ValueError("Requirement assignments do not match the cart")
    return {"quantities": targets, "location_id": location, "budget_cents": budget,
            "requirements": requirements}


class RealCartBridge:
    def __init__(self, account):
        self.account = account
        self.store = account.store

    def _quote(self, target, modality):
        lines = []
        details = {}
        for pid, quantity in sorted(target["quantities"].items()):
            product = normalize_kroger_product(self.account.client.get_product(pid, target["location_id"]))
            detail = product.public_details(product.stock > 0)
            if (product.id != pid or not detail["in_stock"] or product.price_cents <= 0
                    or product.availability.get("curbside" if modality == "PICKUP" else "delivery") is not True):
                raise AccountError(f"Product {pid} is unavailable for {modality}; rerun the shopping workflow")
            if not product.upc or not re.fullmatch(r"\d{13}", product.upc):
                raise AccountError("Cannot submit a product without a tool-observed UPC")
            details[pid] = detail
            lines.append({"product_id": pid, "upc": product.upc, "name": product.name,
                          "package_size": product.raw_size, "quantity": quantity,
                          "price_cents": product.price_cents, "line_total_cents": product.price_cents * quantity})
        for requirement in target["requirements"]:
            pid = requirement.get("selected_product_id")
            if pid not in details:
                raise AccountError("An unresolved requirement cannot be submitted")
            detail = details[pid]
            active = requirement.get("active_requirement") or {}
            if fact_violations(detail, active.get("constraints", [])):
                raise AccountError(f"Product {pid} no longer satisfies hard constraints")
            if ((active.get("product_ids") and pid not in active["product_ids"])
                    or not choice_brand_matches(active.get("brand"), active.get("description", ""), detail)):
                raise AccountError(f"Product {pid} no longer matches the bound product/brand")
            amount = amount_per_package(detail, requirement["measure"]) * requirement["quantity"]
            minimum, maximum = requirement.get("target_min"), requirement.get("target_max")
            if minimum is None or amount < minimum or (maximum is not None and amount > maximum):
                raise AccountError(f"Product {pid} no longer meets the target quantity")
            interpretation = requirement.get("quantity_interpretation") or {}
            if interpretation.get("status") != "proposal" or interpretation.get("facts_fingerprint") != quantity_fingerprint(detail):
                raise AccountError(f"Product {pid} specifications changed or quantity was not interpreted; rerun workflow")
        subtotal = sum(i["line_total_cents"] for i in lines)
        if target["budget_cents"] is not None and subtotal > target["budget_cents"]:
            raise AccountError("Fresh addition subtotal exceeds budget; rerun workflow")
        return {"items": lines, "subtotal_cents": subtotal, "location_id": target["location_id"],
                "modality": modality, "budget_cents": target["budget_cents"],
                "facts_hash": digest(details), "remote_cart_total_known": False}

    def prepare(self, result, purchase_id, modality="PICKUP"):
        if not isinstance(purchase_id, str) or not 1 <= len(purchase_id) <= 128:
            raise ValueError("Stable purchase_id required; reuse it when resuming the same intended addition")
        if modality not in {"PICKUP", "DELIVERY"}:
            raise ValueError("Use PICKUP or DELIVERY")
        target = completed_addition(result)
        value = self.account.access()
        # Re-authorizing the SAME shopper must not erase an ambiguous previous
        # attempt. The intent ID remains blocked even when grant_id changes.
        operation = digest(purchase_id)
        quote = self._quote(target, modality)
        data = {"target": target, "quote": quote, "modality": modality,
                "expires_at": self.account.clock() + 300}
        with self.store.transaction() as db:
            current = self.store.account(db)
            if current["grant_id"] != value["grant_id"]:
                raise AccountError("Account changed during preview; start again")
            old = db.execute("SELECT * FROM submissions WHERE operation_id=?", (operation,)).fetchone()
            if old:
                if old["status"] in {"submitted", "submitting", "unknown"}:
                    raise AccountError("This intended addition was sent or may have been sent; inspect Kroger cart, do not resubmit")
                previous = json.loads(old["data"])
                if previous["target"] != target or previous["modality"] != modality:
                    raise AccountError("purchase_id is bound to a different intended addition")
            plan_id = "cart_" + secrets.token_urlsafe(24)
            db.execute("INSERT OR REPLACE INTO submissions VALUES (?, ?, ?, 'prepared', ?)",
                       (operation, plan_id, value["grant_id"], json.dumps(data)))
        return self._preview(plan_id, data)

    @staticmethod
    def _preview(plan_id, data):
        return {"status": "awaiting_real_cart_confirmation", "plan_id": plan_id,
                **data["quote"], "expires_at": data["expires_at"],
                "effect": "ADD these quantities to existing Kroger cart; existing contents cannot be read or replaced",
                "cart_verification": "User must inspect Kroger cart after submission; this is not checkout"}

    def commit(self, plan_id, confirmation):
        if not isinstance(plan_id, str) or confirmation != plan_id:
            raise ValueError("Explicit confirmation of this exact plan_id is required")
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM submissions WHERE plan_id=?", (plan_id,)).fetchone()
            if not row:
                raise AccountError("Unknown or superseded plan")
            data = json.loads(row["data"])
            if row["status"] == "submitted":
                return data["receipt"]
            if row["status"] != "prepared":
                raise AccountError("Submission is in-flight, rejected or uncertain; do not automatically retry")
            if self.account.clock() >= data["expires_at"]:
                raise AccountError("Preview expired; prepare and review again")
            grant_id = row["grant_id"]
        account = self.account.access(expected_grant=grant_id)
        quote = self._quote(data["target"], data["modality"])
        if quote != data["quote"]:
            with self.store.transaction() as db:
                fresh = db.execute("SELECT status FROM submissions WHERE plan_id=?", (plan_id,)).fetchone()
                if not fresh or fresh[0] != "prepared":
                    raise AccountError("Plan changed while refreshing")
                data.update(quote=quote, expires_at=self.account.clock() + 300)
                new_id = "cart_" + secrets.token_urlsafe(24)
                db.execute("UPDATE submissions SET plan_id=?, data=? WHERE plan_id=?", (new_id, json.dumps(data), plan_id))
            return {**self._preview(new_id, data), "status": "needs_reconfirmation"}
        # Persist before the network call. A crash/timeout leaves a durable
        # non-retryable state instead of blindly adding the same items twice.
        with self.store.transaction() as db:
            if self.store.account(db)["grant_id"] != grant_id:
                raise AccountError("Account changed before dispatch")
            changed = db.execute("UPDATE submissions SET status='submitting' WHERE plan_id=? AND status='prepared'", (plan_id,)).rowcount
            if changed != 1:
                raise AccountError("Plan already dispatched or superseded")
        items = [{"upc": i["upc"], "quantity": i["quantity"], "modality": data["modality"]} for i in quote["items"]]
        try:
            self.account.add(items, account["access_token"])
        except Exception as error:
            status = "rejected" if isinstance(error, AccountHTTPError) and error.status in {400, 401, 403} else "unknown"
            with self.store.transaction() as db:
                db.execute("UPDATE submissions SET status=? WHERE plan_id=?", (status, plan_id))
            raise AccountError(f"Cart submission {status}; inspect Kroger cart before any new attempt") from None
        receipt = {"status": "submitted", "plan_id": plan_id, "api_request_accepted": True,
                   "verified_remote_cart": False, "requires_user_cart_check": True,
                   "items": quote["items"], "addition_subtotal_cents": quote["subtotal_cents"],
                   "checkout_performed": False}
        data["receipt"] = receipt
        with self.store.transaction() as db:
            db.execute("UPDATE submissions SET status='submitted', data=? WHERE plan_id=?", (json.dumps(data), plan_id))
        return receipt
