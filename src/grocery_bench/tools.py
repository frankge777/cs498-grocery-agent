"""Tool schemas exposed to agents (JSON Schema, provider-neutral).

LLM agents should pass these to their provider's function-calling API and
route each call through ``GroceryEnv.call(name, arguments)``.
"""

from __future__ import annotations

from .environment import TOOL_SCHEMA_VERSION

TOOL_SPECS = [
    {
        "name": "search_products",
        "description": "Search the store catalog by free text (product name, category, brand, or dietary tag). "
        "Returns up to max_results products with id, name, brand, category, package size/unit, price in cents, and in_stock.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_product",
        "description": "Get full details for one product: dietary tags, portions per package by meal role, protein grams, stock status. "
        "A dietary tag that is not listed is unknown.",
        "parameters": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}},
            "required": ["product_id"],
        },
    },
    {
        "name": "view_cart",
        "description": "Show the current cart lines and total in cents.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "add_to_cart",
        "description": "Add a quantity of a product (number of packages) to the cart. Fails without changing the cart if the product is out of stock.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "quantity": {"type": "integer", "minimum": 1},
            },
            "required": ["product_id", "quantity"],
        },
    },
    {
        "name": "update_quantity",
        "description": "Set the quantity (number of packages) of a product in the cart. 0 removes it.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "quantity": {"type": "integer", "minimum": 0},
            },
            "required": ["product_id", "quantity"],
        },
    },
    {
        "name": "remove_from_cart",
        "description": "Remove a product from the cart entirely.",
        "parameters": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}},
            "required": ["product_id"],
        },
    },
    {
        "name": "ask_user",
        "description": "Ask the shopper a clarifying question. Only ask when a required choice cannot be determined from the request and household context.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "finish",
        "description": "End the episode. The cart as it stands is scored.",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
        },
    },
]

__all__ = ["TOOL_SPECS", "TOOL_SCHEMA_VERSION"]
