"""
Git Processor Agent  v9.2
=========================
Repo: ahemadshaik/DEAH

File locations in repo:
  Agent:        core/testing/agents/git_processor/git_processor.py
  Validation:   core/testing/agents/validator/output/
  Cert reports: core/testing/agents/validator/certification_reports/
  Workflow:     .github/workflows/git_processor.yml

Usage:
  export GITHUB_TOKEN="ghp_xxx"
  python core/testing/agents/git_processor/git_processor.py --repo "ahemadshaik/DEAH"

v9.2 changes over v9.1:
  - find_validation_file: now filters branches to only those with a commit
    in VALIDATION_DIR within the last 1 hour (configurable via SCAN_WINDOW_HOURS).
  - Teams notifications sent for ALL outcomes:
      • Validation failed          (score N/A — blocked before cert)
      • Certification failed       (score < 90)
      • Certification passed       (score >= 90, merge attempted)
      • PR not found               (no open PR matched the hint)
      • Committed to main/default  (cert report successfully committed)
  - IGNORED_BRANCHES set added: branches listed there (exact names or fnmatch
    wildcards) are never scanned for validation files, so uploading a CSV to
    VALIDATION_DIR on main/master/develop (or any custom branch) will not
    trigger the agent pipeline.
  - load_threshold_config() and get_threshold() added for per-file thresholds
    (backported from v9.1): VALIDATION_THRESHOLD constant replaced by
    DEFAULT_VALIDATION_THRESHOLD; threshold is now loaded from
    core/testing/agents/git_processor/thresholds.json at runtime.
"""

import os, sys, re, io, json, base64, logging, argparse, time, fnmatch
import urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

_miss = []
try:
    from github import Github, GithubException, InputGitAuthor
except ImportError:
    _miss.append("PyGithub")
try:
    import pandas as pd
except ImportError:
    _miss.append("pandas")
try:
    import openpyxl
except ImportError:
    _miss.append("openpyxl")
if _miss:
    sys.exit(f"Missing: pip install {' '.join(_miss)}")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("gp")

# ── PROJECT CONFIG ──
VALIDATION_DIR          = "core/testing/agents/validator/output"
CERT_DIR                = "core/testing/agents/validator/certification_reports"
THRESHOLD_CONFIG_PATH   = "core/testing/agents/git_processor/thresholds.json"
SCAN_WINDOW_HOURS       = 1        # only consider branches with a commit in this window
DEFAULT_VALIDATION_THRESHOLD = 90  # fallback when thresholds.json is absent/broken
SOURCE_PREFIXES = [
    "",
    "core/",
    "core/testing/",
    "core/testing/agents/",
    "core/testing/agents/validator/",
    "core/testing/agents/git_processor/",
    "core/etl/",
    "core/sql/",
    "core/scripts/",
    "core/pipelines/",
    "core/data/",
    "core/models/",
    "core/utils/",
    "src/",
    "scripts/",
    "sql/",
    "pipelines/",
    "etl/",
    "jobs/",
    "dags/",
    "lib/",
    "app/",
]

SRC_EXT             = (".py", ".sql")
PASS_KW             = {"pass", "passed", "success", "ok", "true", "yes", "1"}
FAIL_KW             = {"fail", "failed", "error", "false", "no", "0"}
SKIP_KW             = {"skip", "skipped", "n/a", "na", "not applicable"}
CERT_THRESHOLD      = 90
# Branches that are NEVER scanned for validation files, even if they contain
# a recent commit to VALIDATION_DIR.  Add any branch whose validation uploads
# should NOT trigger the agent (e.g. main, release branches, archiving forks).
# Supports exact names and fnmatch-style wildcards, e.g. "release/*".
IGNORED_BRANCHES    = {
    "main",
    "master",
    "develop",
}
BOT = InputGitAuthor(name="git-processor-bot", email="bot@git-processor.local")


# ══════════════════  DATA MODELS  ══════════════════

@dataclass
class Finding:
    rule: str; sev: str; msg: str; line: Optional[int] = None

@dataclass
class CertReport:
    source: str; lang: str; lines: int = 0
    findings: list[Finding] = field(default_factory=list)
    score: float = 0.0; certified: bool = False; ts: str = ""
    val_file: str = ""; pr_num: Optional[int] = None
    branch: str = ""; file_status: str = ""

    def to_dict(self):
        return {
            "source_file": self.source, "language": self.lang,
            "total_lines": self.lines, "score": self.score,
            "certified": self.certified, "timestamp": self.ts,
            "validation_file": self.val_file, "file_status": self.file_status,
            "pr_number": self.pr_num, "branch": self.branch,
            "findings_count": len(self.findings),
            "findings": [{"rule": f.rule, "severity": f.sev,
                          "message": f.msg, "line": f.line} for f in self.findings],
        }

    def text(self):
        tag = "CERTIFIED" if self.certified else "NOT CERTIFIED"
        h = "=" * 62
        out = [h, f"  CERTIFICATION: {tag}  (score: {self.score}/100)", h,
               f"  Source      : {self.source} ({self.lang})",
               f"  File status : {self.file_status}",
               f"  Lines       : {self.lines}  |  Findings: {len(self.findings)}",
               f"  Threshold   : {CERT_THRESHOLD}",
               f"  Validation  : {self.val_file}",
               f"  PR          : #{self.pr_num or 'N/A'} (branch: {self.branch})", h]
        for i, f in enumerate(self.findings, 1):
            out.append(f"  {i:>3}. [{f.sev:<8}] {f.rule:<24} L{f.line or '-'}  {f.msg}")
        if self.findings: out.append(h)
        return "\n".join(out)

    def markdown(self):
        icon = ":white_check_mark:" if self.certified else ":x:"
        tag = "CERTIFIED" if self.certified else "NOT CERTIFIED"
        md = [f"## :mag: Certification: {icon} {tag}", "",
              f"| | |", f"|---|---|",
              f"| Score | `{self.score}` / 100 (threshold {CERT_THRESHOLD}) |",
              f"| Source | `{self.source}` ({self.lang}, {self.lines} lines) |",
              f"| File status | `{self.file_status}` |",
              f"| Validation | `{self.val_file}` |",
              f"| Branch | `{self.branch}` |", ""]
        if self.findings:
            md += ["### Findings", "",
                   "| # | Sev | Rule | Line | Message |",
                   "|---|-----|------|------|---------|"]
            for i, f in enumerate(self.findings, 1):
                md.append(f"| {i} | **{f.sev}** | `{f.rule}` | {f.line or '-'} | {f.msg} |")
        else:
            md.append("**Zero findings!**")
        md.append("")
        md.append(f"> {icon} **{'Auto-merge triggered.' if self.certified else 'Manual review required.'}**")
        return "\n".join(md)


