"""
Flask UI — GitHub Tools
  1. Repo Analyzer   : AI-powered file-by-file code analysis
  2. Repo Tree       : Folder structure generator
  3. Release Notes   : AI-generated release note for a commit
"""

import os, re, time, uuid, base64, threading, queue, json
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, render_template, request, Response, jsonify, send_file

app = Flask(__name__)

# ── Load .env file if ANTHROPIC_API_KEY is not already in the environment ──────
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            # Always override — covers missing key AND empty-string key
            if val:
                os.environ[key] = val

GITHUB_API  = "https://api.github.com"
MAX_FILE_KB = 100

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".cs",
    ".go", ".rb", ".php", ".swift", ".kt", ".rs", ".scala", ".sh", ".bash",
    ".zsh", ".ps1", ".r", ".m", ".sql", ".html", ".css", ".scss", ".yaml",
    ".yml", ".json", ".xml", ".toml", ".ini", ".dockerfile",
    ".tf", ".vue", ".dart", ".lua", ".pl", ".hs",
}
SKIP_PATTERNS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "vendor", "target",
}

jobs = {}   # in-memory job store


# ── Shared GitHub helpers ──────────────────────────────────────────────────────

def gh_headers(token):
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def parse_github_url(url):
    url = url.strip().rstrip("/")
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)(?:\.git)?(?:/tree/([^/?#]+))?$", url)
    if m:
        return m.group(1), m.group(2), m.group(3) or ""
    return None, None, None


def get_repo_info(owner, repo, token):
    """Returns (default_branch, description, language)."""
    r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=gh_headers(token), timeout=15)
    if r.status_code == 401:
        raise RuntimeError("GitHub auth failed (401) — PAT is invalid or expired.")
    if r.status_code == 404:
        raise RuntimeError(f"Repo not found (404): {owner}/{repo} — check URL and PAT scope.")
    r.raise_for_status()
    d = r.json()
    return d["default_branch"], d.get("description", ""), d.get("language", "")


def get_all_nodes(owner, repo, branch, token):
    r = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        headers=gh_headers(token), timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch tree (HTTP {r.status_code}): {r.json().get('message', r.text[:200])}")
    data = r.json()
    if data.get("truncated"):
        app.logger.warning("GitHub tree response truncated — large repo.")
    return data.get("tree", [])


def fetch_file_content(owner, repo, path, token):
    r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
                     headers=gh_headers(token), timeout=15)
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("size", 0) / 1024 > MAX_FILE_KB:
        return "[Skipped — too large]"
    if data.get("encoding") == "base64":
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception:
            return None
    return None


def is_code_file(path):
    p = Path(path)
    if any(s in p.parts for s in SKIP_PATTERNS):
        return False
    return p.suffix.lower() in CODE_EXTENSIONS or p.name.lower() in {"dockerfile", "makefile", "jenkinsfile"}


def build_ascii_tree(nodes):
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
            connector = "L-- " if is_last else "|-- "
            icon      = "[D]" if is_dir else "[F]"
            lines.append(f"{prefix}{connector}{icon} {name}")
            if is_dir:
                walk(full_path, prefix + ("    " if is_last else "|   "))
    walk("", "")
    return lines


def new_job():
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "queue": queue.Queue(),
                    "total": 0, "done": 0, "output": None, "stop": False}
    return job_id


def start_thread(fn, *args):
    t = threading.Thread(target=fn, args=args, daemon=True)
    t.start()


# ── Tool 1: Repo Analyzer ──────────────────────────────────────────────────────

def analyze_file_claude(client, path, content):
    import anthropic
    msg = client.messages.create(
        model="claude-opus-4-5", max_tokens=1024,
        messages=[{"role": "user", "content": f"""You are a senior software engineer reviewing a codebase.
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
"""}],
    )
    return msg.content[0].text.strip()


