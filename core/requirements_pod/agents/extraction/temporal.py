"""Stage 7 — Temporal reasoning: remove tasks superseded by later document content."""
from __future__ import annotations

from dataclasses import dataclass

from .merge import MergedTask
from .dedup import jaccard


OVERRIDE_MARKERS = [
    "updated", "revised", "changed to", "now should", "instead",
    "replaced by", "no longer", "remove", "deprecated", "superseded",
    "as of now", "currently requires", "should now",
]

INITIAL_MARKERS = [
    "initially", "originally", "first draft", "preliminary",
    "tentatively", "proposed", "tbd", "placeholder", "to be determined",
]


@dataclass
class TemporalTask(MergedTask):
    overrode_count: int = 0
    confidence: float = 0.0


def _has_marker(task: MergedTask, markers: list[str]) -> bool:
    combined = f"{task.summary} {task.description}".lower()
    for m in markers:
        if m in combined:
            return True
    for tm in task.temporal_markers:
        if any(m in tm.lower() for m in markers):
            return True
    return False


def _to_temporal(t: MergedTask) -> TemporalTask:
    return TemporalTask(
        summary=t.summary,
        description=t.description,
        issuetype=t.issuetype,
        priority=t.priority,
        labels=list(t.labels),
        story_points=t.story_points,
        acceptance_criteria=list(t.acceptance_criteria),
        extraction_confidence=t.extraction_confidence,
        temporal_markers=list(t.temporal_markers),
        supersedes=t.supersedes,
        file_index=t.file_index,
        chunk_index=t.chunk_index,
        source_indices=list(t.source_indices),
        cluster_size=t.cluster_size,
        overrode_count=0,
        confidence=0.0,
        reporter=t.reporter,
        sprint=t.sprint,
        fix_version=t.fix_version,
        project_name=t.project_name,
        requirement_type=t.requirement_type,
        stakeholder_name=t.stakeholder_name,
        objective=t.objective,
        expected_outcome=t.expected_outcome,
        connections_db_details=t.connections_db_details,
        success_conditions=list(t.success_conditions),
        validation_rules=list(t.validation_rules),
        schedule_interval=t.schedule_interval,
        assumed_fields=list(t.assumed_fields),
        assignee=getattr(t, "assignee", None),
        start_date=getattr(t, "start_date", None),
        due_date=getattr(t, "due_date", None),
    )


def apply_temporal_reasoning(tasks: list[MergedTask]) -> list[TemporalTask]:
    """Remove tasks that have been superseded by later document content."""
    sorted_tasks = sorted(tasks, key=lambda t: (t.file_index, t.chunk_index))
    temporal = [_to_temporal(t) for t in sorted_tasks]
    dead = [False] * len(temporal)

    # Rule 1: later tasks with override markers kill earlier similar tasks
    for i, later in enumerate(temporal):
        if _has_marker(later, OVERRIDE_MARKERS) or later.supersedes:
            for j in range(i):
                if not dead[j]:
                    if jaccard(temporal[j].summary, later.summary) > 0.35:
                        dead[j] = True
                        later.overrode_count += 1

    # Rule 2: tasks with initial markers die if a later task is similar
    for i, task in enumerate(temporal):
        if not dead[i] and _has_marker(task, INITIAL_MARKERS):
            for j in range(i + 1, len(temporal)):
                if not dead[j] and jaccard(temporal[j].summary, task.summary) > 0.40:
                    dead[i] = True
                    break

    return [t for i, t in enumerate(temporal) if not dead[i]]
