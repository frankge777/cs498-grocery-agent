from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    category: str
    brand: str
    price: float
    tags: Set[str]


@dataclass(frozen=True)
class Requirement:
    category: str
    quantity: int = 1


@dataclass(frozen=True)
class Task:
    id: str
    task_type: str
    instruction: str
    requirements: Sequence[Requirement]
    budget: float
    required_tags: Set[str] = field(default_factory=set)
    forbidden_tags: Set[str] = field(default_factory=set)
    preferred_brand: Optional[str] = None
    events: Sequence[dict] = field(default_factory=list)


@dataclass
class ParsedIntent:
    requirements: List[Requirement]
    budget: Optional[float]
    required_tags: Set[str] = field(default_factory=set)
    forbidden_tags: Set[str] = field(default_factory=set)
    preferred_brand: Optional[str] = None
    ambiguities: List[str] = field(default_factory=list)


@dataclass
class ToolResult:
    ok: bool
    message: str
    data: Optional[dict] = None


@dataclass
class AgentRun:
    agent: str
    task_id: str
    cart: Dict[str, int]
    total_cost: float
    tool_calls: int
    replans: int
    trace: List[dict]
    parsed_intent: Optional[ParsedIntent] = None


@dataclass(frozen=True)
class Evaluation:
    task_id: str
    agent: str
    task_type: str
    success: float
    item_coverage: float
    constraint_satisfaction: float
    budget_compliance: float
    preference_satisfaction: float
    total_cost: float
    tool_calls: int
    replans: int

