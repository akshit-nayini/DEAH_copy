"""Tests for Stage 8 — confidence scoring formula and bounds."""
import pytest
from core.requirements_pod.services.extraction.scoring import score_confidence
from core.requirements_pod.services.extraction.temporal import TemporalTask


def _task(
    extraction_confidence: float = 0.8,
    cluster_size: int = 1,
    source_indices: list[int] | None = None,
    acceptance_criteria: list[str] | None = None,
) -> TemporalTask:
    return TemporalTask(
        summary="Fix login bug authentication",
        description="some description",
        issuetype="Bug",
        priority="High",
        labels=[],
        story_points=3,
        acceptance_criteria=acceptance_criteria or [],
        extraction_confidence=extraction_confidence,
        temporal_markers=[],
        supersedes=False,
        file_index=0,
        chunk_index=0,
        source_indices=source_indices or [0],
        cluster_size=cluster_size,
        overrode_count=0,
        confidence=0.0,
    )


class TestScoreConfidence:
    def test_base_score_is_extraction_confidence(self):
        task = _task(extraction_confidence=0.7, cluster_size=1, source_indices=[0])
        assert score_confidence(task) == pytest.approx(0.7, abs=0.001)

    def test_density_bonus_for_cluster_size_2(self):
        # density = (2-1) * 0.04 = 0.04
        task = _task(extraction_confidence=0.5, cluster_size=2, source_indices=[0])
        assert score_confidence(task) == pytest.approx(0.54, abs=0.001)

    def test_density_bonus_capped_at_0_12(self):
        # cluster_size=100 → (100-1)*0.04=3.96, capped at 0.12
        task = _task(extraction_confidence=0.5, cluster_size=100, source_indices=[0])
        assert score_confidence(task) == pytest.approx(0.62, abs=0.001)  # 0.5 + 0.12

    def test_cross_source_bonus_when_multiple_sources(self):
        # cross_source = 0.10 for >1 source
        task = _task(extraction_confidence=0.5, cluster_size=1, source_indices=[0, 1])
        assert score_confidence(task) == pytest.approx(0.60, abs=0.001)

    def test_no_cross_source_bonus_for_single_source(self):
        task = _task(extraction_confidence=0.5, cluster_size=1, source_indices=[0])
        assert score_confidence(task) == pytest.approx(0.5, abs=0.001)

    def test_ac_richness_bonus(self):
        # 3 ACs → 3 * 0.02 = 0.06
        task = _task(
            extraction_confidence=0.5,
            cluster_size=1,
            source_indices=[0],
            acceptance_criteria=["AC1", "AC2", "AC3"],
        )
        assert score_confidence(task) == pytest.approx(0.56, abs=0.001)

    def test_ac_richness_bonus_capped_at_0_06(self):
        # 10 ACs → 10 * 0.02 = 0.20, capped at 0.06
        acs = [f"AC{i}" for i in range(10)]
        task = _task(
            extraction_confidence=0.5,
            cluster_size=1,
            source_indices=[0],
            acceptance_criteria=acs,
        )
        assert score_confidence(task) == pytest.approx(0.56, abs=0.001)

    def test_score_capped_at_1_0(self):
        # Max all bonuses: extraction=1.0 + density=0.12 + cross=0.10 + ac=0.06 = 1.28 → capped at 1.0
        task = _task(
            extraction_confidence=1.0,
            cluster_size=100,
            source_indices=[0, 1],
            acceptance_criteria=[f"AC{i}" for i in range(10)],
        )
        assert score_confidence(task) == pytest.approx(1.0, abs=0.001)

    def test_score_floor_at_0_0(self):
        task = _task(extraction_confidence=0.0, cluster_size=1, source_indices=[0])
        assert score_confidence(task) >= 0.0

    def test_none_extraction_confidence_defaults_to_0_5(self):
        task = _task(extraction_confidence=0.0)
        task.extraction_confidence = None  # type: ignore[assignment]
        score = score_confidence(task)
        # extraction = max(0, min(1, 0.5)) = 0.5
        assert score == pytest.approx(0.5, abs=0.001)
