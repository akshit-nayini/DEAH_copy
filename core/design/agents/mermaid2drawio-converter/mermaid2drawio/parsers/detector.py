"""
Diagram type detector — inspects raw Mermaid source text and classifies it
into one of the supported diagram types.
"""

from enum import Enum
import re
from typing import Optional


class DiagramType(Enum):
    FLOWCHART = "flowchart"
    ER_DIAGRAM = "erDiagram"
    UNKNOWN = "unknown"


class DiagramDetector:
    """Detect the type of a Mermaid diagram from its source text."""

    # Patterns for the first significant line of a Mermaid block
    _FLOWCHART_RE = re.compile(
        r"^\s*(graph|flowchart)\s+(TB|BT|LR|RL|TD)\s*$", re.IGNORECASE
    )
    _ER_RE = re.compile(r"^\s*erDiagram\s*$", re.IGNORECASE)

    @classmethod
    def detect(cls, source: str) -> DiagramType:
        """
        Return the DiagramType for the given Mermaid source.

        Parameters
        ----------
        source : str
            Raw Mermaid diagram text (may include the ``` fences — they are
            stripped before inspection).

        Returns
        -------
        DiagramType
        """
        # Strip optional code fences
        lines = source.strip().splitlines()
        for line in lines:
            stripped = line.strip()
            # skip blank lines and fence markers
            if not stripped or stripped.startswith("```"):
                continue
            if cls._FLOWCHART_RE.match(stripped):
                return DiagramType.FLOWCHART
            if cls._ER_RE.match(stripped):
                return DiagramType.ER_DIAGRAM
            # Also match bare "graph" without explicit direction
            if re.match(r"^\s*(graph|flowchart)\b", stripped, re.IGNORECASE):
                return DiagramType.FLOWCHART
            break  # only check the first meaningful line

        return DiagramType.UNKNOWN
