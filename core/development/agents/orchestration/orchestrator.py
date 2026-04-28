"""
Development Pod Orchestrator — full pipeline with human-in-the-loop checkpoints.

Merges CodeGenPipeline (plan → generate → optimize → review) and
DeployPipeline (validate → deploy) into a single entry point.

Flow
────
  [INPUT] Implementation.md + mapping.csv
      ↓
  Stage 1: PlannerAgent → ExecutionPlan
      ↓── CHECKPOINT 1 ──────────────────────────────────────────────────────
      │  approve → proceed to Stage 2
      │  revise  → collect human notes → re-run planner → show new plan → loop
      │  abort   → exit
      ↓
  Stage 2: GeneratorAgent → raw artifacts
           OptimizerAgent → improved artifacts
           ReviewerAgent  → review report + quality score
      ↓── CHECKPOINT 2 ──────────────────────────────────────────────────────
      │  approve → proceed to Stage 3
      │  revise  → collect human notes → re-run generator+optimizer+reviewer → loop
      │  abort   → exit
      ↓
  Stage 3 (deploy hand-off)
      ↓── CHECKPOINT 3 ──────────────────────────────────────────────────────
         deploy → hand off to DeployerAgent
         skip   → exit without deploying

Token efficiency
────────────────
All agents share a SessionContext which holds the large static documents
(implementation_md, mapping_csv) and the plan as ContextBlock objects.
Anthropic caches these blocks server-side so each subsequent agent call
reads them from cache instead of re-encoding them.

Human notes collected at any checkpoint are accumulated in SessionContext
and injected into every downstream agent's task prompt.
"""
from __future__ import annotations
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from core.utilities.llm import BaseLLMClient
from config_generator import generate_pipeline_config
from connection_checker import check_connections, print_connection_report
from agents.planner.agent import PlannerAgent
from agents.generator.agent import GeneratorAgent, GeneratorClarificationNeeded
from agents.optimizer.agent import OptimizerAgent
from agents.reviewer.agent import ReviewerAgent
from api.models import (
    CodeGenOutput, GeneratedArtifact, PipelineInput,
    ReviewResult, RunStatus, SessionContext, Verdict,
)

if TYPE_CHECKING:
    from api.routes.code_gen import _RunState

logger = logging.getLogger("development.orchestrator")


# ── BigQuery schema helpers ────────────────────────────────────────────────────

_BQ_TYPE_ALIASES: dict[str, str] = {
    "INTEGER": "INT64",
    "FLOAT":   "FLOAT64",
    "BOOLEAN": "BOOL",
}


def _normalize_bq_type(bq_type: str) -> str:
    """Normalize BQ API type names to their canonical DDL equivalents."""
    return _BQ_TYPE_ALIASES.get(bq_type.upper(), bq_type.upper())


def _parse_mapping_schema(mapping_csv: str) -> dict[str, set[tuple[str, str]]]:
    """
    Parse mapping CSV and return {target_table: {(column_name, bq_type)}}.

    Column names are lowercased; types are normalized via _normalize_bq_type.
    """
    import csv as _csv, io as _io
    reader = _csv.DictReader(_io.StringIO(mapping_csv))
    schema: dict[str, set[tuple[str, str]]] = {}
    for row in reader:
        table = (row.get("target_table") or "").strip().lower()
        col   = (row.get("target_column") or "").strip().lower()
        dtype = (row.get("target_data_type") or "").strip()
        if not table or not col or not dtype:
            continue
        schema.setdefault(table, set()).add((col, _normalize_bq_type(dtype)))
    return schema


