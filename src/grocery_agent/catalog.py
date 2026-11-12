from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from .models import Product, Requirement, Task


ROOT = Path(__file__).resolve().parents[2]


def load_catalog(path: Optional[Path] = None) -> Dict[str, Product]:
    source = path or ROOT / "data" / "catalog.json"
    rows = json.loads(source.read_text(encoding="utf-8"))
    return {
        row["id"]: Product(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            brand=row["brand"],
            price=float(row["price"]),
            tags=set(row.get("tags", [])),
        )
        for row in rows
    }


def load_tasks(path: Optional[Path] = None) -> List[Task]:
    source = path or ROOT / "data" / "tasks.json"
    rows = json.loads(source.read_text(encoding="utf-8"))
    tasks: List[Task] = []
    for row in rows:
        tasks.append(
            Task(
                id=row["id"],
                task_type=row["task_type"],
                instruction=row["instruction"],
                requirements=[Requirement(**item) for item in row["requirements"]],
                budget=float(row["budget"]),
                required_tags=set(row.get("required_tags", [])),
                forbidden_tags=set(row.get("forbidden_tags", [])),
                preferred_brand=row.get("preferred_brand"),
                events=row.get("events", []),
            )
        )
    return tasks

