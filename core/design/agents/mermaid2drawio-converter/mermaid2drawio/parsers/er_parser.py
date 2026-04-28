"""
ER Diagram parser for Mermaid erDiagram blocks.

Supports:
  - Entity declarations with attributes  (CUSTOMER { string name  int age })
  - Relationships with cardinality       (CUSTOMER ||--o{ ORDER : places)
  - Relationship labels
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ERAttribute:
    attr_type: str          # e.g. "string", "int", "FK", "PK"
    attr_name: str
    is_pk: bool = False
    is_fk: bool = False
    comment: Optional[str] = None


@dataclass
class EREntity:
    name: str
    attributes: list[ERAttribute] = field(default_factory=list)


@dataclass
class ERRelationship:
    entity_a: str
    entity_b: str
    cardinality_a: str      # e.g. "||", "|{", "o{", "}o", etc.
    cardinality_b: str
    label: str = ""
    identifying: bool = False  # -- vs == (identifying)


@dataclass
class ERAST:
    """Abstract Syntax Tree for a parsed Mermaid ER diagram."""
    entities: dict[str, EREntity] = field(default_factory=dict)
    relationships: list[ERRelationship] = field(default_factory=list)


class ERParser:
    """
    Parse Mermaid erDiagram source into an ERAST.

    Usage::

        parser = ERParser()
        ast = parser.parse(mermaid_source)
    """

    # Relationship line:  CUSTOMER ||--o{ ORDER : "places"
    _REL_RE = re.compile(
        r"^\s*"
        r"(\w+)"                          # entity A
        r"\s+"
        r"([|o}{]{1,2})"                  # cardinality A  (e.g. ||, o{, }|)
        r"(--|==)"                         # line type
        r"([|o}{]{1,2})"                  # cardinality B
        r"\s+"
        r"(\w+)"                          # entity B
        r"\s*:\s*"
        r"\"?([^\"]*)\"?"                 # label
        r"\s*$"
    )

    # Entity block start:  CUSTOMER {
    _ENTITY_START_RE = re.compile(r"^\s*(\w+)\s*\{\s*$")
    # Entity block end:  }
    _ENTITY_END_RE = re.compile(r"^\s*\}\s*$")
    # Attribute line:  string name PK "Customer name"
    _ATTR_RE = re.compile(
        r"^\s*(\w+)\s+(\w+)"             # type  name
        r"(?:\s+(PK|FK))?"               # optional PK/FK
        r'(?:\s+"([^"]*)")?'             # optional comment
        r"\s*$"
    )

    def parse(self, source: str) -> ERAST:
        """Parse Mermaid erDiagram source into an ERAST."""
        ast = ERAST()
        lines = source.strip().splitlines()

        inside_entity: Optional[str] = None

        for raw_line in lines:
            line = raw_line.split("%%")[0].strip()  # strip comments
            if not line or line.startswith("```"):
                continue
            if re.match(r"^\s*erDiagram\s*$", line, re.IGNORECASE):
                continue

            # ── inside entity block ──
            if inside_entity:
                if self._ENTITY_END_RE.match(line):
                    inside_entity = None
                    continue
                am = self._ATTR_RE.match(line)
                if am:
                    attr = ERAttribute(
                        attr_type=am.group(1),
                        attr_name=am.group(2),
                        is_pk=am.group(3) == "PK" if am.group(3) else False,
                        is_fk=am.group(3) == "FK" if am.group(3) else False,
                        comment=am.group(4),
                    )
                    ast.entities[inside_entity].attributes.append(attr)
                continue

            # ── entity block start ──
            em = self._ENTITY_START_RE.match(line)
            if em:
                ename = em.group(1)
                if ename not in ast.entities:
                    ast.entities[ename] = EREntity(name=ename)
                inside_entity = ename
                continue

            # ── relationship ──
            rm = self._REL_RE.match(line)
            if rm:
                ea, ca, line_type, cb, eb, label = rm.groups()
                # Ensure entities exist
                if ea not in ast.entities:
                    ast.entities[ea] = EREntity(name=ea)
                if eb not in ast.entities:
                    ast.entities[eb] = EREntity(name=eb)
                ast.relationships.append(ERRelationship(
                    entity_a=ea,
                    entity_b=eb,
                    cardinality_a=ca,
                    cardinality_b=cb,
                    label=label.strip(),
                    identifying=(line_type == "=="),
                ))
                continue

        return ast