class CodeGenPipeline:
    def __init__(
        self,
        llm: BaseLLMClient,
        output_root: str = "output",
        git_repo_url: str | None = None,
        git_pat: str | None = None,
        git_local_path: str | None = None,
        push_to_remote: bool = False,
        run_state: Optional["_RunState"] = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> None:
        self._llm = llm
        self._output_root = Path(output_root)
        self._git_repo_url = git_repo_url
        self._git_pat = git_pat
        self._git_local_path = git_local_path
        self._push_to_remote = push_to_remote
        self._run_state = run_state
        self._dry_run = dry_run
        self._force = force

    def _check_existing_bq_tables(self, request: "PipelineInput", ctx: "SessionContext") -> None:
        """
        Before planning, check if target tables already exist in BigQuery
        with a matching schema. Injects a pre-plan note listing tables to skip.

        Silently skips the check if:
        - project_id or dataset_id are empty
        - google-cloud-bigquery is not installed
        - BQ credentials are unavailable
        """
        if not request.project_id or not request.dataset_id:
            logger.info("BQ schema check skipped — project_id or dataset_id not set.")
            return
        if not request.mapping_csv:
            logger.info("BQ schema check skipped — no mapping CSV.")
            return

        try:
            from google.cloud import bigquery as _bq
            from google.api_core.exceptions import NotFound
        except ImportError:
            logger.warning("google-cloud-bigquery not installed — skipping BQ schema check.")
            return

        expected = _parse_mapping_schema(request.mapping_csv)
        if not expected:
            return

        try:
            client = _bq.Client(project=request.project_id)
        except Exception as exc:
            logger.warning("BQ client init failed — skipping schema check: %s", exc)
            return

        already_present: list[str] = []

        for table_name, expected_cols in expected.items():
            table_ref = f"{request.project_id}.{request.dataset_id}.{table_name}"
            try:
                bq_table = client.get_table(table_ref)
            except NotFound:
                logger.info("BQ schema check: %s not found — DDL will be generated.", table_name)
                continue
            except Exception as exc:
                logger.warning("BQ schema check error for %s — %s. Skipping check.", table_name, exc)
                continue

            bq_cols = {
                (field.name.lower(), _normalize_bq_type(field.field_type))
                for field in bq_table.schema
            }

            if bq_cols == expected_cols:
                _info(f"  [SKIP] {table_name} — artifact already present in BQ, schema matches. No DDL needed.")
                already_present.append(table_name)
            else:
                missing = expected_cols - bq_cols
                extra   = bq_cols - expected_cols
                logger.info(
                    "BQ schema check: %s exists but schema differs "
                    "(missing=%s, extra=%s) — DDL will be generated.",
                    table_name, missing, extra,
                )

        if already_present:
            note = (
                "The following tables already exist in BigQuery with a matching schema. "
                "Do NOT generate DDL for them: "
                + ", ".join(already_present)
            )
            ctx.add_note(note)
            logger.info("BQ schema check: %d table(s) already present — injected skip note.", len(already_present))

    # ── Public entry point ─────────────────────────────────────────────────────

    def run(self, request: PipelineInput) -> CodeGenOutput:
        _banner("CODE GEN POD")
        _info(f"Request ID  : {request.request_id}")
        _info(f"Project     : {request.project_id} / {request.dataset_id}")
        _info(f"Environment : {request.environment}")
        _info(f"Cloud       : {request.cloud_provider.value.upper()}")

        input_hash = _compute_input_hash(request)
        cache_file = self._output_root / ".cache" / f"{input_hash}.json"

        if not self._force:
            # ── Check 1: same request_id output directory already has artifacts ──
            existing_out_dir = self._output_root / request.request_id
            if existing_out_dir.exists() and (existing_out_dir / "MANIFEST.json").exists():
                _info(f"Output directory already complete — reusing {existing_out_dir}")
                _info("Use --force to regenerate from scratch.")
                try:
                    cached_manifest = json.loads(
                        (existing_out_dir / "MANIFEST.json").read_text(encoding="utf-8")
                    )
                    _banner("PIPELINE COMPLETE (existing output)")
                    _info(f"Quality score : {cached_manifest.get('quality_score', 'n/a')}")
                    _info(f"Artifacts     : {existing_out_dir}")
                except Exception:
                    pass
                return

            # ── Check 2: same inputs (different request_id) already generated ───
            if cache_file.exists():
                try:
                    cache_meta = json.loads(cache_file.read_text(encoding="utf-8"))
                    cached_run_dir = Path(cache_meta["output_dir"])
                    if cached_run_dir.exists() and (cached_run_dir / "MANIFEST.json").exists():
                        _info(f"Inputs unchanged — reusing cached artifacts from {cached_run_dir}")
                        _info("Use --force to regenerate from scratch.")
                        cached_manifest = json.loads(
                            (cached_run_dir / "MANIFEST.json").read_text(encoding="utf-8")
                        )
                        _banner("PIPELINE COMPLETE (from cache)")
                        _info(f"Quality score : {cached_manifest.get('quality_score', 'n/a')}")
                        _info(f"Artifacts     : {cached_run_dir}")
                        return
                except Exception:
                    pass

        # ── Output directory — git workspace or local output/ ─────────────────
        _git_manager = None
        if self._git_repo_url:
            try:
                _stage("GIT — PREPARING WORKSPACE")
                _git_manager, out_dir = self._prepare_git_workspace(request)
            except Exception as _git_err:
                logger.warning("Git workspace setup failed, falling back to local output — %s", _git_err)
                _info(f"Git workspace error: {_git_err}. Using local output/ instead.")
                out_dir = self._output_root / request.request_id
        else:
            out_dir = self._output_root / request.request_id

        out_dir.mkdir(parents=True, exist_ok=True)

        ctx = SessionContext(
            request_id=request.request_id,
            implementation_md=request.implementation_md,
            mapping_csv=request.mapping_csv,
            project_id=request.project_id,
            dataset_id=request.dataset_id,
            environment=request.environment,
            cloud_provider=request.cloud_provider.value,
        )

        # ── Pre-plan: BigQuery schema check ───────────────────────────────────
        self._check_existing_bq_tables(request, ctx)

        # ── Stage 1: Plan ──────────────────────────────────────────────────────
        _stage("1 / 3 — PLANNING")
        if self._run_state:
            self._run_state.status = RunStatus.PLANNING
        plan = self._run_plan_with_revision(ctx, out_dir)
        ctx.plan = plan
        if self._run_state:
            self._run_state.plan_summary = plan.summary

        if self._dry_run:
            _banner("DRY RUN COMPLETE — plan only, no code generated")
            _info("Remove --dry-run to proceed with code generation.")
            return

        # ── Stage 2: Generate → Optimize → Review ─────────────────────────────
        _stage("2 / 3 — GENERATE  →  OPTIMIZE  →  REVIEW")
        artifacts, reviews, quality = self._run_codegen_with_revision(ctx, out_dir)
        if self._run_state:
            self._run_state.quality_score = quality

        # ── Git: commit approved artifacts to feature branch ───────────────────
        git_branch: str | None = None
        if _git_manager is not None:
            # Pre-configured git workspace path — commit then confirm push
            _stage("GIT — COMMITTING ARTIFACTS TO FEATURE BRANCH")
            if self._run_state:
                self._run_state.status = RunStatus.COMMITTING
            git_branch = self._commit_to_git(_git_manager, ctx)
            if self._run_state and git_branch:
                self._run_state.git_branch = git_branch

            # ── Checkpoint 3: confirm push to remote ───────────────────────────
            _stage("GIT — PUSH TO REMOTE")
            _checkpoint_git_push(
                _git_manager,
                git_branch or _git_manager.target_branch,
                self._run_state,
            )
        else:
            # No pre-configured git URL — offer interactive push after generation
            _stage("GIT — OPTIONAL PUSH TO FEATURE BRANCH")
            git_branch = _checkpoint_git_push_prompt(
                out_dir=out_dir,
                request_id=request.request_id,
                git_repo_url=self._git_repo_url,
                git_pat=self._git_pat,
                git_local_path=self._git_local_path,
                run_state=self._run_state,
            )
            if git_branch and self._run_state:
                self._run_state.git_branch = git_branch

        output = CodeGenOutput(
            request_id=ctx.request_id,
            plan=plan,
            artifacts=artifacts,
            review_results=reviews,
            quality_score=quality,
            output_directory=str(out_dir),
            approved_for_deploy=True,
            git_branch=git_branch,
        )
        _write_manifest(out_dir, output, ctx, git_branch, self._git_repo_url)

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"input_hash": input_hash, "output_dir": str(out_dir),
                        "generated_at": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )

        _banner("PIPELINE COMPLETE")
        _info(f"Quality score       : {quality:.0f}/100")
        _info(f"Artifacts           : {out_dir}")
        if git_branch:
            _info(f"Git branch          : {git_branch}")
        return output

    # ── Standalone optimize + review (no planner / generator) ─────────────────

    def optimize_and_review(
        self,
        artifacts: list[GeneratedArtifact],
        project_id: str = "",
        dataset_id: str = "",
        environment: str = "dev",
        cloud_provider: str = "gcp",
        human_notes: list[str] | None = None,
        request_id: str | None = None,
    ) -> dict:
        """Optimize and review existing artifacts without running the planner or generator."""
        import uuid
        rid = request_id or f"opt-{uuid.uuid4().hex[:8]}"
        out_dir = self._output_root / rid
        out_dir.mkdir(parents=True, exist_ok=True)

        ctx = SessionContext(
            request_id=rid,
            implementation_md="",
            mapping_csv="",
            project_id=project_id,
            dataset_id=dataset_id,
            environment=environment,
            cloud_provider=cloud_provider,
        )
        for note in (human_notes or []):
            ctx.add_note(note)

        _banner("OPTIMIZE + REVIEW MODE")
        _info(f"Request ID : {rid}")
        _info(f"Artifacts  : {len(artifacts)}")

        _stage("OPTIMIZING")
        optimized = OptimizerAgent(self._llm).optimize(ctx, artifacts)

        _stage("RUFF — LINTING PYTHON ARTIFACTS")
        optimized = _run_ruff(optimized, out_dir)

        _stage("REVIEWING (correctness / security / performance + logic_preservation)")
        reviews = ReviewerAgent(self._llm).review_optimized(ctx, artifacts, optimized)
        quality = _quality_score(reviews)
        _info(f"Quality score: {quality:.0f}/100")

        _write_artifacts(out_dir, optimized, reviews)
        _checkpoint_optimize_review(optimized, reviews, quality, self._run_state)

        _banner("OPTIMIZE + REVIEW COMPLETE")
        _info(f"Quality score : {quality:.0f}/100")
        _info(f"Artifacts     : {out_dir}")
        return {
            "request_id": rid,
            "artifacts": optimized,
            "review_results": reviews,
            "quality_score": quality,
            "output_directory": str(out_dir),
        }

    # ── Stage runners with revision loops ─────────────────────────────────────

    def _run_plan_with_revision(self, ctx: SessionContext, out_dir: Path):
        # Pre-plan Q&A — only on the first pass (no human notes yet)
        if not ctx.human_notes and self._run_state is None:
            _info("Planner [1/3]: extracting clarifying questions...")
            questions = PlannerAgent(self._llm).extract_questions(ctx)
            if questions:
                answers = _run_qa_loop(questions)
                if answers:
                    ctx.add_note(answers)
        else:
            _info("Planner [1/3]: skipping Q&A (notes already provided)")

        while True:
            if self._run_state:
                self._run_state.push_log("Planner: generating execution plan...")
            _info("Planner [2/3]: generating execution plan...")
            t_plan = time.monotonic()
            plan = PlannerAgent(self._llm).plan(ctx)
            elapsed_plan = time.monotonic() - t_plan
            plan_file = _write_plan(out_dir, plan)
            msg = (
                f"Planner: plan ready — "
                f"{len(plan.artifacts_to_generate)} artifact(s), "
                f"{len(plan.tables)} table(s) ({elapsed_plan:.1f}s)"
            )
            if self._run_state:
                self._run_state.push_log(msg)
            _info(msg)
            decision, notes = _checkpoint_plan(plan, plan_file, self._run_state)
            if decision == "approve":
                return plan
            if decision == "revise":
                ctx.add_note(notes)
                _info("Re-running planner with your corrections...")

    def _prepare_git_workspace(self, request: PipelineInput):
        """Clone/connect to the git repo, pull latest, and return (GitRepoManager, out_dir)."""
        from core.utilities.versioning_tools import GitRepoManager  # noqa: PLC0415

        local_path = self._git_local_path or str(self._output_root / "git_workspace")
        branch_name = _resolve_branch_name(
            request.request_id,
            self._git_repo_url,
            self._git_pat or "",
            self._run_state,
        )
        branch_url = f"{self._git_repo_url}/tree/{branch_name}"

        git = GitRepoManager(
            branch_url=branch_url,
            pat=self._git_pat or "",
            local_path=local_path,
        )
        git.connect()
        git.pull()

        out_dir = Path(local_path) / "pipelines" / request.project_id / request.request_id
        _info(f"Git branch      : {branch_name}")
        _info(f"Git workspace   : {out_dir}")
        return git, out_dir

    def _commit_to_git(self, git, ctx: SessionContext) -> str | None:
        """Stage all changes and commit; push if push_to_remote is set."""
        try:
            pipeline_name = (
                ctx.implementation_md.splitlines()[0].replace("#", "").strip()
                .lower().replace(" ", "_")[:40]
                or ctx.request_id[:20]
            )
            msg = (
                f"feat({ctx.project_id}): generate {pipeline_name} "
                f"pipeline [{ctx.environment}]"
            )
            git.commit(msg)
            if self._push_to_remote:
                git.push()
                _info("Git             : branch pushed to remote")
            else:
                _info(f"Git             : run 'git push origin {git.target_branch}' to publish")
            _info(f"Git branch      : {git.target_branch}")
            return git.target_branch
        except Exception as exc:
            logger.warning("Git commit skipped — %s", exc)
            _info(f"Git commit skipped: {exc}")
            return getattr(git, "target_branch", None)

    def _run_codegen_with_revision(self, ctx: SessionContext, out_dir: Path):
        from concurrent.futures import ThreadPoolExecutor as _TPE
        from agents.reviewer.agent import (
            _get_failed_artifact_names, _merge_results as _rev_merge, DIMENSIONS,
        )
        from agents.generator.agent import _scan_and_update_requirements
        from api.models import ArtifactType

        # DDL/DML: generator already applies best practices — optimizer adds no value.
        # SP/DAG/Pipeline: complex logic that benefits from structural improvements.
        _SKIP_OPT_TYPES = (ArtifactType.DDL, ArtifactType.DML)
        _OPTIMIZE_TYPES  = (ArtifactType.SP, ArtifactType.DAG, ArtifactType.PIPELINE)

        artifacts: list[GeneratedArtifact] = []
        # Per-artifact review cache — avoids re-reviewing artifacts that haven't changed.
        # Key: file_name, Value: list[ReviewResult] from the last review of that artifact.
        _review_cache: dict[str, list[ReviewResult]] = {}

        # Defined once outside the loop — captures ctx/out_dir/run_state from enclosing scope.
        def _opt_rev_art(art: GeneratedArtifact):
            """Optimize (SP/DAG only) then review a single artifact."""
            rs = self._run_state
            if art.artifact_type in _OPTIMIZE_TYPES:
                _push_log(f"Optimizer: {art.file_name} ...", rs)
                t0 = time.monotonic()
                opt = OptimizerAgent(self._llm).optimize(ctx, [art])
                elapsed = time.monotonic() - t0
                if art.file_name.endswith(".py") and opt:
                    opt = _run_ruff(opt, out_dir)
                target = opt[0] if opt else art
                _push_log(f"Optimizer: {art.file_name} done ({elapsed:.1f}s)", rs)
            else:
                if art.file_name.endswith(".py"):
                    linted = _run_ruff([art], out_dir)
                    target = linted[0] if linted else art
                else:
                    target = art
            _push_log(f"Reviewer: {art.file_name} ...", rs)
            t0 = time.monotonic()
            revs = ReviewerAgent(self._llm).review(ctx, [target])
            elapsed = time.monotonic() - t0
            _push_log(f"Reviewer: {art.file_name} done ({elapsed:.1f}s)", rs)
            return target, revs

        to_process: list[GeneratedArtifact] = []  # artifacts to opt+review this round

        while True:
            # ── Generate (first run or full restart) ────────────────────────────
            if not artifacts:
                _status("GENERATING", self._run_state)
                _push_log("Generator: starting artifact generation...", self._run_state)
                t_gen = time.monotonic()
                try:
                    artifacts = GeneratorAgent(self._llm).generate(ctx)
                except GeneratorClarificationNeeded as clarify_err:
                    _info(f"Generator blocked — clarification needed:\n{clarify_err}")
                    notes = _ask_user_clarification(str(clarify_err), self._run_state)
                    if notes:
                        ctx.add_note(notes)
                    # Trigger re-planning so the planner can fix artifacts_to_generate
                    _info("Re-running planner with clarification notes...")
                    ctx.plan = _run_plan_inline(ctx, out_dir, self._llm, self._run_state)
                    continue  # retry generation with revised plan
                elapsed_gen = time.monotonic() - t_gen
                _push_log(
                    f"Generator: {len(artifacts)} artifact(s) created in {elapsed_gen:.1f}s",
                    self._run_state,
                )
                to_process = list(artifacts)  # first run: process every artifact

            # ── Optimize + review only the pending artifacts (targeted) ──────────
            # On first run: to_process == all artifacts.
            # On revise:    to_process == only the re-generated artifacts.
            # Unchanged artifacts keep their cached review results — no wasted LLM calls.
            n = len(to_process)
            n_opt  = sum(1 for a in to_process if a.artifact_type in _OPTIMIZE_TYPES)
            n_skip = n - n_opt
            _status("OPTIMIZING", self._run_state)
            _push_log(
                f"Starting parallel processing: {n} artifact(s) — "
                f"{n_opt} optimize+review, {n_skip} review-only",
                self._run_state,
            )

            t_opt = time.monotonic()
            with _TPE(max_workers=max(n, 1)) as pool:
                futs = [pool.submit(_opt_rev_art, a) for a in to_process]
            proc_results = [f.result() for f in futs]
            elapsed_opt = time.monotonic() - t_opt
            _push_log(
                f"Optimize+review complete: {n} artifact(s) in {elapsed_opt:.1f}s",
                self._run_state,
            )

            # Update artifact list and review cache with newly processed results only
            proc_map: dict[str, tuple] = {
                target.file_name: (target, revs) for target, revs in proc_results
            }
            for fname, (target, revs) in proc_map.items():
                _review_cache[fname] = revs
            artifacts = [
                proc_map[a.file_name][0] if a.file_name in proc_map else a
                for a in artifacts
            ]

            # Merge all reviews (cache covers all artifacts, new results already updated)
            all_revs = [rv for revs in _review_cache.values() for rv in revs]
            _sample = next(iter(_review_cache.values()), None)
            active_dims = [rv.dimension for rv in _sample] if _sample else list(DIMENSIONS)
            _status("REVIEWING", self._run_state)
            reviews = _rev_merge(all_revs, active_dims)

            quality = _quality_score(reviews)
            _push_log(f"Quality score: {quality:.0f}/100", self._run_state)

            _write_artifacts(out_dir, artifacts, reviews)
            _write_config(out_dir, ctx)
            _run_connection_checks(ctx)

            req_path = Path(__file__).resolve().parent.parent.parent / "requirements.txt"
            _scan_and_update_requirements(artifacts, req_path)

            decision, notes = _checkpoint_code(artifacts, reviews, quality, self._run_state)

            if decision == "approve":
                return artifacts, reviews, quality

            if decision == "revise":
                # ── Check for explicit single-file selection ───────────────────
                # When the user used "file <name>" at the checkpoint, notes is
                # prefixed with [FILE_EXPLICIT:<filename>].  In this case we MUST
                # touch ONLY that file — no cascade, no other artifacts modified.
                explicit_file: str | None = None
                actual_notes = notes
                import re as _re_local
                _explicit_match = _re_local.match(
                    r"^\[FILE_EXPLICIT:([^\]]+)\]\s*(.*)", notes, _re_local.DOTALL
                )
                if _explicit_match:
                    explicit_file = _explicit_match.group(1).strip()
                    actual_notes = _explicit_match.group(2).strip()
                    _push_log(
                        f"Explicit single-file edit requested: {explicit_file!r}",
                        self._run_state,
                    )

                # Targeted: only re-generate and re-process artifacts that failed review.
                # Passing artifacts are untouched — their cached reviews are preserved.
                failed_names = _get_failed_artifact_names(artifacts, reviews)
                if failed_names and not explicit_file:
                    ctx.add_note(
                        f"{notes}\n"
                        f"Fix ONLY these files: {', '.join(sorted(failed_names))}"
                    )
                    _push_log(
                        f"Re-generating {len(failed_names)} artifact(s): {sorted(failed_names)}",
                        self._run_state,
                    )
                    _status("GENERATING", self._run_state)
                    t_rev = time.monotonic()
                    revised = GeneratorAgent(self._llm).generate_for_revision(
                        ctx, failed_names, current_artifacts=artifacts
                    )
                    _push_log(
                        f"Re-generation done: {len(revised)} artifact(s) in {time.monotonic() - t_rev:.1f}s",
                        self._run_state,
                    )
                    revised_map = {a.file_name: a for a in revised}
                    artifacts = [revised_map.get(a.file_name, a) for a in artifacts]
                    # Evict only revised artifacts from cache — passing ones stay cached
                    for name in revised_map:
                        _review_cache.pop(name, None)
                    to_process = list(revised_map.values())  # only re-process revised
                    _write_artifacts(out_dir, to_process, [])
                else:
                    # No CRITICAL failures — targeted changes only, no full restart
                    ctx.add_note(actual_notes)

                    if explicit_file:
                        # ── Explicit single-file selection ─────────────────────
                        # User picked exactly one file via "file <name>".
                        # Honour their choice strictly: only touch that file.
                        # Use the change scope to decide HOW to modify it, but
                        # NEVER cascade to other files in this path.
                        target_names = {explicit_file}
                    else:
                        target_names = _extract_file_names_from_notes(actual_notes, artifacts)
                        if not target_names:
                            target_names = _prompt_file_selection(artifacts, self._run_state)

                    if target_names:
                        # ── Classify change scope ─────────────────────────────
                        # comment_only: reviewer applies annotation — no optimizer/generator
                        # minor:        optimizer patches in-place
                        # major:        generator re-generates (with optional cascade)
                        scope = _classify_change_scope(actual_notes)
                        _push_log(f"Change scope: {scope.upper()}", self._run_state)

                        if scope == "comment_only" and not explicit_file:
                            # ── Comment/annotation-only change — reviewer handles ──
                            # User asked to add/modify comments or annotations only.
                            # No code logic change needed → skip optimizer and generator.
                            # Reviewer applies the annotation and the result goes through
                            # the normal review pass in the next loop iteration.
                            target_arts = [a for a in artifacts if a.file_name in target_names]
                            _push_log(
                                f"Comment-only patch (reviewer): "
                                f"{len(target_arts)} file(s) — {sorted(target_names)}",
                                self._run_state,
                            )
                            _status("REVIEWING", self._run_state)
                            t_rev = time.monotonic()
                            revised = ReviewerAgent(self._llm).annotate(
                                ctx, target_arts, actual_notes
                            )
                            _push_log(
                                f"Annotation done: {len(revised)} artifact(s) "
                                f"in {time.monotonic() - t_rev:.1f}s",
                                self._run_state,
                            )
                            revised_map = {a.file_name: a for a in revised}
                            artifacts = [revised_map.get(a.file_name, a) for a in artifacts]
                            for name in revised_map:
                                _review_cache.pop(name, None)
                            to_process = list(revised_map.values())
                            _write_artifacts(out_dir, to_process, [])

                        elif scope == "minor" or explicit_file:
                            # ── Minor change OR explicit single-file selection ─
                            # Use the optimizer to patch in-place.
                            # For explicit_file: NEVER cascade regardless of scope.
                            target_arts = [a for a in artifacts if a.file_name in target_names]
                            _push_log(
                                f"{'Explicit' if explicit_file else 'Minor'} patch: "
                                f"{len(target_arts)} file(s) — {sorted(target_names)}",
                                self._run_state,
                            )
                            _status("OPTIMIZING", self._run_state)
                            t_rev = time.monotonic()
                            revised = OptimizerAgent(self._llm).optimize(ctx, target_arts)
                            _push_log(
                                f"Patch done: {len(revised)} artifact(s) "
                                f"in {time.monotonic() - t_rev:.1f}s",
                                self._run_state,
                            )
                            revised_map = {a.file_name: a for a in revised}
                            # Only update the patched artifacts; leave ALL others unchanged
                            artifacts = [revised_map.get(a.file_name, a) for a in artifacts]
                            for name in revised_map:
                                _review_cache.pop(name, None)
                            to_process = list(revised_map.values())
                            _write_artifacts(out_dir, to_process, [])

                        else:
                            # ── Major change — cascade to impacted artifacts ──
                            # Only reached for freeform "revise" notes (not explicit
                            # file selection).  Smart cascade: only expand to
                            # artifacts that are genuinely impacted by the change.
                            cascade = _cascade_targets(target_names, actual_notes, artifacts)
                            extra = cascade - target_names
                            if extra:
                                _push_log(
                                    f"Major change detected — cascading to related "
                                    f"artifact(s): {sorted(extra)}",
                                    self._run_state,
                                )
                            else:
                                _push_log(
                                    f"Major revision: {len(cascade)} file(s) — {sorted(cascade)}",
                                    self._run_state,
                                )
                            _status("GENERATING", self._run_state)
                            t_rev = time.monotonic()
                            revised = GeneratorAgent(self._llm).generate_for_revision(
                                ctx, cascade, current_artifacts=artifacts
                            )
                            _push_log(
                                f"Re-generation done: {len(revised)} artifact(s) "
                                f"in {time.monotonic() - t_rev:.1f}s",
                                self._run_state,
                            )
                            revised_map = {a.file_name: a for a in revised}
                            artifacts = [revised_map.get(a.file_name, a) for a in artifacts]
                            _remove_stale_artifacts(out_dir, artifacts)
                            for name in revised_map:
                                _review_cache.pop(name, None)
                            to_process = list(revised_map.values())
                            _write_artifacts(out_dir, to_process, [])
                    else:
                        _info("No files selected — keeping current artifacts.")


