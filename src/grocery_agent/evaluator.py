from __future__ import annotations

from collections import Counter

from .models import AgentRun, Evaluation, Product, Task


def evaluate_run(run: AgentRun, task: Task, catalog: dict[str, Product]) -> Evaluation:
    counts: Counter = Counter()
    selected = []
    for product_id, quantity in run.cart.items():
        product = catalog[product_id]
        counts[product.category] += quantity
        selected.extend([product] * quantity)

    required_units = sum(requirement.quantity for requirement in task.requirements)
    covered_units = sum(
        min(requirement.quantity, counts[requirement.category]) for requirement in task.requirements
    )
    coverage = covered_units / required_units if required_units else 1.0

    constraints_ok = all(
        task.required_tags.issubset(product.tags)
        and not task.forbidden_tags.intersection(product.tags)
        for product in selected
    )
    budget_ok = run.total_cost <= task.budget + 1e-9
    preference = 1.0
    if task.preferred_brand:
        preference = (
            sum(1 for product in selected if product.brand == task.preferred_brand) / len(selected)
            if selected
            else 0.0
        )
    success = float(coverage == 1.0 and constraints_ok and budget_ok)

    return Evaluation(
        task_id=task.id,
        agent=run.agent,
        task_type=task.task_type,
        success=success,
        item_coverage=round(coverage, 4),
        constraint_satisfaction=float(constraints_ok),
        budget_compliance=float(budget_ok),
        preference_satisfaction=round(preference, 4),
        total_cost=run.total_cost,
        tool_calls=run.tool_calls,
        replans=run.replans,
    )

