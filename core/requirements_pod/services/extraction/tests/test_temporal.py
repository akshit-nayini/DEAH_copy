"""Tests for Stage 7 — temporal reasoning: override and initial-marker detection."""
import pytest
from core.requirements_pod.services.extraction.temporal import apply_temporal_reasoning
from core.requirements_pod.services.extraction.merge import MergedTask
from core.requirements_pod.services.extraction.llm import RawTask


def _merged(
    summary: str,
    description: str = "",
    temporal_markers: list[str] | None = None,
    supersedes: bool = False,
    fi: int = 0,
    ci: int = 0,
) -> MergedTask:
    return MergedTask(
        summary=summary,
        description=description,
        issuetype="Task",
        priority="Medium",
        labels=[],
        story_points=3,
        acceptance_criteria=[],
        extraction_confidence=0.8,
        temporal_markers=temporal_markers or [],
        supersedes=supersedes,
        file_index=fi,
        chunk_index=ci,
        source_indices=[fi],
        cluster_size=1,
    )


class TestOverrideDetection:
    def test_later_override_kills_earlier_similar_task(self):
        earlier = _merged("Implement user authentication login", fi=0, ci=0)
        later = _merged(
            "Updated user authentication login service",
            description="now should use OAuth instead",
            fi=0, ci=1,
        )
        result = apply_temporal_reasoning([earlier, later])
        summaries = [t.summary for t in result]
        assert earlier.summary not in summaries
        assert later.summary in summaries

    def test_supersedes_flag_kills_earlier_similar_task(self):
        earlier = _merged("Fix login bug authentication", fi=0, ci=0)
        later = _merged("Fix login bug authentication", supersedes=True, fi=0, ci=1)
        result = apply_temporal_reasoning([earlier, later])
        assert len(result) == 1
        assert result[0].supersedes is True

    def test_override_does_not_kill_dissimilar_task(self):
        unrelated = _merged("Implement CSV export reporting feature", fi=0, ci=0)
        override = _merged(
            "Updated login authentication",
            description="now should use OAuth",
            fi=0, ci=1,
        )
        result = apply_temporal_reasoning([unrelated, override])
        assert len(result) == 2

    def test_overrode_count_incremented(self):
        earlier = _merged("Fix login authentication bug", fi=0, ci=0)
        later = _merged(
            "Fix login authentication bug",
            description="revised to use new method",
            fi=0, ci=1,
        )
        result = apply_temporal_reasoning([earlier, later])
        override_tasks = [t for t in result if t.summary == later.summary]
        assert override_tasks[0].overrode_count >= 1


class TestInitialMarkerDetection:
    def test_initial_task_removed_when_later_similar_exists(self):
        initial = _merged(
            "Implement user authentication service login",
            description="initially this will be basic",
            fi=0, ci=0,
        )
        later = _merged("Implement user authentication service login", fi=0, ci=1)
        result = apply_temporal_reasoning([initial, later])
        # The initial one should be dead
        assert initial.summary not in [t.summary for t in result] or len(result) == 1

    def test_initial_task_kept_when_no_later_similar_exists(self):
        initial = _merged(
            "Implement authentication login service",
            description="initially a placeholder",
            fi=0, ci=0,
        )
        unrelated = _merged("Create CSV export dashboard feature", fi=0, ci=1)
        result = apply_temporal_reasoning([initial, unrelated])
        assert len(result) == 2

    def test_tbd_marker_in_description(self):
        tbd_task = _merged(
            "Implement payment gateway integration service",
            description="tbd will define later",
            fi=0, ci=0,
        )
        later = _merged("Implement payment gateway integration service", fi=0, ci=1)
        result = apply_temporal_reasoning([tbd_task, later])
        assert tbd_task.summary not in [t.summary for t in result] or len(result) == 1


class TestNoMarkers:
    def test_tasks_without_markers_all_survive(self):
        tasks = [
            _merged("Fix login authentication bug", fi=0, ci=0),
            _merged("Create CSV export dashboard", fi=0, ci=1),
            _merged("Migrate database connection pool", fi=0, ci=2),
        ]
        result = apply_temporal_reasoning(tasks)
        assert len(result) == 3

    def test_empty_input(self):
        assert apply_temporal_reasoning([]) == []