# ══════════════════  SONAR RULES  ══════════════════

PEN = {"BLOCKER": 15, "CRITICAL": 10, "MAJOR": 5, "MINOR": 2, "INFO": 0.5}

def _py_rules(code):
    ff = []; lines = code.splitlines()
    for i, ln in enumerate(lines, 1):
        s = ln.rstrip()
        if len(s) > 120: ff.append(Finding("py:S103", "MINOR", f"Line {len(s)} chars", i))
        if ln != s: ff.append(Finding("py:S1131", "INFO", "Trailing whitespace", i))
        if re.match(r"\s*except\s*:", s): ff.append(Finding("py:S5754", "CRITICAL", "Bare except", i))
        if re.match(r"\s*print\s*\(", s) and "# noqa" not in s: ff.append(Finding("py:S106", "MINOR", "Use logging", i))
        if re.search(r'(?i)(password|secret|token|api_key)\s*=\s*["\'][^"\']+["\']', s): ff.append(Finding("py:S2068", "BLOCKER", "Hardcoded credential", i))
        if re.search(r"#\s*(TODO|FIXME|HACK|XXX)", s, re.I): ff.append(Finding("py:S1135", "INFO", "TODO/FIXME", i))
        if re.match(r"\s*from\s+\S+\s+import\s+\*", s): ff.append(Finding("py:S2208", "MAJOR", "Wildcard import", i))
        if re.search(r"\b(eval|exec)\s*\(", s): ff.append(Finding("py:S1523", "BLOCKER", "eval/exec", i))
        if re.search(r"def\s+\w+\(.*=\s*(\[\]|\{\})\s*[,)]", s): ff.append(Finding("py:S5765", "CRITICAL", "Mutable default", i))
        if re.match(r"\s*pass\s*$", s):
            for p in range(i-2, max(i-4,-1), -1):
                if p >= 0 and re.match(r"\s*(def |class )", lines[p]):
                    ff.append(Finding("py:S1186", "MAJOR", "Empty body", i)); break
        if re.match(r"\s*assert\b", s) and "test" not in s.lower(): ff.append(Finding("py:S5727", "MAJOR", "assert outside test", i))
        if re.search(r"\bos\.system\s*\(", s): ff.append(Finding("py:S4721", "CRITICAL", "os.system unsafe", i))
    t = code.lstrip()
    if not (t.startswith('"""') or t.startswith("'''")): ff.append(Finding("py:S1451", "MINOR", "No module docstring", None))
    if len(lines) > 500: ff.append(Finding("py:S104", "MAJOR", f"File {len(lines)} lines", None))
    mx = max((len(l)-len(l.lstrip()) for l in lines if l.strip()), default=0)
    if mx > 24: ff.append(Finding("py:S3776", "CRITICAL", f"Deep nesting ({mx})", None))
    return ff

def _sql_rules(code):
    ff = []; lines = code.splitlines()
    for i, ln in enumerate(lines, 1):
        u = ln.upper().strip()
        if re.search(r"\bSELECT\s+\*", u): ff.append(Finding("sql:S2583", "MAJOR", "SELECT *", i))
        if re.match(r"\s*(DELETE\s+FROM|UPDATE\s+\w+\s+SET)\b", u):
            w = "WHERE" in u
            if i < len(lines): w = w or "WHERE" in lines[i].upper()
            if not w: ff.append(Finding("sql:S3972", "BLOCKER", "No WHERE clause", i))
        if re.search(r"\|\||CONCAT\s*\(.*\+", u): ff.append(Finding("sql:S2077", "CRITICAL", "SQL injection risk", i))
        if re.search(r"(?i)(password|secret)\s*=\s*'[^']+'", ln): ff.append(Finding("sql:S2068", "BLOCKER", "Hardcoded cred", i))
        if "NOLOCK" in u: ff.append(Finding("sql:S2153", "MAJOR", "NOLOCK dirty read", i))
        if re.match(r"\s*GOTO\b", u): ff.append(Finding("sql:S907", "CRITICAL", "GOTO", i))
    if re.search(r"\bDROP\s+(TABLE|VIEW|PROCEDURE)\b(?!.*IF\s+EXISTS)", code, re.I):
        ff.append(Finding("sql:S4524", "MAJOR", "DROP no IF EXISTS", None))
    return ff

def certify(path, code):
    lang = "python" if path.endswith(".py") else "sql"
    ff = _py_rules(code) if lang == "python" else _sql_rules(code)
    pen = sum(PEN.get(f.sev, 1) for f in ff)
    sc = max(0.0, 100.0 - pen)
    return CertReport(source=path, lang=lang, lines=len(code.splitlines()),
                      findings=ff, score=round(sc, 1), certified=sc >= CERT_THRESHOLD,
                      ts=datetime.now(timezone.utc).isoformat())


# ══════════════════  VALIDATION PARSER  ══════════════════

