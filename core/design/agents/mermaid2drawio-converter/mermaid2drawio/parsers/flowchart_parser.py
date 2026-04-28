"""
Flowchart / Graph parser for Mermaid diagrams.

Supports:
  - graph TB / LR / BT / RL / TD
  - flowchart TB / LR / BT / RL / TD
  - Node shapes: [] () {} (()) [[]] [/  /] [\\  \\] {{}}  >  ]
  - Edge types: -->, ---, -.->,-.->, ==>  with optional labels |text|
  - Subgraphs (nested)
  - & combinator:  A & B --> C  and  A --> B & C
  - Class definitions (classDef) and class assignments
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FlowNode:
    node_id: str
    label: str
    shape: str = "rect"          # rect | round | diamond | hexagon | stadium | cylinder | ...
    css_class: Optional[str] = None
    subgraph: Optional[str] = None


@dataclass
class FlowEdge:
    source: str
    target: str
    label: Optional[str] = None
    edge_type: str = "normal"    # normal | dotted | thick


@dataclass
class Subgraph:
    sg_id: str
    title: str
    children: list[str] = field(default_factory=list)


@dataclass
class FlowchartAST:
    """Abstract Syntax Tree for a parsed Mermaid flowchart."""
    direction: str = "TB"
    nodes: dict[str, FlowNode] = field(default_factory=dict)
    edges: list[FlowEdge] = field(default_factory=list)
    subgraphs: list[Subgraph] = field(default_factory=list)
    class_defs: dict[str, str] = field(default_factory=dict)


def _strip_quotes(text: str) -> str:
    """Remove surrounding double or single quotes from a string."""
    text = text.strip()
    if len(text) >= 2:
        if (text[0] == '"' and text[-1] == '"') or (text[0] == "'" and text[-1] == "'"):
            return text[1:-1]
    return text


class FlowchartParser:
    """
    Parse Mermaid flowchart/graph source into a FlowchartAST.
    """

    _HEADER = re.compile(
        r"^\s*(?:graph|flowchart)\s+(TB|BT|LR|RL|TD)\s*$", re.IGNORECASE
    )
    _HEADER_BARE = re.compile(r"^\s*(?:graph|flowchart)\b", re.IGNORECASE)

    # Subgraph
    _SUBGRAPH_RE = re.compile(
        r'^\s*subgraph\s+(\w[\w\d_]*)(?:\s*\["([^"]*)"\])?\s*$', re.IGNORECASE
    )
    _SUBGRAPH_END_RE = re.compile(r"^\s*end\s*$", re.IGNORECASE)

    # classDef / class
    _CLASSDEF_RE = re.compile(r"^\s*classDef\s+(\w+)\s+(.*)\s*$", re.IGNORECASE)
    _CLASS_RE = re.compile(r"^\s*class\s+([\w,\s]+)\s+(\w+)\s*$", re.IGNORECASE)

    # Edge markers — ordered longest first for regex alternation
    _EDGE_MARKERS = [
        ("-.->",  "dotted"),
        ("-..->", "dotted"),
        ("-.-",   "dotted"),
        ("===>",  "thick"),
        ("==>",   "thick"),
        ("===",   "thick"),
        ("-->",   "normal"),
        ("---",   "normal"),
    ]

    # Build a regex that splits a line on edge markers, including |label| syntax
    # Pattern: optional |label| before or after the arrow
    _EDGE_SPLIT_RE = re.compile(
        r'\s*'
        r'(?:\|"?([^"|]*)"?\|\s*)?'   # optional leading |label|
        r'(---->|--->|-->|---|-\.->|-\.\.\->|-\.-|====>|===>|==>|===)'  # arrow
        r'(?:\s*\|"?([^"|]*)"?\|)?'   # optional trailing |label|
        r'\s*'
    )

    # Node with shape: ID["label"] or ID[label] etc.
    _NODE_PATTERN = re.compile(
        r'(\w[\w\d_]*)'           # node ID
        r'(?:'
        r'\[\["([^"]*?)"\]\]'     # [[...]] subroutine
        r'|\[\[([^\]]*?)\]\]'     # [[...]] subroutine (no quotes)
        r'|\(\("([^"]*?)"\)\)'    # ((...)) circle
        r'|\(\(([^)]*?)\)\)'      # ((...)) circle (no quotes)
        r'|\{\{"([^"]*?)"\}\}'    # {{...}} hexagon
        r'|\{\{([^}]*?)\}\}'      # {{...}} hexagon (no quotes)
        r'|\[\("([^"]*?)"\)\]'    # [(...)] cylinder
        r'|\[\(([^)]*?)\)\]'      # [(...)] cylinder (no quotes)
        r'|\(\["([^"]*?)"\]\)'    # ([...]) stadium
        r'|\(\[([^\]]*?)\]\)'     # ([...]) stadium (no quotes)
        r'|\["([^"]*?)"\]'        # [...] rect (quoted)
        r'|\[([^\]]*?)\]'         # [...] rect (unquoted)
        r'|\("([^"]*?)"\)'        # (...) round (quoted)
        r'|\(([^)]*?)\)'          # (...) round (unquoted)
        r'|\{"([^"]*?)"\}'        # {...} diamond (quoted)
        r'|\{([^}]*?)\}'          # {...} diamond (unquoted)
        r'|>"([^"]*?)"\]'         # >...] asymmetric (quoted)
        r'|>([^\]]*?)\]'          # >...] asymmetric (unquoted)
        r')?'
    )

    # Shape group mapping: (shape_name, group_indices)
    _SHAPE_GROUPS = [
        ("subroutine", [2, 3]),
        ("circle",     [4, 5]),
        ("hexagon",    [6, 7]),
        ("cylinder",   [8, 9]),
        ("stadium",    [10, 11]),
        ("rect",       [12, 13]),
        ("round",      [14, 15]),
        ("diamond",    [16, 17]),
        ("asymmetric", [18, 19]),
    ]

    def parse(self, source: str) -> FlowchartAST:
        """Parse Mermaid flowchart source into a FlowchartAST."""
        ast = FlowchartAST()
        lines = source.strip().splitlines()

        current_subgraph: Optional[Subgraph] = None
        sg_stack: list[Subgraph] = []

        for raw_line in lines:
            line = raw_line.split("%%")[0].strip()
            if not line or line.startswith("```"):
                continue

            # Header
            hdr = self._HEADER.match(line)
            if hdr:
                ast.direction = hdr.group(1).upper()
                continue
            if self._HEADER_BARE.match(line):
                # Check if this is just the bare header with no edge content
                if not self._EDGE_SPLIT_RE.search(line):
                    continue

            # classDef
            cdef = self._CLASSDEF_RE.match(line)
            if cdef:
                ast.class_defs[cdef.group(1)] = cdef.group(2).strip()
                continue

            # class assignment
            ca = self._CLASS_RE.match(line)
            if ca:
                class_name = ca.group(2).strip()
                for nid in ca.group(1).split(","):
                    nid = nid.strip()
                    if nid in ast.nodes:
                        ast.nodes[nid].css_class = class_name
                continue

            # Subgraph start
            sg = self._SUBGRAPH_RE.match(line)
            if sg:
                new_sg = Subgraph(
                    sg_id=sg.group(1),
                    title=_strip_quotes(sg.group(2) or sg.group(1)),
                )
                ast.subgraphs.append(new_sg)
                if current_subgraph is not None:
                    sg_stack.append(current_subgraph)
                current_subgraph = new_sg
                continue

            if self._SUBGRAPH_END_RE.match(line):
                current_subgraph = sg_stack.pop() if sg_stack else None
                continue

            # Try to parse edge line (handles chains and & combinators)
            if self._parse_edge_line(line, ast, current_subgraph):
                continue

            # Standalone node declaration
            self._parse_standalone_node(line, ast, current_subgraph)

        return ast

    def _parse_node_token(self, token: str) -> tuple[str, str, Optional[str]]:
        """
        Parse a node token like 'A["label"]' into (node_id, shape, label).
        Returns (node_id, shape, label_or_None).
        """
        token = token.strip()
        m = self._NODE_PATTERN.match(token)
        if not m:
            return (token, "rect", None)

        node_id = m.group(1)

        for shape_name, groups in self._SHAPE_GROUPS:
            for gi in groups:
                if m.group(gi) is not None:
                    return (node_id, shape_name, _strip_quotes(m.group(gi)))

        return (node_id, "rect", None)

    def _ensure_node(self, ast, node_id, label, shape, subgraph):
        """Ensure a node exists in the AST."""
        if node_id not in ast.nodes:
            ast.nodes[node_id] = FlowNode(
                node_id=node_id,
                label=_strip_quotes(label or node_id),
                shape=shape,
                subgraph=subgraph.sg_id if subgraph else None,
            )
        else:
            node = ast.nodes[node_id]
            if label and node.label == node_id:
                node.label = _strip_quotes(label)
                node.shape = shape
            if subgraph and not node.subgraph:
                node.subgraph = subgraph.sg_id
        if subgraph and node_id not in subgraph.children:
            subgraph.children.append(node_id)

    def _parse_edge_line(self, line: str, ast, subgraph) -> bool:
        """
        Parse a line with edges, including chains and & combinators.
        Examples:
            A --> B
            A --> B --> C
            A & B --> C
            A --> B & C
            GCS1 & GCS2 & GCS3 -->|"label"| D
            A -->|"text"| B --> C
        """
        # Check if there's any edge marker in the line
        if not self._EDGE_SPLIT_RE.search(line):
            return False

        # Split line into segments by edge markers
        parts = self._EDGE_SPLIT_RE.split(line)
        # parts alternates: [node_group, label_before, arrow, label_after, node_group, ...]

        if len(parts) < 4:
            return False

        # Extract: node_groups and edge_info
        segments = []
        i = 0
        while i < len(parts):
            if i == 0:
                # First node group
                segments.append(("nodes", parts[0].strip()))
                i += 1
            elif i + 3 <= len(parts):
                label_before = parts[i] or ""
                arrow = parts[i + 1]
                label_after = parts[i + 2] or ""
                edge_label = (label_before or label_after).strip()
                edge_label = _strip_quotes(edge_label) if edge_label else ""

                etype = "normal"
                for marker, mtype in self._EDGE_MARKERS:
                    if arrow == marker:
                        etype = mtype
                        break

                segments.append(("edge", etype, edge_label))

                if i + 3 < len(parts):
                    segments.append(("nodes", parts[i + 3].strip()))
                    i += 4
                else:
                    i += 3
            else:
                break

        # Now process segments
        node_groups = []
        edge_infos = []
        for seg in segments:
            if seg[0] == "nodes":
                raw = seg[1]
                if not raw:
                    continue
                # Split on & combinator
                tokens = [t.strip() for t in raw.split("&")]
                group = []
                for tok in tokens:
                    if not tok:
                        continue
                    nid, shape, label = self._parse_node_token(tok)
                    self._ensure_node(ast, nid, label, shape, subgraph)
                    group.append(nid)
                node_groups.append(group)
            elif seg[0] == "edge":
                edge_infos.append((seg[1], seg[2]))

        # Create edges: each source in group[i] -> each target in group[i+1]
        for i, (etype, elabel) in enumerate(edge_infos):
            if i >= len(node_groups) or i + 1 >= len(node_groups):
                break
            sources = node_groups[i]
            targets = node_groups[i + 1]
            for src in sources:
                for tgt in targets:
                    ast.edges.append(FlowEdge(
                        source=src,
                        target=tgt,
                        label=elabel if elabel else None,
                        edge_type=etype,
                    ))

        return True

    def _parse_standalone_node(self, line: str, ast, subgraph) -> bool:
        """Parse a standalone node declaration like: A["Some Label"]"""
        line = line.strip()
        nid, shape, label = self._parse_node_token(line)
        if nid and re.match(r"^\w[\w\d_]*$", nid):
            # Only treat as standalone if there's an explicit shape/label
            if label is not None:
                self._ensure_node(ast, nid, label, shape, subgraph)
                return True
        return False