def mock_analyze(path, content):
    lines   = content.splitlines()
    imports = [l.strip() for l in lines if re.match(r"^\s*(import |from |require\(|#include)", l)]
    funcs   = [l.strip() for l in lines if re.match(r"(def |function |class |async def )", l.strip())]
    ext  = Path(path).suffix.lower()
    lang = {".py":"Python",".js":"JavaScript",".ts":"TypeScript",".html":"HTML",
            ".css":"CSS",".json":"JSON",".yml":"YAML",".sh":"Shell",".sql":"SQL"}.get(ext,"source code")
    return (f"PURPOSE:\nA {lang} file with {len(lines)} lines.\n\n"
            f"KEY COMPONENTS:\n" + ("\n".join(f"  - {f}" for f in funcs[:5]) or "  - (none)") +
            f"\n\nDEPENDENCIES:\n" + ("\n".join(f"  - {i}" for i in imports[:5]) or "  - (none)") +
            "\n\nNOTABLE LOGIC:\n  - [Simulation]\n\nPOTENTIAL ISSUES:\n  - [Simulation]")


def extract_purpose(analysis):
    m = re.search(r"PURPOSE:\s*\n(.+?)(?:\n[A-Z ]+:|$)", analysis, re.DOTALL)
    return m.group(1).strip().replace("\n", " ")[:120] if m else "See analysis."