_STRIP_PREFIXES = [
    "",
    "result_validation_", "result_validation-",
    "result-validation-", "result-validation_",
    "validation_results_", "validation_results-",
    "validation_result_",  "validation_result-",
    "validation_", "validation-",
    "val_results_", "val_results-",
    "val_result_",  "val_result-",
    "val_", "val-",
    "test_results_", "test_results-",
    "test_result_",  "test_result-",
    "results_", "results-",
    "result_", "result-",
    "output_", "output-",
]
_STRIP_SUFFIXES = [
    "_validation", "-validation",
    "_result",     "-result",
    "_results",    "-results",
    "_output",     "-output",
    "_val",        "-val",
    "_test",       "-test",
]
_TRAIL_RE = re.compile(r"[_-](\d{6,}|v\d+|\d+)$", re.IGNORECASE)


def extract_hint(fname: str) -> str:
    stem = fname.rsplit(".", 1)[0]
    work = stem.lower()
    for pfx in sorted(_STRIP_PREFIXES, key=len, reverse=True):
        if work.startswith(pfx):
            stem = stem[len(pfx):]
            work = work[len(pfx):]
            break
    for sfx in sorted(_STRIP_SUFFIXES, key=len, reverse=True):
        if work.endswith(sfx):
            stem = stem[: -len(sfx)]
            work = work[: -len(sfx)]
            break
    stem = _TRAIL_RE.sub("", stem)
    return stem.strip("_- ")


def parse_validation(fname, raw, threshold=DEFAULT_VALIDATION_THRESHOLD):
    hint = extract_hint(fname)
    vr = {"file": fname, "hint": hint, "total": 0,
          "passed": 0, "failed": 0, "skipped": 0, "pass_pct": 0.0, "verdict": "UNKNOWN",
          "threshold": threshold}
    try:
        if fname.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(raw), engine="openpyxl")
        else:
            df = pd.read_csv(io.StringIO(raw.decode("utf-8", "replace")))
    except Exception as e:
        log.error("  Parse error: %s", e); return vr
    df.columns = [c.strip().lower() for c in df.columns]
    status_col = None
    for c in ("verdict", "result", "status", "outcome", "pass_fail", "pass/fail", "test_result"):
        if c in df.columns: status_col = c; break
    if status_col:
        log.info("  Found column: '%s'", status_col)
        vals = df[status_col].astype(str).str.strip().str.lower()
        vr["passed"]  = sum(1 for v in vals if v in PASS_KW)
        vr["failed"]  = sum(1 for v in vals if v in FAIL_KW)
        vr["skipped"] = sum(1 for v in vals if v in SKIP_KW)
        vr["total"]   = vr["passed"] + vr["failed"]  # exclude skipped from denominator
    else:
        log.warning("  No verdict/result/status column. Scanning all cells.")
        flat = [str(x).strip().lower() for x in df.astype(str).values.flatten()]
        vr["passed"] = sum(1 for x in flat if x in PASS_KW)
        vr["failed"] = sum(1 for x in flat if x in FAIL_KW)
        vr["total"] = vr["passed"] + vr["failed"]
    if vr["total"] > 0:
        vr["pass_pct"] = round(vr["passed"] / vr["total"] * 100, 1)
    vr["verdict"] = "PASS" if vr["pass_pct"] >= threshold and vr["total"] > 0 else "FAIL"
    return vr


# ══════════════════  FILE OPS  ══════════════════

def download(repo, path, ref):
    try:
        fc = repo.get_contents(path, ref=ref)
        if fc.content: return base64.b64decode(fc.content)
        return base64.b64decode(repo.get_git_blob(fc.sha).content)
    except GithubException as e:
        log.error("  Download failed %s@%s: %s", path, ref, e); return None

def _normalize(name):
    return name.lower().replace("-", "_").replace(" ", "_").strip("_")

def _exact_match(filepath, hint):
    if not filepath.lower().endswith(SRC_EXT): return False
    basename = filepath.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return _normalize(hint) == _normalize(basename)

def _substr_match(filepath, hint):
    if not filepath.lower().endswith(SRC_EXT): return False
    basename = filepath.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return _normalize(hint) in _normalize(basename)


# ══════════════════  THRESHOLD CONFIG  ══════════════════

def load_threshold_config(repo, ref):
    """
    Load thresholds.json from the repo at THRESHOLD_CONFIG_PATH.
    Returns the parsed config dict, or a safe default if missing/broken.

    Expected format:
    {
      "thresholds": [
        { "pattern": "core/etl/*",     "threshold": 95 },
        { "pattern": "core/scripts/*", "threshold": 80 },
        { "pattern": "*",              "threshold": 90 }
      ]
    }
    Rules are matched top-to-bottom; first match wins.
    The "*" catch-all at the bottom acts as the default.
    """
    try:
        fc = repo.get_contents(THRESHOLD_CONFIG_PATH, ref=ref)
        raw = base64.b64decode(fc.content).decode("utf-8")
        config = json.loads(raw)
        log.info("  Threshold config loaded from %s", THRESHOLD_CONFIG_PATH)
        for entry in config.get("thresholds", []):
            log.info("    pattern=%-30s  threshold=%s", entry["pattern"], entry["threshold"])
        return config
    except GithubException:
        log.warning(
            "  thresholds.json not found at %s — using default %d%%",
            THRESHOLD_CONFIG_PATH, DEFAULT_VALIDATION_THRESHOLD,
        )
    except (json.JSONDecodeError, KeyError) as e:
        log.warning("  thresholds.json is malformed (%s) — using default %d%%",
                    e, DEFAULT_VALIDATION_THRESHOLD)
    # Safe fallback — behaves exactly like the old hardcoded constant
    return {"thresholds": [{"pattern": "*", "threshold": DEFAULT_VALIDATION_THRESHOLD}]}


