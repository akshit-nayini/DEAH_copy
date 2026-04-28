"""Generator agent.

Token strategy
──────────────
Reuses the cached prefix established by PlannerAgent:
  [cached] implementation_md  → already in Anthropic cache
  [cached] mapping_csv        → already in Anthropic cache
  [cached] plan               → added and cached here for optimizer/reviewer

DDL, DML, and DAG calls run concurrently (ThreadPoolExecutor) so total
generation time equals the slowest single call instead of the sum of all three.

Human notes from checkpoint 1 are appended to every task prompt so the LLM
incorporates corrections without re-reading the documents.
"""
from __future__ import annotations
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.utilities.llm import BaseLLMClient, ContextBlock
from api.models import ArtifactType, ExecutionPlan, GeneratedArtifact, SessionContext
from agents.generator.prompts import (
    GENERATOR_SYSTEM,
    build_ddl_task,
    build_dml_task,
    build_dag_task,
)

logger = logging.getLogger("development.generator")


class GeneratorClarificationNeeded(ValueError):
    """Raised when the generator cannot proceed without answers from the user.

    The orchestrator catches this, surfaces the message at a checkpoint, and
    retries generation after the user provides the missing information.
    """


class GeneratorAgent:
    def __init__(self, llm: BaseLLMClient) -> None:
        self._llm = llm

    def generate(self, ctx: SessionContext) -> list[GeneratedArtifact]:
        assert ctx.plan is not None, "SessionContext.plan must be set before calling generate()"

        blocker_questions = [
            q for q in ctx.plan.clarifying_questions
            if q.strip().upper().startswith("[BLOCKER]")
        ]
        if blocker_questions:
            raise ValueError(
                f"Cannot generate code: {len(blocker_questions)} BLOCKER clarifying "
                f"question(s) are unresolved. Answer them at Checkpoint 1 before proceeding.\n"
                + "\n".join(f"  • {q}" for q in blocker_questions)
            )

        base_blocks = _base_context_blocks(ctx)
        notes_block = ctx.human_notes_block()

        def _gen_ddl():
            logger.info("Generator: generating DDL (parallel)...")
            resp = self._llm.complete_with_context(
                context_blocks=base_blocks,
                task_prompt=build_ddl_task(ctx.plan, notes_block),
                system=GENERATOR_SYSTEM,
                max_tokens=8192,
            )
            arts = _extract_artifacts(resp.content, ArtifactType.DDL)
            logger.info(
                "Generator DDL: %d artifact(s) | %d input tokens (%d cached)",
                len(arts), resp.input_tokens, resp.cache_read_tokens,
            )
            return arts

        def _gen_dml():
            logger.info("Generator: generating DML (parallel)...")
            resp = self._llm.complete_with_context(
                context_blocks=base_blocks,
                task_prompt=build_dml_task(ctx.plan, notes_block),
                system=GENERATOR_SYSTEM,
                max_tokens=8192,
            )
            arts = _extract_artifacts(resp.content, ArtifactType.DML)
            logger.info(
                "Generator DML: %d artifact(s) | %d input tokens (%d cached)",
                len(arts), resp.input_tokens, resp.cache_read_tokens,
            )
            return arts

        def _gen_dag():
            logger.info("Generator: generating Airflow DAGs (parallel)...")
            resp = self._llm.complete_with_context(
                context_blocks=base_blocks,
                task_prompt=build_dag_task(ctx.plan, notes_block),
                system=GENERATOR_SYSTEM,
                max_tokens=8192,
            )
            arts = _extract_artifacts(resp.content, ArtifactType.DAG)
            logger.info(
                "Generator DAGs: %d artifact(s) | %d input tokens (%d cached)",
                len(arts), resp.input_tokens, resp.cache_read_tokens,
            )
            return arts

        # ── Check plan has artifacts to generate ────────────────────────────────
        if not ctx.plan.artifacts_to_generate:
            raise GeneratorClarificationNeeded(
                "The approved plan contains no artifacts_to_generate entries. "
                "Cannot start code generation without knowing which files to produce.\n"
                "Please revise the plan and provide:\n"
                "  • The exact file names (e.g. ddl_stg_employees.sql, dag_employees_extract.py)\n"
                "  • The artifact type for each file (DDL | DML | SP | DAG)"
            )

        # ── Detect artifacts with missing type AND missing extension ─────────────
        unresolvable = [
            _artifact_name(a)
            for a in ctx.plan.artifacts_to_generate
            if not getattr(a, "type", "").strip()
            and "." not in _artifact_name(a)
        ]
        if unresolvable:
            raise GeneratorClarificationNeeded(
                f"{len(unresolvable)} artifact(s) have no file extension and no type — "
                f"cannot determine whether they are SQL or Python:\n"
                + "\n".join(f"  • {n}" for n in unresolvable)
                + "\nPlease revise the plan: add .sql / .py extension or set the type field "
                "to DDL / DML / SP / DAG for each artifact."
            )

        # ── Determine which LLM calls are needed based on plan artifacts ─────────
        # Use ArtifactSpec.type as primary signal; fall back to file extension.
        needs_ddl = needs_dml = needs_dag = False
        for a in ctx.plan.artifacts_to_generate:
            t   = getattr(a, "type", "").upper()
            ext = _artifact_name(a).rsplit(".", 1)[-1].lower()
            if t == "DDL" or (ext == "sql" and t not in ("DML", "SP")):
                needs_ddl = True
            if t in ("DML", "SP") or (ext == "sql" and t == ""):
                needs_dml = True
            if t == "DAG" or ext == "py":
                needs_dag = True
        # Fallback: types/extensions are present but all unrecognised — run all three
        if not (needs_ddl or needs_dml or needs_dag):
            needs_ddl = needs_dml = needs_dag = True

        workers: list = []
        if needs_ddl:
            workers.append(_gen_ddl)
        if needs_dml:
            workers.append(_gen_dml)
        if needs_dag:
            workers.append(_gen_dag)

        logger.info(
            "Generator: launching %d call(s) in parallel (DDL=%s DML=%s DAG=%s)...",
            len(workers), needs_ddl, needs_dml, needs_dag,
        )
        ddl_arts, dml_arts, dag_arts = [], [], []
        with ThreadPoolExecutor(max_workers=max(len(workers), 1)) as pool:
            futures = {fn.__name__: pool.submit(fn) for fn in workers}
            if "_gen_ddl" in futures:
                ddl_arts = futures["_gen_ddl"].result()
            if "_gen_dml" in futures:
                dml_arts = futures["_gen_dml"].result()
            if "_gen_dag" in futures:
                dag_arts = futures["_gen_dag"].result()

        all_arts = _global_dedup(ddl_arts + dml_arts + dag_arts)

        # ── Check every planned artifact was actually generated ──────────────────
        if not all_arts:
            planned = [_artifact_name(a) for a in ctx.plan.artifacts_to_generate]
            raise GeneratorClarificationNeeded(
                "Generator ran but produced 0 artifacts. The plan lists "
                f"{len(planned)} file(s) but the LLM returned no code blocks:\n"
                + "\n".join(f"  • {n}" for n in planned)
                + "\nPossible causes:\n"
                "  1. File names in the plan don't match expected naming conventions "
                "     (e.g. missing ddl_ / dml_ / dag_ prefix, or wrong extension)\n"
                "  2. The plan's artifact types are incorrect\n"
                "Please revise the plan with correct file names and types."
            )

        # Retry any planned artifacts the batch calls didn't emit.
        # The initial batch makes one LLM call per type group (DDL/DML/DAG).
        # When a group contains multiple large files (e.g. two DAGs), the later
        # ones can be silently dropped when the LLM exhausts max_tokens.
        # Each missing artifact gets its own dedicated call so the full token
        # budget is available and no planned artifact is ever silently dropped.
        generated_names = {a.file_name.lower() for a in all_arts}
        missing_specs = [
            a for a in ctx.plan.artifacts_to_generate
            if _artifact_name(a).lower() not in generated_names
        ]
        if missing_specs:
            missing_names = [_artifact_name(a) for a in missing_specs]
            logger.warning(
                "Generator did not produce %d expected artifact(s): %s — "
                "retrying each individually...",
                len(missing_specs), ", ".join(missing_names),
            )
            retried = self._retry_missing_artifacts(ctx, missing_specs, base_blocks, notes_block)
            if retried:
                all_arts = _global_dedup(all_arts + retried)

            # Report anything still missing after the retry pass
            generated_names = {a.file_name.lower() for a in all_arts}
            still_missing = [
                n for n in missing_names if n.lower() not in generated_names
            ]
            if still_missing:
                logger.warning(
                    "Generator [retry]: still missing after individual retry: %s",
                    ", ".join(still_missing),
                )

        # Per-artifact: check DB existence → set is_alter, inject version header
        project = ctx.plan.project if ctx.plan else ctx.project_id
        sprint = ctx.plan.sprint if ctx.plan else ""
        enriched: list[GeneratedArtifact] = []
        for art in all_arts:
            is_alter = _artifact_exists_in_db(art.file_name, ctx.request_id)
            content = _inject_version_header(
                art.content, art.file_name, project, sprint, ctx.request_id, is_alter
            )
            enriched.append(art.model_copy(update={"content": content, "is_alter": is_alter}))

        return enriched

    def _retry_missing_artifacts(
        self,
        ctx: SessionContext,
        missing_specs: list,
        base_blocks: list[ContextBlock],
        notes_block: str,
    ) -> list[GeneratedArtifact]:
        """Generate each missing planned artifact in its own dedicated LLM call.

        Called when the initial batch generation dropped one or more artifacts.
        Each artifact gets the full max_tokens budget instead of competing with
        sibling artifacts in a shared call.

        Returns raw (unenriched) artifacts — the caller's enrichment loop will
        apply version headers and is_alter flags.
        """
        results: list[GeneratedArtifact] = []

        for spec in missing_specs:
            art_name = _artifact_name(spec)
            art_type_str = getattr(spec, "type", "").upper()
            lower_name = art_name.lower()

            # Select prompt builder and default artifact type from the spec type,
            # falling back to file extension heuristics.
            if art_type_str == "DAG" or lower_name.endswith(".py"):
                build_fn = build_dag_task
                default_type = ArtifactType.DAG
            elif art_type_str in ("DML", "SP") or lower_name.startswith("sp_"):
                build_fn = build_dml_task
                default_type = ArtifactType.DML
            elif art_type_str == "DDL" or lower_name.startswith("ddl_"):
                build_fn = build_ddl_task
                default_type = ArtifactType.DDL
            elif lower_name.endswith(".sql"):
                # Ambiguous SQL without a ddl_ prefix — likely a stored procedure or DML
                build_fn = build_dml_task
                default_type = ArtifactType.DML
            else:
                build_fn = build_dag_task
                default_type = ArtifactType.DAG

            filter_note = (
                f"\n\nIMPORTANT: Generate ONLY this one file: {art_name}\n"
                f"All other planned artifacts have already been generated successfully.\n"
                f"Focus the entire response on producing {art_name} — one code block, "
                f"nothing else."
            )

            logger.info("Generator [retry]: generating missing artifact %s ...", art_name)
            try:
                resp = self._llm.complete_with_context(
                    context_blocks=base_blocks,
                    task_prompt=build_fn(ctx.plan, notes_block + filter_note),
                    system=GENERATOR_SYSTEM,
                    max_tokens=8192,
                )
            except Exception as exc:
                logger.warning(
                    "Generator [retry]: LLM call failed for %s — %s", art_name, exc
                )
                continue

            arts = _extract_artifacts(resp.content, default_type)
            logger.info(
                "Generator [retry] %s: %d artifact(s) extracted | %d input tokens (%d cached)",
                art_name, len(arts), resp.input_tokens, resp.cache_read_tokens,
            )

            # Prefer an exact filename match; fall back to the first result in the response
            matched = [a for a in arts if a.file_name.lower() == lower_name]
            results.extend(matched if matched else arts[:1])

        return results

    def generate_for_revision(
        self,
        ctx: SessionContext,
        artifact_names: set[str],
        current_artifacts: list[GeneratedArtifact] | None = None,
    ) -> list[GeneratedArtifact]:
        """Re-generate only the specified artifacts (targeted revision after review).

        current_artifacts: the full in-memory artifact list from the current round.
        When provided, artifact types are derived from it so only the necessary
        LLM calls (DDL / DML / DAG) are launched — avoiding duplicate generation
        from parallel calls that would produce the same file twice.
        """
        assert ctx.plan is not None
        base_blocks = _base_context_blocks(ctx)
        notes_block = ctx.human_notes_block()
        filter_note = (
            f"\n\nIMPORTANT: Generate ONLY these files (leave all others unchanged):\n"
            + "\n".join(f"  - {n}" for n in sorted(artifact_names))
        )

        project = ctx.plan.project or ctx.project_id
        sprint = ctx.plan.sprint

        # ── Determine which LLM calls are needed ─────────────────────────────────
        # Primary signal: artifact type from the current in-memory list.
        # Fallback: file extension (may launch both DDL+DML to be safe, but global
        # dedup at the end ensures no duplicate artifacts reach the caller).
        name_to_type: dict[str, ArtifactType] = {}
        if current_artifacts:
            name_to_type = {a.file_name.lower(): a.artifact_type for a in current_artifacts}

        needs_ddl = needs_dml = needs_dag = False
        for n in artifact_names:
            lower_n = n.lower()
            art_type = name_to_type.get(lower_n)
            if art_type is not None:
                if art_type == ArtifactType.DDL:
                    needs_ddl = True
                elif art_type in (ArtifactType.DML, ArtifactType.SP):
                    needs_dml = True
                elif art_type in (ArtifactType.DAG, ArtifactType.PIPELINE):
                    needs_dag = True
                else:
                    # Unknown type — fall back to extension
                    if lower_n.endswith(".sql"):
                        needs_ddl = needs_dml = True
                    elif lower_n.endswith(".py"):
                        needs_dag = True
            else:
                # No type info — use extension (may over-generate, dedup handles it)
                if lower_n.endswith(".sql"):
                    needs_ddl = needs_dml = True
                elif lower_n.endswith(".py"):
                    needs_dag = True

        if not (needs_ddl or needs_dml or needs_dag):
            # Absolute fallback: run all three
            needs_ddl = needs_dml = needs_dag = True

        logger.info(
            "Generator [revision]: DDL=%s DML=%s DAG=%s for %s",
            needs_ddl, needs_dml, needs_dag, sorted(artifact_names),
        )

        results: list[GeneratedArtifact] = []

        def _run_ddl():
            resp = self._llm.complete_with_context(
                context_blocks=base_blocks,
                task_prompt=build_ddl_task(ctx.plan, notes_block + filter_note),
                system=GENERATOR_SYSTEM,
                max_tokens=8192,
            )
            return _extract_artifacts(resp.content, ArtifactType.DDL)

        def _run_dml():
            resp = self._llm.complete_with_context(
                context_blocks=base_blocks,
                task_prompt=build_dml_task(ctx.plan, notes_block + filter_note),
                system=GENERATOR_SYSTEM,
                max_tokens=8192,
            )
            return _extract_artifacts(resp.content, ArtifactType.DML)

        def _run_dag():
            resp = self._llm.complete_with_context(
                context_blocks=base_blocks,
                task_prompt=build_dag_task(ctx.plan, notes_block + filter_note),
                system=GENERATOR_SYSTEM,
                max_tokens=8192,
            )
            return _extract_artifacts(resp.content, ArtifactType.DAG)

        workers = []
        if needs_ddl:
            workers.append(_run_ddl)
        if needs_dml:
            workers.append(_run_dml)
        if needs_dag:
            workers.append(_run_dag)

        with ThreadPoolExecutor(max_workers=max(len(workers), 1)) as pool:
            futs = [pool.submit(fn) for fn in workers]
            for f in futs:
                results.extend(f.result())

        # Global dedup: parallel calls can emit the same file name independently
        results = _global_dedup(results)

        # Filter to only the requested artifacts and inject version headers
        target_names_lower = {n.lower() for n in artifact_names}
        filtered = [a for a in results if a.file_name.lower() in target_names_lower]
        enriched = []
        for art in filtered:
            is_alter = _artifact_exists_in_db(art.file_name, ctx.request_id)
            content = _inject_version_header(
                art.content, art.file_name, project, sprint, ctx.request_id, is_alter
            )
            enriched.append(art.model_copy(update={"content": content, "is_alter": is_alter}))
        return enriched