def run_analyzer(job_id, owner, repo, token, api_key, output_path, folder=""):
    q = jobs[job_id]["queue"]
    folder = folder.strip().strip("/")          # normalise  e.g. "src/components"
    def emit(msg, t="info"): q.put({"type": t, "message": msg})
    try:
        emit(f"Parsed: owner={owner}, repo={repo}")
        if folder:
            emit(f"Folder scope: {folder}/", "info")
        branch, _, _ = get_repo_info(owner, repo, token)
        emit(f"Branch: {branch}")

        emit("Fetching repository tree ...")
        all_nodes  = get_all_nodes(owner, repo, branch, token)

        # Scope the tree display to the requested sub-folder if given
        if folder:
            scoped_nodes = [n for n in all_nodes
                            if n["path"] == folder or n["path"].startswith(folder + "/")]
        else:
            scoped_nodes = all_nodes

        tree_lines = build_ascii_tree(scoped_nodes)
        root_label = f"[DIR] {repo}/{folder}/" if folder else f"[DIR] {repo}/"
        tree_text  = "\n".join([root_label] + tree_lines)
        n_files = sum(1 for n in scoped_nodes if n["type"] == "blob")
        n_dirs  = sum(1 for n in scoped_nodes if n["type"] == "tree")
        emit(f"Tree built — {n_files} files, {n_dirs} dirs" + (f" (under {folder}/)" if folder else ""))

        blobs      = [n for n in all_nodes if n["type"] == "blob"]
        code_files = [b for b in blobs if is_code_file(b["path"])]

        # Apply folder filter to code files
        if folder:
            code_files = [b for b in code_files
                          if b["path"] == folder or b["path"].startswith(folder + "/")]
            if not code_files:
                emit(f"No code files found under '{folder}/' — check the path.", "error")
                jobs[job_id]["status"] = "error"
                q.put({"type": "error", "message": f"No code files found under '{folder}/'."}); return

        emit(f"Found {len(code_files)} code files to analyse", "success")
        jobs[job_id]["total"] = len(code_files)

        claude = None
        if api_key:
            try:
                import anthropic
                claude = anthropic.Anthropic(api_key=api_key)
                emit("Claude API connected — real AI analysis", "success")
            except Exception as e:
                emit(f"Claude init failed: {e} — simulation mode", "warn")
        else:
            emit("ANTHROPIC_API_KEY not set — simulation mode", "warn")

        analyses, file_summaries = [], []
        for idx, blob in enumerate(code_files, 1):
            if jobs[job_id].get("stop"):
                emit("Stopped by user.", "warn"); jobs[job_id]["status"] = "stopped"
                q.put({"type": "stopped"}); return

            path = blob["path"]
            emit(f"[{idx}/{len(code_files)}] {path}", "file")
            content = fetch_file_content(owner, repo, path, token)
            jobs[job_id]["done"] = idx

            if not content:
                emit("  Skipped (empty)", "skip"); continue
            if content.startswith("[Skipped"):
                analyses.append({"path": path, "analysis": content, "purpose": content})
                emit(f"  {content}", "skip"); continue
            try:
                analysis = analyze_file_claude(claude, path, content) if claude else mock_analyze(path, content)
                purpose  = extract_purpose(analysis)
                analyses.append({"path": path, "analysis": analysis, "purpose": purpose})
                file_summaries.append({"path": path, "purpose": purpose})
                emit("  Done", "done")
            except Exception as e:
                emit(f"  Error: {e}", "error")
                analyses.append({"path": path, "analysis": f"[Failed: {e}]", "purpose": ""})
            time.sleep(0.1)

        emit("Generating repository overview ...", "info")
        if claude:
            import anthropic
            bullets = "\n".join(f"- {s['path']}: {s['purpose']}" for s in file_summaries)
            msg = claude.messages.create(model="claude-opus-4-5", max_tokens=600, messages=[{"role":"user","content":
                f"Write a concise REPOSITORY OVERVIEW (max 300 words) for '{repo}' based on these files:\n{bullets}\n"
                "Cover: project purpose, main technologies, architecture, notable patterns."}])
            repo_summary = msg.content[0].text.strip()
        else:
            repo_summary = f"[Simulation] {repo} — {len(file_summaries)} files analysed."

        sep, sep2 = "="*70, "-"*70
        doc_lines = [sep, "  REPOSITORY ANALYSIS REPORT", f"  {owner}/{repo}  |  branch: {branch}",
                     f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                     f"  Total files analysed: {len(analyses)}", sep, "",
                     "REPOSITORY OVERVIEW", sep2, repo_summary, "",
                     "REPOSITORY STRUCTURE", sep2, tree_text, "", "FILE-BY-FILE ANALYSIS", sep]
        for i, item in enumerate(analyses, 1):
            doc_lines += ["", f"[{i}/{len(analyses)}]  {item['path']}", sep2, item["analysis"], ""]
        doc_lines += [sep, "  END OF REPORT", sep]
        document = "\n".join(doc_lines)

        Path(output_path).write_text(document, encoding="utf-8")
        jobs[job_id].update({"status": "done", "output": output_path})
        emit(f"Done! {len(analyses)} files analysed.", "success")
        q.put({"type": "complete", "output": output_path})

    except Exception as e:
        import traceback; tb = traceback.format_exc()
        app.logger.error(f"Analyzer job {job_id} failed:\n{tb}")
        jobs[job_id]["status"] = "error"
        emit(f"Fatal error: {e}", "error")
        emit(f"Traceback:\n{tb}", "error")
        q.put({"type": "error", "message": str(e)})


# ── Tool 2: Repo Tree ──────────────────────────────────────────────────────────

