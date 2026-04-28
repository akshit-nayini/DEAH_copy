"""Stages 4 & 5 — Local per-document deduplication and global pool assembly."""
from __future__ import annotations

from .llm import RawTask


def jaccard(a: str, b: str) -> float:
    """Jaccard similarity over word tokens longer than 2 characters."""
    sa = {w for w in a.lower().split() if len(w) > 2}
    sb = {w for w in b.lower().split() if len(w) > 2}
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def task_key(task: RawTask) -> str:
    return f"{task.summary} {task.description}"


def local_dedup(tasks: list[RawTask], threshold: float) -> list[RawTask]:
    """Keep a task only if no already-kept task exceeds the jaccard threshold."""
    kept: list[RawTask] = []
    for task in tasks:
        if not any(jaccard(task_key(task), task_key(k)) >= threshold for k in kept):
            kept.append(task)
    return kept


def build_global_pool(tasks_by_file: dict[int, list[RawTask]]) -> list[RawTask]:
    """Flatten per-document deduplicated lists into a single pool."""
    return [t for tasks in tasks_by_file.values() for t in tasks]
