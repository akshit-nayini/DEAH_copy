"""
agents/validator/run_backend.py
--------------------------------
Runs the validator backend directly — no Flask, no web UI.
Pulls latest test cases CSV from generator output, validates against BQ, saves output.

Usage:
    python3 agents/validator/run_backend.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.validator.connectors import ValidatorConnector
from agents.validator.agent import ValidatorAgent

if __name__ == "__main__":
    print("=== Loading test cases from generator output ===")
    connector = ValidatorConnector()
    data = connector.load_latest()
    print(f"File     : {data['file_path']}")
    print(f"Rows     : {data['row_count']}")
    print(f"Columns  : {data['columns']}")

    print("\n=== Running ValidatorAgent ===")
    agent = ValidatorAgent()
    results = agent.run(records=data["records"])

    print(f"\n=== Done: {len(results)} test cases validated ===")
