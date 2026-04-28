"""
GitHub Release Notes Generator
Fetches a commit (or the latest one) and generates a formatted release note.

Requirements:
    pip install requests anthropic

Usage:
    # Latest commit
    python release_notes.py --url https://github.com/owner/repo --token ghp_xxx

    # Specific commit
    python release_notes.py --url https://github.com/owner/repo --token ghp_xxx --commit abc1234

    # Save to file
    python release_notes.py --url https://github.com/owner/repo --token ghp_xxx --output release.txt
"""

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
import anthropic

GITHUB_API = "https://api.github.com"


# ── GitHub URL parser ──────────────────────────────────────────────────────────
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


# ── GitHub API helpers ─────────────────────────────────────────────────────────
def gh_headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_default_branch(owner: str, repo: str, token: str) -> str:
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}",
        headers=gh_headers(token), timeout=15,
    )
    if resp.status_code == 401:
        sys.exit("❌  Authentication failed — check your PAT.")
    if resp.status_code == 404:
        sys.exit("❌  Repository not found — check URL and PAT scope (needs 'repo').")
    resp.raise_for_status()
    data = resp.json()
    return data["default_branch"], data.get("description", ""), data.get("language", "")


def get_latest_commit(owner: str, repo: str, branch: str, token: str) -> dict:
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/commits/{branch}",
        headers=gh_headers(token), timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_commit(owner: str, repo: str, sha: str, token: str) -> dict:
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/commits/{sha}",
        headers=gh_headers(token), timeout=15,
    )
    if resp.status_code == 404:
        sys.exit(f"❌  Commit '{sha}' not found in {owner}/{repo}.")
    resp.raise_for_status()
    return resp.json()


def get_associated_pr(owner: str, repo: str, sha: str, token: str) -> dict | None:
    """Find the PR that introduced this commit, if any."""
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/commits/{sha}/pulls",
        headers={**gh_headers(token), "Accept": "application/vnd.github+json"},
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    prs = resp.json()
    return prs[0] if prs else None


def get_recent_commits(owner: str, repo: str, branch: str, token: str, count: int = 10) -> list:
    """Fetch the last N commits for context."""
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/commits",
        headers=gh_headers(token),
        params={"sha": branch, "per_page": count},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_tags(owner: str, repo: str, token: str) -> list:
    """Get the latest tags/releases for versioning context."""
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/tags",
        headers=gh_headers(token),
        params={"per_page": 5},
        timeout=15,
    )
    if resp.status_code != 200:
        return []
    return resp.json()


def get_latest_release(owner: str, repo: str, token: str) -> dict | None:
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/releases/latest",
        headers=gh_headers(token), timeout=15,
    )
    if resp.status_code != 200:
        return None
    return resp.json()


# ── Data extraction helpers ────────────────────────────────────────────────────
def extract_commit_data(commit: dict) -> dict:
    """Flatten a raw GitHub commit response into a clean dict."""
    c      = commit.get("commit", {})
    author = c.get("author", {})
    files  = commit.get("files", [])
    stats  = commit.get("stats", {})

    return {
        "sha":           commit.get("sha", ""),
        "short_sha":     commit.get("sha", "")[:7],
        "message":       c.get("message", "").strip(),
        "author_name":   author.get("name", "Unknown"),
        "author_email":  author.get("email", ""),
        "date":          author.get("date", ""),
        "additions":     stats.get("additions", 0),
        "deletions":     stats.get("deletions", 0),
        "total_changes": stats.get("total", 0),
        "files_changed": [
            {
                "filename": f.get("filename"),
                "status":   f.get("status"),          # added/modified/removed/renamed
                "additions":f.get("additions", 0),
                "deletions":f.get("deletions", 0),
                "patch":    f.get("patch", "")[:500], # first 500 chars of diff
            }
            for f in files
        ],
    }


def categorize_files(files: list) -> dict:
    """Group changed files by rough category for the prompt."""
    cats = {"added": [], "modified": [], "removed": [], "renamed": []}
    for f in files:
        status = f.get("status", "modified")
        cats.get(status, cats["modified"]).append(f["filename"])
    return {k: v for k, v in cats.items() if v}