# ── Deploy Pipeline ────────────────────────────────────────────────────────────

class DeployPipeline:
    def run(self, request) -> object:
        from agents.deployer.agent import DeployerAgent
        from api.models import DeployStatus

        _banner("DEPLOY POD")
        _info(f"Request ID  : {request.request_id}")
        _info(f"Project     : {request.project_id} / {request.dataset_id}")
        _info(f"Environment : {request.environment}")
        _info(f"Target      : {request.target.value.upper()}")
        _info(f"Artifacts   : {request.artifacts_dir}")
        print()

        output = DeployerAgent().deploy(request)

        _banner("DEPLOY COMPLETE")
        _icons = {
            DeployStatus.SUCCESS: "✓",
            DeployStatus.SKIPPED: "~",
            DeployStatus.FAILED:  "✗",
        }
        for step in output.steps:
            icon = _icons.get(step.status, "?")
            print(f"  {icon} {step.step:<35} {step.status.value:<8}  {step.message}")
        print()
        overall_icon = _icons.get(output.overall_status, "?")
        print(f"  {overall_icon} Overall: {output.overall_status.value.upper()}")
        return output


# ── Blocker priority sorter ────────────────────────────────────────────────────

_BLOCKER_PRIORITY_RULES: list[tuple[list[str], int]] = [
    (["source system", "oracle", "mysql", "true source", "jdbc driver",
      "source: oracle", "source: mysql", "source database"], 1),
    (["load pattern", "full load", "incremental", "cdc", "change data",
      "full table extract", "watermark"], 2),
    (["scd type", "scd 1", "scd 2", "type 1", "type 2", "history",
      "overwrite", "historical version"], 3),
    (["core table", "downstream", "dim_", "presentation layer",
      "delivery scope", "staging only", "also a core"], 4),
    (["secret", "credential", "secret manager", "airflow connection",
      "vault", "connection string"], 5),
]


