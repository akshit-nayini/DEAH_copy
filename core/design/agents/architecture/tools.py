"""
tools.py — Tool definitions for the Architecture Agent.

Defines all callable tools this agent uses:
  - llm_call      : Call Claude API (system prompt + user message)
  - write_file    : Write an output file to disk
  - read_file     : Read an input file from disk
  - validate_json : Validate and extract JSON from LLM response

Tool functions are stateless. The agent (agent.py) calls them as needed.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Ensure DEAH root is on sys.path so core.utilities is importable
_DEAH_ROOT = Path(__file__).resolve().parents[4]
if str(_DEAH_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEAH_ROOT))

from core.utilities.llm import create_llm_client

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 16000
DEFAULT_TEMPERATURE = 0.0


# ──────────────────────────────────────────────
# Tool 1: LLM Call
# ──────────────────────────────────────────────

def llm_call(
    system_prompt: str,
    user_message: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
) -> dict:
    """
    Call the Anthropic Messages API via the shared LLM client.

    Returns:
        {
            "text": str,
            "input_tokens": int,
            "output_tokens": int,
            "model": str,
        }

    Raises:
        RuntimeError: If ANTHROPIC_API_KEY is not set.
    """
    logger.info("llm_call  model=%s  max_tokens=%d", model, max_tokens)
    llm = create_llm_client("claude-code-sdk")
    result = llm.complete(prompt=user_message, system=system_prompt, max_tokens=max_tokens)
    logger.info(
        "llm_call success  input_tokens=%d  output_tokens=%d",
        result.input_tokens, result.output_tokens,
    )
    return {
        "text": result.content,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "model": result.model,
    }


# ──────────────────────────────────────────────
# Tool 2: Write File
# ──────────────────────────────────────────────

def write_file(path: str, content: str, mkdir: bool = True) -> dict:
    """
    Write string content to a file.

    Returns:
        {"path": str, "bytes_written": int}
    """
    p = Path(path)
    if mkdir:
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    logger.info("write_file: %s (%d bytes)", p, len(content.encode("utf-8")))
    return {"path": str(p), "bytes_written": len(content.encode("utf-8"))}


# ──────────────────────────────────────────────
# Tool 3: Read File
# ──────────────────────────────────────────────

def read_file(path: str) -> dict:
    """
    Read a file and return its content.

    Returns:
        {"path": str, "content": str, "size_bytes": int}

    Raises:
        FileNotFoundError: If the path does not exist.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    content = p.read_text(encoding="utf-8")
    logger.info("read_file: %s (%d bytes)", p, len(content.encode("utf-8")))
    return {"path": str(p), "content": content, "size_bytes": len(content.encode("utf-8"))}


# ──────────────────────────────────────────────
# Tool 4: Validate JSON
# ──────────────────────────────────────────────

def validate_json(raw_text: str) -> dict:
    """
    Attempt to parse a string as JSON. Handles markdown fences and leading prose.

    Returns:
        {
            "valid": bool,
            "data": dict | None,
            "error": str | None,
            "extraction_method": str,
        }
    """
    text = raw_text.strip()

    # Method 1: Direct parse
    try:
        data = json.loads(text)
        return {"valid": True, "data": data, "error": None, "extraction_method": "direct"}
    except json.JSONDecodeError:
        pass

    # Method 2: Strip markdown fences
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        try:
            data = json.loads(fence_match.group(1).strip())
            return {"valid": True, "data": data, "error": None, "extraction_method": "markdown_fence"}
        except json.JSONDecodeError:
            pass

    # Method 3: Find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start: end + 1])
            return {"valid": True, "data": data, "error": None, "extraction_method": "brace_extraction"}
        except json.JSONDecodeError as exc:
            return {"valid": False, "data": None, "error": str(exc), "extraction_method": "brace_extraction_failed"}

    return {"valid": False, "data": None, "error": "No JSON found in text", "extraction_method": "none"}


# ──────────────────────────────────────────────
# Tool Registry
# ──────────────────────────────────────────────

TOOL_REGISTRY = {
    "llm_call": {
        "function": llm_call,
        "description": "Call Claude API with system prompt and user message",
        "inputs": ["system_prompt", "user_message", "model", "max_tokens", "temperature"],
    },
    "write_file": {
        "function": write_file,
        "description": "Write string content to a file on disk",
        "inputs": ["path", "content", "mkdir"],
    },
    "read_file": {
        "function": read_file,
        "description": "Read a file from disk",
        "inputs": ["path"],
    },
    "validate_json": {
        "function": validate_json,
        "description": "Parse and validate a JSON string with fallback extraction",
        "inputs": ["raw_text"],
    },
}


def get_tool(name: str):
    """Retrieve a tool function by name from the registry."""
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        raise KeyError(f"Unknown tool: {name}. Available: {list(TOOL_REGISTRY.keys())}")
    return entry["function"]