def _artifact_name(a) -> str:
    """Return the file name from an ArtifactSpec (or any object with a file_name attr)."""
    return a.file_name


def _global_dedup(artifacts: list[GeneratedArtifact]) -> list[GeneratedArtifact]:
    """Remove duplicate file names produced by parallel generator calls.

    When DDL and DML tasks both emit a file with the same name (e.g. stg_employees.sql
    appearing in both responses), keep only the LAST occurrence.  This is the same
    "last-wins" policy already applied inside _extract_artifacts for within-call
    duplicates — this function extends it across call boundaries.

    STRICT POLICY: no artifact file name may appear more than once in the returned list.
    """
    seen: dict[str, GeneratedArtifact] = {}
    for art in artifacts:
        key = art.file_name.lower()
        if key in seen:
            logger.warning(
                "Dedup [cross-call]: duplicate artifact %r produced by parallel generator "
                "calls — enforcing strict no-duplicate policy, keeping last occurrence.",
                art.file_name,
            )
        seen[key] = art
    return list(seen.values())


def _base_context_blocks(ctx: SessionContext) -> list[ContextBlock]:
    return [
        ContextBlock(
            text=(
                f"## Implementation Document\n"
                f"Project: {ctx.project_id} | Dataset: {ctx.dataset_id} | "
                f"Env: {ctx.environment} | Cloud: {ctx.cloud_provider.upper()}\n\n"
                f"{ctx.implementation_md}"
            ),
            label="implementation_md",
            cacheable=True,
        ),
        ContextBlock(
            text=f"## Column Mapping (CSV)\n```csv\n{ctx.mapping_csv}\n```",
            label="mapping_csv",
            cacheable=True,
        ),
        ContextBlock(
            text=f"## Approved Execution Plan\n{ctx.plan.raw_plan}",
            label="plan",
            cacheable=True,
        ),
    ]