def _blocker_priority(question: str) -> int:
    q = question.lower()
    for keywords, priority in _BLOCKER_PRIORITY_RULES:
        if any(kw in q for kw in keywords):
            return priority
    return 99


# ── Human Checkpoints ──────────────────────────────────────────────────────────

def _checkpoint_plan(plan, plan_file: Path | None = None, run_state=None) -> tuple[str, str]:
    """CHECKPOINT 1 — show plan, collect human decision."""
    blocker_qs = sorted(
        [q for q in plan.clarifying_questions if "[BLOCKER]" in q.upper()],
        key=_blocker_priority,
    )
    important_qs = [q for q in plan.clarifying_questions if "[IMPORTANT]" in q.upper()]
    nice_qs = [q for q in plan.clarifying_questions if "[NICE-TO-HAVE]" in q.upper()]
    has_hard_block = bool(blocker_qs)

    plan_file_note = (
        f"\nPlan saved to: {plan_file}\n"
        "Open the file to review it. Add missing information via 'revise'.\n"
        if plan_file else ""
    )
    lines = [f"CHECKPOINT 1 — PLAN REVIEW{plan_file_note}\n"]
    if blocker_qs:
        lines.append(f"⛔  BLOCKER QUESTIONS ({len(blocker_qs)}) — must be answered before approval:")
        for i, q in enumerate(blocker_qs, start=1):
            lines.append(f"   B{i}. {q}")
        lines.append("")
    if important_qs:
        lines.append(f"ℹ   PROCEEDING WITH ASSUMPTIONS ({len(important_qs)}) — answer via 'revise' to override:")
        for q in important_qs:
            lines.append(f"   {q}")
        lines.append("")
    if plan.open_blockers:
        lines.append(f"⚠   OPEN BLOCKERS ({len(plan.open_blockers)}) — deployment/governance gates (code generation proceeds):")
        for b in plan.open_blockers:
            lines.append(f"   ! {b}")
        lines.append("")
    lines.append("── Plan ──")
    lines.append(plan.raw_plan)
    lines.append("")
    lines.append(
        f"Tables: {len(plan.tables)} | Artifacts: {len(plan.artifacts_to_generate)} "
        f"| PII columns: {len(plan.pii_columns)}"
    )
    if nice_qs:
        lines.append(f"ℹ   {len(nice_qs)} nice-to-have question(s) — type 'revise' to address them.")
    if has_hard_block:
        lines.append("\nApproval is BLOCKED. Answer all BLOCKER questions via 'revise'.")
        lines.append("Options: revise (provide answers) | abort")
    else:
        lines.append("\nOptions: approve | revise (with notes) | abort")
    prompt = "\n".join(lines)

    if run_state is not None:
        decision = run_state.pause_at_checkpoint(number=1, prompt=prompt)
        if decision.decision.value == "abort":
            run_state.status = RunStatus.ABORTED
            raise SystemExit("Pipeline aborted via API")
        if decision.decision.value == "approve" and has_hard_block:
            return "revise", (
                "Approval attempted with blockers outstanding. "
                "Please answer all BLOCKER questions first."
            )
        return decision.decision.value, decision.notes

    # CLI mode
    print()
    _sep()
    print("  CHECKPOINT 1 — PLAN REVIEW")
    _sep()
    print()
    _info(f"Artifacts  : {len(plan.artifacts_to_generate)} files planned")
    _info(f"Tables     : {len(plan.tables)} target table(s)")
    _info(f"Assumptions: {len(important_qs) + len(nice_qs)} applied — type 'details' to view all")
    if plan.open_blockers:
        _info(f"Open gates : {len(plan.open_blockers)} deployment blocker(s) — not code blockers")
    if plan_file is not None:
        _info(f"Plan saved : {plan_file}")
        _info("           Open the file, review it, and optionally add notes via 'revise'.")
    _sep()
    print()

    if blocker_qs:
        print(f"  ⛔  QUESTIONS REQUIRING YOUR ANSWER ({len(blocker_qs)}):")
        print()
        for i, q in enumerate(blocker_qs, start=1):
            lines = q.split("\n")
            print(f"       B{i}. {lines[0].strip()}")
            for extra in lines[1:]:
                if extra.strip():
                    print(f"           {extra.strip()}")
        print()

    if plan.open_blockers:
        print(f"  ⚠   DEPLOYMENT GATES — code generation proceeds; resolve before deploying:")
        for b in plan.open_blockers:
            print(f"       • {b.strip('*').strip()}")
        print()

    if nice_qs:
        _info(f"Nice-to-have: {len(nice_qs)} low-priority item(s) — type 'details' to review")

    if has_hard_block:
        print("  ⛔  Approval BLOCKED — answer questions above before proceeding.")
        print()
        print("  Options:  revise | details | abort")
        print()
        while True:
            raw = _input("Choose").lower().strip()
            if raw == "abort":
                print("\n  Pipeline aborted.")
                sys.exit(0)
            if raw == "details":
                print()
                print(plan.raw_plan)
                print()
                continue
            if raw == "revise":
                print()
                print("  Answer each question by number, e.g.:")
                print("    B1: MySQL   B2: Full load   B3: Dev only")
                print()
                notes = _input("Your answers").strip()
                if not notes:
                    print("  No answers provided — please answer the questions above.")
                    continue
                print(f"\n  Saved: \"{notes}\"")
                return "revise", notes
            print(f"  Unknown option '{raw}'. Type revise, details, or abort.")
    else:
        print("  Options:  approve | revise | details | abort")
        print()
        while True:
            raw = _input("Choose").lower().strip()
            if raw == "approve":
                return "approve", ""
            if raw == "abort":
                print("\n  Pipeline aborted.")
                sys.exit(0)
            if raw == "details":
                print()
                print(plan.raw_plan)
                print()
                continue
            if raw == "revise":
                print()
                notes = _input("Your corrections or additional details").strip()
                if not notes:
                    print("  No notes provided — please type your input first.")
                    continue
                print(f"\n  Saved: \"{notes}\"")
                return "revise", notes
            print(f"  Unknown option '{raw}'. Type approve, revise, details, or abort.")


