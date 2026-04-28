"""
GitHub Repository Code Analyzer
Reads the tree.txt from github_repo_tree.py, fetches every script file,
and uses Claude AI to generate a detailed explanation document.

Requirements:
    pip install requests anthropic

Usage:
    python repo_analyzer.py --url https://github.com/owner/repo --token ghp_xxx
    python repo_analyzer.py --url https://github.com/owner/repo --token ghp_xxx --tree tree.txt
    python repo_analyzer.py --url https://github.com/owner/repo --token ghp_xxx --output analysis.txt
"""

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import anthropic

# ── File extensions considered "scripts / source code" ───────────────────────
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".cs",
    ".go", ".rb", ".php", ".swift", ".kt", ".rs", ".scala", ".sh", ".bash",
    ".zsh", ".ps1", ".r", ".m", ".sql", ".html", ".css", ".scss", ".yaml",
    ".yml", ".json", ".xml", ".toml", ".ini", ".env.example", ".dockerfile",
    ".tf", ".vue", ".dart", ".lua", ".pl", ".hs",
}

# Files/dirs to always skip
SKIP_PATTERNS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "vendor", "target",
}

GITHUB_API  = "https://api.github.com"
MAX_FILE_KB = 100   # Skip files larger than this (likely generated/binary)


# ── GitHub helpers ─────────────────────────────────────────────────────────────
def gh_headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def parse_github_url(url: str) -> tuple:
    url = url.strip().rstrip("/")
    ssh = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", url)
    if ssh:
        return ssh.group(1), ssh.group(2), ""
    https = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)(?:\.git)?(?:/tree/([^/?#]+))?(?:[/?#].*)?$",
        url,
    )
    if https:
        return https.group(1), https.group(2), https.group(3) or ""
    sys.exit("❌  Could not parse GitHub URL.")


def get_default_branch(owner: str, repo: str, token: str) -> str:
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}",
        headers=gh_headers(token), timeout=15
    )
    if resp.status_code == 401:
        sys.exit("❌  Authentication failed — check your PAT.")
    if resp.status_code == 404:
        sys.exit("❌  Repository not found — check URL and PAT scope (needs 'repo').")
    resp.raise_for_status()
    return resp.json()["default_branch"]


def get_all_files(owner: str, repo: str, branch: str, token: str) -> list:
    """Return all blob nodes from the recursive git tree."""
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        headers=gh_headers(token), timeout=30,
    )
    resp.raise_for_status()
    return [
        n for n in resp.json().get("tree", [])
        if n["type"] == "blob"
    ]


def fetch_file_content(owner: str, repo: str, path: str, token: str) -> str | None:
    """Fetch raw content of a file; returns None if too large or binary."""
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers=gh_headers(token), timeout=15,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    size_kb = data.get("size", 0) / 1024
    if size_kb > MAX_FILE_KB:
        return f"[Skipped — file too large: {size_kb:.1f} KB]"
    if data.get("encoding") == "base64":
        import base64
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception:
            return "[Skipped — could not decode file content]"
    return None


def get_tree_nodes(owner: str, repo: str, branch: str, token: str) -> list:
    """Fetch all tree nodes (blobs + trees) for the folder structure display."""
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        headers=gh_headers(token), timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("tree", [])


def build_display_tree(nodes: list) -> list:
    """Convert flat git-tree nodes into an indented ASCII tree."""
    children = {}
    for node in nodes:
        path   = node["path"]
        is_dir = node["type"] in ("tree", "dir")
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        name   = path.rsplit("/", 1)[-1]
        children.setdefault(parent, []).append((name, path, is_dir))

    for lst in children.values():
        lst.sort(key=lambda x: (not x[2], x[0].lower()))

    lines = []

    def walk(parent, prefix):
        for idx, (name, full_path, is_dir) in enumerate(children.get(parent, [])):
            is_last   = idx == len(children[parent]) - 1
            connector = "└── " if is_last else "├── "
            icon      = "📁" if is_dir else "📄"
            lines.append(f"{prefix}{connector}{icon} {name}")
            if is_dir:
                walk(full_path, prefix + ("    " if is_last else "│   "))

    walk("", "")
    return lines


def is_code_file(path: str) -> bool:
    p = Path(path)
    if any(skip in p.parts for skip in SKIP_PATTERNS):
        return False
    suffix = p.suffix.lower()
    name   = p.name.lower()
    # Match by extension or special names like Dockerfile, Makefile
    return suffix in CODE_EXTENSIONS or name in {"dockerfile", "makefile", "jenkinsfile"}


