"""
orchestration — pipeline runner for the DE design agents.

Usage:
    from orchestration.orchestrator import run_pipeline

    result = run_pipeline(
        requirements_dict=output.to_dict(),
        output_root="output",
    )

API key is read automatically from the ANTHROPIC_API_KEY environment variable
via the shared LLM utility (core.utilities.llm).
"""

from orchestration.orchestrator import run_pipeline

__all__ = ["run_pipeline"]