def _checkpoint_code(
    artifacts: list[GeneratedArtifact],
    reviews: list[ReviewResult],
    quality: float,
    run_state=None,
) -> tuple[str, str]:
    """CHECKPOINT 2 — show generated code summary + review results."""
    critical_findings = [
        f for r in reviews
        for f in r.findings if f.severity.value == "CRITICAL"
    ]
    failed_dimensions = [r for r in reviews if r.verdict.value == "FAIL"]
    has_hard_block = bool(critical_findings or failed_dimensions)

    artifact_lines = "\n".join(
        f"  [{a.artifact_type.value.upper():8}]  {a.file_name}" for a in artifacts
    )
    review_lines = "\n".join(
        f"  {r.dimension.upper()}: {r.verdict.value} ({len(r.findings)} finding(s))"
        for r in reviews
    )
    block_note = ""
    if critical_findings:
        block_note = (
            f"\n⛔ APPROVAL BLOCKED: {len(critical_findings)} CRITICAL finding(s) found. "
            "Fix all CRITICAL issues before approval."
        )
    elif failed_dimensions:
        block_note = (
            f"\n⛔ APPROVAL BLOCKED: {len(failed_dimensions)} dimension(s) have FAIL verdict. "
            "Revise the code to fix all CRITICAL findings."
        )

    prompt = (
        f"CHECKPOINT 2 — GENERATED CODE REVIEW\n\n"
        f"Artifacts ({len(artifacts)}):\n{artifact_lines}\n\n"
        f"Quality Score: {quality:.0f}/100\n\n"
        f"Review Results:\n{review_lines}"
        f"{block_note}\n\n"
        + ("Options: revise (address findings) | abort"
           if has_hard_block else
           "Options: approve | revise (with notes) | abort")
    )

    if run_state is not None:
        decision = run_state.pause_at_checkpoint(number=2, prompt=prompt)
        if decision.decision.value == "abort":
            run_state.status = RunStatus.ABORTED
            raise SystemExit("Pipeline aborted via API")
        if decision.decision.value == "approve" and has_hard_block:
            return "revise", (
                "Approval attempted while CRITICAL findings are outstanding. "
                "Fix all ASSUMPTION markers and FAIL verdicts first."
            )
        return decision.decision.value, decision.notes

    # CLI mode
    _icons = {Verdict.PASS: "✓", Verdict.CONDITIONAL_PASS: "⚠", Verdict.FAIL: "✗"}
    all_criticals = [
        (r.dimension, f) for r in reviews
        for f in r.findings if f.severity.value == "CRITICAL"
    ]

    print()
    _sep()
    print("  CHECKPOINT 2 — CODE REVIEW")
    _sep()
    print()
    print(f"  Generated {len(artifacts)} artifact(s):")
    for a in artifacts:
        print(f"    {a.file_name}")
    print()
    threshold = "HEALTHY" if quality >= 70 else ("REVIEW" if quality >= 50 else "FIX REQUIRED")
    print(f"  Quality Score : {quality:.0f} / 100  [{threshold}]  (dev threshold: 70 healthy / 50 review)")
    print()
    print("  Review:")
    for r in reviews:
        icon = _icons.get(r.verdict, "?")
        criticals = sum(1 for f in r.findings if f.severity.value == "CRITICAL")
        warnings  = sum(1 for f in r.findings if f.severity.value == "WARNING")
        infos     = sum(1 for f in r.findings if f.severity.value == "INFO")
        counts = f"{criticals}C / {warnings}W / {infos}I" if r.findings else "clean"
        print(f"    {icon} {r.dimension.upper():<20} {r.verdict.value:<18} ({counts})")
    print()

    if all_criticals:
        print(f"  ⛔  {len(all_criticals)} CRITICAL finding(s) — must fix before approving:")
        print()
        for dim, f in all_criticals:
            print(f"       [{dim.upper()}] {f.check_name}")
            print(f"         → {f.description}")
            print()

    non_critical_count = sum(
        1 for r in reviews for f in r.findings if f.severity.value != "CRITICAL"
    )
    if non_critical_count:
        _info(f"{non_critical_count} warning/info finding(s) — type 'details' to view")

    _sep()
    print()

    if has_hard_block:
        print("  ⛔  Approval BLOCKED — fix CRITICAL findings above.")
        print()
        print("  Options:  revise | details | abort")
        print()
        while True:
            raw = _input("Choose").lower().strip()
            if raw == "abort":
                print("\n  Pipeline aborted.")
                sys.exit(0)
            if raw == "details":
                print()
                for r in reviews:
                    print(f"  ── {r.dimension.upper()} ({r.verdict.value}) ──")
                    for f in r.findings:
                        print(f"    [{f.severity.value}] {f.check_name} — {f.file_name}")
                        print(f"      {f.description}")
                        if f.suggested_fix:
                            print(f"      Fix: {f.suggested_fix}")
                    print()
                continue
            if raw == "revise":
                print()
                notes = _input("Your corrections").strip()
                if not notes:
                    print("  No corrections provided — describe what needs fixing.")
                    continue
                print(f"\n  Saved: \"{notes}\"")
                return "revise", notes
            print(f"  Unknown option '{raw}'. Type revise, details, or abort.")
    else:
        _file_map = {a.file_name.lower(): a.file_name for a in artifacts}
        print("  Options:  approve | revise | file <name> | details | abort")
        print()
        while True:
            raw = _input("Choose").lower().strip()
            if raw == "approve":
                return "approve", ""
            if raw == "abort":
                print("\n  Pipeline aborted.")
                sys.exit(0)
            if raw == "details":
                print()
                for r in reviews:
                    print(f"  ── {r.dimension.upper()} ({r.verdict.value}) ──")
                    for f in r.findings:
                        print(f"    [{f.severity.value}] {f.check_name} — {f.file_name}")
                        print(f"      {f.description}")
                        if f.suggested_fix:
                            print(f"      Fix: {f.suggested_fix}")
                    print()
                continue
            if raw == "revise":
                print()
                print("  Tip: mention specific file names in your notes for targeted revision.")
                print("       To add/update comments only → say 'add comment ...' (reviewer handles, no regeneration)")
                print("       For style/format fixes        → say 'fix formatting ...' (optimizer patches in-place)")
                print("       For code/schema changes       → say 'add column ...' (generator re-generates)")
                print(f"  Files: {', '.join(a.file_name for a in artifacts)}")
                print()
                notes = _input("Your corrections or additional details").strip()
                if not notes:
                    print("  No corrections provided.")
                    continue
                print(f"\n  Saved: \"{notes}\"")
                return "revise", notes
            if raw.startswith("file"):
                fname_input = raw[4:].strip()
                if not fname_input:
                    # Show list and ask
                    print()
                    print("  Generated files:")
                    for i, a in enumerate(artifacts, 1):
                        print(f"    {i}. {a.file_name}")
                    print()
                    fname_input = _input("File name (or number)").strip().lower()
                # Support selection by number
                if fname_input.isdigit():
                    idx = int(fname_input) - 1
                    if 0 <= idx < len(artifacts):
                        matched = artifacts[idx].file_name
                    else:
                        print(f"  Number out of range (1–{len(artifacts)}).")
                        continue
                else:
                    matched = _file_map.get(fname_input)
                    if not matched:
                        # Partial match
                        candidates = [v for k, v in _file_map.items() if fname_input in k]
                        if len(candidates) == 1:
                            matched = candidates[0]
                        elif len(candidates) > 1:
                            print(f"  Ambiguous — matches: {', '.join(candidates)}. Be more specific.")
                            continue
                        else:
                            print(f"  Unknown file. Available: {', '.join(a.file_name for a in artifacts)}")
                            continue
                print()
                change_req = _input(f"What change do you want in {matched}").strip()
                if not change_req:
                    print("  No change specified.")
                    continue
                # [FILE_EXPLICIT] marker tells the revision loop to touch ONLY this
                # file — no cascade to related artifacts regardless of change scope.
                note = f"[FILE_EXPLICIT:{matched}] {change_req}"
                print(f"\n  Saved: change {matched!r}: \"{change_req}\"")
                return "revise", note
            print(f"  Unknown option '{raw}'. Type approve, file <name>, revise, details, or abort.")


def _checkpoint_git_push(
    git,
    branch_name: str,
    run_state=None,
) -> bool:
    """
    CHECKPOINT 3 — ask the user whether to push the committed feature branch
    to the remote. Returns True if the user chose to push, False otherwise.

    git        : GitRepoManager instance (already connected, branch committed)
    branch_name: the feature branch name, e.g. feature/SCRUM-75_20260415_v1
    run_state  : API run state; if provided, pause_at_checkpoint is used
    """
    prompt = (
        f"CHECKPOINT 3 — PUSH TO GIT\n\n"
        f"Artifacts committed locally to branch: {branch_name}\n\n"
        f"Push to remote? [yes / no]"
    )

    if run_state is not None:
        decision = run_state.pause_at_checkpoint(number=3, prompt=prompt)
        if decision.decision.value in ("approve", "deploy"):
            git.push()
            _info(f"Git: pushed to origin/{branch_name}")
            return True
        _info(f"Git: branch committed locally. Push manually with: git push origin {branch_name}")
        return False

    # CLI mode
    print()
    _sep()
    print("  CHECKPOINT 3 — PUSH TO GIT")
    _sep()
    print()
    _info(f"Branch  : {branch_name}")
    _info("Artifacts committed locally.")
    print()

    while True:
        raw = _input("Push to remote? [yes / no]").lower().strip()
        if raw in ("yes", "y"):
            git.push()
            _info(f"Git: pushed to origin/{branch_name}")
            return True
        if raw in ("no", "n"):
            _info(f"Git: branch committed locally.")
            _info(f"Run to publish: git push origin {branch_name}")
            return False
        print(f"  Type yes or no.")


def _checkpoint_git_push_prompt(
    out_dir: Path,
    request_id: str,
    git_repo_url: str | None,
    git_pat: str | None,
    git_local_path: str | None,
    run_state=None,
) -> str | None:
    """
    CHECKPOINT 3 (no-git-URL path) — prompt the user to push generated artifacts
    to a new git feature branch after code generation completes.

    Branch name format: feature/{request_id}_{YYYYMMDD}_v1
    Returns the branch name if push succeeds, None otherwise.
    """
    import os as _os
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    proposed_branch = f"feature/{request_id}_{date_str}_v1"

    prompt = (
        f"CHECKPOINT 3 — PUSH TO GIT\n\n"
        f"Artifacts saved in: {out_dir}\n"
        f"Proposed branch   : {proposed_branch}\n\n"
        f"Push generated files to a new git branch? [yes / no]"
    )

    if run_state is not None:
        decision = run_state.pause_at_checkpoint(number=3, prompt=prompt)
        if decision.decision.value not in ("approve", "deploy"):
            _info(f"Git push skipped. Artifacts in: {out_dir}")
            return None
        repo_url = git_repo_url or _os.environ.get("GIT_REPO_URL", "")
        pat = git_pat or _os.environ.get("GIT_PAT", "")
        if not repo_url or not pat:
            _info("Git push skipped — GIT_REPO_URL or GIT_PAT not configured.")
            return None
        return _do_git_push(out_dir, request_id, repo_url, pat, git_local_path)

    # CLI mode
    print()
    _sep()
    print("  CHECKPOINT 3 — PUSH TO GIT BRANCH")
    _sep()
    print()
    _info(f"Artifacts saved to : {out_dir}")
    _info(f"Proposed branch    : {proposed_branch}")
    print()

    while True:
        raw = _input("Push to git branch? [yes / no]").lower().strip()
        if raw in ("no", "n"):
            _info("Git push skipped.")
            _info(f"Files are in: {out_dir}")
            return None
        if raw in ("yes", "y"):
            break
        print("  Type yes or no.")

    # Collect git repo URL (env → interactive)
    repo_url = git_repo_url or _os.environ.get("GIT_REPO_URL", "")
    if not repo_url:
        print()
        _info("Git repository URL required. Example: https://github.com/org/repo")
        repo_url = _input("Git repo URL").strip()
        if not repo_url:
            _info("No URL provided — git push skipped.")
            return None

    # Collect PAT (env → interactive, masked)
    pat = git_pat or _os.environ.get("GIT_PAT", "")
    if not pat:
        import getpass as _getpass
        print()
        _info("Personal Access Token (PAT) required. Input will not be echoed.")
        pat = _getpass.getpass("  PAT: ").strip()
        if not pat:
            _info("No PAT provided — git push skipped.")
            return None

    return _do_git_push(out_dir, request_id, repo_url, pat, git_local_path)