def get_threshold(config, filepath):
    """
    Walk the thresholds list and return the threshold for the first
    pattern that matches *filepath*.  Falls back to DEFAULT_VALIDATION_THRESHOLD
    if nothing matches (should not happen when config has a "*" catch-all).
    """
    for entry in config.get("thresholds", []):
        if fnmatch.fnmatch(filepath, entry["pattern"]):
            log.info("  Threshold: %d%% (matched pattern '%s')",
                     entry["threshold"], entry["pattern"])
            return entry["threshold"]
    log.warning("  No threshold pattern matched '%s' — using default %d%%",
                filepath, DEFAULT_VALIDATION_THRESHOLD)
    return DEFAULT_VALIDATION_THRESHOLD


# ══════════════════  FIND VALIDATION FILE  ══════════════════

def find_validation_file(repo):
    """
    Scan VALIDATION_DIR on ALL branches, but only consider branches that:
      1. Are NOT listed in IGNORED_BRANCHES (exact name or fnmatch wildcard).
      2. Had a commit to VALIDATION_DIR within the last SCAN_WINDOW_HOURS hours.

    Branches matching IGNORED_BRANCHES are silently skipped — validation files
    committed to those branches will never trigger the agent.

    Returns (ContentFile, branch_name, commit_date) or (None, None, None).
    """
    now_utc   = datetime.now(timezone.utc)
    cutoff    = now_utc - timedelta(hours=SCAN_WINDOW_HOURS)

    log.info("  Validation dir  : %s", VALIDATION_DIR)
    log.info("  Scan window     : last %d hour(s)  (since %s)",
             SCAN_WINDOW_HOURS, cutoff.isoformat())
    log.info("  Ignored branches: %s", ", ".join(sorted(IGNORED_BRANCHES)) or "(none)")

    candidates = []

    branches = list(repo.get_branches())
    log.info("  Branches found  : %d", len(branches))

    for br in branches:
        # ── Gate 0: skip branches that must never trigger the agent ──────
        if any(fnmatch.fnmatch(br.name, pattern) for pattern in IGNORED_BRANCHES):
            log.info("    [ignore] %s — matches IGNORED_BRANCHES", br.name)
            continue

        # ── Quick gate: any commit to the validation dir in the window? ──
        try:
            recent = list(repo.get_commits(
                sha=br.name, path=VALIDATION_DIR, since=cutoff
            ))
        except GithubException:
            recent = []

        if not recent:
            log.debug("    [skip] %s — no recent commit to %s", br.name, VALIDATION_DIR)
            continue

        log.info("  Branch %-28s — %d recent commit(s) in window", br.name, len(recent))

        # ── Enumerate files in the validation directory ──────────────────
        try:
            contents = repo.get_contents(VALIDATION_DIR, ref=br.name)
        except GithubException:
            continue

        if not isinstance(contents, list):
            contents = [contents]

        for f in contents:
            if not f.name.lower().endswith((".csv", ".xlsx", ".xls")):
                continue
            try:
                commits = list(repo.get_commits(sha=br.name, path=f.path))
                if not commits:
                    continue
                commit_date = commits[0].commit.author.date

                # Only include files whose latest commit falls inside the window
                # Make commit_date timezone-aware if it isn't already
                if commit_date.tzinfo is None:
                    commit_date = commit_date.replace(tzinfo=timezone.utc)

                if commit_date < cutoff:
                    log.debug(
                        "    [skip] %-40s committed %s (outside window)",
                        f.name, commit_date.isoformat(),
                    )
                    continue

                candidates.append({
                    "file":   f,
                    "branch": br.name,
                    "date":   commit_date,
                    "sha":    f.sha,
                })
                log.info(
                    "    FOUND  %-40s  branch=%-20s  committed=%s",
                    f.name, br.name, commit_date.isoformat(),
                )
            except GithubException as e:
                log.debug("    Skipping %s on %s: %s", f.name, br.name, e)

    if not candidates:
        log.warning(
            "  No validation files committed within the last %d hour(s) on any branch.",
            SCAN_WINDOW_HOURS,
        )
        return None, None, None

    # ── Pick the most recently committed file ──────────────────────────
    candidates.sort(key=lambda c: c["date"], reverse=True)
    latest = candidates[0]

    log.info("")
    log.info("  ┌─ SELECTED VALIDATION FILE ──────────────────────────────")
    log.info("  │  Name   : %s", latest["file"].name)
    log.info("  │  Path   : %s", latest["file"].path)
    log.info("  │  Branch : %s", latest["branch"])
    log.info("  │  Date   : %s", latest["date"].isoformat())
    log.info("  └─────────────────────────────────────────────────────────")

    if len(candidates) > 1:
        log.info("  (Skipped %d older candidate(s) within window)", len(candidates) - 1)

    return latest["file"], latest["branch"], latest["date"]


# ══════════════════  FIND FILE IN OPEN PRs  ══════════════════

def _check_pr(repo, pr, hint):
    branch = pr.head.ref
    substr_hit = None
    try:
        diff_files = list(pr.get_files())
        log.info("      [A] Diff: %d files", len(diff_files))
        for cf in diff_files:
            if _exact_match(cf.filename, hint):
                log.info("          EXACT: %s [%s]", cf.filename, cf.status)
                return cf.filename, cf.status
            if not substr_hit and _substr_match(cf.filename, hint):
                substr_hit = (cf.filename, cf.status)
    except GithubException as e:
        log.warning("      [A] Failed: %s", e)
    try:
        tree = repo.get_git_tree(branch, recursive=True)
        for item in tree.tree:
            if item.type != "blob": continue
            if _exact_match(item.path, hint):
                log.info("      [B] EXACT in tree: %s", item.path)
                return item.path, "unknown"
            if not substr_hit and _substr_match(item.path, hint):
                substr_hit = (item.path, "unknown")
    except GithubException as e:
        log.warning("      [B] Failed: %s", e)
    norm = _normalize(hint)
    for name in dict.fromkeys([hint, norm, hint.lower()]):
        for ext in SRC_EXT:
            for pfx in SOURCE_PREFIXES:
                test_path = f"{pfx}{name}{ext}"
                try:
                    repo.get_contents(test_path, ref=branch)
                    log.info("      [C] MATCH: %s", test_path)
                    return test_path, "unknown"
                except GithubException:
                    pass
    if substr_hit:
        log.info("      Substring match: %s", substr_hit[0])
        return substr_hit
    return None, None

