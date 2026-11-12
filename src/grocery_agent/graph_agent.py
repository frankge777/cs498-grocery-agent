"""LangGraph implementation of the intent-grounded agent.

The graph mirrors ``IntentGroundedAgent`` node for node so the two can be
compared directly; the only difference is that control flow lives in explicit
nodes and conditional edges instead of a hand-written ``while`` loop:

    parse_intent -> verify --(complete / step limit)--> finish -> END
                      |  ^
            (missing) v  | (ok)          (failed)
                    search_select -> add_to_cart ---> replan -> verify
                      |
           (no feasible candidate) -> finish

The environment and parser are passed as run-time context rather than stored
in graph state, so the state stays plain data. Later, ``parse_intent`` and
``search_select`` are the nodes to replace with LLM calls.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, List, Literal, Optional, Set

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from typing_extensions import TypedDict

from .agents import BaseShoppingAgent, _intent_dict, _products_from_result
from .environment import GroceryEnvironment
from .intent import IntentParser
from .models import AgentRun, ParsedIntent, Product, Requirement


@dataclass
class ShoppingContext:
    env: GroceryEnvironment
    parser: IntentParser
    max_steps: int


class ShoppingState(TypedDict, total=False):
    instruction: str
    intent: ParsedIntent
    # Requirement still unmet in the current iteration, and the product picked for it.
    current: Optional[Requirement]
    chosen: Optional[Product]
    last_add_ok: bool
    failed_products: Set[str]
    steps: int
    replans: int
    status: str
    trace: Annotated[List[dict], operator.add]


def parse_intent(state: ShoppingState, runtime: Runtime[ShoppingContext]) -> dict:
    intent = runtime.context.parser.parse(state["instruction"])
    return {
        "intent": intent,
        "failed_products": set(),
        "steps": 0,
        "replans": 0,
        "trace": [{"phase": "parse", "intent": _intent_dict(intent)}],
    }


def verify(state: ShoppingState, runtime: Runtime[ShoppingContext]) -> dict:
    if state["steps"] >= runtime.context.max_steps:
        return {"status": "step_limit", "current": None}
    counts = BaseShoppingAgent._cart_counts(runtime.context.env)
    for requirement in state["intent"].requirements:
        have = counts[requirement.category]
        if have < requirement.quantity:
            return {
                "status": "missing",
                "current": Requirement(requirement.category, requirement.quantity - have),
            }
    return {
        "status": "complete",
        "current": None,
        "trace": [{"phase": "verify", "status": "complete"}],
    }


def search_select(state: ShoppingState, runtime: Runtime[ShoppingContext]) -> dict:
    env = runtime.context.env
    intent = state["intent"]
    requirement = state["current"]
    search = env.search(requirement.category)
    products = _products_from_result(search.data or {})
    candidates = BaseShoppingAgent._valid_candidates(products, intent, state["failed_products"])
    affordable = [
        product
        for product in candidates
        if intent.budget is None
        or env.total_cost + product.price * requirement.quantity <= intent.budget + 1e-9
    ]
    if not affordable:
        return {
            "status": "no_feasible_candidate",
            "chosen": None,
            "trace": [
                {
                    "phase": "verify",
                    "category": requirement.category,
                    "status": "no_feasible_candidate",
                }
            ],
        }
    return {"chosen": affordable[0]}


def add_to_cart(state: ShoppingState, runtime: Runtime[ShoppingContext]) -> dict:
    requirement = state["current"]
    chosen = state["chosen"]
    result = runtime.context.env.add_to_cart(chosen.id, requirement.quantity)
    return {
        "steps": state["steps"] + 1,
        "last_add_ok": result.ok,
        "trace": [
            {
                "phase": "execute",
                "category": requirement.category,
                "product_id": chosen.id,
                "quantity": requirement.quantity,
                "ok": result.ok,
                "message": result.message,
            }
        ],
    }


def replan(state: ShoppingState) -> dict:
    failed = state["chosen"].id
    return {
        "failed_products": state["failed_products"] | {failed},
        "replans": state["replans"] + 1,
        "trace": [{"phase": "replan", "failed_product": failed}],
    }


def finish(state: ShoppingState, runtime: Runtime[ShoppingContext]) -> dict:
    runtime.context.env.view_cart()
    return {}


def route_after_verify(state: ShoppingState) -> Literal["search_select", "finish"]:
    return "search_select" if state["status"] == "missing" else "finish"


def route_after_search(state: ShoppingState) -> Literal["add_to_cart", "finish"]:
    return "add_to_cart" if state.get("chosen") is not None else "finish"


def route_after_add(state: ShoppingState) -> Literal["verify", "replan"]:
    return "verify" if state["last_add_ok"] else "replan"


def build_graph():
    builder = StateGraph(ShoppingState, context_schema=ShoppingContext)
    builder.add_node("parse_intent", parse_intent)
    builder.add_node("verify", verify)
    builder.add_node("search_select", search_select)
    builder.add_node("add_to_cart", add_to_cart)
    builder.add_node("replan", replan)
    builder.add_node("finish", finish)

    builder.add_edge(START, "parse_intent")
    builder.add_edge("parse_intent", "verify")
    builder.add_conditional_edges("verify", route_after_verify)
    builder.add_conditional_edges("search_select", route_after_search)
    builder.add_conditional_edges("add_to_cart", route_after_add)
    builder.add_edge("replan", "verify")
    builder.add_edge("finish", END)
    return builder.compile()


class LangGraphIntentAgent:
    """Same behaviour as ``IntentGroundedAgent``, orchestrated with LangGraph."""

    name = "langgraph_intent"

    def __init__(self, max_steps: int = 40, parser: Optional[IntentParser] = None):
        self.max_steps = max_steps
        self.parser = parser or IntentParser(infer_bundles=True)
        self.graph = build_graph()

    def run(self, task_id: str, instruction: str, env: GroceryEnvironment) -> AgentRun:
        context = ShoppingContext(env=env, parser=self.parser, max_steps=self.max_steps)
        # Each add_to_cart iteration visits up to 4 nodes (verify, search, add, replan).
        recursion_limit = 4 * self.max_steps + 10
        final = self.graph.invoke(
            {"instruction": instruction, "trace": []},
            context=context,
            config={"recursion_limit": recursion_limit},
        )
        return AgentRun(
            agent=self.name,
            task_id=task_id,
            cart=dict(env.cart),
            total_cost=env.total_cost,
            tool_calls=env.tool_calls,
            replans=final["replans"],
            trace=final["trace"] + env.log,
            parsed_intent=final["intent"],
        )