def _do_git_push(
    out_dir: Path,
    request_id: str,
    repo_url: str,
    pat: str,
    git_local_path: str | None,
) -> str | None:
    """Copy artifacts into a git workspace, commit to a versioned feature branch, push."""
    import shutil as _shutil
    try:
        from core.utilities.versioning_tools import GitRepoManager
        branch_name = _resolve_branch_name(request_id, repo_url, pat, None)
        branch_url = f"{repo_url.rstrip('/')}/tree/{branch_name}"
        local_path = git_local_path or str(out_dir.parent / "git_workspace")

        git = GitRepoManager(branch_url=branch_url, pat=pat, local_path=local_path)
        git.connect()
        git.pull()

        dest = Path(local_path) / "pipelines" / request_id
        if dest.exists():
            _shutil.rmtree(dest)
        _shutil.copytree(out_dir, dest)
        _info(f"Artifacts staged in: {dest}")

        commit_msg = f"feat({request_id}): generate pipeline artifacts"
        git.commit(commit_msg)
        git.push()
        _info(f"Git: pushed to origin/{branch_name}")
        return branch_name
    except Exception as exc:
        logger.warning("Git push failed — %s", exc)
        _info(f"Git push failed: {exc}")
        return None


def _checkpoint_optimize_review(
    artifacts: list[GeneratedArtifact],
    reviews: list[ReviewResult],
    quality: float,
    run_state=None,
) -> None:
    """Single checkpoint for optimize-review mode (Mode 2).

    Gate logic:
    - CRITICAL logic_preservation findings  → hard block, only 'abort' allowed
    - CRITICAL findings in other dimensions  → soft block, user must acknowledge
    - No CRITICAL findings                   → approve | abort
    """
    _icons = {"PASS": "✓", "CONDITIONAL_PASS": "⚠", "FAIL": "✗"}

    lp = next((r for r in reviews if r.dimension == "logic_preservation"), None)
    lp_criticals = [f for f in (lp.findings if lp else []) if f.severity.value == "CRITICAL"]
    has_logic_block = bool(lp_criticals)

    other_criticals = [
        f
        for r in reviews if r.dimension != "logic_preservation"
        for f in r.findings if f.severity.value == "CRITICAL"
    ]

    # ── Build review table for API prompt ─────────────────────────────────────
    review_lines = "\n".join(
        f"  {_icons.get(r.verdict.value, '?')}  {r.dimension.upper():<22}"
        f"  {r.verdict.value:<18}  {len(r.findings)} finding(s)"
        for r in reviews
    )
    artifact_lines = "\n".join(
        f"  [{a.artifact_type.value.upper():8}]  {a.file_name}" for a in artifacts
    )
    lp_detail = ""
    if lp_criticals:
        lp_detail = "\n⛔ LOGIC CHANGES:\n" + "\n".join(
            f"  [{f.severity.value}] {f.check_name}: {f.description}"
            for f in lp_criticals
        )
    other_detail = ""
    if other_criticals:
        other_detail = "\n⚠ OTHER CRITICAL FINDINGS:\n" + "\n".join(
            f"  [{f.severity.value}] {f.check_name} ({f.file_name}): {f.description}"
            for f in other_criticals
        )

    prompt = (
        f"OPTIMIZE + REVIEW CHECKPOINT\n\n"
        f"Artifacts ({len(artifacts)}):\n{artifact_lines}\n\n"
        f"Quality Score: {quality:.0f}/100\n\n"
        f"Review dimensions:\n{review_lines}"
        f"{lp_detail}{other_detail}\n\n"
        + ("⛔ BLOCKED — CRITICAL logic changes detected. Options: abort"
           if has_logic_block else
           "Options: approve | abort")
    )

    if run_state is not None:
        decision = run_state.pause_at_checkpoint(number=4, prompt=prompt)
        if decision.decision.value == "abort" or has_logic_block:
            run_state.status = RunStatus.ABORTED
            if has_logic_block:
                raise SystemExit("Optimize aborted — CRITICAL logic changes detected")
        return

    # ── CLI mode ───────────────────────────────────────────────────────────────
    print()
    _sep()
    print("  OPTIMIZE + REVIEW CHECKPOINT")
    _sep()
    print()
    print(f"  {len(artifacts)} optimized artifact(s):")
    for a in artifacts:
        print(f"    [{a.artifact_type.value.upper():8}]  {a.file_name}")
    print()
    print(f"  Quality Score : {quality:.0f} / 100")
    print()

    # Show all review dimensions
    print("  Review dimensions:")
    for r in reviews:
        icon = _icons.get(r.verdict.value, "?")
        criticals = sum(1 for f in r.findings if f.severity.value == "CRITICAL")
        warnings  = sum(1 for f in r.findings if f.severity.value == "WARNING")
        detail = f"  ({criticals} critical, {warnings} warning)" if r.findings else ""
        print(f"    {icon}  {r.dimension.upper():<22}  {r.verdict.value}{detail}")
    print()

    # Show logic_preservation CRITICAL findings in detail
    if lp_criticals:
        print(f"  ⛔  {len(lp_criticals)} CRITICAL logic change(s) detected:")
        for f in lp_criticals:
            print(f"       [{f.severity.value}] {f.check_name}: {f.description}")
        print()

    # Show other CRITICAL findings in detail
    if other_criticals:
        print(f"  ⚠   {len(other_criticals)} other CRITICAL finding(s) (not logic changes):")
        for f in other_criticals:
            print(f"       [{f.severity.value}] {f.check_name} ({f.file_name}): {f.description}")
        print()

    _sep()
    print()

    if has_logic_block:
        print("  ⛔  CRITICAL logic changes detected — optimized files MUST NOT be used.")
        print("  The optimizer changed business logic. Fix the original files manually")
        print("  and re-run --optimize, or use the original files without optimization.")
        print()
        print("  Options: abort")
        print()
        _input("Press Enter to abort")
        sys.exit(1)
    else:
        if other_criticals:
            print("  ⚠   Other CRITICAL findings exist (correctness / security / performance).")
            print("  Logic is preserved but other issues require attention before production.")
            print()
        print("  Options: approve | abort")
        print()
        while True:
            raw = _input("Choose").lower().strip()
            if raw == "approve":
                return
            if raw == "abort":
                print("\n  Optimize aborted.")
                sys.exit(0)
            print(f"  Unknown option '{raw}'. Type approve or abort.")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _status(stage: str, run_state=None) -> None:
    """Update run_state status and print a stage banner."""
    _stage(stage)
    if run_state is None:
        return
    mapping = {
        "GENERATING": RunStatus.GENERATING,
        "OPTIMIZING": RunStatus.OPTIMIZING,
        "REVIEWING":  RunStatus.REVIEWING,
        "COMMITTING": RunStatus.COMMITTING,
    }
    new_status = mapping.get(stage.upper())
    if new_status is not None:
        run_state.status = new_status


def _push_log(msg: str, run_state=None) -> None:
    """Print msg and push to run_state.log_messages if available."""
    _info(msg)
    if run_state is not None and hasattr(run_state, "push_log"):
        run_state.push_log(msg)


def _write_config(out_dir: Path, ctx: SessionContext) -> None:
    """Generate pipeline_config.py in out_dir/config/.

    Connection details (db_host, db_name, gcs_bucket, etc.) are extracted from
    ctx.plan.connection_details and written directly into the file so that
    FILL_IN placeholders are minimised.
    """
    try:
        pipeline_name = (
            ctx.implementation_md.splitlines()[0].replace("#", "").strip()[:40]
            if ctx.implementation_md else ctx.request_id[:20]
        )
        connection_details = ctx.plan.connection_details if ctx.plan else []
        services = ctx.plan.services if ctx.plan else []
        written = generate_pipeline_config(
            out_dir=out_dir,
            project_id=ctx.project_id,
            dataset_id=ctx.dataset_id,
            environment=ctx.environment,
            pipeline_name=pipeline_name,
            connection_details=connection_details,
            services=services,
        )
        _info(f"Config         : {out_dir / 'config'}/")
        for fname in written:
            _info(f"  → {fname}")
        remaining = _count_fill_in(out_dir / "config" / "pipeline_config.py")
        if remaining:
            _info(f"  {remaining} FILL_IN placeholder(s) remain — update before deploying.")
        else:
            _info("  All connection values populated from plan.")
    except Exception as exc:
        logger.warning("Config generation skipped — %s", exc)


def _count_fill_in(config_path: Path) -> int:
    """Return the number of FILL_IN tokens left in pipeline_config.py."""
    if not config_path.exists():
        return 0
    return config_path.read_text(encoding="utf-8").count("FILL_IN")


def _run_connection_checks(ctx: SessionContext) -> None:
    """
    Run connection checks for every entry in plan.connection_details.

    - Tests TCP reachability for DB connections.
    - Tests package importability for GCS / BigQuery / Pub/Sub.
    - Reports missing env vars referenced in connection specs.
    - Appends missing packages to requirements.txt.
    - Adds missing packages to the open_blockers list in the plan.
    """
    if not ctx.plan or not ctx.plan.connection_details:
        return

    req_path = Path(__file__).resolve().parent.parent.parent / "requirements.txt"
    results = check_connections(ctx.plan.connection_details, requirements_path=req_path)
    print_connection_report(results)

    # Collect issues to surface as open blockers
    new_blockers: list[str] = []
    for r in results:
        for pkg in r.missing_packages:
            blocker = f"[CONNECTION] Missing package for {r.service}: install {pkg}"
            if blocker not in ctx.plan.open_blockers:
                ctx.plan.open_blockers.append(blocker)
                new_blockers.append(blocker)
        for var in r.missing_env_vars:
            blocker = f"[CONNECTION] Env var not set for {r.service}: {var} is missing/not set"
            if blocker not in ctx.plan.open_blockers:
                ctx.plan.open_blockers.append(blocker)
                new_blockers.append(blocker)

    if new_blockers:
        _info("Connection issues added to open blockers:")
        for b in new_blockers:
            _info(f"  • {b}")