def run_tree(job_id, owner, repo, token, output_path):
    q = jobs[job_id]["queue"]
    def emit(msg, t="info"): q.put({"type": t, "message": msg})
    try:
        emit(f"Parsed: owner={owner}, repo={repo}")
        branch, _, _ = get_repo_info(owner, repo, token)
        emit(f"Branch: {branch}")

        emit("Fetching tree from GitHub ...")
        all_nodes = get_all_nodes(owner, repo, branch, token)
        n_files = sum(1 for n in all_nodes if n["type"] == "blob")
        n_dirs  = sum(1 for n in all_nodes if n["type"] == "tree")
        emit(f"Fetched — {n_files} files, {n_dirs} directories", "success")

        tree_lines = build_ascii_tree(all_nodes)
        sep = "=" * 60
        header = [sep, f"  Repository : {owner}/{repo}", f"  Branch     : {branch}",
                  f"  Generated  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                  f"  Files: {n_files}   Dirs: {n_dirs}", sep, f"[DIR] {repo}/"]
        footer = ["", "-"*60, f"  {n_files} files  |  {n_dirs} directories", "-"*60]
        document = "\n".join(header + tree_lines + footer)

        Path(output_path).write_text(document, encoding="utf-8")
        jobs[job_id].update({"status": "done", "output": output_path})
        emit(f"Tree saved — {n_files} files, {n_dirs} dirs.", "success")
        q.put({"type": "complete", "output": output_path})

    except Exception as e:
        import traceback; tb = traceback.format_exc()
        app.logger.error(f"Tree job {job_id} failed:\n{tb}")
        jobs[job_id]["status"] = "error"
        emit(f"Fatal error: {e}", "error")
        emit(f"Traceback:\n{tb}", "error")
        q.put({"type": "error", "message": str(e)})


# ── Tool 3: Release Notes ──────────────────────────────────────────────────────

def get_commit(owner, repo, sha, token):
    r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/commits/{sha}",
                     headers=gh_headers(token), timeout=15)
    if r.status_code == 404:
        raise RuntimeError(f"Commit '{sha}' not found.")
    r.raise_for_status()
    return r.json()


def get_latest_commit(owner, repo, branch, token):
    r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/commits/{branch}",
                     headers=gh_headers(token), timeout=15)
    r.raise_for_status()
    return r.json()


def get_associated_pr(owner, repo, sha, token):
    r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/commits/{sha}/pulls",
                     headers=gh_headers(token), timeout=15)
    if r.status_code != 200:
        return None
    prs = r.json()
    return prs[0] if prs else None


def get_recent_commits(owner, repo, branch, token, count=10):
    r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/commits",
                     headers=gh_headers(token), params={"sha": branch, "per_page": count}, timeout=15)
    r.raise_for_status()
    return r.json()


def get_latest_release(owner, repo, token):
    r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/releases/latest",
                     headers=gh_headers(token), timeout=15)
    return r.json() if r.status_code == 200 else None


def get_tags(owner, repo, token):
    r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/tags",
                     headers=gh_headers(token), params={"per_page": 5}, timeout=15)
    return r.json() if r.status_code == 200 else []


def extract_commit_data(commit):
    c = commit.get("commit", {})
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
        "files_changed": [{"filename": f.get("filename"), "status": f.get("status"),
                           "additions": f.get("additions", 0), "deletions": f.get("deletions", 0),
                           "patch": f.get("patch", "")[:500]} for f in files],
    }


