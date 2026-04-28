"""
agents/generator/run_backend.py
--------------------------------
Runs the generator backend directly — no Flask, no web UI.
Pulls latest ICD + AC from Git, generates test cases, saves output.

Usage:
    python3 agents/generator/run_backend.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.generator.connectors import GeneratorConnector
from agents.generator.agent import GeneratorAgent

if __name__ == "__main__":
    print("=== Loading ICD and AC from Git ===")
    connector = GeneratorConnector()
    data = connector.load_latest()
    print(f"ICD file : {data['icd_file']}")
    print(f"AC file  : {data['ac_file']}")

    print("\n=== Running GeneratorAgent ===")
    agent = GeneratorAgent()
    cases = agent.run(icd=data["icd"], ac=data["ac"])

    print(f"\n=== Done: {len(cases)} test cases generated ===")
