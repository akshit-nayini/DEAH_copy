"""
LLM connectivity smoke test.

Usage:
    python test_connection.py                      # reads ANTHROPIC_API_KEY from env
    python test_connection.py --api-key sk-ant-...
    python test_connection.py --provider openai --api-key sk-...
    python test_connection.py --provider gemini --api-key AI...
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))  # DEAH root

from core.utilities.llm import create_llm_client

_ENV_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "gemini":    "GEMINI_API_KEY",
}

parser = argparse.ArgumentParser(description="LLM connection test")
parser.add_argument("--provider", default="anthropic", choices=["anthropic", "openai", "gemini"])
parser.add_argument("--api-key",  default=None)
parser.add_argument("--model",    default=None)
args = parser.parse_args()

# ── Resolve key ───────────────────────────────────────────────────────────────
api_key = args.api_key or os.environ.get(_ENV_KEYS[args.provider], "")
if not api_key:
    print(f"ERROR: no API key found. Set {_ENV_KEYS[args.provider]} or pass --api-key.")
    sys.exit(1)

print(f"Provider : {args.provider}")
print(f"Key      : loaded ({api_key[:12]}...)")

# ── Build client ──────────────────────────────────────────────────────────────
kwargs = {"api_key": api_key}
if args.model:
    kwargs["model"] = args.model

llm = create_llm_client(args.provider, **kwargs)
print(f"Client   : ready\n")

# ── Two simple prompts ────────────────────────────────────────────────────────
for question in [
    "How are you today?",
    "How's the weather where you are?",
]:
    print(f"Q: {question}")
    response = llm.complete(question, max_tokens=128)
    print(f"A: {response.content.strip()}")
    print(f"   [{response.input_tokens} in / {response.output_tokens} out]\n")