# ── AI Analysis via Claude ─────────────────────────────────────────────────────
def analyze_file_with_claude(client: anthropic.Anthropic, path: str, content: str) -> str:
    """Ask Claude to explain a single file."""
    prompt = f"""You are a senior software engineer reviewing a codebase.
Analyze the following file and provide a clear, structured explanation.

File path: {path}

```
{content[:8000]}  
```

Provide your analysis in this exact format:

PURPOSE:
<One or two sentences on what this file does.>

KEY COMPONENTS:
<List the main functions, classes, or sections and briefly explain each.>

DEPENDENCIES:
<List any imported libraries/modules and why they are used.>

NOTABLE LOGIC:
<Highlight any important algorithms, patterns, or design decisions.>

POTENTIAL ISSUES:
<Note any obvious bugs, security concerns, or areas for improvement. Write 'None identified.' if clean.>
"""
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def generate_repo_summary(client: anthropic.Anthropic, repo: str, file_summaries: list) -> str:
    """Ask Claude to produce a high-level overview of the entire repo."""
    bullet_list = "\n".join(
        f"- {item['path']}: {item['purpose']}" for item in file_summaries
    )
    prompt = f"""You are a senior software engineer.
Below is a list of files in the GitHub repository '{repo}' with one-line descriptions of each.

{bullet_list}

Write a concise REPOSITORY OVERVIEW (max 300 words) covering:
1. What the project does overall.
2. The main technologies and languages used.
3. The high-level architecture or folder structure pattern.
4. Any notable design patterns or conventions observed.
"""
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def extract_purpose(analysis: str) -> str:
    """Pull the PURPOSE line from an analysis block for the summary table."""
    match = re.search(r"PURPOSE:\s*\n(.+?)(?:\n[A-Z ]+:|$)", analysis, re.DOTALL)
    if match:
        return match.group(1).strip().replace("\n", " ")[:120]
    return "See analysis below."