# ── Claude AI release note generator ──────────────────────────────────────────
def generate_release_note(
    client: anthropic.Anthropic,
    repo: str,
    repo_description: str,
    repo_language: str,
    commit_data: dict,
    pr: dict | None,
    recent_commits: list,
    latest_release: dict | None,
    tags: list,
) -> str:

    file_categories = categorize_files(commit_data["files_changed"])
    file_list       = "\n".join(
        f"  [{f['status'].upper()}] {f['filename']}  (+{f['additions']} -{f['deletions']})"
        for f in commit_data["files_changed"][:30]
    )

    pr_section = ""
    if pr:
        pr_section = f"""
Associated Pull Request:
  Title  : {pr.get('title', '')}
  Number : #{pr.get('number', '')}
  Body   : {(pr.get('body') or 'No description')[:500]}
  Labels : {', '.join(l['name'] for l in pr.get('labels', [])) or 'None'}
  Merged : {pr.get('merged_at', 'N/A')}
"""

    recent_msgs = "\n".join(
        f"  - {c['commit']['message'].splitlines()[0][:100]}"
        for c in recent_commits[:8]
    )

    last_release = ""
    if latest_release:
        last_release = f"Last Release: {latest_release.get('tag_name', '')} — {latest_release.get('name', '')}"
    elif tags:
        last_release = f"Last Tag: {tags[0].get('name', 'none')}"
    else:
        last_release = "Last Release: None found (first release)"

    prompt = f"""You are a technical writer generating a professional software release note.

Repository  : {repo}
Description : {repo_description or 'Not provided'}
Language    : {repo_language or 'Not specified'}
{last_release}

COMMIT DETAILS
--------------
SHA     : {commit_data['sha']}
Author  : {commit_data['author_name']} <{commit_data['author_email']}>
Date    : {commit_data['date']}
Message :
{commit_data['message']}

CHANGED FILES ({len(commit_data['files_changed'])} files | +{commit_data['additions']} -{commit_data['deletions']} lines)
{file_list}
{pr_section}
RECENT COMMIT HISTORY (context only):
{recent_msgs}

---

Generate a professional release note in the following exact format:

RELEASE NOTE
============
Version    : [Suggest a semantic version bump e.g. v1.2.3 based on context, or 'See tags' if unclear]
Date       : [Formatted date from commit]
Commit     : [{commit_data['short_sha']}]
Author     : [{commit_data['author_name']}]

SUMMARY
-------
[2-3 sentence plain-English summary of what this commit/release changes and why it matters.]

WHAT'S CHANGED
--------------
[Bullet list of user-facing changes, improvements, or fixes. Be specific and clear. Group by: ✨ New Features, 🐛 Bug Fixes, ⚡ Improvements, 🔧 Maintenance — only include sections that apply.]

FILES MODIFIED
--------------
[Concise list of key files changed with a one-line note on what changed in each.]

BREAKING CHANGES
----------------
[List any breaking changes. Write 'None' if there are no breaking changes.]

NOTES FOR DEVELOPERS
--------------------
[Any technical notes, migration steps, or things developers should be aware of.]
"""

    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ── Document builder ───────────────────────────────────────────────────────────
def build_document(owner: str, repo: str, commit_data: dict, release_note: str) -> str:
    sep = "=" * 70
    return "\n".join([
        sep,
        f"  RELEASE NOTE  —  {owner}/{repo}",
        f"  Generated    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  Commit       : {commit_data['sha']}",
        sep,
        "",
        release_note,
        "",
        sep,
        "  END OF RELEASE NOTE",
        sep,
    ])


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Generate a release note for a GitHub commit using AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python release_notes.py --url https://github.com/owner/repo --token ghp_xxx\n"
            "  python release_notes.py --url https://github.com/owner/repo --token ghp_xxx --commit abc1234\n"
            "  python release_notes.py --url https://github.com/owner/repo --token ghp_xxx --output release.txt\n"
        ),
    )
    parser.add_argument("--url",    required=True, help="GitHub repository URL")
    parser.add_argument("--token",  required=True, help="GitHub Personal Access Token (PAT)")
    parser.add_argument("--commit", default="",    help="Commit SHA (short or full). Defaults to latest.")
    parser.add_argument("--output", default="release_note.txt", help="Output file (default: release_note.txt)")
    args = parser.parse_args()

    # ── Anthropic client ───────────────────────────────────────────────────────
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        sys.exit(
            "❌  Anthropic API key not found.\n"
            "    Windows : set ANTHROPIC_API_KEY=sk-ant-xxx\n"
            "    Mac/Linux: export ANTHROPIC_API_KEY=sk-ant-xxx"
        )
    claude = anthropic.Anthropic(api_key=api_key)

    # ── Parse URL & fetch repo info ────────────────────────────────────────────
    owner, repo, branch = parse_github_url(args.url)
    print(f"🔗  Repository : {owner}/{repo}")

    branch, repo_description, repo_language = get_default_branch(owner, repo, args.token)
    print(f"🌿  Branch     : {branch}")

    # ── Resolve commit ─────────────────────────────────────────────────────────
    if args.commit:
        print(f"🔍  Fetching commit : {args.commit} …")
        raw_commit = get_commit(owner, repo, args.commit, args.token)
    else:
        print("🔍  Fetching latest commit …")
        raw_commit = get_latest_commit(owner, repo, branch, args.token)

    commit_data = extract_commit_data(raw_commit)
    print(f"✅  Commit found  : [{commit_data['short_sha']}] {commit_data['message'].splitlines()[0][:72]}")
    print(f"    Author        : {commit_data['author_name']}")
    print(f"    Files changed : {len(commit_data['files_changed'])}  (+{commit_data['additions']} -{commit_data['deletions']})")

    # ── Fetch supporting context ───────────────────────────────────────────────
    print("📥  Fetching PR, tags, and recent history …")
    pr             = get_associated_pr(owner, repo, commit_data["sha"], args.token)
    recent_commits = get_recent_commits(owner, repo, branch, args.token)
    latest_release = get_latest_release(owner, repo, args.token)
    tags           = get_tags(owner, repo, args.token)

    if pr:
        print(f"🔀  Associated PR  : #{pr.get('number')} — {pr.get('title', '')}")
    else:
        print("ℹ️   No associated PR found.")

    # ── Generate release note ──────────────────────────────────────────────────
    print("\n🤖  Generating release note with Claude AI …")
    release_note = generate_release_note(
        claude, repo, repo_description, repo_language,
        commit_data, pr, recent_commits, latest_release, tags,
    )

    # ── Save output ────────────────────────────────────────────────────────────
    document = build_document(owner, repo, commit_data, release_note)
    print("\n" + document)

    Path(args.output).write_text(document, encoding="utf-8")
    print(f"\n💾  Release note saved to: {args.output}")


if __name__ == "__main__":
    main()