def _write_plan(out_dir: Path, plan) -> Path:
    """Write plan to out_dir/plan.json (JSON) and return the path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_file = out_dir / "plan.json"
    plan_file.write_text(plan.raw_plan, encoding="utf-8")
    return plan_file


def _run_qa_loop(questions: list[str]) -> str:
    """Present questions to user one at a time; return Q&A formatted as notes string."""
    if not questions:
        return ""
    print()
    _sep()
    print("  PRE-PLAN QUESTIONS")
    _sep()
    print(f"\n  The planner has {len(questions)} question(s) before generating the plan.\n")

    qa_pairs: list[str] = []
    for i, q in enumerate(questions, start=1):
        print(f"  Q{i}: {q.lstrip('-* ')}")
        print()
        answer = _input(f"A{i} (Enter to skip)").strip()
        if answer:
            qa_pairs.append(f"Q{i}: {q.lstrip('-* ')}\nA{i}: {answer}")
        else:
            qa_pairs.append(f"Q{i}: {q.lstrip('-* ')}\nA{i}: [No answer — record as open blocker]")
        print()
    return "\n\n".join(qa_pairs)


def _ask_user_clarification(message: str, run_state=None) -> str:
    """Surface a generator blocker to the user and collect their answer.

    CLI mode: prints the message and prompts for typed input.
    API mode: pauses at a lightweight checkpoint (number=5) so the caller
    can supply the answer via the normal checkpoint response mechanism.
    Returns the user's answer as a string (empty string if no answer given).
    """
    if run_state is not None:
        prompt = (
            "GENERATOR — CLARIFICATION NEEDED\n\n"
            f"{message}\n\n"
            "Please provide the missing information in the 'notes' field. "
            "The planner will be re-run with your answer so code generation can continue."
        )
        decision = run_state.pause_at_checkpoint(number=5, prompt=prompt)
        if decision.decision.value == "abort":
            run_state.status = RunStatus.ABORTED
            raise SystemExit("Pipeline aborted via API")
        return decision.notes or ""

    # CLI mode
    print()
    _sep()
    print("  GENERATOR — CLARIFICATION NEEDED")
    _sep()
    print()
    for line in message.splitlines():
        print(f"  {line}")
    print()
    print("  The planner will be re-run with your answer.")
    print("  Press Enter without typing to abort.")
    print()
    answer = _input("Your answer").strip()
    if not answer:
        print("\n  No answer provided — pipeline aborted.")
        sys.exit(0)
    print(f"\n  Saved: \"{answer}\"")
    return answer


def _run_plan_inline(ctx: SessionContext, out_dir: Path, llm, run_state=None):
    """Re-run the planner in-place and return the new plan.

    Used when the generator raises GeneratorClarificationNeeded — the planner
    is called again with any new human notes already in ctx so it can revise
    artifacts_to_generate before generation is retried.
    """
    _stage("RE-PLANNING (generator clarification received)")
    if run_state is not None:
        run_state.status = RunStatus.PLANNING
    plan = PlannerAgent(llm).plan(ctx)
    plan_file = _write_plan(out_dir, plan)
    _info(f"Revised plan: {len(plan.artifacts_to_generate)} artifact(s) — {plan_file}")
    return plan


def _resolve_branch_name(
    ticket_id: str,
    git_repo_url: str,
    git_pat: str,
    run_state=None,
) -> str:
    """
    Return the feature branch name to use: feature/{ticket}_{YYYYMMDD}_v{N}.

    Remote branch discovery is done via the ``_run`` / ``_inject_pat`` helpers
    from git_manager.py so that all git calls stay inside that module.

    If a versioned branch already exists the user is prompted:
      - CLI  : printed prompt, input collected interactively
      - API  : paused at checkpoint 0 so the caller can submit a decision
    """
    from core.utilities.versioning_tools.git_manager import (  # noqa: PLC0415
        _run as _git_run,
        _inject_pat,
    )
    import re as _re

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    base = f"feature/{ticket_id}_{date_str}"

    existing_versions: list[int] = []
    try:
        authed_url = _inject_pat(git_repo_url, git_pat) if git_pat else git_repo_url
        result = _git_run(["git", "ls-remote", "--heads", authed_url], check=False)
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                ref = parts[1].replace("refs/heads/", "").strip()
                m = _re.search(rf"^{_re.escape(base)}_v(\d+)$", ref)
                if m:
                    existing_versions.append(int(m.group(1)))
    except Exception as exc:
        logger.warning("Could not check remote branches for versioning — using v1: %s", exc)

    if not existing_versions:
        return f"{base}_v1"

    latest_v = max(existing_versions)
    existing_branch = f"{base}_v{latest_v}"
    new_branch = f"{base}_v{latest_v + 1}"
    return _prompt_branch_selection(existing_branch, new_branch, run_state)


def _prompt_branch_selection(
    existing_branch: str,
    new_branch: str,
    run_state=None,
) -> str:
    """
    Ask the user whether to push to an already-existing branch or create a new one.

    CLI  mode: interactive prompt printed to stdout.
    API  mode: pauses at checkpoint 0 so the caller submits a decision via the
               normal checkpoint response mechanism.
               • approve / deploy  → new branch
               • skip              → existing branch

    Returns the chosen branch name.
    """
    prompt = (
        f"GIT BRANCH CONFLICT\n\n"
        f"Branch '{existing_branch}' already exists on the remote.\n\n"
        f"Options:\n"
        f"  new      — create a new branch : {new_branch}\n"
        f"  existing — push to existing    : {existing_branch}\n"
    )

    if run_state is not None:
        decision = run_state.pause_at_checkpoint(number=0, prompt=prompt)
        if decision.decision.value in ("approve", "deploy"):
            _info(f"Git: new branch selected — {new_branch}")
            return new_branch
        _info(f"Git: existing branch selected — {existing_branch}")
        return existing_branch

    # CLI mode
    print()
    _sep()
    print("  GIT BRANCH SELECTION")
    _sep()
    print()
    _info(f"Branch '{existing_branch}' already exists on the remote.")
    print()
    _info(f"  new      → create new branch : {new_branch}")
    _info(f"  existing → push to existing  : {existing_branch}")
    print()
    while True:
        raw = _input("Choose [new / existing]").lower().strip()
        if raw in ("new", "n"):
            _info(f"Git: creating new branch — {new_branch}")
            return new_branch
        if raw in ("existing", "e"):
            _info(f"Git: using existing branch — {existing_branch}")
            return existing_branch
        print("  Type 'new' or 'existing'.")


def _run_ruff(
    artifacts: list[GeneratedArtifact],
    out_dir: Path,
) -> list[GeneratedArtifact]:
    """Run ruff format + ruff check --fix on every Python artifact.

    Writes each Python artifact to a temp file, runs ruff on it,
    reads the formatted result back, and returns the updated artifact list.
    Silently skips if ruff is not installed.
    """
    import shutil
    import subprocess
    import tempfile

    ruff = shutil.which("ruff")
    if ruff is None:
        logger.warning("ruff not found — skipping linting. Run: pip install ruff")
        return artifacts

    updated: list[GeneratedArtifact] = []
    for artifact in artifacts:
        if not artifact.file_name.endswith(".py"):
            updated.append(artifact)
            continue

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(artifact.content)
            tmp_path = tmp.name

        try:
            # Format first, then fix lint issues
            subprocess.run(
                [ruff, "format", "--quiet", tmp_path],
                capture_output=True, text=True,
            )
            subprocess.run(
                [ruff, "check", "--fix", "--quiet", tmp_path],
                capture_output=True, text=True,
            )
            formatted = Path(tmp_path).read_text(encoding="utf-8")
            updated.append(artifact.model_copy(update={"content": formatted}))
            logger.info("Ruff: formatted %s", artifact.file_name)
        except Exception as exc:
            logger.warning("Ruff failed on %s — %s", artifact.file_name, exc)
            updated.append(artifact)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    return updated


def _quality_score(reviews: list[ReviewResult]) -> float:
    """Verdict-based score — stable regardless of artifact count.

    Each of the 4 review dimensions contributes 25 points:
      PASS             →  25 pts  (no penalty)
      CONDITIONAL_PASS →  15 pts  (−10 penalty: warnings present, nothing critical)
      FAIL             →   0 pts  (−25 penalty: at least one CRITICAL finding)

    Max = 100 (all dimensions PASS).

    Thresholds:
      90–100: Clean — all clear
      70–89:  Minor warnings — safe to proceed
      50–69:  Significant warnings — human review recommended
      < 50:   Critical issues — fix before approving
    """
    if not reviews:
        return 100.0

    _PENALTY: dict[Verdict, float] = {
        Verdict.PASS:             0.0,
        Verdict.CONDITIONAL_PASS: 10.0,
        Verdict.FAIL:             25.0,
    }

    # One merged result per dimension; take worst verdict if somehow called
    # with per-artifact results before merging.
    dim_verdicts: dict[str, Verdict] = {}
    for r in reviews:
        prev = dim_verdicts.get(r.dimension)
        if (prev is None
                or r.verdict == Verdict.FAIL
                or (r.verdict == Verdict.CONDITIONAL_PASS and prev == Verdict.PASS)):
            dim_verdicts[r.dimension] = r.verdict

    total_penalty = sum(_PENALTY.get(v, 0.0) for v in dim_verdicts.values())
    return max(0.0, 100.0 - total_penalty)


def _compute_input_hash(request: PipelineInput) -> str:
    data = (
        request.implementation_md
        + request.mapping_csv
        + request.project_id
        + request.dataset_id
        + request.environment
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def _write_artifacts(
    out_dir: Path,
    artifacts: list[GeneratedArtifact],
    reviews: list[ReviewResult],
) -> None:
    for a in artifacts:
        sub = out_dir / a.artifact_type.value
        sub.mkdir(parents=True, exist_ok=True)
        # a.file_name may already include the type prefix (e.g. "ddl/stg_employees.sql")
        # Use only the basename to avoid doubled paths like ddl/ddl/stg_employees.sql
        fname = Path(a.file_name).name
        (sub / fname).write_text(a.content, encoding="utf-8")

    report_lines = []
    for r in reviews:
        report_lines.append(f"## {r.dimension.upper()} — {r.verdict.value}")
        report_lines.append(r.summary)
        if r.findings:
            report_lines.append(
                "| Severity | Check | File | Description | Suggested Fix |"
            )
            report_lines.append(
                "|----------|-------|------|-------------|---------------|"
            )
            for f in r.findings:
                report_lines.append(
                    f"| {f.severity.value} | {f.check_name} | {f.file_name} "
                    f"| {f.description} | {f.suggested_fix} |"
                )
        report_lines.append("")

    (out_dir / "REVIEW_REPORT.md").write_text(
        "\n".join(report_lines), encoding="utf-8"
    )


def _write_manifest(
    out_dir: Path,
    output: CodeGenOutput,
    ctx: "SessionContext | None" = None,
    git_branch: str | None = None,
    git_repo_url: str | None = None,
) -> None:
    """Write rich MANIFEST.json for testing team artifact discovery."""
    import re as _re
    plan = output.plan

    # Strip any embedded PAT from the URL
    repo_url = ""
    if git_repo_url:
        repo_url = _re.sub(r"://[^@]+@", "://", git_repo_url)

    # Build per-file entries
    files: list[dict] = []
    for a in output.artifacts:
        change_type = "modified" if a.is_alter else "created"
        artifact_path = str(out_dir / a.artifact_type.value / Path(a.file_name).name)
        files.append({
            "file_path": artifact_path,
            "file_type": a.artifact_type.value,
            "change_type": change_type,
            "columns_affected": [],
            "tkt_no": [output.request_id],
            "owner": "",
        })

    request_id = ctx.request_id if ctx else output.request_id
    summary = plan.summary[:80] if plan.summary else ""
    commit_msg = (
        f"feat: {request_id} — {summary}"
        if summary else f"feat: {request_id} pipeline artifacts"
    )

    manifest = {
        "project": plan.project or (ctx.project_id if ctx else ""),
        "sprint": plan.sprint,
        "version": "1.0",
        "repo": repo_url,
        "branch": git_branch or "",
        "target_branch": "main",
        "commit_message": commit_msg,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request_id": output.request_id,
        "quality_score": output.quality_score,
        "approved_for_deploy": output.approved_for_deploy,
        "files": files,
    }
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def _extract_file_names_from_notes(notes: str, artifacts: list[GeneratedArtifact]) -> set[str]:
    """Return artifact file names mentioned (directly or by reference) in the user's notes.

    Matching order — stops at the first strategy that yields at least one match:

    1. Exact full filename  — "stg_employees.sql" appears verbatim in the notes.
    2. Stem match           — "stg_employees" (filename without extension) appears in notes.
    3. Unambiguous partial  — a word token in the notes is a substring of exactly ONE
                              artifact's stem (e.g. "employees" → only "stg_employees.sql").
                              Tokens shorter than 4 characters are skipped (too generic).

    Returns an empty set if no artifact can be confidently identified — the caller
    will then fall through to the interactive file-selection prompt.
    """
    lower_notes = notes.lower()
    matched: set[str] = set()

    # 1. Exact full filename match
    for a in artifacts:
        if a.file_name.lower() in lower_notes:
            matched.add(a.file_name)
    if matched:
        return matched

    # 2. Stem match (filename without extension)
    for a in artifacts:
        stem = Path(a.file_name).stem.lower()
        if stem and stem in lower_notes:
            matched.add(a.file_name)
    if matched:
        return matched

    # 3. Unambiguous partial stem match
    # Extract meaningful word tokens from the notes (min length 4 to avoid noise)
    tokens = re.findall(r'\b[a-z_][a-z0-9_]{3,}\b', lower_notes)
    for token in tokens:
        candidates = [
            a for a in artifacts
            if token in Path(a.file_name).stem.lower()
        ]
        if len(candidates) == 1:
            matched.add(candidates[0].file_name)

    return matched


# ── Change-scope classification ────────────────────────────────────────────────

# Comment-only = user explicitly requests adding/modifying comments or annotations.
# No code logic, schema, or style changes implied → reviewer handles directly.
# Checked BEFORE _MINOR_RE so "add comment" is not misclassified as minor.
_COMMENT_ONLY_RE = re.compile(
    r"\b(add\s+comment|add\s+a\s+comment|add\s+(?:inline\s+)?comments|"
    r"update\s+comment|fix\s+comment|correct\s+comment|"
    r"add\s+description|add\s+a\s+description|update\s+description|"
    r"add\s+docstring|update\s+docstring|add\s+annotation|"
    r"add\s+(?:a\s+)?note|add\s+(?:a\s+)?header\s+comment|update\s+header|"
    r"add\s+pii\s+comment|add\s+assumption\s+comment|"
    r"add\s+assumption|update\s+assumption)\b",
    re.IGNORECASE,
)

# Minor = cosmetic / documentation only — no logic, schema, or structure change.
_MINOR_RE = re.compile(
    r"\b(comment|comments|doc|docs|documentation|docstring|format|indent|"
    r"style|whitespace|blank line|blank lines|typo|spelling|logging|log line|"
    r"log message|log messages|description|readme)\b",
    re.IGNORECASE,
)

# Major = structural / schema / logic change that may cascade to other artifacts.
# Note: "dag", "pipeline" intentionally excluded — they are used as file-type
# references ("to the DAG file") and are too broad to signal a structural change.
# Structural DAG changes are captured via more specific terms (schedule, cron, task…).
_MAJOR_RE = re.compile(
    r"\b(column|field|schema|index|partition|primary key|foreign key|"
    r"rename|drop|truncate|alter|join|cte|subquery|merge|"
    r"logic|calculation|transform|transformation|business rule|"
    r"new column|add column|remove column|change type|data type|"
    r"task dependency|operator|sensor|schedule|cron|retry|sla|"
    r"dataflow template|flex template)\b",
    re.IGNORECASE,
)


def _classify_change_scope(notes: str) -> str:
    """
    Classify the user's revision request into one of three scopes:

    'comment_only' — user is adding/modifying code comments or annotations only.
                     Reviewer handles this directly; no generator or optimizer needed.

    'minor'        — cosmetic/documentation-only changes (no logic or schema change).
                     Optimizer patches the artifact in-place.

    'major'        — structural/schema/logic changes that may cascade to other files.
                     Generator re-generates the affected artifact(s).

    Defaults to 'major' (safer — cascades when uncertain).
    """
    has_major = bool(_MAJOR_RE.search(notes))
    has_comment_only = bool(_COMMENT_ONLY_RE.search(notes))
    has_minor = bool(_MINOR_RE.search(notes))

    if has_major:
        return "major"
    # Pure comment/annotation request — reviewer handles without optimizer or generator.
    # Checked before minor because _MINOR_RE also matches "comment|comments".
    if has_comment_only and not has_major:
        return "comment_only"
    if has_minor:
        return "minor"
    return "major"  # unknown → treat as major (safer default)


def _cascade_targets(
    target_names: set[str],
    notes: str,
    artifacts: list[GeneratedArtifact],
) -> set[str]:
    """
    For major-scope changes, expand the target set to include artifacts that are
    likely impacted by the change described in notes.

    Rules (conservative):
    - DDL change (schema/column) → also cascade to DAG/Pipeline that read that table
    - DAG change (schedule/task) → stay scoped (DAG is self-contained)
    - SP/DML change → cascade to DDL only if schema changes detected
    """
    from api.models import ArtifactType

    expanded = set(target_names)
    notes_lower = notes.lower()

    # If any DDL file is in target and notes suggest schema/column change,
    # cascade to DAG/Pipeline artifacts (they reference the same table columns).
    schema_keywords = {"column", "field", "schema", "add column", "new column",
                       "remove column", "rename", "data type", "change type", "alter"}
    schema_change = any(kw in notes_lower for kw in schema_keywords)

    target_types = {
        a.artifact_type for a in artifacts if a.file_name in target_names
    }

    if schema_change and ArtifactType.DDL in target_types:
        for a in artifacts:
            if a.artifact_type in (ArtifactType.DAG, ArtifactType.PIPELINE):
                expanded.add(a.file_name)

    # If a stored-procedure touches schema, cascade to DDL too
    if schema_change and ArtifactType.SP in target_types:
        for a in artifacts:
            if a.artifact_type == ArtifactType.DDL:
                expanded.add(a.file_name)

    return expanded


def _prompt_file_selection(
    artifacts: list[GeneratedArtifact],
    run_state=None,
) -> set[str]:
    """
    Ask the user to pick which files to revise when their notes didn't name any.
    Returns a set of file names. Returns empty set if user skips.
    """
    if run_state is not None:
        # API mode — can't prompt interactively; caller should have provided notes
        return set()

    print()
    print("  Which file(s) do you want to change?")
    for i, a in enumerate(artifacts, 1):
        print(f"    {i}. {a.file_name}")
    print()
    print("  Enter number(s) separated by commas, file name(s), or press Enter to skip.")
    raw = _input("File(s)").strip()
    if not raw:
        return set()

    selected: set[str] = set()
    name_map = {a.file_name.lower(): a.file_name for a in artifacts}
    for token in [t.strip() for t in raw.replace(",", " ").split()]:
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(artifacts):
                selected.add(artifacts[idx].file_name)
        else:
            matched = name_map.get(token.lower())
            if not matched:
                candidates = [v for k, v in name_map.items() if token.lower() in k]
                if len(candidates) == 1:
                    matched = candidates[0]
            if matched:
                selected.add(matched)
    return selected


def _remove_stale_artifacts(out_dir: Path, current_artifacts: list[GeneratedArtifact]) -> None:
    """
    Remove any artifact files on disk whose names are no longer in the current
    artifact list. Prevents duplicate / orphaned files after targeted revisions.
    """
    current_names = {Path(a.file_name).name for a in current_artifacts}
    for sub in out_dir.iterdir():
        if not sub.is_dir():
            continue
        for f in sub.iterdir():
            if f.is_file() and f.suffix in (".sql", ".py") and f.name not in current_names:
                f.unlink()
                logger.info("Removed stale artifact: %s", f)


def _banner(text: str) -> None:
    print()
    print("=" * 70)
    print(f"  {text}")
    print("=" * 70)


def _stage(text: str) -> None:
    print()
    print(f"  ── {text} ──")
    print()


def _info(text: str) -> None:
    print(f"  {text}")


def _sep() -> None:
    print("  " + "─" * 66)


def _input(prompt: str) -> str:
    return input(f"\n  {prompt}: ").strip()
