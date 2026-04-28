"""
GitHub Private Repository - Folder Structure Generator
Only requires the repo URL and a Personal Access Token (PAT).

Requirements:
    pip install requests

Usage:
    python github_tree.py --url https://github.com/owner/repo --token ghp_xxx

    Optionally save to a file:
    python github_tree.py --url https://github.com/owner/repo --token ghp_xxx --output tree.txt
"""

import argparse
import re
import sys
from datetime import datetime

import requests

GITHUB_API = "https://api.github.com"


# ── Parse owner, repo, and optional branch from any GitHub URL ───────────────
def parse_github_url(url: str) -> tuple[str, str, str]:
    """
    Supports URL formats:
        https://github.com/owner/repo
        https://github.com/owner/repo.git
        https://github.com/owner/repo/tree/branch-name
        git@github.com:owner/repo.git
    Returns (owner, repo, branch)  — branch may be empty string.
    """
    url = url.strip().rstrip("/")

    # SSH  →  git@github.com:owner/repo.git
    ssh = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", url)
    if ssh:
        return ssh.group(1), ssh.group(2), ""

    # HTTPS with optional /tree/<branch>
    https = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/?#]+))?(?:[/?#].*)?$",
        url,
    )
    if https:
        owner  = https.group(1)
        repo   = https.group(2)
        branch = https.group(3) or ""
        return owner, repo, branch

    sys.exit(
        "❌  Could not parse GitHub URL.\n"
        "    Expected: https://github.com/owner/repo  or  git@github.com:owner/repo.git"
    )


# ── GitHub API helpers ────────────────────────────────────────────────────────
def headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_default_branch(owner: str, repo: str, token: str) -> str:
    url  = f"{GITHUB_API}/repos/{owner}/{repo}"
    resp = requests.get(url, headers=headers(token), timeout=15)
    if resp.status_code == 401:
        sys.exit("❌  Authentication failed — check your PAT.")
    if resp.status_code == 404:
        sys.exit("❌  Repository not found — check the URL and PAT scope (needs 'repo').")
    resp.raise_for_status()
    return resp.json()["default_branch"]


def get_tree(owner: str, repo: str, branch: str, token: str) -> list[dict]:
    url  = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    resp = requests.get(url, headers=headers(token), timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("truncated"):
        print("⚠️  Tree truncated (>100 k items). Switching to Contents API …")
        return get_tree_via_contents(owner, repo, "", token)

    return data.get("tree", [])


def get_tree_via_contents(owner: str, repo: str, path: str, token: str) -> list[dict]:
    """Recursive fallback for very large repos."""
    url  = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    resp = requests.get(url, headers=headers(token), timeout=15)
    resp.raise_for_status()
    nodes = []
    for item in resp.json():
        nodes.append({"path": item["path"], "type": item["type"]})
        if item["type"] == "dir":
            nodes.extend(get_tree_via_contents(owner, repo, item["path"], token))
    return nodes


# ── ASCII tree renderer ───────────────────────────────────────────────────────
def build_display_tree(nodes: list[dict]) -> list[str]:
    children: dict[str, list[tuple[str, str, bool]]] = {}

    for node in nodes:
        path   = node["path"]
        is_dir = node["type"] in ("tree", "dir")
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        name   = path.rsplit("/", 1)[-1]
        children.setdefault(parent, []).append((name, path, is_dir))

    for lst in children.values():
        lst.sort(key=lambda x: (not x[2], x[0].lower()))   # dirs first, then files

    lines: list[str] = []

    def walk(parent: str, prefix: str) -> None:
        for idx, (name, full_path, is_dir) in enumerate(children.get(parent, [])):
            is_last   = idx == len(children[parent]) - 1
            connector = "└── " if is_last else "├── "
            icon      = "📁" if is_dir else "📄"
            lines.append(f"{prefix}{connector}{icon} {name}")
            if is_dir:
                walk(full_path, prefix + ("    " if is_last else "│   "))

    walk("", "")
    return lines


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a folder-structure tree for a GitHub repo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python github_tree.py --url https://github.com/owner/repo --token ghp_xxx\n"
            "  python github_tree.py --url https://github.com/owner/repo --token ghp_xxx --output tree.txt\n"
            "  python github_tree.py --url git@github.com:owner/repo.git  --token ghp_xxx\n"
        ),
    )
    parser.add_argument("--url",    required=True, help="GitHub repository URL")
    parser.add_argument("--token",  required=True, help="Personal Access Token (PAT)")
    parser.add_argument("--output", default="",    help="Optional: save output to this file")
    args = parser.parse_args()

    owner, repo, branch = parse_github_url(args.url)

    print(f"🔗  Repository : {owner}/{repo}")

    if not branch:
        branch = get_default_branch(owner, repo, args.token)
        print(f"🌿  Branch     : {branch} (default)")
    else:
        print(f"🌿  Branch     : {branch}")

    print("📥  Fetching tree …")
    nodes = get_tree(owner, repo, branch, args.token)

    dirs  = sum(1 for n in nodes if n["type"] in ("tree", "dir"))
    files = sum(1 for n in nodes if n["type"] in ("blob", "file"))
    print(f"✅  {files} files, {dirs} directories found.\n")

    header = [
        "=" * 60,
        f"  Repository : {owner}/{repo}",
        f"  Branch     : {branch}",
        f"  Generated  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  Files      : {files}   Directories : {dirs}",
        "=" * 60,
        f"📁 {repo}/",
    ]
    footer = [
        "",
        "-" * 60,
        f"  {files} files  |  {dirs} directories",
        "-" * 60,
    ]

    output = "\n".join(header + build_display_tree(nodes) + footer)
    print(output)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output + "\n")
        print(f"\n💾  Saved to: {args.output}")


if __name__ == "__main__":
    main()
