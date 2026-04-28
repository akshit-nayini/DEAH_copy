"""
Convert a FlowchartAST into a Draw.io XML file with color-coded subgraphs and embedded SVG icons.

Key features:
  - FLAT layout: all nodes are children of root (parent="1"), subgraphs are background containers
  - Color-coded subgraphs: each section type gets unique fill and stroke colors
  - Embedded SVG icons: branded service icons (64x64) with base64 data URIs
  - Child node coloring: nodes inherit lighter shade of their subgraph's color scheme
  - Auto-layout with configurable direction (TB/LR/BT/RL)
  - Edge style preservation (normal, dotted, thick)
  - Title banner at the top spanning full width
"""

from __future__ import annotations

import math
import re
from typing import Optional

from ..parsers.flowchart_parser import FlowchartAST, FlowNode, FlowEdge, Subgraph
from ..icons.registry import IconRegistry
from . import drawio_xml as dx


class FlowchartConverter:
    """
    Convert a parsed Mermaid flowchart AST to Draw.io XML with color-coded subgraphs
    and embedded SVG icons.
    """

    # Layout constants
    H_GAP = 60          # horizontal gap between nodes
    V_GAP = 80          # vertical gap between layers
    SUBGRAPH_PAD_X = 30
    SUBGRAPH_PAD_Y = 60  # extra top padding for title
    SUBGRAPH_GAP = 40    # gap between subgraphs

    # Sizing
    MIN_NODE_W = 180
    MAX_NODE_W = 220
    MIN_NODE_H = 50
    ICON_W = 70
    ICON_H = 70
    CHAR_W = 7           # approx pixels per character for width calc
    LINE_H = 18          # approx pixels per line for height calc

    # Subgraph color schemes (fillColor, strokeColor)
    SUBGRAPH_COLORS = {
        "source": ("#FFF8E1", "#F9A825"),           # yellow
        "orchestration": ("#E3F2FD", "#1565C0"),    # blue
        "landing": ("#E8F5E9", "#2E7D32"),          # green
        "gcs": ("#E8F5E9", "#2E7D32"),              # green
        "storage": ("#E8F5E9", "#2E7D32"),          # green
        "cloud storage": ("#E8F5E9", "#2E7D32"),    # green
        "raw": ("#E8F5E9", "#2E7D32"),              # green
        "processing": ("#EDE7F6", "#4527A0"),       # purple
        "dataflow": ("#EDE7F6", "#4527A0"),         # purple
        "beam": ("#EDE7F6", "#4527A0"),             # purple
        "dataproc": ("#EDE7F6", "#4527A0"),         # purple
        "spark": ("#EDE7F6", "#4527A0"),            # purple
        "bigquery": ("#E3F2FD", "#0D47A1"),         # dark blue
        "warehouse": ("#E3F2FD", "#0D47A1"),        # dark blue
        "bq": ("#E3F2FD", "#0D47A1"),               # dark blue
        "consumption": ("#F1F8E9", "#33691E"),      # light green
        "serve": ("#F1F8E9", "#33691E"),            # light green
        "dashboard": ("#F1F8E9", "#33691E"),        # light green
        "reporting": ("#F1F8E9", "#33691E"),        # light green
        "operations": ("#FBE9E7", "#BF360C"),       # red/orange
        "ops": ("#FBE9E7", "#BF360C"),              # red/orange
        "monitoring": ("#FBE9E7", "#BF360C"),       # red/orange
        "infra": ("#FBE9E7", "#BF360C"),            # red/orange
        "composer": ("#E3F2FD", "#1565C0"),         # blue
        "airflow": ("#E3F2FD", "#1565C0"),          # blue
    }

    # Child node colors (lighter fill, same stroke family as parent)
    CHILD_NODE_COLORS = {
        ("source", "#FFF8E1", "#F9A825"): ("#FFF9C4", "#F9A825"),
        ("orchestration", "#E3F2FD", "#1565C0"): ("#BBDEFB", "#1565C0"),
        ("landing", "#E8F5E9", "#2E7D32"): ("#C8E6C9", "#2E7D32"),
        ("gcs", "#E8F5E9", "#2E7D32"): ("#C8E6C9", "#2E7D32"),
        ("storage", "#E8F5E9", "#2E7D32"): ("#C8E6C9", "#2E7D32"),
        ("cloud storage", "#E8F5E9", "#2E7D32"): ("#C8E6C9", "#2E7D32"),
        ("raw", "#E8F5E9", "#2E7D32"): ("#C8E6C9", "#2E7D32"),
        ("processing", "#EDE7F6", "#4527A0"): ("#D1C4E9", "#4527A0"),
        ("dataflow", "#EDE7F6", "#4527A0"): ("#D1C4E9", "#4527A0"),
        ("beam", "#EDE7F6", "#4527A0"): ("#D1C4E9", "#4527A0"),
        ("dataproc", "#EDE7F6", "#4527A0"): ("#D1C4E9", "#4527A0"),
        ("spark", "#EDE7F6", "#4527A0"): ("#D1C4E9", "#4527A0"),
        ("bigquery", "#E3F2FD", "#0D47A1"): ("#BBDEFB", "#0D47A1"),
        ("warehouse", "#E3F2FD", "#0D47A1"): ("#BBDEFB", "#0D47A1"),
        ("bq", "#E3F2FD", "#0D47A1"): ("#BBDEFB", "#0D47A1"),
        ("consumption", "#F1F8E9", "#33691E"): ("#DCEDC8", "#33691E"),
        ("serve", "#F1F8E9", "#33691E"): ("#DCEDC8", "#33691E"),
        ("dashboard", "#F1F8E9", "#33691E"): ("#DCEDC8", "#33691E"),
        ("reporting", "#F1F8E9", "#33691E"): ("#DCEDC8", "#33691E"),
        ("operations", "#FBE9E7", "#BF360C"): ("#FFCCBC", "#BF360C"),
        ("ops", "#FBE9E7", "#BF360C"): ("#FFCCBC", "#BF360C"),
        ("monitoring", "#FBE9E7", "#BF360C"): ("#FFCCBC", "#BF360C"),
        ("infra", "#FBE9E7", "#BF360C"): ("#FFCCBC", "#BF360C"),
        ("composer", "#E3F2FD", "#1565C0"): ("#BBDEFB", "#1565C0"),
        ("airflow", "#E3F2FD", "#1565C0"): ("#BBDEFB", "#1565C0"),
    }

    # Fallback colors for unknown subgraph types
    DEFAULT_SUBGRAPH_FILL = "#F5F5F5"
    DEFAULT_SUBGRAPH_STROKE = "#999999"
    DEFAULT_CHILD_FILL = "#E8E8E8"

    def __init__(self, icon_registry: Optional[IconRegistry] = None):
        self.icons = icon_registry or IconRegistry()
        self._id_counter = 0

    def convert(self, ast: FlowchartAST, diagram_name: str = "Flowchart") -> str:
        """Convert FlowchartAST → Draw.io XML string."""
        mxfile = dx.create_mxfile()
        diagram = dx.create_diagram(mxfile, name=diagram_name)
        root = dx.create_graph_model(diagram)

        # Assign Draw.io cell IDs
        id_map: dict[str, str] = {}
        for nid in ast.nodes:
            id_map[nid] = dx.new_id()

        sg_id_map: dict[str, str] = {}
        for sg in ast.subgraphs:
            sg_id_map[sg.sg_id] = dx.new_id()

        # Calculate node dimensions
        node_sizes: dict[str, tuple[float, float]] = {}
        for nid, node in ast.nodes.items():
            node_sizes[nid] = self._calc_node_size(node)

        # Layout
        positions = self._layout(ast, node_sizes)

        # Add title banner at the top
        self._add_title_banner(root)

        # Create subgraph containers (FLAT layout: children of root, not subgraphs)
        subgraph_colors: dict[str, tuple[str, str]] = {}
        for sg in ast.subgraphs:
            bbox = self._subgraph_bbox(sg, positions, node_sizes)
            fill, stroke = self._get_subgraph_colors(sg)
            subgraph_colors[sg.sg_id] = (fill, stroke)

            style = (
                f"rounded=1;html=1;fillColor={fill};strokeColor={stroke};"
                f"fontSize=11;fontColor=#333;fontStyle=1;"
                f"verticalAlign=top;align=left;spacingLeft=10;spacingTop=6;"
            )
            dx.add_group(
                root,
                group_id=sg_id_map[sg.sg_id],
                label=sg.title,
                x=bbox[0],
                y=bbox[1],
                width=bbox[2],
                height=bbox[3],
                style=style,
            )

        # Create nodes (all children of root parent="1" for FLAT layout)
        for nid, node in ast.nodes.items():
            x, y = positions.get(nid, (0, 0))
            w, h = node_sizes[nid]

            is_icon = self.icons.is_icon_node(node.label)

            # Determine parent (all are root "1" for flat layout)
            parent_id = "1"

            # Get child node color from parent subgraph
            child_fill = self.DEFAULT_CHILD_FILL
            child_stroke = "#999999"
            if node.subgraph and node.subgraph in subgraph_colors:
                parent_fill, parent_stroke = subgraph_colors[node.subgraph]
                # Lighter shade for child
                child_fill = self._lighten_color(parent_fill)
                child_stroke = parent_stroke

            # For icon nodes, add both icon and text label as separate elements
            if is_icon:
                # Icon cell (48x48)
                icon_style = self.icons.get_style_for_node(node.label)
                dx.add_node(
                    root,
                    cell_id=id_map[nid],
                    label="",
                    style=icon_style,
                    x=x + (w - self.ICON_W) / 2,
                    y=y,
                    width=self.ICON_W,
                    height=self.ICON_H,
                    parent=parent_id,
                )
                # Label cell below icon
                label_id = dx.new_id()
                clean_label = self._clean_label(node.label)
                label_style = (
                    "text;html=1;align=center;verticalAlign=top;"
                    "whiteSpace=wrap;rounded=0;fillColor=none;strokeColor=none;"
                    "fontSize=10;fontStyle=1;fontColor=#333333;"
                )
                dx.add_node(
                    root,
                    cell_id=label_id,
                    label=clean_label,
                    style=label_style,
                    x=x,
                    y=y + self.ICON_H + 4,
                    width=w,
                    height=h - self.ICON_H - 4,
                    parent=parent_id,
                )
            else:
                # Description box (text node with colored background)
                clean_label = self._clean_label(node.label)
                node_style = (
                    f"rounded=1;whiteSpace=wrap;html=1;fillColor={child_fill};"
                    f"strokeColor={child_stroke};strokeWidth=2;fontSize=9;fontStyle=0;"
                    f"align=center;verticalAlign=middle;spacingTop=2;spacingBottom=2;"
                )
                dx.add_node(
                    root,
                    cell_id=id_map[nid],
                    label=clean_label,
                    style=node_style,
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    parent=parent_id,
                )

        # Create edges
        for edge in ast.edges:
            if edge.source not in id_map or edge.target not in id_map:
                continue
            style = self._edge_style(edge)
            edge_label = self._clean_label(edge.label) if edge.label else ""
            dx.add_edge(
                root,
                cell_id=dx.new_id(),
                source_id=id_map[edge.source],
                target_id=id_map[edge.target],
                label=edge_label,
                style=style,
            )

        return dx.serialize(mxfile)

    # ── Title Banner ───────────────────────────────────────────────────

    def _add_title_banner(self, root) -> None:
        """Add a title banner at the top spanning full width."""
        title_style = (
            "text;html=1;align=center;verticalAlign=middle;"
            "whiteSpace=wrap;rounded=1;fillColor=#E8EAF6;strokeColor=#3949AB;"
            "fontSize=16;fontStyle=1;fontColor=#1A237E;strokeWidth=2;"
        )
        dx.add_node(
            root,
            cell_id=dx.new_id(),
            label="Data Pipeline Architecture",
            style=title_style,
            x=60,
            y=10,
            width=1400,
            height=40,
            parent="1",
        )

    # ── Label cleaning ─────────────────────────────────────────────────

    def _clean_label(self, text: str) -> str:
        """
        Clean up a label: strip quotes and convert escape sequences to actual newlines.
        Draw.io respects actual newlines in value attributes when whiteSpace=wrap is set.
        """
        if not text:
            return ""
        # Strip surrounding quotes
        text = text.strip().strip('"').strip("'")
        # Convert \\n escape sequence to actual newline
        text = text.replace("\\n", "\n")
        return text

    # ── Node sizing ────────────────────────────────────────────────────

    def _calc_node_size(self, node: FlowNode) -> tuple[float, float]:
        """Calculate node width and height based on label content."""
        label = node.label.strip().strip('"').strip("'")
        lines = label.replace("\\n", "\n").split("\n")
        is_icon = self.icons.is_icon_node(label)

        # Width: based on longest line
        max_line_len = max((len(line) for line in lines), default=5)
        w = max(self.MIN_NODE_W, min(self.MAX_NODE_W, max_line_len * self.CHAR_W + 20))

        # Height: based on number of lines
        n_lines = len(lines)
        text_h = max(self.MIN_NODE_H, n_lines * self.LINE_H + 16)

        if is_icon:
            # Icon on top + text below
            h = self.ICON_H + text_h + 4
            w = max(w, self.ICON_W + 20)
        else:
            h = text_h

        return (w, h)

    # ── Subgraph color helpers ──────────────────────────────────────────

    def _get_subgraph_colors(self, sg: Subgraph) -> tuple[str, str]:
        """
        Determine fill and stroke colors for a subgraph based on its title keywords.
        Returns (fillColor, strokeColor) tuple.
        """
        title_lower = sg.title.lower()

        # Check for matching keywords in priority order
        for keyword, (fill, stroke) in self.SUBGRAPH_COLORS.items():
            if keyword in title_lower:
                return (fill, stroke)

        # Fallback to gray
        return (self.DEFAULT_SUBGRAPH_FILL, self.DEFAULT_SUBGRAPH_STROKE)

    def _lighten_color(self, hex_color: str) -> str:
        """
        Lighten a hex color by interpolating towards white.
        E.g., #E3F2FD (light) -> even lighter shade.
        """
        # Simple approach: already light colors stay mostly as-is
        # For known colors, return the lighter shade
        lightness_map = {
            "#FFF8E1": "#FFFEF5",
            "#E3F2FD": "#F5FBFF",
            "#E8F5E9": "#F1F9F2",
            "#EDE7F6": "#F7F2FD",
            "#F1F8E9": "#F9FCF5",
            "#FBE9E7": "#FEF5F2",
            "#F5F5F5": "#FAFAFA",
        }
        return lightness_map.get(hex_color, "#F9F9F9")

    # ── Layout engine ──────────────────────────────────────────────────

    def _layout(self, ast: FlowchartAST, node_sizes: dict) -> dict[str, tuple[float, float]]:
        """
        Layer-based layout using topological ordering.
        Groups nodes by subgraph and lays out subgraphs sequentially.
        """
        # Build adjacency for topological sort
        adj: dict[str, list[str]] = {nid: [] for nid in ast.nodes}
        in_deg: dict[str, int] = {nid: 0 for nid in ast.nodes}
        for edge in ast.edges:
            if edge.source in adj and edge.target in in_deg:
                adj[edge.source].append(edge.target)
                in_deg[edge.target] = in_deg.get(edge.target, 0) + 1

        # BFS layering (Kahn's algorithm)
        layers: list[list[str]] = []
        queue = [n for n, d in in_deg.items() if d == 0]
        visited = set()

        while queue:
            layers.append(list(queue))
            visited.update(queue)
            next_q = []
            for n in queue:
                for nb in adj.get(n, []):
                    in_deg[nb] -= 1
                    if in_deg[nb] <= 0 and nb not in visited:
                        next_q.append(nb)
                        visited.add(nb)
            queue = next_q

        # Add remaining nodes (cycles/disconnected)
        remaining = [n for n in ast.nodes if n not in visited]
        if remaining:
            layers.append(remaining)

        # Assign positions
        positions: dict[str, tuple[float, float]] = {}
        direction = ast.direction.upper()
        is_horizontal = direction in ("LR", "RL")

        # Calculate max width per layer for centering
        layer_widths = []
        for layer in layers:
            if is_horizontal:
                total = sum(node_sizes[nid][1] for nid in layer) + self.H_GAP * (len(layer) - 1)
            else:
                total = sum(node_sizes[nid][0] for nid in layer) + self.H_GAP * (len(layer) - 1)
            layer_widths.append(total)
        max_layer_width = max(layer_widths) if layer_widths else 0

        primary_offset = 120  # starting offset (below title banner at y=10, h=40)

        for layer_idx, layer in enumerate(layers):
            # Calculate total span of this layer for centering
            if is_horizontal:
                total_span = sum(node_sizes[nid][1] for nid in layer) + self.H_GAP * (len(layer) - 1)
            else:
                total_span = sum(node_sizes[nid][0] for nid in layer) + self.H_GAP * (len(layer) - 1)

            center_offset = (max_layer_width - total_span) / 2

            secondary_pos = 100 + center_offset  # cross-axis position

            for nid in layer:
                w, h = node_sizes[nid]

                if direction in ("TB", "TD"):
                    x = secondary_pos
                    y = primary_offset
                    secondary_pos += w + self.H_GAP
                elif direction == "BT":
                    x = secondary_pos
                    y = primary_offset
                    secondary_pos += w + self.H_GAP
                elif direction == "LR":
                    x = primary_offset
                    y = secondary_pos
                    secondary_pos += h + self.H_GAP
                elif direction == "RL":
                    x = primary_offset
                    y = secondary_pos
                    secondary_pos += h + self.H_GAP
                else:
                    x = secondary_pos
                    y = primary_offset
                    secondary_pos += w + self.H_GAP

                positions[nid] = (x, y)

            # Advance primary axis
            if is_horizontal:
                max_dim = max(node_sizes[nid][0] for nid in layer)
            else:
                max_dim = max(node_sizes[nid][1] for nid in layer)
            primary_offset += max_dim + self.V_GAP

        # Flip for BT/RL
        if direction == "BT" and positions:
            max_y = max(y + node_sizes[nid][1] for nid, (_, y) in positions.items())
            for nid in positions:
                x, y = positions[nid]
                positions[nid] = (x, max_y - y - node_sizes[nid][1] + 60)
        elif direction == "RL" and positions:
            max_x = max(x + node_sizes[nid][0] for nid, (x, _) in positions.items())
            for nid in positions:
                x, y = positions[nid]
                positions[nid] = (max_x - x - node_sizes[nid][0] + 60, y)

        return positions

    def _subgraph_bbox(
        self, sg: Subgraph, positions: dict, node_sizes: dict
    ) -> tuple[float, float, float, float]:
        """Return (x, y, width, height) for a subgraph container."""
        if not sg.children:
            return (60, 60, 300, 150)

        valid = [c for c in sg.children if c in positions]
        if not valid:
            return (60, 60, 300, 150)

        min_x = min(positions[c][0] for c in valid) - self.SUBGRAPH_PAD_X
        min_y = min(positions[c][1] for c in valid) - self.SUBGRAPH_PAD_Y
        max_x = max(positions[c][0] + node_sizes[c][0] for c in valid) + self.SUBGRAPH_PAD_X
        max_y = max(positions[c][1] + node_sizes[c][1] for c in valid) + self.SUBGRAPH_PAD_X

        return (min_x, min_y, max_x - min_x, max_y - min_y)

    # ── Edge style builder ──────────────────────────────────────────────

    def _edge_style(self, edge: FlowEdge) -> str:
        """Build Draw.io style for an edge."""
        base_style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=1;"
            "orthogonalLoop=1;jettySize=auto;html=1;"
            "fontSize=8;fontColor=#333;"
        )

        if edge.edge_type == "dotted":
            return (
                f"{base_style}strokeColor=#999;strokeWidth=1.5;dashed=1;"
            )
        elif edge.edge_type == "thick":
            return (
                f"{base_style}strokeColor=#333;strokeWidth=2.5;dashed=0;"
            )
        else:
            return (
                f"{base_style}strokeColor=#555;strokeWidth=1.5;dashed=0;"
            )