def find_file_in_prs(repo, hint):
    log.info("    Fetching open PRs (fresh)...")
    try:
        all_prs = list(repo.get_pulls(state="open", sort="created", direction="desc"))
    except GithubException as e:
        log.error("    Cannot list PRs: %s", e); return None, None, None, None
    log.info("    Open PRs: %d", len(all_prs))
    for pr in all_prs:
        branch = pr.head.ref
        log.info("")
        log.info("    PR #%d [%s -> %s] '%s'",
                 pr.number, branch, pr.base.ref, pr.title[:60])
        path, status = _check_pr(repo, pr, hint)
        if path:
            log.info("    >>> FOUND: %s in PR #%d", path, pr.number)
            return pr, path, branch, status
        log.info("      No match.")
    log.info("    File not found in any open PR.")
    return None, None, None, None


# ══════════════════  GITHUB WRITE OPS  ══════════════════

def commit_report(repo, rpt):
    default_branch = repo.default_branch
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = rpt.source.replace("/", "__").replace(".", "_")
    path = f"{CERT_DIR}/{slug}__{ts}.json"
    status_word = "new file" if rpt.file_status == "added" else "updated file"
    tag = "CERTIFIED" if rpt.certified else "BLOCKED"
    msg = f"cert({rpt.source}): {status_word} | score={rpt.score}/100 | {tag}"
    try:
        repo.create_file(path=path, content=json.dumps(rpt.to_dict(), indent=2),
                         message=msg, branch=default_branch, author=BOT)
        log.info("  Committed: %s (on %s)", path, default_branch)
        return True, path
    except GithubException as e:
        log.error("  Commit failed: %s", e); return False, None

def do_merge(pr, rpt, dry_run=False):
    sw = "new" if rpt.file_status == "added" else "updated"
    msg = (f"Auto-merged by git_processor v9.2\n\n"
           f"Source: {rpt.source} ({sw})\nScore: {rpt.score}/100\n"
           f"Validation: {rpt.val_file}\n"
           f"Signed-off-by: git-processor-bot <bot@git-processor.local>")
    title = f"chore: auto-merge {rpt.source} ({sw}, score {rpt.score})"
    if dry_run:
        log.info("  [DRY RUN] Would merge PR #%d", pr.number); return True
    try:
        pr.merge(commit_title=title, commit_message=msg, merge_method="squash")
        log.info("  MERGED PR #%d", pr.number); return True
    except GithubException as e:
        log.error("  Merge failed: %s", e); return False

def check_all_pr_files_certified(repo, pr, certified_file):
    log.info("  Checking ALL source files in PR #%d...", pr.number)
    try:
        diff_files = list(pr.get_files())
    except GithubException as e:
        log.error("  Cannot read PR files: %s", e); return False, []
    other_source_files = [
        cf.filename for cf in diff_files
        if cf.filename.lower().endswith(SRC_EXT) and cf.filename != certified_file
    ]
    if not other_source_files:
        log.info("  No other source files in PR. Safe to merge.")
        return True, []
    log.info("  PR has %d other source file(s):", len(other_source_files))
    for f in other_source_files: log.info("    - %s", f)
    uncertified = []
    for src_file in other_source_files:
        slug = src_file.replace("/", "__").replace(".", "_")
        has_cert = False
        try:
            cert_contents = repo.get_contents(CERT_DIR, ref=repo.default_branch)
            if not isinstance(cert_contents, list): cert_contents = [cert_contents]
            for cf in cert_contents:
                if cf.name.startswith(slug) and cf.name.endswith(".json"):
                    try:
                        raw = base64.b64decode(cf.content)
                        data = json.loads(raw.decode("utf-8"))
                        if data.get("certified") is True:
                            log.info("    %s -> CERTIFIED", src_file)
                            has_cert = True; break
                    except Exception: pass
        except GithubException: pass
        if not has_cert:
            uncertified.append(src_file)
            log.warning("    %s -> NOT CERTIFIED", src_file)
    if uncertified:
        log.warning("  MERGE BLOCKED: %d file(s) not certified", len(uncertified))
        return False, uncertified
    log.info("  All source files certified. Safe to merge.")
    return True, []

def label(pr, name, color="0e8a16"):
    try:
        r = pr.base.repo
        try: r.get_label(name)
        except Exception: r.create_label(name=name, color=color)
        pr.add_to_labels(name)
    except Exception: pass


# ══════════════════════════════════════════════════════════════
#  TEAMS NOTIFICATIONS  (all outcomes)
# ══════════════════════════════════════════════════════════════

def _teams_post(webhook_url, title, message, facts, color="attention", file_url=None):
    """
    Low-level Teams Adaptive Card sender.
    color is used as a header accent; recognised values: good, attention, warning.
    """
    if not webhook_url:
        log.info("  Teams: No webhook URL configured. Skipping.")
        return False

    # Map semantic colour to hex for the header bar
    COLOURS = {"good": "00b33c", "attention": "d93f0b", "warning": "e36209", "info": "0366d6"}
    hex_col = COLOURS.get(color, "d93f0b")

    fact_items = [{"title": k, "value": str(v)} for k, v in facts.items()]
    body_blocks = [
        {
            "type": "ColumnSet",
            "columns": [
                {
                    "type": "Column", "width": "auto",
                    "items": [{
                        "type": "TextBlock",
                        "text": "●",
                        "color": "Accent",
                        "size": "ExtraLarge",
                        "weight": "Bolder",
                    }],
                },
                {
                    "type": "Column", "width": "stretch",
                    "items": [{
                        "type": "TextBlock",
                        "text": title,
                        "size": "Large",
                        "weight": "Bolder",
                        "wrap": True,
                    }],
                },
            ],
        },
        {"type": "TextBlock", "text": message, "wrap": True, "spacing": "Medium"},
        {"type": "FactSet", "facts": fact_items, "spacing": "Medium"},
    ]

    actions = []
    if file_url:
        actions.append({"type": "Action.OpenUrl", "title": "View file", "url": file_url})

    card = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": body_blocks,
                **({"actions": actions} if actions else {}),
            },
        }],
    }

    payload = json.dumps(card).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            log.info("  Teams notification sent (HTTP %d): %s", resp.status, title)
            return True
    except urllib.error.URLError as e:
        log.warning("  Teams notification failed: %s", e)
        return False


