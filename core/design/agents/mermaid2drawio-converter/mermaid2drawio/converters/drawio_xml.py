"""
Low-level Draw.io XML builder utilities.

Draw.io files are XML with the structure:
  <mxfile>
    <diagram name="..." id="...">
      <mxGraphModel>
        <root>
          <mxCell id="0"/>                           <!-- layer 0 -->
          <mxCell id="1" parent="0"/>                <!-- default parent -->
          ... actual shapes and edges ...
        </root>
      </mxGraphModel>
    </diagram>
  </mxfile>
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
import uuid
import urllib.parse


def new_id() -> str:
    """Generate a unique Draw.io-compatible ID."""
    return str(uuid.uuid4()).replace("-", "")[:12]


def create_mxfile() -> ET.Element:
    """Create the top-level <mxfile> element."""
    return ET.Element("mxfile", attrib={
        "host": "mermaid2drawio",
        "modified": "",
        "agent": "mermaid2drawio/1.0",
        "version": "21.0.0",
        "type": "device",
    })


def create_diagram(parent: ET.Element, name: str = "Page-1") -> ET.Element:
    """Create a <diagram> inside an mxfile."""
    diagram = ET.SubElement(parent, "diagram", attrib={
        "name": name,
        "id": new_id(),
    })
    return diagram


def create_graph_model(diagram: ET.Element, dx: int = 0, dy: int = 0) -> ET.Element:
    """Create <mxGraphModel> with a root containing the two base cells."""
    model = ET.SubElement(diagram, "mxGraphModel", attrib={
        "dx": str(dx),
        "dy": str(dy),
        "grid": "1",
        "gridSize": "10",
        "guides": "1",
        "tooltips": "1",
        "connect": "1",
        "arrows": "1",
        "fold": "1",
        "page": "1",
        "pageScale": "1",
        "pageWidth": "1654",
        "pageHeight": "1169",
        "math": "0",
        "shadow": "0",
    })
    root = ET.SubElement(model, "root")
    # Base cells required by Draw.io
    ET.SubElement(root, "mxCell", attrib={"id": "0"})
    ET.SubElement(root, "mxCell", attrib={"id": "1", "parent": "0"})
    return root


def add_node(
    root: ET.Element,
    cell_id: str,
    label: str,
    style: str,
    x: float,
    y: float,
    width: float = 120,
    height: float = 60,
    parent: str = "1",
) -> ET.Element:
    """Add a vertex (shape) to the draw.io root."""
    cell = ET.SubElement(root, "mxCell", attrib={
        "id": cell_id,
        "value": _escape_html(label),
        "style": style,
        "vertex": "1",
        "parent": parent,
    })
    ET.SubElement(cell, "mxGeometry", attrib={
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(width)),
        "height": str(int(height)),
        "as": "geometry",
    })
    return cell


def add_edge(
    root: ET.Element,
    cell_id: str,
    source_id: str,
    target_id: str,
    label: str = "",
    style: str = "",
    parent: str = "1",
) -> ET.Element:
    """Add an edge (connector) to the draw.io root."""
    if not style:
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=1;"
            "orthogonalLoop=1;jettySize=auto;html=1;"
        )
    attribs = {
        "id": cell_id,
        "style": style,
        "edge": "1",
        "parent": parent,
        "source": source_id,
        "target": target_id,
    }
    if label:
        attribs["value"] = _escape_html(label)
    else:
        attribs["value"] = ""
    cell = ET.SubElement(root, "mxCell", attrib=attribs)
    ET.SubElement(cell, "mxGeometry", attrib={
        "relative": "1",
        "as": "geometry",
    })
    return cell


def add_group(
    root: ET.Element,
    group_id: str,
    label: str,
    x: float,
    y: float,
    width: float,
    height: float,
    parent: str = "1",
    style: str = "",
) -> ET.Element:
    """Add a container/group (for subgraphs).

    If style is provided, it overrides the default style.
    """
    if not style:
        style = (
            "rounded=1;whiteSpace=wrap;html=1;"
            "fillColor=#F5F5F5;strokeColor=#999999;fontColor=#333333;"
            "dashed=1;dashPattern=8 8;container=1;collapsible=0;"
            "verticalAlign=top;fontStyle=1;fontSize=13;"
            "strokeWidth=2;shadow=1;spacingTop=4;"
        )
    cell = ET.SubElement(root, "mxCell", attrib={
        "id": group_id,
        "value": _escape_html(label),
        "style": style,
        "vertex": "1",
        "parent": parent,
    })
    ET.SubElement(cell, "mxGeometry", attrib={
        "x": str(int(x)),
        "y": str(int(y)),
        "width": str(int(width)),
        "height": str(int(height)),
        "as": "geometry",
    })
    return cell


def serialize(mxfile: ET.Element) -> str:
    """Pretty-print the mxfile XML."""
    rough = ET.tostring(mxfile, encoding="unicode")
    dom = minidom.parseString(rough)
    return dom.toprettyxml(indent="  ", encoding=None)


def _escape_html(text: str) -> str:
    """
    Prepare text for Draw.io XML value attributes.

    Draw.io respects actual newlines in value attributes when whiteSpace=wrap
    is set. We preserve newlines (both literal and \\n escape sequences) and
    let ElementTree handle XML entity encoding automatically.
    """
    # No manual escaping needed - ElementTree handles it.
    # Just return the text as-is; actual newlines are preserved in the value.
    return text