def run_release_notes(job_id, owner, repo, token, api_key, commit_sha, output_path):
    q = jobs[job_id]["queue"]
    def emit(msg, t="info"): q.put({"type": t, "message": msg})
    def stopped():
        if jobs[job_id].get("stop"):
            emit("Stopped by user.", "warn")
            jobs[job_id]["status"] = "stopped"
            q.put({"type": "stopped"})
            return True
        return False

    try:
        emit(f"Parsed: owner={owner}, repo={repo}")
        if stopped(): return
        branch, repo_desc, repo_lang = get_repo_info(owner, repo, token)
        emit(f"Branch: {branch}  |  Language: {repo_lang or 'N/A'}")

        if stopped(): return
        if commit_sha:
            emit(f"Fetching commit: {commit_sha} ...")
            raw_commit = get_commit(owner, repo, commit_sha, token)
        else:
            emit("No commit SHA provided — fetching latest commit ...")
            raw_commit = get_latest_commit(owner, repo, branch, token)

        cd = extract_commit_data(raw_commit)
        emit(f"Commit: [{cd['short_sha']}] {cd['message'].splitlines()[0][:72]}", "success")
        emit(f"Author: {cd['author_name']}  |  Files changed: {len(cd['files_changed'])}  (+{cd['additions']} -{cd['deletions']})")

        if stopped(): return
        emit("Fetching PR, tags, recent history ...")
        pr             = get_associated_pr(owner, repo, cd["sha"], token)
        recent_commits = get_recent_commits(owner, repo, branch, token)
        latest_release = get_latest_release(owner, repo, token)
        tags           = get_tags(owner, repo, token)

        if pr:
            emit(f"Associated PR: #{pr.get('number')} — {pr.get('title','')}", "success")
        else:
            emit("No associated PR found.")

        if stopped(): return
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set — cannot generate release notes without AI.")

        import anthropic
        claude = anthropic.Anthropic(api_key=api_key)
        emit("Claude API connected — generating release note ...", "success")

        file_list = "\n".join(
            f"  [{f['status'].upper()}] {f['filename']}  (+{f['additions']} -{f['deletions']})"
            for f in cd["files_changed"][:30]
        )
        pr_section = ""
        if pr:
            pr_section = (f"\nAssociated PR:\n  Title: {pr.get('title','')}\n"
                          f"  #{pr.get('number','')}  |  Labels: {', '.join(l['name'] for l in pr.get('labels',[]))or'None'}\n"
                          f"  Body: {(pr.get('body') or 'No description')[:400]}\n")

        recent_msgs = "\n".join(
            f"  - {c['commit']['message'].splitlines()[0][:100]}" for c in recent_commits[:8])
        last_release = (f"Last Release: {latest_release.get('tag_name','')} — {latest_release.get('name','')}"
                        if latest_release else (f"Last Tag: {tags[0].get('name','none')}" if tags else "Last Release: None"))

        prompt = f"""You are a technical writer generating a professional software release note.

Repository  : {repo}
Description : {repo_desc or 'Not provided'}
Language    : {repo_lang or 'Not specified'}
{last_release}

COMMIT DETAILS
--------------
SHA     : {cd['sha']}
Author  : {cd['author_name']} <{cd['author_email']}>
Date    : {cd['date']}
Message :
{cd['message']}

CHANGED FILES ({len(cd['files_changed'])} files | +{cd['additions']} -{cd['deletions']} lines)
{file_list}
{pr_section}
RECENT COMMIT HISTORY (context):
{recent_msgs}

---
Generate a professional release note in this exact format:

RELEASE NOTE
============
Version    : [Suggest a semantic version bump based on context]
Date       : [Formatted date from commit]
Commit     : [{cd['short_sha']}]
Author     : [{cd['author_name']}]

SUMMARY
-------
[2-3 sentence plain-English summary of what changed and why it matters.]

WHAT'S CHANGED
--------------
[Bullet list grouped by: New Features, Bug Fixes, Improvements, Maintenance — only include relevant sections.]

FILES MODIFIED
--------------
[Key files changed with a one-line note on each.]

BREAKING CHANGES
----------------
[List breaking changes or write 'None'.]

NOTES FOR DEVELOPERS
--------------------
[Technical notes, migration steps, or things developers should know.]
"""
        msg = claude.messages.create(model="claude-opus-4-5", max_tokens=1200,
                                     messages=[{"role": "user", "content": prompt}])
        release_note = msg.content[0].text.strip()

        sep = "=" * 70
        document = "\n".join([sep, f"  RELEASE NOTE  —  {owner}/{repo}",
                               f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                               f"  Commit    : {cd['sha']}", sep, "", release_note, "", sep,
                               "  END OF RELEASE NOTE", sep])

        Path(output_path).write_text(document, encoding="utf-8")
        jobs[job_id].update({"status": "done", "output": output_path})
        emit("Release note generated successfully!", "success")
        q.put({"type": "complete", "output": output_path})

    except Exception as e:
        import traceback; tb = traceback.format_exc()
        app.logger.error(f"Release notes job {job_id} failed:\n{tb}")
        jobs[job_id]["status"] = "error"
        emit(f"Fatal error: {e}", "error")
        emit(f"Traceback:\n{tb}", "error")
        q.put({"type": "error", "message": str(e)})


