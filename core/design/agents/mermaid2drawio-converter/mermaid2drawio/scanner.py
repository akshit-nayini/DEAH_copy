"""
RepoScanner — walks a Git repository (or any directory) and discovers
Mermaid diagram source blocks in .md and .mmd/.mermaid files.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class MermaidBlock:
    """A single Mermaid diagram found in the repo."""
    source: str                     # raw Mermaid text (without fences)
    file_path: str                  # absolute path to the source file
    line_start: int                 # 1-based line number where the block starts
    block_index: int = 0            # index within the file (0, 1, 2, ...)
    context_name: str = ""          # name extracted from nearest heading/comment above the block


class RepoScanner:
    """
    Scan a directory tree for Mermaid diagrams.

    Looks for:
    1. Fenced code blocks in Markdown files:
       ```mermaid
       ...
       ```
    2. Standalone .mmd and .mermaid files (entire content is Mermaid)

    Usage::

        scanner = RepoScanner("/path/to/repo")
        for block in scanner.scan():
            print(block.file_path, block.line_start)
    """

    MARKDOWN_EXTS = {".md", ".markdown", ".mdx"}
    MERMAID_EXTS = {".mmd", ".mermaid"}
    # Additional text files that may contain ```mermaid fenced blocks
    TEXT_EXTS = {".py", ".txt", ".rst", ".adoc", ".html", ".htm", ".yaml", ".yml", ".json", ".toml"}
    SKIP_DIRS = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
        ".eggs", "*.egg-info",
    }

    _FENCE_START = re.compile(r"^\s*```\s*mermaid\b", re.IGNORECASE)
    _FENCE_END = re.compile(r"^\s*```\s*$")

    # Patterns to extract diagram names from context above a mermaid block
    # Matches: ## Option 1 — Composer + Dataflow, ### Architecture Diagram, ## ER Diagram, etc.
    _HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+)")
    # Matches Python string section headers: sections.append("""## ER Diagram
    _PY_SECTION_RE = re.compile(r"##\s+(.+?)(?:\s*$|\\n)")

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        if not self.repo_path.is_dir():
            raise FileNotFoundError(
                f"Repository path does not exist or is not a directory: {self.repo_path}"
            )

    def scan(self) -> list[MermaidBlock]:
        """
        Walk the repo and return all discovered Mermaid blocks.

        Returns
        -------
        list[MermaidBlock]
        """
        blocks: list[MermaidBlock] = []

        for dirpath, dirnames, filenames in os.walk(self.repo_path):
            # Prune skip directories
            dirnames[:] = [
                d for d in dirnames
                if d not in self.SKIP_DIRS and not d.endswith(".egg-info")
            ]

            for fname in sorted(filenames):
                fpath = os.path.join(dirpath, fname)
                ext = os.path.splitext(fname)[1].lower()

                if ext in self.MARKDOWN_EXTS:
                    blocks.extend(self._extract_from_markdown(fpath))
                elif ext in self.MERMAID_EXTS:
                    blocks.extend(self._extract_from_mermaid_file(fpath))
                elif ext in self.TEXT_EXTS:
                    # Scan other text files for ```mermaid blocks too
                    blocks.extend(self._extract_from_markdown(fpath))

        return blocks

    def _extract_from_markdown(self, fpath: str) -> list[MermaidBlock]:
        """Extract ```mermaid ... ``` blocks and their context names from a file."""
        blocks: list[MermaidBlock] = []
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except (OSError, UnicodeDecodeError):
            return blocks

        inside = False
        buf: list[str] = []
        start_line = 0
        block_idx = 0

        for i, line in enumerate(lines, 1):
            if not inside:
                if self._FENCE_START.match(line):
                    inside = True
                    start_line = i
                    buf = []
            else:
                if self._FENCE_END.match(line):
                    inside = False
                    source = "".join(buf).strip()
                    if source:
                        # Look backwards from the ```mermaid line to find a name
                        context_name = self._find_context_name(lines, start_line - 1)
                        blocks.append(MermaidBlock(
                            source=source,
                            file_path=fpath,
                            line_start=start_line,
                            block_index=block_idx,
                            context_name=context_name,
                        ))
                        block_idx += 1
                else:
                    buf.append(line)

        return blocks

    def _find_context_name(self, lines: list[str], fence_line_idx: int) -> str:
        """
        Search backwards from the ```mermaid fence line to find the nearest
        heading, comment, or section label that names this diagram.

        Searches up to 15 lines above the fence for:
        - Markdown headings: ## Option 1 — Composer + Dataflow + BigQuery
        - Markdown headings: ### Architecture Diagram
        - Python string headings: ## ER Diagram  (inside triple-quoted strings)
        - Comments: # Data Flow Diagram
        """
        search_start = max(0, fence_line_idx - 15)

        # Collect candidate names going backwards (closest first)
        candidates: list[tuple[int, str]] = []

        for j in range(fence_line_idx - 1, search_start - 1, -1):
            raw = lines[j]

            # 1. Markdown heading: ## Title or ### Title
            m = self._HEADING_RE.match(raw)
            if m:
                title = m.group(1).strip()
                # Clean up: remove emoji, trailing symbols
                title = re.sub(r"[✅⚠️🔥💡📌]+", "", title).strip()
                title = re.sub(r"\s*[—\-|]+\s*$", "", title).strip()
                if title and len(title) > 2:
                    candidates.append((j, title))
                    continue

            # 2. Python/embedded string with ## heading pattern
            m2 = self._PY_SECTION_RE.search(raw)
            if m2:
                title = m2.group(1).strip()
                title = re.sub(r"[✅⚠️🔥💡📌]+", "", title).strip()
                if title and len(title) > 2:
                    candidates.append((j, title))
                    continue

        if not candidates:
            return ""

        # Prefer the closest candidate. But if there are multiple headings,
        # prefer a higher-level (##) heading over a lower-level (###) one
        # when both are close by (within 5 lines of each other).
        best = candidates[0]  # closest
        for dist, (line_idx, title) in enumerate(candidates):
            if dist > 3:
                break
            # Check if this is a higher-level heading (fewer #'s = more important)
            raw = lines[line_idx]
            level = len(raw) - len(raw.lstrip("#"))
            best_raw = lines[best[0]]
            best_level = len(best_raw) - len(best_raw.lstrip("#"))
            if level < best_level and level >= 1:
                best = (line_idx, title)

        return best[1]

    def _extract_from_mermaid_file(self, fpath: str) -> list[MermaidBlock]:
        """Read an entire .mmd/.mermaid file as a single block."""
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                source = f.read().strip()
        except (OSError, UnicodeDecodeError):
            return []

        if not source:
            return []

        return [MermaidBlock(
            source=source,
            file_path=fpath,
            line_start=1,
            block_index=0,
        )]