_BLOCK_RE = re.compile(
    r"(?:###?\s*(?:file(?:name)?:?\s*)?`?([^`\n]+\.(?:sql|py|json|yaml|yml))`?\s*\n)?"
    r"```(?:sql|python|py|json|yaml|bash)?\s*\n(.*?)```",
    re.DOTALL,
)


def _extract_artifacts(
    llm_output: str,
    default_type: ArtifactType,
) -> list[GeneratedArtifact]:
    """
    Parse code blocks from LLM output into GeneratedArtifact objects.

    Strict deduplication: if the LLM emits the same file name more than once
    (identical or different content), only the LAST occurrence is kept.
    This overwrites any earlier duplicate rather than producing twin files.
    """
    # Use an ordered dict keyed on file_name (case-insensitive) so the last
    # occurrence wins — the LLM sometimes repeats a block after corrections.
    seen: dict[str, GeneratedArtifact] = {}

    for i, match in enumerate(_BLOCK_RE.finditer(llm_output)):
        raw_name = (match.group(1) or "").strip()
        code = match.group(2).strip()
        if not code:
            continue

        ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else ""
        if ext == "py":
            art_type = ArtifactType.DAG
        elif ext == "sql":
            code_upper = code.upper()
            if "CREATE OR REPLACE PROCEDURE" in code_upper or "CREATE PROCEDURE" in code_upper:
                art_type = ArtifactType.SP
            elif any(k in code_upper for k in ("CREATE TABLE", "CREATE OR REPLACE TABLE", "CREATE SCHEMA")):
                art_type = ArtifactType.DDL
            else:
                art_type = ArtifactType.DML
        else:
            art_type = default_type

        file_name = raw_name or f"{default_type.value}_{i + 1}.{_ext(art_type)}"
        dedup_key = file_name.lower()

        artifact = GeneratedArtifact(
            file_name=file_name,
            artifact_type=art_type,
            content=code,
            description=f"Generated {art_type.value}: {file_name}",
            target_path=f"{art_type.value}/{file_name}",
        )

        if dedup_key in seen:
            logger.debug(
                "Dedup: overwriting earlier occurrence of %s with latest content",
                file_name,
            )
        seen[dedup_key] = artifact

    return list(seen.values())


