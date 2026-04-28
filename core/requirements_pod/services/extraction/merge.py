"""Stage 6 — Graph similarity merge using Union-Find to cluster and merge similar tasks."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .llm import RawTask
from .dedup import jaccard, task_key


@dataclass
class MergedTask(RawTask):
    cluster_size: int = 1


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


_PRIORITY_ORDER = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}


def _highest_priority(priorities: list[str]) -> str:
    return max(priorities, key=lambda p: _PRIORITY_ORDER.get(p, 0), default="Medium")


def graph_merge(tasks: list[RawTask], threshold: float) -> list[MergedTask]:
    """Cluster tasks by similarity and merge each cluster into one canonical task."""
    n = len(tasks)
    if n == 0:
        return []

    uf = UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(task_key(tasks[i]), task_key(tasks[j])) >= threshold:
                uf.union(i, j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        clusters[uf.find(i)].append(i)

    merged: list[MergedTask] = []
    for indices in clusters.values():
        cluster_tasks = [tasks[i] for i in indices]
        best = max(cluster_tasks, key=lambda t: t.extraction_confidence)

        # Union of labels, deduplicated, capped at 5
        seen_labels: set[str] = set()
        all_labels: list[str] = []
        for t in cluster_tasks:
            for lbl in t.labels:
                if lbl not in seen_labels:
                    seen_labels.add(lbl)
                    all_labels.append(lbl)

        all_ac = list(dict.fromkeys(ac for t in cluster_tasks for ac in t.acceptance_criteria))
        all_tm = list(dict.fromkeys(tm for t in cluster_tasks for tm in t.temporal_markers))
        all_sources = sorted({s for t in cluster_tasks for s in t.source_indices})

        all_sc = list(dict.fromkeys(sc for t in cluster_tasks for sc in t.success_conditions))
        all_vr = list(dict.fromkeys(vr for t in cluster_tasks for vr in t.validation_rules))
        all_assumed = list(dict.fromkeys(f for t in cluster_tasks for f in t.assumed_fields))

        merged.append(MergedTask(
            summary=best.summary,
            description=best.description,
            issuetype=best.issuetype,
            priority=_highest_priority([t.priority for t in cluster_tasks]),
            labels=all_labels[:5],
            story_points=max(t.story_points for t in cluster_tasks),
            acceptance_criteria=all_ac,
            extraction_confidence=best.extraction_confidence,
            temporal_markers=all_tm,
            supersedes=any(t.supersedes for t in cluster_tasks),
            file_index=min(t.file_index for t in cluster_tasks),
            chunk_index=min(t.chunk_index for t in cluster_tasks),
            source_indices=all_sources,
            cluster_size=len(cluster_tasks),
            reporter=best.reporter,
            sprint=best.sprint,
            fix_version=best.fix_version,
            project_name=best.project_name,
            requirement_type=best.requirement_type,
            stakeholder_name=best.stakeholder_name,
            objective=best.objective,
            expected_outcome=best.expected_outcome,
            connections_db_details=best.connections_db_details,
            success_conditions=all_sc,
            validation_rules=all_vr,
            schedule_interval=best.schedule_interval,
            assumed_fields=all_assumed,
        ))

    return merged
