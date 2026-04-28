"""
Command-line interface for mermaid2drawio.

Usage:
    mermaid2drawio /path/to/repo --output /path/to/output
    mermaid2drawio /path/to/repo  # output defaults to <repo>/drawio_output/
    mermaid2drawio --file diagram.mmd --output result.drawio
    mermaid2drawio --list-icons
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

from .converter import MermaidToDrawio
from .icons.registry import IconRegistry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mermaid2drawio",
        description=(
            "Scan a Git repo for Mermaid diagrams (.md, .mmd, .mermaid) and "
            "convert them to Draw.io files with cloud service icons."
        ),
    )

    parser.add_argument(
        "repo_path",
        nargs="?",
        default=None,
        help="Path to the Git repository or folder to scan.",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output directory for .drawio files (default: <repo>/drawio_output/).",
    )
    parser.add_argument(
        "-f", "--file",
        default=None,
        help="Convert a single .mmd/.mermaid file instead of scanning a repo.",
    )
    parser.add_argument(
        "--list-icons",
        action="store_true",
        help="List all supported service/tool icon keywords and exit.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed output for each conversion.",
    )

    args = parser.parse_args(argv)

    # ── List icons mode ──
    if args.list_icons:
        registry = IconRegistry()
        services = registry.list_supported_services()
        print(f"Supported service keywords ({len(services)}):\n")
        col_width = max(len(s) for s in services) + 4
        cols = max(1, 80 // col_width)
        for i, svc in enumerate(services):
            end = "\n" if (i + 1) % cols == 0 else ""
            print(f"  {svc:<{col_width}}", end=end)
        print()
        return 0

    # ── Single file mode ──
    if args.file:
        fpath = Path(args.file).resolve()
        if not fpath.is_file():
            print(f"Error: File not found: {fpath}", file=sys.stderr)
            return 1

        output = args.output or str(fpath.with_suffix(".drawio"))
        source = fpath.read_text(encoding="utf-8")

        converter = MermaidToDrawio(
            repo_path=fpath.parent,
            output_dir=Path(output).parent,
        )
        result = converter.convert_single(
            mermaid_source=source,
            output_path=output,
            diagram_name=fpath.stem,
        )
        if result.success:
            print(f"Converted: {result.output_path}  ({result.diagram_type.value})")
        else:
            print(f"Failed: {result.error}", file=sys.stderr)
            return 1
        return 0

    # ── Repo scan mode ──
    if not args.repo_path:
        parser.print_help()
        return 1

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.is_dir():
        print(f"Error: Directory not found: {repo_path}", file=sys.stderr)
        return 1

    converter = MermaidToDrawio(
        repo_path=repo_path,
        output_dir=args.output,
    )

    print(f"Scanning: {repo_path}")
    results = converter.convert_all()

    if not results:
        print("No Mermaid diagrams found.")
        return 0

    # Report
    ok = [r for r in results if r.success]
    fail = [r for r in results if not r.success]

    print(f"\nConverted {len(ok)} diagram(s) to Draw.io:\n")
    for r in ok:
        rel_src = os.path.relpath(r.source_file, repo_path)
        rel_out = os.path.relpath(r.output_path, repo_path)
        print(f"  [{r.diagram_type.value:>10}]  {rel_src}  ->  {rel_out}")

    if fail:
        print(f"\nFailed ({len(fail)}):\n")
        for r in fail:
            rel_src = os.path.relpath(r.source_file, repo_path)
            print(f"  FAIL  {rel_src}: {r.error}")

    print(f"\nOutput directory: {converter.output_dir}")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