def _ext(t: ArtifactType) -> str:
    return {
        ArtifactType.DDL: "sql",
        ArtifactType.DML: "sql",
        ArtifactType.SP: "sql",
        ArtifactType.DAG: "py",
        ArtifactType.PIPELINE: "py",
        ArtifactType.CONFIG: "yaml",
        ArtifactType.DOC: "md",
    }.get(t, "txt")


def _artifact_exists_in_db(file_name: str, ticket_id: str) -> bool:
    """Return True if this artifact file was previously generated for this ticket."""
    try:
        from sqlalchemy import text
        from db import build_metadata_engine
        engine = build_metadata_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM agent_output_metadata "
                    "WHERE AGENT = 'Development' AND IDENTIFIER = :ticket AND FILENAME = :fname"
                ),
                {"ticket": ticket_id, "fname": file_name},
            ).fetchone()
        return (row[0] if row else 0) > 0
    except Exception as exc:
        logger.warning("DB artifact check failed — defaulting to CREATE: %s", exc)
        return False


def _inject_version_header(
    content: str,
    file_name: str,
    project: str,
    sprint: str,
    ticket: str,
    is_alter: bool,
) -> str:
    """Prepend or update a version history header block on a generated file."""
    from datetime import datetime as _dt

    today = _dt.now().strftime("%Y-%m-%d")
    is_sql = file_name.endswith(".sql")
    comment = "--" if is_sql else "#"
    sep = f"{comment} {'=' * 60}"

    # Check if content already has a version history header from this agent
    history_pattern = re.compile(
        r"(?:--|#) Version History:(.*?)(?:--|#) =", re.DOTALL
    )
    history_match = history_pattern.search(content)

    if history_match and is_alter:
        # Append new version line to existing history
        existing_lines = history_match.group(1).strip().splitlines()
        last_ver = (1, 0)
        for line in reversed(existing_lines):
            m = re.search(r"v(\d+)\.(\d+)", line)
            if m:
                last_ver = (int(m.group(1)), int(m.group(2)) + 1)
                break
        new_ver = f"v{last_ver[0]}.{last_ver[1]}"
        new_line = f"{comment}   {new_ver}  {today}  {ticket}  Modified"
        new_history = history_match.group(1).rstrip() + f"\n{new_line}\n"
        content = history_pattern.sub(
            f"{comment} Version History:{new_history}{comment} =",
            content,
            count=1,
        )
        return content

    # Build fresh header
    purpose_map = {
        "ddl_": "DDL — table definition",
        "dml_": "DML — data merge / transform",
        "sp_": "Stored procedure",
        "dag_": "Airflow DAG — orchestration",
    }
    purpose = next(
        (v for k, v in purpose_map.items() if file_name.startswith(k)),
        f"Generated artifact: {file_name}",
    )
    action = "Modified" if is_alter else "Initial creation"
    header = (
        f"{sep}\n"
        f"{comment} File    : {file_name}\n"
        f"{comment} Purpose : {purpose}\n"
        f"{comment} Project : {project} | Sprint: {sprint}\n"
        f"{comment} Ticket  : {ticket}\n"
        f"{sep}\n"
        f"{comment} Version History:\n"
        f"{comment}   v1.0  {today}  {ticket}  {action}\n"
        f"{sep}\n"
    )
    return header + content