# ── 1. VALIDATION FAILED ─────────────────────────────────────────────────────

def notify_teams_validation_failed(webhook_url, repo_name, vr, vf_path, vf_branch,
                                   threshold=DEFAULT_VALIDATION_THRESHOLD):
    file_url = f"https://github.com/{repo_name}/blob/{vf_branch}/{vf_path}"
    _teams_post(
        webhook_url=webhook_url,
        title="⚠️ Validation Failed — Certification Blocked",
        message=(
            f"The validation pass rate ({vr['pass_pct']}%) is below "
            f"the {threshold}% threshold. "
            f"Code certification was NOT performed."
        ),
        facts={
            "Repository":      repo_name,
            "Validation file": vr["file"],
            "File path":       vf_path,
            "Branch":          vf_branch,
            "Pass rate":       f"{vr['pass_pct']}% ({vr['passed']}/{vr['total']})",
            "Failed tests":    str(vr["failed"]),
            "Skipped tests":   str(vr.get("skipped", 0)),
            "Threshold":       f"{threshold}%",
            "Source hint":     vr["hint"],
            "Action":          "Upload a corrected validation CSV and re-trigger.",
        },
        color="attention",
        file_url=file_url,
    )


# ── 2. CERTIFICATION FAILED  (score < 90) ────────────────────────────────────

def notify_teams_certification_failed(webhook_url, repo_name, rpt):
    pr_url = (
        f"https://github.com/{repo_name}/pull/{rpt.pr_num}"
        if rpt.pr_num else None
    )
    top_findings = "; ".join(
        f"[{f.sev}] {f.rule} L{f.line or '?'}" for f in rpt.findings[:5]
    )
    _teams_post(
        webhook_url=webhook_url,
        title="❌ Code Certification Failed — Merge Blocked",
        message=(
            f"`{rpt.source}` scored **{rpt.score}/100** "
            f"(threshold: {CERT_THRESHOLD}). "
            f"{len(rpt.findings)} finding(s) detected. "
            f"Manual review required."
        ),
        facts={
            "Repository":      repo_name,
            "Source file":     rpt.source,
            "Branch":          rpt.branch,
            "PR":              f"#{rpt.pr_num}" if rpt.pr_num else "N/A",
            "Score":           f"{rpt.score} / {CERT_THRESHOLD} (threshold)",
            "Findings":        str(len(rpt.findings)),
            "Top findings":    top_findings or "N/A",
            "Validation file": rpt.val_file,
            "File status":     rpt.file_status,
        },
        color="attention",
        file_url=pr_url,
    )


# ── 3. CERTIFICATION PASSED  (score >= 90) ───────────────────────────────────

def notify_teams_certification_passed(webhook_url, repo_name, rpt, action,
                                      committed_path=None, default_branch=None):
    """
    Sent when score >= 90, regardless of whether the merge ultimately succeeded
    or was blocked by other uncertified files.
    """
    pr_url = (
        f"https://github.com/{repo_name}/pull/{rpt.pr_num}"
        if rpt.pr_num else None
    )
    action_labels = {
        "MERGED":                     "✅ Auto-merged into the default branch.",
        "MERGE_FAILED":               "⚠️ Merge attempted but failed — check PR.",
        "BLOCKED_UNCERTIFIED_FILES":  "⚠️ Merge blocked — other files in PR not certified.",
        "DRY_RUN":                    "ℹ️ Dry-run: no actual merge performed.",
    }
    action_text = action_labels.get(action, f"Action: {action}")
    facts = {
        "Repository":      repo_name,
        "Source file":     rpt.source,
        "Branch":          rpt.branch,
        "PR":              f"#{rpt.pr_num}" if rpt.pr_num else "N/A",
        "Score":           f"{rpt.score} / 100",
        "Findings":        str(len(rpt.findings)),
        "Validation file": rpt.val_file,
        "File status":     rpt.file_status,
        "Outcome":         action_text,
    }
    if committed_path and default_branch:
        facts["Cert report"] = f"{default_branch}/{committed_path}"

    _teams_post(
        webhook_url=webhook_url,
        title="✅ Code Certified" + (" & Merged" if action == "MERGED" else " — Review Merge Status"),
        message=(
            f"`{rpt.source}` passed certification with score **{rpt.score}/100**. "
            f"{action_text}"
        ),
        facts=facts,
        color="good",
        file_url=pr_url,
    )


# ── 4. PR NOT FOUND ──────────────────────────────────────────────────────────

def notify_teams_pr_not_found(webhook_url, repo_name, vr, vf_path, vf_branch):
    file_url = f"https://github.com/{repo_name}/blob/{vf_branch}/{vf_path}"
    _teams_post(
        webhook_url=webhook_url,
        title="🔍 No Matching PR Found — Action Required",
        message=(
            f"Validation passed for hint `{vr['hint']}` "
            f"({vr['pass_pct']}% pass rate), but no open PR contains a matching "
            f".py or .sql source file. Certification cannot proceed."
        ),
        facts={
            "Repository":      repo_name,
            "Source hint":     vr["hint"],
            "Validation file": vr["file"],
            "Validation path": vf_path,
            "Branch":          vf_branch,
            "Pass rate":       f"{vr['pass_pct']}% ({vr['passed']}/{vr['total']})",
            "Action required": "Open a PR containing the source file, or rename the validation CSV to match.",
        },
        color="warning",
        file_url=file_url,
    )