# ── Document builder ───────────────────────────────────────────────────────────
def build_document(
    owner: str,
    repo: str,
    branch: str,
    tree_text: str,
    analyses: list,
    repo_summary: str,
) -> str:
    sep  = "=" * 70
    sep2 = "-" * 70

    lines = [
        sep,
        f"  REPOSITORY ANALYSIS REPORT",
        f"  {owner}/{repo}  |  branch: {branch}",
        f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  Total files analysed: {len(analyses)}",
        sep,
        "",
        "REPOSITORY OVERVIEW",
        sep2,
        repo_summary,
        "",
        "REPOSITORY STRUCTURE",
        sep2,
        tree_text if tree_text else "(tree not provided)",
        "",
        "FILE-BY-FILE ANALYSIS",
        sep,
    ]

    for i, item in enumerate(analyses, 1):
        lines += [
            "",
            f"[{i}/{len(analyses)}]  📄 {item['path']}",
            sep2,
            item["analysis"],
            "",
        ]

    lines += [
        sep,
        "  END OF REPORT",
        sep,
    ]
    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Analyze all code files in a GitHub repo using Claude AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python repo_analyzer.py --url https://github.com/owner/repo --token ghp_xxx\n"
            "  python repo_analyzer.py --url https://github.com/owner/repo --token ghp_xxx --output report.txt\n"
        ),
    )
    parser.add_argument("--url",    required=True, help="GitHub repository URL")
    parser.add_argument("--token",  required=True, help="GitHub Personal Access Token (PAT)")
    parser.add_argument("--tree",   default="",    help="Optional: path to tree.txt from github_repo_tree.py")
    parser.add_argument("--output", default="analysis.txt", help="Output file (default: analysis.txt)")
    parser.add_argument("--folder", default="",    help="Optional: only analyse files inside this sub-folder path (e.g. src/components)")
    args = parser.parse_args()

    # ── Anthropic client (reads ANTHROPIC_API_KEY from environment) ──────────
    import os
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        sys.exit(
            "❌  Anthropic API key not found.\n"
            "    Set it once in your terminal before running:\n\n"
            "    Windows : set ANTHROPIC_API_KEY=sk-ant-xxx\n"
            "    Mac/Linux: export ANTHROPIC_API_KEY=sk-ant-xxx"
        )
    claude = anthropic.Anthropic(api_key=api_key)

    # ── Parse repo URL ─────────────────────────────────────────────────────────
    owner, repo, branch = parse_github_url(args.url)
    print(f"🔗  Repository : {owner}/{repo}")

    if not branch:
        branch = get_default_branch(owner, repo, args.token)
        print(f"🌿  Branch     : {branch} (default)")
    else:
        print(f"🌿  Branch     : {branch}")

    # ── Resolve optional folder filter ────────────────────────────────────────
    folder_prefix = args.folder.strip().strip("/")   # normalise  e.g. "src/components"
    if folder_prefix:
        print(f"📂  Folder filter  : {folder_prefix}/")

    # ── Load or generate folder tree ──────────────────────────────────────────
    tree_text = ""

    # Priority 1: explicit --tree flag
    if args.tree:
        if Path(args.tree).exists():
            tree_text = Path(args.tree).read_text(encoding="utf-8")
            print(f"📂  Loaded tree from: {args.tree}")
        else:
            print(f"⚠️   '{args.tree}' not found — generating tree from GitHub …")

    # Priority 2: auto-detect tree.txt in current folder
    if not tree_text and Path("tree.txt").exists():
        tree_text = Path("tree.txt").read_text(encoding="utf-8")
        print("📂  Found tree.txt in current folder — using it.")

    # Priority 3: generate the tree on the fly (scoped to folder if given)
    if not tree_text:
        print("📥  Generating folder structure from GitHub …")
        all_nodes  = get_tree_nodes(owner, repo, branch, args.token)
        # When a folder filter is active, only show the subtree rooted there
        if folder_prefix:
            scoped_nodes = [
                n for n in all_nodes
                if n["path"] == folder_prefix
                or n["path"].startswith(folder_prefix + "/")
            ]
        else:
            scoped_nodes = all_nodes
        tree_lines = build_display_tree(scoped_nodes)
        root_label = f"📁 {repo}/{folder_prefix}/" if folder_prefix else f"📁 {repo}/"
        tree_text  = "\n".join([root_label] + tree_lines)
        print("✅  Folder structure generated.")

    # ── Fetch all code files ───────────────────────────────────────────────────
    print("📥  Fetching file list from GitHub …")
    all_blobs  = get_all_files(owner, repo, branch, args.token)
    code_files = [b for b in all_blobs if is_code_file(b["path"])]

    # Apply folder filter: keep only files inside the requested sub-folder
    if folder_prefix:
        code_files = [
            b for b in code_files
            if b["path"] == folder_prefix
            or b["path"].startswith(folder_prefix + "/")
        ]
        if not code_files:
            sys.exit(
                f"❌  No code files found under '{folder_prefix}'.\n"
                f"    Check the folder path — it must match the repository structure exactly."
            )
        print(f"✅  {len(code_files)} code files found under '{folder_prefix}/'.\n")
    else:
        if not code_files:
            sys.exit("❌  No code files found in the repository.")
        print(f"✅  {len(code_files)} code files identified for analysis.\n")

    # ── Analyse each file ──────────────────────────────────────────────────────
    analyses     = []
    file_summaries = []

    for idx, blob in enumerate(code_files, 1):
        path = blob["path"]
        print(f"  [{idx}/{len(code_files)}] Analysing: {path} …", end=" ", flush=True)

        content = fetch_file_content(owner, repo, path, args.token)
        if not content:
            print("skipped (empty or unreadable)")
            continue

        if content.startswith("[Skipped"):
            print(content)
            analyses.append({"path": path, "analysis": content, "purpose": content})
            continue

        try:
            analysis = analyze_file_with_claude(claude, path, content)
            purpose  = extract_purpose(analysis)
            analyses.append({"path": path, "analysis": analysis, "purpose": purpose})
            file_summaries.append({"path": path, "purpose": purpose})
            print("done ✓")
        except Exception as e:
            print(f"error — {e}")
            analyses.append({"path": path, "analysis": f"[Analysis failed: {e}]", "purpose": ""})

        time.sleep(0.3)   # gentle rate limiting

    # ── Repo-level summary ─────────────────────────────────────────────────────
    print("\n🧠  Generating repository overview …")
    repo_summary = generate_repo_summary(claude, repo, file_summaries)

    # ── Write output ───────────────────────────────────────────────────────────
    document = build_document(owner, repo, branch, tree_text, analyses, repo_summary)

    Path(args.output).write_text(document, encoding="utf-8")
    print(f"\n💾  Analysis saved to: {args.output}")
    print(f"📊  {len(analyses)} files analysed.")


if __name__ == "__main__":
    main()
