"""Unit tests for _get_all_ticket_documents per-type query logic."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from input_parser import _get_all_ticket_documents


def _make_row(agent, file_type, path, filename):
    row = MagicMock()
    row.AGENT = agent
    row.FILE_TYPE = file_type
    row.PATH = path
    row.FILENAME = filename
    return row


def _make_execute_result(row):
    m = MagicMock()
    m.fetchone.return_value = row
    return m


def test_fetches_three_separate_queries(tmp_path):
    """Three queries issued: one per file type (MD, CSV, JSON)."""
    md_row  = _make_row("DesignAgent", "MD",  "output/SCRUM-1", "impl.md")
    csv_row = _make_row("DataModel",   "CSV", "output/SCRUM-1", "mapping.csv")
    json_row = _make_row("RequirementsAgent", "JSON", "output/SCRUM-1", "req.json")

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        _make_execute_result(md_row),
        _make_execute_result(csv_row),
        _make_execute_result(json_row),
    ]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("input_parser.build_metadata_engine", return_value=mock_engine):
        docs = _get_all_ticket_documents("SCRUM-1", tmp_path)

    assert mock_conn.execute.call_count == 3
    assert len(docs) == 3
    types = {d["file_type"] for d in docs}
    assert types == {"MD", "CSV", "JSON"}

    # Verify each query used the correct file_type parameter
    call_params = [call.args[1] for call in mock_conn.execute.call_args_list]
    file_types_queried = [p["file_type"] for p in call_params]
    assert file_types_queried == ["MD", "CSV", "JSON"]


def test_missing_file_type_returns_partial(tmp_path):
    """If one file type has no rows, only the found types are returned."""
    md_row = _make_row("DesignAgent", "MD", "output/SCRUM-2", "impl.md")

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        _make_execute_result(md_row),
        _make_execute_result(None),
        _make_execute_result(None),
    ]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("input_parser.build_metadata_engine", return_value=mock_engine):
        docs = _get_all_ticket_documents("SCRUM-2", tmp_path)

    assert len(docs) == 1
    assert docs[0]["file_type"] == "MD"


def test_no_rows_raises_file_not_found(tmp_path):
    """If all three queries return no rows, FileNotFoundError is raised."""
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        _make_execute_result(None),
        _make_execute_result(None),
        _make_execute_result(None),
    ]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    import pytest
    with patch("input_parser.build_metadata_engine", return_value=mock_engine):
        with pytest.raises(FileNotFoundError, match="SCRUM-99"):
            _get_all_ticket_documents("SCRUM-99", tmp_path)
