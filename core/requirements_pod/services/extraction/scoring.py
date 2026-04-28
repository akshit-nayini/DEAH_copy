"""Stage 8 — Confidence scoring formula."""
from .temporal import TemporalTask


def score_confidence(task: TemporalTask) -> float:
    """Compute final confidence score (0.0–1.0) for a task."""
    extraction = max(0.0, min(1.0, task.extraction_confidence or 0.5))
    density = min(0.12, (task.cluster_size - 1) * 0.04)
    cross_source = 0.10 if len(task.source_indices) > 1 else 0.0
    ac_richness = min(0.06, len(task.acceptance_criteria) * 0.02)
    return min(1.0, extraction + density + cross_source + ac_richness)
