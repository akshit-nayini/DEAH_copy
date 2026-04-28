"""
Convert an ERAST (ER diagram AST) into a Draw.io XML file.

Generates proper ER model notation with:
  - Entity tables (header row + attribute rows)
  - Primary/Foreign key indicators
  - Relationship lines with cardinality labels
  - Auto grid layout
"""

from __future__ import annotations

from ..parsers.er_parser import ERAST, EREntity, ERRelationship, ERAttribute
from . import drawio_xml as dx


class ERConverter:
    """
    Convert a parsed Mermaid ER diagram AST to Draw.io XML.

    Usage::

        converter = ERConverter()
        xml_str = converter.convert(ast, diagram_name="ER Model")
    """

    # Layout constants
    ENTITY_W = 220
    ENTITY_ROW_H = 26
    ENTITY_HEADER_H = 32
    H_GAP = 120
    V_GAP = 80
    COLS = 3  # entities per row in grid layout

    def convert(self, ast: ERAST, diagram_name: str = "ER Diagram") -> str:
        """
        Convert ERAST → Draw.io XML string.

        Returns a complete .drawio file content.
        """
        mxfile = dx.create_mxfile()
        diagram = dx.create_diagram(mxfile, name=diagram_name)
        root = dx.create_graph_model(diagram)

        # ── Layout entities on a grid ──
        entity_positions: dict[str, tuple[float, float]] = {}
        entity_ids: dict[str, str] = {}  # entity name → container cell ID
        entity_header_ids: dict[str, str] = {}

        entities = list(ast.entities.values())
        for idx, entity in enumerate(entities):
            col = idx % self.COLS
            row = idx // self.COLS
            x = 60 + col * (self.ENTITY_W + self.H_GAP)
            y = 60 + row * (self._entity_height(entity) + self.V_GAP)
            entity_positions[entity.name] = (x, y)

            container_id, header_id = self._render_entity(root, entity, x, y)
            entity_ids[entity.name] = container_id
            entity_header_ids[entity.name] = header_id

        # ── Render relationships ──
        for rel in ast.relationships:
            if rel.entity_a not in entity_ids or rel.entity_b not in entity_ids:
                continue
            self._render_relationship(root, rel, entity_ids)

        return dx.serialize(mxfile)

    # ── Entity rendering ───────────────────────────────────────────────

    def _entity_height(self, entity: EREntity) -> float:
        return self.ENTITY_HEADER_H + max(len(entity.attributes), 1) * self.ENTITY_ROW_H + 4

    def _render_entity(
        self, root, entity: EREntity, x: float, y: float
    ) -> tuple[str, str]:
        """
        Render an entity as a Draw.io table-like shape.
        Returns (container_id, header_cell_id).
        """
        total_h = self._entity_height(entity)
        container_id = dx.new_id()

        # Container (entity box)
        container_style = (
            "shape=table;startSize=0;container=1;collapsible=0;"
            "childLayout=tableLayout;fixedRows=1;rowLines=1;fontStyle=0;"
            "strokeColor=#6c8ebf;fillColor=#FFFFFF;"
            "rounded=1;shadow=1;"
        )
        dx.add_node(
            root,
            cell_id=container_id,
            label="",
            style=container_style,
            x=x,
            y=y,
            width=self.ENTITY_W,
            height=total_h,
        )

        # Header row
        header_id = dx.new_id()
        header_style = (
            "shape=partialRectangle;overflow=hidden;connectable=0;"
            "fillColor=#dae8fc;top=0;left=0;bottom=0;right=0;"
            "fontStyle=1;fontSize=13;strokeColor=#6c8ebf;"
        )
        dx.add_node(
            root,
            cell_id=header_id,
            label=entity.name,
            style=header_style,
            x=0,
            y=0,
            width=self.ENTITY_W,
            height=self.ENTITY_HEADER_H,
            parent=container_id,
        )

        # Attribute rows
        if entity.attributes:
            for i, attr in enumerate(entity.attributes):
                row_id = dx.new_id()
                prefix = ""
                if attr.is_pk:
                    prefix = "PK  "
                elif attr.is_fk:
                    prefix = "FK  "

                attr_label = f"{prefix}{attr.attr_type}  {attr.attr_name}"
                if attr.comment:
                    attr_label += f"  -- {attr.comment}"

                row_style = (
                    "shape=partialRectangle;overflow=hidden;connectable=0;"
                    "fillColor=#FFFFFF;top=0;left=0;bottom=0;right=0;"
                    "fontFamily=Courier New;fontSize=11;align=left;spacingLeft=8;"
                    "strokeColor=#CCCCCC;"
                )
                if attr.is_pk:
                    row_style += "fontStyle=5;"  # bold + underline

                dx.add_node(
                    root,
                    cell_id=row_id,
                    label=attr_label,
                    style=row_style,
                    x=0,
                    y=self.ENTITY_HEADER_H + i * self.ENTITY_ROW_H,
                    width=self.ENTITY_W,
                    height=self.ENTITY_ROW_H,
                    parent=container_id,
                )
        else:
            # Empty placeholder row
            dx.add_node(
                root,
                cell_id=dx.new_id(),
                label="(no attributes)",
                style=(
                    "shape=partialRectangle;overflow=hidden;connectable=0;"
                    "fillColor=#FFFFFF;top=0;left=0;bottom=0;right=0;"
                    "fontColor=#999999;fontStyle=2;fontSize=11;align=center;"
                    "strokeColor=#CCCCCC;"
                ),
                x=0,
                y=self.ENTITY_HEADER_H,
                width=self.ENTITY_W,
                height=self.ENTITY_ROW_H,
                parent=container_id,
            )

        return container_id, header_id

    # ── Relationship rendering ─────────────────────────────────────────

    _CARDINALITY_LABELS = {
        "||": "1",
        "|{": "1..*",
        "o{": "0..*",
        "}|": "1..*",
        "}o": "0..*",
        "o|": "0..1",
        "|o": "0..1",
    }

    def _render_relationship(
        self,
        root,
        rel: ERRelationship,
        entity_ids: dict[str, str],
    ):
        """Render a relationship line between two entities."""
        source_id = entity_ids[rel.entity_a]
        target_id = entity_ids[rel.entity_b]

        card_a = self._CARDINALITY_LABELS.get(rel.cardinality_a, rel.cardinality_a)
        card_b = self._CARDINALITY_LABELS.get(rel.cardinality_b, rel.cardinality_b)

        # Build label:  card_a ──── rel_label ──── card_b
        label_parts = []
        if rel.label:
            label_parts.append(rel.label)

        edge_label = rel.label or ""

        # Edge style
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=1;"
            "orthogonalLoop=1;jettySize=auto;html=1;"
            "strokeColor=#333333;fontColor=#333333;fontSize=11;"
            "exitX=1;exitY=0.5;exitDx=0;exitDy=0;"
            "entryX=0;entryY=0.5;entryDx=0;entryDy=0;"
        )
        if rel.identifying:
            style += "strokeWidth=2;"
        else:
            style += "strokeWidth=1;"

        edge_id = dx.new_id()

        # Main edge
        dx.add_edge(
            root,
            cell_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            label=edge_label,
            style=style,
        )

        # Cardinality labels as child cells of the edge
        if card_a:
            card_a_id = dx.new_id()
            self._add_cardinality_label(root, card_a_id, edge_id, card_a, position=-0.8)

        if card_b:
            card_b_id = dx.new_id()
            self._add_cardinality_label(root, card_b_id, edge_id, card_b, position=0.8)

    def _add_cardinality_label(
        self,
        root,
        cell_id: str,
        edge_id: str,
        label: str,
        position: float = 0.5,
    ):
        """Add a cardinality label as a child of an edge."""
        import xml.etree.ElementTree as ET

        cell = ET.SubElement(root, "mxCell", attrib={
            "id": cell_id,
            "value": label,
            "style": (
                "edgeLabel;html=1;align=center;verticalAlign=middle;"
                "resizable=0;points=[];fontSize=10;fontColor=#666666;"
                "fontStyle=1;labelBackgroundColor=#FFFFFF;"
            ),
            "vertex": "1",
            "connectable": "0",
            "parent": edge_id,
        })
        geo = ET.SubElement(cell, "mxGeometry", attrib={
            "x": str(position),
            "y": "0",
            "relative": "1",
            "as": "geometry",
        })
        ET.SubElement(geo, "mxPoint", attrib={"as": "offset"})