# ── Flask routes ───────────────────────────────────────────────────────────────

def validate_request(data):
    gh_url = data.get("url", "").strip()
    token  = data.get("token", "").strip()
    owner, repo, _ = parse_github_url(gh_url)
    app.logger.info(f"Parsed: owner={owner!r} repo={repo!r}")
    if not owner:
        return None, None, None, None, jsonify({"error": f"Could not parse GitHub URL: {gh_url!r}"}), 400
    if not token:
        return None, None, None, None, jsonify({"error": "GitHub PAT is required"}), 400
    return owner, repo, token, gh_url, None, None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    data    = request.json
    owner, repo, token, _, err, code = validate_request(data)
    if err: return err, code
    # Prefer key from form; fall back to environment (with quote-stripping for Windows)
    api_key = (data.get("api_key", "").strip().strip('"').strip("'")
               or os.environ.get("ANTHROPIC_API_KEY", "").strip().strip('"').strip("'"))
    output  = data.get("output", "analysis.txt").strip() or "analysis.txt"
    folder  = data.get("folder", "").strip()
    if not api_key:
        app.logger.warning("ANTHROPIC_API_KEY not set — simulation mode")
    job_id  = new_job()
    start_thread(run_analyzer, job_id, owner, repo, token, api_key,
                 str(Path(__file__).parent / output), folder)
    return jsonify({"job_id": job_id})


@app.route("/tree", methods=["POST"])
def tree():
    data    = request.json
    owner, repo, token, _, err, code = validate_request(data)
    if err: return err, code
    output  = data.get("output", "tree.txt").strip() or "tree.txt"
    job_id  = new_job()
    start_thread(run_tree, job_id, owner, repo, token,
                 str(Path(__file__).parent / output))
    return jsonify({"job_id": job_id})


@app.route("/release", methods=["POST"])
def release():
    data    = request.json
    owner, repo, token, _, err, code = validate_request(data)
    if err: return err, code
    # Prefer key from form; fall back to environment (with quote-stripping for Windows)
    api_key    = (data.get("api_key", "").strip().strip('"').strip("'")
                  or os.environ.get("ANTHROPIC_API_KEY", "").strip().strip('"').strip("'"))
    commit_sha = data.get("commit", "").strip()
    output     = data.get("output", "release_note.txt").strip() or "release_note.txt"
    job_id     = new_job()
    start_thread(run_release_notes, job_id, owner, repo, token, api_key, commit_sha,
                 str(Path(__file__).parent / output))
    return jsonify({"job_id": job_id})


@app.route("/stream/<job_id>")
def stream(job_id):
    if job_id not in jobs:
        return "Job not found", 404
    def generate():
        q = jobs[job_id]["queue"]
        while True:
            try:
                event = q.get(timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] in ("complete", "error", "stopped"):
                    break
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/stop/<job_id>", methods=["POST"])
def stop_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job["stop"] = True
    return jsonify({"status": "stop requested"})


@app.route("/output/<job_id>")
def output_text(job_id):
    job = jobs.get(job_id)
    if not job or not job.get("output"):
        return "Not ready", 404
    try:
        return Path(job["output"]).read_text(encoding="utf-8"), 200, \
               {"Content-Type": "text/plain; charset=utf-8"}
    except Exception as e:
        return str(e), 500


@app.route("/download/<job_id>")
def download(job_id):
    job = jobs.get(job_id)
    if not job or not job.get("output"):
        return "Not found", 404
    filename = Path(job["output"]).name
    return send_file(job["output"], as_attachment=True, download_name=filename)


if __name__ == "__main__":
    app.run(debug=False, port=5050, threaded=True)