# ── 5. COMMITTED TO MAIN/DEFAULT BRANCH ──────────────────────────────────────

def notify_teams_committed_to_main(webhook_url, repo_name, rpt,
                                   committed_path, default_branch):
    report_url = f"https://github.com/{repo_name}/blob/{default_branch}/{committed_path}"
    _teams_post(
        webhook_url=webhook_url,
        title=f"📄 Cert Report Committed to `{default_branch}`",
        message=(
            f"A certification report for `{rpt.source}` (score {rpt.score}/100) "
            f"has been committed to the `{default_branch}` branch."
        ),
        facts={
            "Repository":    repo_name,
            "Source file":   rpt.source,
            "Score":         f"{rpt.score} / 100",
            "Certified":     "Yes" if rpt.certified else "No",
            "Report path":   committed_path,
            "Branch":        default_branch,
            "PR":            f"#{rpt.pr_num}" if rpt.pr_num else "N/A",
            "Committed at":  datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        },
        color="info",
        file_url=report_url,
    )


# ══════════════════  MAIN PIPELINE  ══════════════════

def run(repo_name, dry_run=False):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN not set.\nexport GITHUB_TOKEN='ghp_...'")

    webhook = (os.environ.get("TEAMS_WEBHOOK_URL") or "").strip().strip("'\"")
    log.info("Teams webhook: %s",
             f"configured ({len(webhook)} chars)" if webhook else "NOT CONFIGURED")

    g = Github(token, per_page=100)
    repo = g.get_repo(repo_name)
    default = repo.default_branch
    log.info("Repo: %s (default branch: %s)", repo.full_name, default)

    # ── STEP 0: Load per-file threshold config ────────────────────────────
    log.info("\n" + "─" * 62)
    log.info("STEP 0: Loading threshold config")
    log.info("─" * 62)
    threshold_config = load_threshold_config(repo, default)

    # ── STEP 1: Find the most recently committed validation file (≤1 h) ──
    log.info("\n" + "─" * 62)
    log.info("STEP 1: Locating latest validation file (last %dh)", SCAN_WINDOW_HOURS)
    log.info("─" * 62)
    vf, vf_branch, vf_date = find_validation_file(repo)
    if not vf:
        log.warning("No validation files found within the scan window. Stopping.")
        return

    # ── STEP 2: Download and parse the validation file ───────────────────
    log.info("\n" + "─" * 62)
    log.info("STEP 2: Downloading and parsing validation file")
    log.info("─" * 62)
    log.info("  File   : %s", vf.path)
    log.info("  Branch : %s", vf_branch)
    log.info("  Date   : %s", vf_date.isoformat())

    raw = download(repo, vf.path, vf_branch)
    if not raw:
        log.error("  Download failed. Stopping."); return

    validation_threshold = get_threshold(threshold_config, vf.path)
    vr = parse_validation(vf.name, raw, threshold=validation_threshold)
    log.info("  Hint       : '%s'  (extracted from filename)", vr["hint"])
    log.info("  Pass rate  : %.1f%%  (%d/%d passed, %d failed, %d skipped)",
             vr["pass_pct"], vr["passed"], vr["total"], vr["failed"], vr.get("skipped", 0))
    log.info("  Threshold  : %d%%", validation_threshold)
    log.info("  Verdict    : %s", vr["verdict"])

    # ── STEP 3: Gate on validation pass rate ─────────────────────────────
    if vr["verdict"] != "PASS":
        log.warning("\n  VALIDATION BLOCKED: %.1f%% < %d%% threshold.",
                    vr["pass_pct"], validation_threshold)
        log.warning("  Code certification will NOT be performed.")

        log.info("\n  Creating GitHub Issue for validation failure...")
        file_url = f"https://github.com/{repo_name}/blob/{vf_branch}/{vf.path}"
        try:
            issue_title = (
                f"Validation Failed: {vr['file']} — {vr['pass_pct']}% pass rate"
            )
            issue_body = (
                f"## :warning: Validation Failed — Certification Blocked\n\n"
                f"| Field | Value |\n|---|---|\n"
                f"| **Validation file** | [`{vr['file']}`]({file_url}) |\n"
                f"| **File path** | `{vf.path}` |\n"
                f"| **Branch** | `{vf_branch}` |\n"
                f"| **Committed** | `{vf_date.isoformat()}` |\n"
                f"| **Pass rate** | **{vr['pass_pct']}%** (threshold: {validation_threshold}%) |\n"
                f"| **Total tests** | {vr['total']} |\n"
                f"| **Passed** | {vr['passed']} |\n"
                f"| **Failed** | {vr['failed']} |\n"
                f"| **Skipped** | {vr.get('skipped', 0)} |\n"
                f"| **Source file hint** | `{vr['hint']}` |\n\n"
                f"### :page_facing_up: Validation file\n\n"
                f"**Path:** `{vf.path}`\n\n"
                f"**Open file:** [Click here to view]({file_url})\n\n"
                f"### What happened\n\n"
                f"The validation pass rate ({vr['pass_pct']}%) is below the "
                f"{validation_threshold}% threshold. "
                f"Code certification was **not performed**.\n\n"
                f"### Action required\n\n"
                f"1. Open the [validation file]({file_url})\n"
                f"2. Review the failing test cases\n"
                f"3. Fix the issues\n"
                f"4. Re-upload the validation CSV to `{VALIDATION_DIR}/`\n"
            )
            repo.create_issue(
                title=issue_title, body=issue_body,
                labels=["validation-failed"],
            )
            log.info("  GitHub Issue created.")
        except GithubException as e:
            log.warning("  Could not create issue: %s", e)

        # ── NOTIFY: validation failed ─────────────────────────────────────
        notify_teams_validation_failed(webhook, repo_name, vr, vf.path, vf_branch,
                                       threshold=validation_threshold)
        return

    log.info("  Validation PASSED (%.1f%% >= %d%%)", vr["pass_pct"], validation_threshold)

    # ── STEP 4: Find matching source file in open PRs ────────────────────
    log.info("\n" + "─" * 62)
    log.info("STEP 4: Searching open PRs for source file matching '%s'", vr["hint"])
    log.info("─" * 62)
    pr, src_path, src_branch, file_status = find_file_in_prs(repo, vr["hint"])
    if not src_path:
        log.error(
            "\n  No open PR contains a file matching hint '%s'.\n"
            "  Ensure a PR is open whose diff or branch tree contains a .py or\n"
            "  .sql file whose name matches the core token in '%s'.",
            vr["hint"], vf.name,
        )
        # ── NOTIFY: PR not found ─────────────────────────────────────────
        notify_teams_pr_not_found(webhook, repo_name, vr, vf.path, vf_branch)
        return

    status_label = (
        "added"    if file_status == "added" else
        "modified" if file_status in ("modified", "renamed", "changed") else
        "added/modified"
    )
    log.info("  Source : %s", src_path)
    log.info("  PR     : #%d (%s -> %s)", pr.number, src_branch, pr.base.ref)
    log.info("  Status : %s", status_label)

    # ── STEP 5: Run certification (static analysis) ───────────────────────
    log.info("\n" + "─" * 62)
    log.info("STEP 5: Certifying '%s' (%s)", src_path, status_label)
    log.info("─" * 62)
    src_raw = download(repo, src_path, src_branch)
    if not src_raw:
        log.error("  Source file download failed."); return
    rpt = certify(src_path, src_raw.decode("utf-8", "replace"))
    rpt.val_file    = vf.name
    rpt.branch      = src_branch
    rpt.pr_num      = pr.number
    rpt.file_status = status_label
    print("\n" + rpt.text() + "\n")

    # ── STEP 6: Commit cert report + post PR comment ──────────────────────
    log.info("─" * 62)
    log.info("STEP 6: Committing certification report to '%s'", default)
    log.info("─" * 62)
    committed_ok, committed_path = commit_report(repo, rpt)
    time.sleep(3)
    pr.create_issue_comment(rpt.markdown())
    log.info("  Comment posted on PR #%d", pr.number)
    label(pr,
          "certified" if rpt.certified else "needs-review",
          "0e8a16"    if rpt.certified else "d93f0b")
    label(pr, f"file-{status_label}", "c5def5")

    # ── NOTIFY: committed to main ─────────────────────────────────────────
    if committed_ok and committed_path:
        notify_teams_committed_to_main(webhook, repo_name, rpt, committed_path, default)

    # ── STEP 7: Merge (or block) ──────────────────────────────────────────
    log.info("\n" + "─" * 62)
    log.info("STEP 7: Merge decision")
    log.info("─" * 62)

    if rpt.certified:
        log.info("  Score %.1f >= %d. Checking all PR files for certification...",
                 rpt.score, CERT_THRESHOLD)
        safe, uncertified = check_all_pr_files_certified(repo, pr, src_path)
        if safe:
            if dry_run:
                action = "DRY_RUN"
            elif do_merge(pr, rpt, dry_run):
                label(pr, "auto-merged", "6f42c1"); action = "MERGED"
            else:
                action = "MERGE_FAILED"
        else:
            block_msg = (
                f"## :warning: Merge blocked\n\n"
                f"`{src_path}` passed (score: {rpt.score}), "
                f"but these files are **not yet certified**:\n\n"
            )
            for uf in uncertified: block_msg += f"- `{uf}`\n"
            block_msg += "\nUpload validation CSVs for remaining files to unblock."
            pr.create_issue_comment(block_msg)
            label(pr, "merge-blocked-uncertified", "d93f0b")
            action = "BLOCKED_UNCERTIFIED_FILES"

        # ── NOTIFY: certification passed (regardless of merge outcome) ────
        notify_teams_certification_passed(
            webhook, repo_name, rpt, action,
            committed_path=committed_path,
            default_branch=default,
        )
    else:
        log.info("  Score %.1f < %d -> BLOCKED.", rpt.score, CERT_THRESHOLD)
        action = "BLOCKED_LOW_SCORE"
        # ── NOTIFY: certification failed ──────────────────────────────────
        notify_teams_certification_failed(webhook, repo_name, rpt)

    log.info("\n" + "=" * 62)
    log.info("RESULT: %s", json.dumps({
        "validation_file":   vf.name,
        "validation_branch": vf_branch,
        "validation_date":   vf_date.isoformat(),
        "source":            src_path,
        "file_status":       status_label,
        "pr":                f"#{pr.number}",
        "branch":            src_branch,
        "score":             rpt.score,
        "certified":         rpt.certified,
        "action":            action,
    }, default=str))
    log.info("=" * 62)


def main():
    print("""
   +------------------------------------------------------------+
   |          GIT PROCESSOR AGENT  v9.2                         |
   |          Repo: ahemadshaik/DEAH                            |
   |                                                            |
   |  Agent:      core/testing/agents/git_processor/            |
   |  Validation: core/testing/agents/validator/output/         |
   +------------------------------------------------------------+
    """)
    p = argparse.ArgumentParser(description="Git Processor v9.2 for DEAH")
    p.add_argument("--repo", default="ahemadshaik/DEAH")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse and certify but do not merge or commit")
    a = p.parse_args()
    run(a.repo, a.dry_run)

if __name__ == "__main__":
    main()
