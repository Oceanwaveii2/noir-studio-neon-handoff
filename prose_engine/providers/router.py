"""Provider routing: cheap local for flagging/cutting, frontier only for directed variation."""

from __future__ import annotations

from dataclasses import dataclass

TASKS = {
    "flag": "local",
    "cut": "local",
    "condition": "local",
    "variation": "deepseek",
}


@dataclass
class Route:
    task: str
    provider: str
    reason: str


def route(task: str, has_direction: bool = False, budget_exhausted: bool = False) -> Route:
    """Choose a provider for a task. Refuses frontier work when the budget is out."""
    provider = TASKS.get(task, "local")
    if task == "variation" and not has_direction:
        return Route(task, "local", "variation without a DIRECTION runs local; frontier is reserved for directed takes")
    if provider != "local" and budget_exhausted:
        return Route(task, "local", "frontier budget exhausted; falling back to local")
    return Route(task, provider, "policy")