_IMPORT_TO_PACKAGE: dict[str, str] = {
    "airflow": "apache-airflow",
    "google": "google-cloud-bigquery",
    "pandas": "pandas",
    "numpy": "numpy",
    "sqlalchemy": "sqlalchemy",
    "requests": "requests",
    "pydantic": "pydantic",
    "anthropic": "anthropic",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
}

_STDLIB_MODULES: frozenset[str] = frozenset({
    "os", "sys", "re", "json", "pathlib", "datetime", "logging", "typing",
    "collections", "itertools", "functools", "abc", "io", "time", "math",
    "hashlib", "uuid", "copy", "dataclasses", "enum", "ast", "concurrent",
    "threading", "subprocess", "tempfile", "shutil", "traceback", "warnings",
})


def _scan_and_update_requirements(artifacts: list[GeneratedArtifact], req_path: Path) -> None:
    """Scan Python imports in generated artifacts, append missing packages to requirements.txt."""
    import ast as _ast

    current_text = req_path.read_text(encoding="utf-8") if req_path.exists() else ""
    current_pkgs = {
        line.split("==")[0].split(">=")[0].split("~=")[0].strip().lower()
        for line in current_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    missing: list[str] = []
    for artifact in artifacts:
        if not artifact.file_name.endswith(".py"):
            continue
        try:
            tree = _ast.parse(artifact.content)
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                top_modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, _ast.ImportFrom):
                top_modules = [node.module.split(".")[0]] if node.module else []
            else:
                continue
            for mod in top_modules:
                if mod in _STDLIB_MODULES:
                    continue
                pkg = _IMPORT_TO_PACKAGE.get(mod, mod)
                if pkg.lower() not in current_pkgs and pkg not in missing:
                    missing.append(pkg)

    if missing:
        logger.info(
            "Generator: adding %d missing package(s) to requirements.txt: %s",
            len(missing), missing,
        )
        with req_path.open("a", encoding="utf-8") as f:
            f.write("\n# Auto-added by development agent\n")
            for pkg in missing:
                f.write(f"{pkg}\n")
