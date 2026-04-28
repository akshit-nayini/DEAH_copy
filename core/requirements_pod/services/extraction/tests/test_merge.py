"""Tests for Stage 6 — UnionFind correctness and graph_merge field rules."""
import pytest
from core.requirements_pod.services.extraction.merge import UnionFind, graph_merge, MergedTask
from core.requirements_pod.services.extraction.llm import RawTask


def _task(
    summary: str,
    description: str = "",
    priority: str = "Medium",
    labels: list[str] | None = None,
    story_points: int = 3,
    acceptance_criteria: list[str] | None = None,
    extraction_confidence: float = 0.8,
    fi: int = 0,
    ci: int = 0,
) -> RawTask:
    return RawTask(
        summary=summary,
        description=description,
        issuetype="Task",
        priority=priority,
        labels=labels or [],
        story_points=story_points,
        acceptance_criteria=acceptance_criteria or [],
        extraction_confidence=extraction_confidence,
        temporal_markers=[],
        supersedes=False,
        file_index=fi,
        chunk_index=ci,
        source_indices=[fi],
    )


class TestUnionFind:
    def test_find_self(self):
        uf = UnionFind(3)
        assert uf.find(0) == 0
        assert uf.find(1) == 1

    def test_union_connects_elements(self):
        uf = UnionFind(4)
        uf.union(0, 1)
        assert uf.find(0) == uf.find(1)

    def test_path_compression(self):
        uf = UnionFind(5)
        uf.union(0, 1)
        uf.union(1, 2)
        uf.union(2, 3)
        root = uf.find(3)
        # After path compression, all nodes should point to root
        assert uf.find(0) == root
        assert uf.find(1) == root
        assert uf.find(2) == root

    def test_union_by_rank(self):
        uf = UnionFind(4)
        uf.union(0, 1)
        uf.union(2, 3)
        uf.union(0, 2)
        root = uf.find(0)
        assert uf.find(1) == root
        assert uf.find(2) == root
        assert uf.find(3) == root

    def test_no_merge_of_disjoint(self):
        uf = UnionFind(4)
        uf.union(0, 1)
        assert uf.find(0) == uf.find(1)
        assert uf.find(2) != uf.find(0)


class TestGraphMerge:
    def test_empty_input(self):
        assert graph_merge([], threshold=0.55) == []

    def test_no_merge_for_dissimilar_tasks(self):
        tasks = [
            _task("Fix authentication login security vulnerability"),
            _task("Create CSV export reporting dashboard feature"),
            _task("Migrate database connection pool async driver"),
        ]
        result = graph_merge(tasks, threshold=0.55)
        assert len(result) == 3

    def test_merges_identical_tasks(self):
        tasks = [
            _task("Fix login authentication bug completely", fi=0, ci=0),
            _task("Fix login authentication bug completely", fi=1, ci=0),
        ]
        result = graph_merge(tasks, threshold=0.55)
        assert len(result) == 1
        assert result[0].cluster_size == 2

    def test_merged_summary_from_highest_confidence(self):
        tasks = [
            _task("Fix login bug auth", extraction_confidence=0.9, fi=0),
            _task("Fix login bug auth", extraction_confidence=0.5, fi=1),
        ]
        result = graph_merge(tasks, threshold=0.55)
        assert len(result) == 1
        assert result[0].extraction_confidence == 0.9

    def test_merged_priority_takes_highest(self):
        tasks = [
            _task("Fix login authentication bug", priority="Low", fi=0),
            _task("Fix login authentication bug", priority="Critical", fi=1),
        ]
        result = graph_merge(tasks, threshold=0.55)
        assert result[0].priority == "Critical"

    def test_merged_labels_union_capped_at_5(self):
        tasks = [
            _task("Fix login auth", labels=["auth", "backend", "security"], fi=0),
            _task("Fix login auth", labels=["frontend", "ui", "ux"], fi=1),
        ]
        result = graph_merge(tasks, threshold=0.55)
        assert len(result[0].labels) <= 5

    def test_merged_story_points_max(self):
        tasks = [
            _task("Fix login auth", story_points=3, fi=0),
            _task("Fix login auth", story_points=8, fi=1),
        ]
        result = graph_merge(tasks, threshold=0.55)
        assert result[0].story_points == 8

    def test_merged_acceptance_criteria_union(self):
        tasks = [
            _task("Fix login auth", acceptance_criteria=["User can log in"], fi=0),
            _task("Fix login auth", acceptance_criteria=["Session persists"], fi=1),
        ]
        result = graph_merge(tasks, threshold=0.55)
        ac = result[0].acceptance_criteria
        assert "User can log in" in ac
        assert "Session persists" in ac

    def test_merged_source_indices_union(self):
        t0 = _task("Fix login auth", fi=0)
        t1 = _task("Fix login auth", fi=1)
        t1.source_indices = [1]
        result = graph_merge([t0, t1], threshold=0.55)
        assert sorted(result[0].source_indices) == [0, 1]

    def test_merged_file_chunk_index_minimum(self):
        tasks = [
            _task("Fix login authentication", fi=2, ci=5),
            _task("Fix login authentication", fi=0, ci=1),
        ]
        result = graph_merge(tasks, threshold=0.55)
        assert result[0].file_index == 0
        assert result[0].chunk_index == 1
