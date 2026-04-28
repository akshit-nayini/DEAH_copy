"""
MermaidToDrawio — high-level facade that ties together scanning, parsing,
detection, and conversion.

This is the main entry point for programmatic use.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .scanner import RepoScanner, MermaidBlock
from .parsers.detector import DiagramDetector, DiagramType
from .parsers.flowchart_parser import FlowchartParser
from .parsers.er_parser import ERParser
from .converters.flowchart_converter import FlowchartConverter
from .converters.er_converter import ERConverter
from .icons.registry import IconRegistry


class ConversionResult:
    """Result of converting a single Mermaid block."""

    def __init__(
        self,
        source_file: str,
        block_index: int,
        diagram_type: DiagramType,
        output_path: str,
        success: bool = True,
        error: Optional[str] = None,
    ):
        self.source_file = source_file
        self.block_index = block_index
        self.diagram_type = diagram_type
        self.output_path = output_path
        self.success = success
        self.error = error

    def __repr__(self):
        status = "OK" if self.success else f"FAIL: {self.error}"
        return (
            f"ConversionResult({self.diagram_type.value}, "
            f"{os.path.basename(self.output_path)}, {status})"
        )


class MermaidToDrawio:
    """
    High-level converter: scan a repo and convert all Mermaid diagrams
    to Draw.io files.

    Usage::

        converter = MermaidToDrawio(
            repo_path="/path/to/repo",
            output_dir="/path/to/output",
        )
        results = converter.convert_all()
        for r in results:
            print(r)
    """

    def __init__(
        self,
        repo_path: str | Path,
        output_dir: Optional[str | Path] = None,
        icon_registry: Optional[IconRegistry] = None,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.output_dir = Path(output_dir).resolve() if output_dir else self.repo_path / "drawio_output"
        self.icon_registry = icon_registry or IconRegistry()

        # Sub-components
        self._scanner = RepoScanner(self.repo_path)
        self._detector = DiagramDetector()
        self._flow_parser = FlowchartParser()
        self._er_parser = ERParser()
        self._flow_converter = FlowchartConverter(icon_registry=self.icon_registry)
        self._er_converter = ERConverter()

    def convert_all(self) -> list[ConversionResult]:
        """
        Scan the repository, detect diagram types, parse, and convert
        each Mermaid block to a separate .drawio file.

        Returns
        -------
        list[ConversionResult]
        """
        os.makedirs(self.output_dir, exist_ok=True)

        blocks = self._scanner.scan()
        results: list[ConversionResult] = []

        for block in blocks:
            result = self._convert_block(block)
            results.append(result)

        return results

    def convert_single(self, mermaid_source: str, output_path: str, diagram_name: str = "Diagram") -> ConversionResult:
        """
        Convert a single Mermaid source string to a Draw.io file.

        Parameters
        ----------
        mermaid_source : str
            Raw Mermaid diagram text.
        output_path : str
            Path for the output .drawio file.
        diagram_name : str
            Name for the diagram tab inside Draw.io.

        Returns
        -------
        ConversionResult
        """
        dtype = self._detector.detect(mermaid_source)

        try:
            if dtype == DiagramType.FLOWCHART:
                ast = self._flow_parser.parse(mermaid_source)
                xml = self._flow_converter.convert(ast, diagram_name=diagram_name)
            elif dtype == DiagramType.ER_DIAGRAM:
                ast = self._er_parser.parse(mermaid_source)
                xml = self._er_converter.convert(ast, diagram_name=diagram_name)
            else:
                # Attempt flowchart as default
                ast = self._flow_parser.parse(mermaid_source)
                xml = self._flow_converter.convert(ast, diagram_name=diagram_name)
                dtype = DiagramType.FLOWCHART

            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(xml)

            return ConversionResult(
                source_file="<inline>",
                block_index=0,
                diagram_type=dtype,
                output_path=output_path,
                success=True,
            )
        except Exception as e:
            return ConversionResult(
                source_file="<inline>",
                block_index=0,
                diagram_type=dtype,
                output_path=output_path,
                success=False,
                error=str(e),
            )

    # ── Internal ───────────────────────────────────────────────────────

    def _extract_diagram_name(self, source: str, block_index: int) -> str:
        """
        Extract a meaningful diagram name from the Mermaid source.
        Looks for:
        1. A 'title' directive in the source
        2. The first subgraph title that hints at the architecture type
        3. Combines unique subgraph keywords to build a descriptive name
        Falls back to 'Architecture_Diagram_{index}'.
        """
        lines = source.split("\n")

        # 1. Check for explicit title directive
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith("title "):
                title = stripped[6:].strip().strip('"').strip("'")
                if title:
                    # Keep first 2 words to stay concise
                    words = title.split()
                    return "_".join(words[:2])

        # 2. Collect subgraph titles
        sg_titles = []
        for line in lines:
            stripped = line.strip()
            m = re.match(r'subgraph\s+\w+\s*\[\s*"([^"]+)"\s*\]', stripped)
            if m:
                sg_titles.append(m.group(1))
            elif re.match(r'subgraph\s+\w+\s*\[\s*([^\]]+)\s*\]', stripped):
                m2 = re.match(r'subgraph\s+\w+\s*\[\s*([^\]]+)\s*\]', stripped)
                if m2:
                    sg_titles.append(m2.group(1).strip())

        # Scan SUBGRAPH TITLES for primary technology names (most reliable)
        sg_text = " ".join(sg_titles)

        # Ordered by architectural significance — most distinctive first
        tech_patterns = [
            (r'Pub.?Sub', 'PubSub'),
            (r'Dataproc', 'Dataproc'),
            (r'Composer', 'Composer'),
            (r'Airflow', 'Airflow'),
            (r'Dataflow', 'Dataflow'),
            (r'BigQuery', 'BigQuery'),
            (r'PySpark|Spark', 'Spark'),
            (r'Kafka', 'Kafka'),
            (r'Cloud Run', 'CloudRun'),
            (r'Cloud Functions', 'CloudFunctions'),
        ]
        tech_keywords = []

        # First pass: subgraph titles only (high confidence)
        for pattern, label in tech_patterns:
            if re.search(pattern, sg_text, re.IGNORECASE):
                if label not in tech_keywords:
                    tech_keywords.append(label)

        # Second pass: full source (catches node labels) — only add NEW keywords
        for pattern, label in tech_patterns:
            if label not in tech_keywords and re.search(pattern, source, re.IGNORECASE):
                tech_keywords.append(label)

        if tech_keywords:
            # Clean up: skip Airflow if Composer already present
            if 'Composer' in tech_keywords and 'Airflow' in tech_keywords:
                tech_keywords.remove('Airflow')
            name = "_".join(tech_keywords[:2])
            return name

        # 3. Fallback
        return f"Diagram_{block_index + 1}"

    def _make_safe_filename(self, raw_name: str, max_len: int = 30) -> str:
        """Sanitise a string into a safe, short filename stem."""
        safe = re.sub(r"[^\w\-.]", "_", raw_name)
        safe = re.sub(r"_+", "_", safe).strip("_")
        if len(safe) > max_len:
            safe = safe[:max_len].rstrip("_")
        return safe

    def _convert_block(self, block: MermaidBlock) -> ConversionResult:
        """Convert a single discovered Mermaid block."""
        dtype = self._detector.detect(block.source)

        # Build output filename from:
        #   1. context_name (heading found above the mermaid block in source)
        #   2. Technology keywords extracted from diagram content (fallback)
        option_num = block.block_index + 1

        if block.context_name:
            # Use the actual heading from the source file
            # Clean up: remove leading numbering like "4." or "5."
            diagram_name = re.sub(r"^\d+\.\s*", "", block.context_name)
            # Remove redundant "Option N —" prefix since we already add Option-N
            diagram_name = re.sub(r"^Option\s*\d+\s*[—\-:]+\s*", "", diagram_name)
            # Remove trailing qualifiers like "Recommended", "(Hybrid)", etc.
            diagram_name = re.sub(r"\s*[\(]?(?:Recommended|Hybrid|Draft|Final|v\d+)[\)]?\s*$", "", diagram_name, flags=re.IGNORECASE)
            diagram_name = diagram_name.strip().rstrip("+")
            if not diagram_name:
                diagram_name = block.context_name
        else:
            # Fall back to technology keyword extraction
            diagram_name = self._extract_diagram_name(block.source, block.block_index)

        safe_name = self._make_safe_filename(diagram_name)
        output_name = f"Opt{option_num}_{safe_name}.drawio"
        output_path = os.path.join(self.output_dir, output_name)

        try:
            if dtype == DiagramType.FLOWCHART:
                ast = self._flow_parser.parse(block.source)
                xml = self._flow_converter.convert(ast, diagram_name=diagram_name)
            elif dtype == DiagramType.ER_DIAGRAM:
                ast = self._er_parser.parse(block.source)
                xml = self._er_converter.convert(ast, diagram_name=diagram_name)
            else:
                # Best-effort: try flowchart
                ast = self._flow_parser.parse(block.source)
                xml = self._flow_converter.convert(ast, diagram_name=diagram_name)
                dtype = DiagramType.FLOWCHART

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(xml)

            return ConversionResult(
                source_file=block.file_path,
                block_index=block.block_index,
                diagram_type=dtype,
                output_path=output_path,
                success=True,
            )

        except Exception as e:
            return ConversionResult(
                source_file=block.file_path,
                block_index=block.block_index,
                diagram_type=dtype,
                output_path=output_path,
                success=False,
                error=str(e),
            )
