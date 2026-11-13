"""LLM agents evaluated on the grocery benchmark.

* ``IntentGroundedLLMAgent`` (ours): LangGraph state machine
  observe -> extract_intent -> [clarify -> extract_intent] -> shop <-> tools
  -> verify --(violations)--> shop ... -> finish.
  The key idea is that "the tool calls succeeded" is not accepted as "the goal
  is met": the cart is checked by deterministic code against a structured,
  quantity- and unit-aware intent, and violations are fed back for replanning.
* ``ReActAgent``: think-then-act tool loop (Yao et al., 2023).
* ``DirectFunctionCallingAgent``: one information-gathering turn, then one
  turn that emits every cart action at once; no observation of results and
  no recovery.

All three use the same LLM, the same benchmark tools (``TOOL_SPECS``) and the
same caps. Agents only see the public observation and tool outputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from typing_extensions import TypedDict

from grocery_bench.environment import GroceryEnv
from grocery_bench.tools import TOOL_SPECS

from . import prompts

TOOLS_BY_NAME = {spec["name"]: spec for spec in TOOL_SPECS}
INFO_TOOLS = [TOOLS_BY_NAME[n] for n in ("search_products", "get_product", "view_cart", "ask_user")]
CART_TOOLS = [TOOLS_BY_NAME[n] for n in ("add_to_cart", "update_quantity", "remove_from_cart")]
SHOP_TOOLS = [spec for spec in TOOL_SPECS if spec["name"] != "finish"]
SUBMIT_CART_SPEC = {
    "name": "submit_cart",
    "description": "Call when you believe the cart satisfies every requirement. Assign each product in the cart to the "
    "requirement id it fulfils. The cart will be checked; you will get a list of violations if any.",
    "parameters": {
        "type": "object",
        "properties": {
            "assignments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"product_id": {"type": "string"}, "requirement_id": {"type": "string"}},
                    "required": ["product_id", "requirement_id"],
                },
            },
            "note": {"type": "string"},
        },
        "required": ["assignments"],
    },
}


# --------------------------------------------------------------------- shared
def task_message(env: GroceryEnv, cart: dict) -> str:
    obs = env.observation()
    return prompts.TASK_TEMPLATE.format(
        instruction=obs["instruction"],
        context=json.dumps(obs["household_context"], indent=1),
        cart=json.dumps(cart),
    )


def run_tool(env: GroceryEnv, name: str, args: Optional[dict]) -> dict:
    if args is None:
        return {"ok": False, "message": "Arguments were not valid JSON", "data": None}
    return env.call(name, args)


def tool_message(call_id: str, result: Any) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, separators=(",", ":"))}


# ------------------------------------------------------------- direct baseline
class DirectFunctionCallingAgent:
    name = "direct_fc"

    def __init__(self, llm):
        self.llm = llm
        self.notes: Dict[str, Any] = {"llm": llm.describe()}

    def run(self, env: GroceryEnv) -> None:
        cart = env.view_cart().data
        messages = [
            {"role": "system", "content": prompts.DIRECT_SYSTEM},
            {"role": "user", "content": task_message(env, cart) + "\n\n" + prompts.DIRECT_TURN1},
        ]
        first = self.llm.chat(messages, tools=INFO_TOOLS, env=env)
        messages.append(first.message)
        for call in first.tool_calls:
            messages.append(tool_message(call.id, run_tool(env, call.name, call.arguments)))
        messages.append({"role": "user", "content": prompts.DIRECT_TURN2})
        second = self.llm.chat(messages, tools=CART_TOOLS, env=env)
        for call in second.tool_calls:  # executed blind: results are not shown to the model
            run_tool(env, call.name, call.arguments)
        self.notes["planned_actions"] = [{"tool": c.name, "args": c.arguments} for c in second.tool_calls]
        env.finish("direct function calling done")


# -------------------------------------------------------------- ReAct baseline
class ReActAgent:
    name = "react"

    def __init__(self, llm, max_turns: int = 40):
        self.llm = llm
        self.max_turns = max_turns
        self.notes: Dict[str, Any] = {"llm": llm.describe()}

    def run(self, env: GroceryEnv) -> None:
        cart = env.view_cart().data
        messages = [
            {"role": "system", "content": prompts.REACT_SYSTEM},
            {"role": "user", "content": task_message(env, cart)},
        ]
        nudged = False
        for _ in range(self.max_turns):
            reply = self.llm.chat(messages, tools=TOOL_SPECS, env=env)
            messages.append(reply.message)
            if not reply.tool_calls:
                if nudged:
                    break
                nudged = True
                messages.append({"role": "user", "content": prompts.REACT_NUDGE})
                continue
            for call in reply.tool_calls:
                messages.append(tool_message(call.id, run_tool(env, call.name, call.arguments)))
                if env.done:
                    return
        if not env.done:
            env.finish("react loop ended")


# ------------------------------------------------------------------------ ours
@dataclass
class AgentContext:
    env: GroceryEnv
    llm: Any
    use_clarify: bool
    use_verifier: bool
    allow_ask: bool
    max_shop_turns: int
    max_verify_rounds: int


class OursState(TypedDict, total=False):
    cart_at_start: dict
    intent: dict
    clarifications: List[dict]
    clarify_rounds: int
    messages: List[dict]
    submitted: Optional[dict]
    verify_rounds: int
    verify_reports: List[dict]
    product_cache: Dict[str, dict]
    status: str


def observe(state: OursState, runtime: Runtime[AgentContext]) -> dict:
    cart = runtime.context.env.view_cart().data
    return {"cart_at_start": cart, "clarifications": [], "clarify_rounds": 0, "verify_rounds": 0,
            "verify_reports": [], "product_cache": {}}


def extract_intent(state: OursState, runtime: Runtime[AgentContext]) -> dict:
    ctx = runtime.context
    user = task_message(ctx.env, state["cart_at_start"])
    if state["clarifications"]:
        user += "\n\nAnswers from the shopper to your earlier questions:\n" + json.dumps(state["clarifications"], indent=1)
    messages = [
        {"role": "system", "content": prompts.INTENT_SYSTEM},
        {"role": "user", "content": user + "\n\n" + prompts.INTENT_INSTRUCTIONS},
    ]
    intent = None
    for _ in range(2):
        reply = ctx.llm.chat(messages, json_mode=True, env=ctx.env)
        try:
            intent = normalize_intent(json.loads(reply.content))
            break
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as error:
            messages += [reply.message, {"role": "user", "content": f"Invalid JSON for the schema ({error}). Reply again."}]
    if intent is None:
        intent = normalize_intent({"requirements": []})
    return {"intent": intent}


def clarify(state: OursState, runtime: Runtime[AgentContext]) -> dict:
    env = runtime.context.env
    answers = list(state["clarifications"])
    for item in state["intent"]["open_questions"][:3]:
        question = item.get("question") if isinstance(item, dict) else str(item)
        obs = env.ask_user(question)
        answers.append({"question": question, "answer": obs.message})
    return {"clarifications": answers, "clarify_rounds": state["clarify_rounds"] + 1}


def start_shopping(state: OursState, runtime: Runtime[AgentContext]) -> dict:
    ctx = runtime.context
    content = task_message(ctx.env, state["cart_at_start"])
    if state["clarifications"]:
        content += "\n\nClarifications from the shopper:\n" + json.dumps(state["clarifications"], indent=1)
    content += "\n\nStructured requirements (your checklist):\n" + json.dumps(state["intent"], indent=1)
    return {"messages": [{"role": "system", "content": prompts.SHOP_SYSTEM}, {"role": "user", "content": content}]}


def shop(state: OursState, runtime: Runtime[AgentContext]) -> dict:
    """Tool loop until the model submits the cart (or the turn budget runs out)."""
    ctx = runtime.context
    messages = list(state["messages"])
    cache = dict(state["product_cache"])
    submitted = None
    for _ in range(ctx.max_shop_turns):
        tools = SHOP_TOOLS if ctx.allow_ask else [t for t in SHOP_TOOLS if t["name"] != "ask_user"]
        reply = ctx.llm.chat(messages, tools=tools + [SUBMIT_CART_SPEC], env=ctx.env)
        messages.append(reply.message)
        if not reply.tool_calls:
            messages.append({"role": "user", "content": prompts.SHOP_NUDGE})
            continue
        for call in reply.tool_calls:
            if call.name == "submit_cart":
                submitted = call.arguments or {"assignments": []}
                messages.append(tool_message(call.id, {"ok": True, "message": "Submitted for checking"}))
                continue
            result = run_tool(ctx.env, call.name, call.arguments)
            if call.name == "get_product" and result.get("ok"):
                cache[result["data"]["id"]] = result["data"]
            messages.append(tool_message(call.id, result))
        if submitted is not None:
            break
    return {"messages": messages, "submitted": submitted, "product_cache": cache}


def verify(state: OursState, runtime: Runtime[AgentContext]) -> dict:
    ctx = runtime.context
    env = ctx.env
    cache = dict(state["product_cache"])
    for pid in env.cart:
        if pid not in cache:
            obs = env.get_product(pid)
            if obs.ok:
                cache[pid] = obs.data
    initial = {item["id"]: item["quantity"] for item in state["cart_at_start"]["items"]}
    report = check_cart(state["intent"], dict(env.cart), cache, (state.get("submitted") or {}).get("assignments", []),
                        initial, env.total_cents)
    rounds = state["verify_rounds"] + 1
    messages = list(state["messages"])
    if report["violations"] and rounds <= ctx.max_verify_rounds:
        messages.append({"role": "user", "content": prompts.VERIFY_FEEDBACK.format(
            violations="\n".join(f"- {v}" for v in report["violations"]))})
    return {"verify_rounds": rounds, "verify_reports": state["verify_reports"] + [report],
            "product_cache": cache, "messages": messages, "submitted": None}


def finish(state: OursState, runtime: Runtime[AgentContext]) -> dict:
    runtime.context.env.finish("intent-grounded agent done")
    return {"status": "finished"}


def route_after_intent(state: OursState, runtime: Runtime[AgentContext]) -> Literal["clarify", "start_shopping"]:
    wants = bool(state["intent"]["open_questions"])
    if runtime.context.use_clarify and runtime.context.allow_ask and wants and state["clarify_rounds"] < 1:
        return "clarify"
    return "start_shopping"


def route_after_shop(state: OursState, runtime: Runtime[AgentContext]) -> Literal["verify", "finish"]:
    return "verify" if runtime.context.use_verifier else "finish"


def route_after_verify(state: OursState, runtime: Runtime[AgentContext]) -> Literal["shop", "finish"]:
    last = state["verify_reports"][-1]
    if last["violations"] and state["verify_rounds"] <= runtime.context.max_verify_rounds:
        return "shop"
    return "finish"


def build_ours_graph():
    g = StateGraph(OursState, context_schema=AgentContext)
    for name, fn in [("observe", observe), ("extract_intent", extract_intent), ("clarify", clarify),
                     ("start_shopping", start_shopping), ("shop", shop), ("verify", verify), ("finish", finish)]:
        g.add_node(name, fn)
    g.add_edge(START, "observe")
    g.add_edge("observe", "extract_intent")
    g.add_conditional_edges("extract_intent", route_after_intent)
    g.add_edge("clarify", "extract_intent")
    g.add_edge("start_shopping", "shop")
    g.add_conditional_edges("shop", route_after_shop)
    g.add_conditional_edges("verify", route_after_verify)
    g.add_edge("finish", END)
    return g.compile()


_GRAPH = None


class IntentGroundedLLMAgent:
    def __init__(self, llm, use_clarify: bool = True, use_verifier: bool = True, allow_ask: bool = True,
                 max_shop_turns: int = 30, max_verify_rounds: int = 2, name: Optional[str] = None):
        global _GRAPH
        if _GRAPH is None:
            _GRAPH = build_ours_graph()
        self.graph = _GRAPH
        self.llm = llm
        self.use_clarify = use_clarify
        self.use_verifier = use_verifier
        self.allow_ask = allow_ask
        self.max_shop_turns = max_shop_turns
        self.max_verify_rounds = max_verify_rounds
        suffix = "".join(["_noclarify" if not use_clarify else "", "_noverify" if not use_verifier else "",
                          "_noask" if not allow_ask else ""])
        self.name = name or f"ours{suffix}"
        self.notes: Dict[str, Any] = {"llm": llm.describe()}

    def run(self, env: GroceryEnv) -> None:
        ctx = AgentContext(env, self.llm, self.use_clarify, self.use_verifier, self.allow_ask,
                           self.max_shop_turns, self.max_verify_rounds)
        state: Dict[str, Any] = {}
        try:
            for update in self.graph.stream({}, context=ctx, config={"recursion_limit": 60}, stream_mode="values"):
                state = update
        finally:
            self.notes.update({
                "intent": state.get("intent"),
                "clarifications": state.get("clarifications"),
                "verify_reports": state.get("verify_reports"),
            })
        if not env.done:
            env.finish("intent-grounded agent done")


# ------------------------------------------------------------ intent + verify
MEASURES = ("units", "count", "volume_ml", "weight_g")


def normalize_intent(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("intent must be an object")
    requirements = []
    for index, req in enumerate(raw.get("requirements") or []):
        measure = str(req.get("measure") or "units")
        if measure not in MEASURES and not measure.startswith("portions:"):
            measure = "units"
        low = req.get("min", req.get("quantity", 1))
        high = req.get("max", low)
        requirements.append({
            "id": str(req.get("id") or f"r{index + 1}"),
            "description": str(req.get("description") or ""),
            "search_query": str(req.get("search_query") or req.get("description") or ""),
            "measure": measure,
            "min": int(low),
            "max": None if high is None else int(high),
            "required_tags": [str(t) for t in req.get("required_tags") or []],
            "product_ids": [str(p) for p in req.get("product_ids") or []],
            "brand": req.get("brand") or None,
        })
    budget = raw.get("budget_cents")
    return {
        "requirements": requirements,
        "budget_cents": None if budget in (None, "") else int(budget),
        "all_items_required_tags": [str(t) for t in raw.get("all_items_required_tags") or []],
        "preferences": raw.get("preferences") or [],
        "keep_existing_items": bool(raw.get("keep_existing_items", False)),
        "remove_unlisted_items": bool(raw.get("remove_unlisted_items", True)),
        "open_questions": [q for q in raw.get("open_questions") or [] if q],
    }


def amount_per_package(details: dict, measure: str) -> int:
    if measure == "units":
        return 1
    if measure == "count":
        return details["size"] if details["unit"] == "ct" else 0
    if measure == "volume_ml":
        return details["size"] if details["unit"] == "ml" else 0
    if measure == "weight_g":
        return details["size"] if details["unit"] == "g" else 0
    if measure.startswith("portions:"):
        return int((details.get("portions") or {}).get(measure.split(":", 1)[1], 0))
    return 0


def check_cart(intent: dict, cart: Dict[str, int], details: Dict[str, dict], assignments: List[dict],
               initial: Dict[str, int], total_cents: int) -> dict:
    """Deterministic check of the cart against the structured intent."""
    violations: List[str] = []
    reqs = {r["id"]: r for r in intent["requirements"]}
    assigned: Dict[str, str] = {}
    for item in assignments or []:
        if isinstance(item, dict) and item.get("product_id") in cart:
            assigned[item["product_id"]] = str(item.get("requirement_id"))

    for pid, qty in cart.items():
        info = details.get(pid)
        if info is None:
            violations.append(f"{pid}: could not look up product details")
            continue
        if not info.get("in_stock", True):
            violations.append(f"{pid} is out of stock; remove it and substitute")
        missing_all = set(intent["all_items_required_tags"]) - set(info.get("dietary_tags", []))
        if missing_all:
            violations.append(f"{pid} lacks required tags {sorted(missing_all)} that apply to every item")
        rid = assigned.get(pid)
        if rid is None or rid not in reqs:
            if intent["keep_existing_items"] and pid in initial:
                continue
            violations.append(f"{pid} (x{qty}) is not assigned to any requirement: remove it or assign it")
            continue
        req = reqs[rid]
        if amount_per_package(info, req["measure"]) == 0:
            violations.append(f"{pid} does not provide '{req['measure']}' for requirement {rid}")
        missing = set(req["required_tags"]) - set(info.get("dietary_tags", []))
        if missing:
            violations.append(f"{pid} lacks required tags {sorted(missing)} for requirement {rid} (unlisted tags count as unknown)")
        if req["product_ids"] and pid not in req["product_ids"]:
            violations.append(f"{pid} is not one of the specified products {req['product_ids']} for {rid}")
        if req["brand"] and info.get("brand") != req["brand"]:
            violations.append(f"{pid} is brand {info.get('brand')}, but {rid} requires {req['brand']}")

    for rid, req in reqs.items():
        amount = sum(amount_per_package(details[pid], req["measure"]) * qty
                     for pid, qty in cart.items() if assigned.get(pid) == rid and pid in details)
        if amount < req["min"] or (req["max"] is not None and amount > req["max"]):
            bound = f"[{req['min']}, {req['max']}]" if req["max"] is not None else f">= {req['min']}"
            violations.append(f"requirement {rid} ({req['description']}): {req['measure']} = {amount}, needs {bound}")

    if intent["budget_cents"] is not None and total_cents > intent["budget_cents"]:
        violations.append(f"cart total {total_cents} cents exceeds budget {intent['budget_cents']} cents")
    if intent["keep_existing_items"]:
        for pid, qty in initial.items():
            if cart.get(pid, 0) < qty:
                violations.append(f"{pid} was in the original cart (x{qty}) and must be kept")
    return {"violations": violations, "total_cents": total_cents, "cart": dict(cart)}
