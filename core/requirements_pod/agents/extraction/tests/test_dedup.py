"""Tests for Stages 4 & 5 — jaccard similarity, local dedup, global pool."""
import pytest
from core.requirements_pod.agents.extraction.dedup import jaccard, task_key, local_dedup, build_global_pool
from core.requirements_pod.agents.extraction.llm import RawTask


def _task(summary: str, description: str = "", fi: int = 0, ci: int = 0) -> RawTask:
    return RawTask(
        summary=summary,
        description=description,
        issuetype="Task",
        priority="Medium",
        labels=[],
        story_points=3,
        acceptance_criteria=[],
        extraction_confidence=0.8,
        temporal_markers=[],
        supersedes=False,
        file_index=fi,
        chunk_index=ci,
        source_indices=[fi],
    )


class TestJaccard:
    def test_identical_strings(self):
        assert jaccard("hello world test", "hello world test") == 1.0

    def test_completely_disjoint(self):
        # Short words (≤2 chars) are excluded; use long words
        assert jaccard("alpha bravo charlie", "delta echo foxtrot") == 0.0

    def test_partial_overlap(self):
        score = jaccard("fix login bug authentication", "fix login crash")
        assert 0.0 < score < 1.0

    def test_empty_strings(self):
        # Both empty → filtered sets are empty → returns 0.0
        assert jaccard("", "") == 0.0

    def test_short_words_excluded(self):
        # Words with length ≤ 2 are filtered out; use purely 2-char words → empty sets → 0.0
        assert jaccard("to be or he we", "go do me an of") == 0.0

    def test_symmetry(self):
        a, b = "implement user authentication service", "update authentication service"
        assert jaccard(a, b) == jaccard(b, a)


class TestLocalDedup:
    def test_keeps_unique_tasks(self):
        tasks = [
            _task("Fix login bug authentication flow"),
            _task("Add CSV export dashboard reporting"),
            _task("Migrate database connection pool async"),
        ]
        result = local_dedup(tasks, threshold=0.75)
        assert len(result) == 3

    def test_removes_near_duplicate(self):
        tasks = [
            _task("Fix login bug authentication flow user"),
            _task("Fix login bug authentication flow user"),  # identical
        ]
        result = local_dedup(tasks, threshold=0.75)
        assert len(result) == 1

    def test_threshold_boundary(self):
        # Two tasks with jaccard == 1.0 — both above any threshold > 0
        task_a = _task("implement user authentication service completely")
        task_b = _task("implement user authentication service completely")
        result = local_dedup([task_a, task_b], threshold=0.50)
        assert len(result) == 1

    def test_empty_input(self):
        assert local_dedup([], threshold=0.75) == []

    def test_preserves_order_of_first_occurrence(self):
        tasks = [
            _task("Fix login bug authentication"),
            _task("Fix login bug authentication"),
        ]
        result = local_dedup(tasks, threshold=0.75)
        assert result[0] is tasks[0]


class TestBuildGlobalPool:
    def test_flattens_multiple_files(self):
        t0 = [_task("Task A", fi=0), _task("Task B", fi=0)]
        t1 = [_task("Task C", fi=1)]
        pool = build_global_pool({0: t0, 1: t1})
        assert len(pool) == 3

    def test_empty_dict(self):
        assert build_global_pool({}) == []

    def test_single_file(self):
        tasks = [_task("Task A"), _task("Task B")]
        assert build_global_pool({0: tasks}) == tasks
