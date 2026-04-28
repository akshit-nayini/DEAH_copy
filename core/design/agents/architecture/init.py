"""
architecture — init.py

Registers the Architecture Agent with the orchestrator.
Exposes the agent callable, skills reference, and description
so the orchestrator can discover and invoke this agent by name.
"""

from agent import ArchitectureAgent

AGENT_NAME = "architecture"
AGENT_DESCRIPTION = (
    "Senior Staff-Level Data Architect agent. Consumes Requirements Agent output "
    "and produces an Architecture Decision Document with 2–3 scored options, "
    "a weighted recommendation, risk analysis, and full traceability to requirements. "
    "Defaults to GCP managed services unless another cloud is explicitly specified."
)


def get_agent(config: dict | None = None) -> ArchitectureAgent:
    """Factory used by the orchestrator to instantiate this agent."""
    return ArchitectureAgent(config=config)


__all__ = [
    "AGENT_NAME",
    "AGENT_DESCRIPTION",
    "get_agent",
    "ArchitectureAgent",
]
