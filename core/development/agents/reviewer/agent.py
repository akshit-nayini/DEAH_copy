"""Self-review agent.

Token strategy
──────────────
Per-artifact review — one LLM call per artifact, all 4 dimensions combined.
The plan block is cached by the generator and reused across every artifact call.

All artifact reviews run concurrently (ThreadPoolExecutor) so total review time
equals the slowest single artifact instead of the sum of all artifacts.

logic_preservation review (Mode 2) is unchanged: it compares original vs
optimized artifacts side-by-side and runs as a single additional call.

Human notes are appended to the task prompt so the LLM verifies corrections.
"""
from __future__ import annotations
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from core.utilities.llm import BaseLLMClient, ContextBlock
from api.models import (
    GeneratedArtifact, ReviewFinding, ReviewResult, SessionContext, Severity, Verdict,
)
from agents.reviewer.prompts import (
    ANNOTATOR_SYSTEM,
    REVIEWER_SYSTEM,
    build_annotate_task,
    build_combined_review_task,
    build_logic_preservation_task,
)

logger = logging.getLogger("development.reviewer")

# Cap used only for logic_preservation (original + optimized side-by-side comparison)
_MAX_LOGIC_PRESERVATION_CHARS = 20_000

DIMENSIONS = ["syntax", "audit_compliance", "data_integrity", "pii_encryption", "cross_artifact_consistency", "plan_compliance"]
_MAX_WORKERS = 5


class ReviewerAgent:
    def __init__(self, llm: BaseLLMClient) -> None:
        self._llm = llm

    def review(
        self,
        ctx: SessionContext,
        artifacts: list[GeneratedArtifact],
    ) -> list[ReviewResult]:
        """Review each artifact individually across active dimensions in one LLM call.

        All artifact calls run concurrently — plan cached throughout.
        """
        if not artifacts:
            return [
                ReviewResult(dimension=d, verdict=Verdict.PASS, summary="No artifacts to review.")
                for d in DIMENSIONS
            ]

        # Conditionally skip dimensions based on plan contents
        active_dimensions = list(DIMENSIONS)
        if ctx.plan is not None:
            # Skip pii_encryption if no PII columns declared
            if not ctx.plan.pii_columns:
                impl_lower = (ctx.implementation_md or "").lower()
                if "pii" not in impl_lower and "encrypt" not in impl_lower:
                    active_dimensions = [d for d in active_dimensions if d != "pii_encryption"]
                    logger.info("Reviewer: skipping pii_encryption (no PII in plan)")

            # Skip audit_compliance if audit logging is not required in the plan
            if not getattr(ctx.plan.audit_table, "enabled", False):
                active_dimensions = [d for d in active_dimensions if d != "audit_compliance"]
                logger.info("Reviewer: skipping audit_compliance (audit not required in plan)")

        base_blocks: list[ContextBlock] = []
        if ctx.plan is not None:
            base_blocks = [
                ContextBlock(
                    text=f"## Approved Execution Plan\n{ctx.plan.raw_plan}",
                    label="plan",
                    cacheable=True,
                )
            ]

        notes_block = ctx.human_notes_block()

        def _review_one(artifact: GeneratedArtifact) -> list[ReviewResult]:
            artifact_block = ContextBlock(
                text=(
                    f"## Artifact: {artifact.file_name} ({artifact.artifact_type.value.upper()})\n"
                    f"```\n{artifact.content}\n```"
                ),
                label=f"artifact:{artifact.file_name}",
                cacheable=False,
            )
            logger.info("Reviewer: reviewing %s...", artifact.file_name)
            resp = self._llm.complete_with_context(
                context_blocks=base_blocks + [artifact_block],
                task_prompt=build_combined_review_task(
                    artifact.file_name, notes_block, active_dimensions
                ),
                system=REVIEWER_SYSTEM,
                max_tokens=4096,
            )
            results = _parse_combined_result(resp.content, artifact.file_name, active_dimensions)
            logger.info(
                "Reviewer %s: %d dimension result(s) | %d input tokens (%d cached)",
                artifact.file_name, len(results),
                resp.input_tokens, resp.cache_read_tokens,
            )
            return results

        workers = min(_MAX_WORKERS, len(artifacts))
        logger.info("Reviewer: reviewing %d artifact(s) with %d workers...", len(artifacts), workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_review_one, a) for a in artifacts]
            all_results = [r for f in futures for r in f.result()]

        return _merge_results(all_results, active_dimensions)

    def annotate(
        self,
        ctx: SessionContext,
        artifacts: list[GeneratedArtifact],
        user_notes: str,
    ) -> list[GeneratedArtifact]:
        """Apply comment/annotation-only changes to artifacts without regenerating code.

        Called when the user's revision request is classified as "comment_only":
        e.g. "add a PII comment", "update the file header", "add assumption note".
        Uses a narrow ANNOTATOR_SYSTEM prompt that strictly forbids logic changes.

        Returns the modified artifacts (same types/names, updated comment content).
        The caller should evict these from the review cache and re-review them.
        """
        if not artifacts:
            return []

        base_blocks: list[ContextBlock] = []
        if ctx.plan is not None:
            base_blocks = [
                ContextBlock(
                    text=f"## Approved Execution Plan\n{ctx.plan.raw_plan}",
                    label="plan",
                    cacheable=True,
                )
            ]

        def _annotate_one(artifact: GeneratedArtifact) -> GeneratedArtifact:
            artifact_block = ContextBlock(
                text=(
                    f"## Artifact: {artifact.file_name} ({artifact.artifact_type.value.upper()})\n"
                    f"```\n{artifact.content}\n```"
                ),
                label=f"artifact:{artifact.file_name}",
                cacheable=False,
            )
            logger.info("Reviewer [annotate]: patching comments in %s...", artifact.file_name)
            resp = self._llm.complete_with_context(
                context_blocks=base_blocks + [artifact_block],
                task_prompt=build_annotate_task(artifact.file_name, user_notes),
                system=ANNOTATOR_SYSTEM,
                max_tokens=4096,
            )
            improved = _extract_code(resp.content)
            if improved is None:
                logger.warning(
                    "Reviewer [annotate] %s: no code block in response — keeping original",
                    artifact.file_name,
                )
                improved = artifact.content
            logger.info(
                "Reviewer [annotate] %s: done (%d input tokens, %d cached)",
                artifact.file_name, resp.input_tokens, resp.cache_read_tokens,
            )
            return artifact.model_copy(update={"content": improved})

        workers = min(_MAX_WORKERS, len(artifacts))
        logger.info(
            "Reviewer [annotate]: patching %d artifact(s) with %d workers...",
            len(artifacts), workers,
        )
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_annotate_one, a) for a in artifacts]
            return [f.result() for f in futures]

    def review_optimized(
        self,
        ctx: SessionContext,
        original_artifacts: list[GeneratedArtifact],
        optimized_artifacts: list[GeneratedArtifact],
    ) -> list[ReviewResult]:
        """Standard per-artifact review on optimized artifacts, plus logic_preservation."""
        results = self.review(ctx, optimized_artifacts)

        original_text = "\n\n".join(
            f"### ORIGINAL: {a.file_name} ({a.artifact_type.value})\n"
            f"```\n{a.content[:_MAX_LOGIC_PRESERVATION_CHARS]}\n```"
            for a in original_artifacts
        )
        optimized_text = "\n\n".join(
            f"### OPTIMIZED: {a.file_name} ({a.artifact_type.value})\n"
            f"```\n{a.content[:_MAX_LOGIC_PRESERVATION_CHARS]}\n```"
            for a in optimized_artifacts
        )

        logger.info("Reviewer: logic_preservation review...")
        resp = self._llm.complete_with_context(
            context_blocks=[
                ContextBlock(
                    text=f"## Original Artifacts\n{original_text}",
                    label="original_artifacts",
                    cacheable=False,
                ),
                ContextBlock(
                    text=f"## Optimized Artifacts\n{optimized_text}",
                    label="optimized_artifacts",
                    cacheable=False,
                ),
            ],
            task_prompt=build_logic_preservation_task(ctx.human_notes_block()),
            system=REVIEWER_SYSTEM,
            max_tokens=4096,
        )
        lp_result = _parse_single_result("logic_preservation", resp.content)
        logger.info(
            "Reviewer logic_preservation: %s (%d finding(s)) | %d input tokens (%d cached)",
            lp_result.verdict.value, len(lp_result.findings),
            resp.input_tokens, resp.cache_read_tokens,
        )
        return results + [lp_result]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_code(llm_output: str) -> str | None:
    """Extract a single fenced code block from LLM output (used by annotate())."""
    match = re.search(
        r"```(?:sql|python|py|json|yaml)?\s*\n(.*?)```",
        llm_output,
        re.DOTALL,
    )
    return match.group(1).strip() if match else None


# ── Parsers ────────────────────────────────────────────────────────────────────

def _get_failed_artifact_names(
    artifacts: list[GeneratedArtifact],
    reviews: list[ReviewResult],
) -> set[str]:
    """Return file names of artifacts with FAIL or CONDITIONAL_PASS verdict findings."""
    failed_files: set[str] = set()
    for r in reviews:
        if r.verdict in (Verdict.FAIL, Verdict.CONDITIONAL_PASS):
            for f in r.findings:
                if f.file_name:
                    failed_files.add(f.file_name)
    # If findings have no file_name, return all artifact names (conservative)
    if not failed_files and any(
        r.verdict in (Verdict.FAIL, Verdict.CONDITIONAL_PASS) for r in reviews
    ):
        failed_files = {a.file_name for a in artifacts}
    return failed_files


def _parse_combined_result(
    raw: str, file_name: str, dimensions: list[str] | None = None
) -> list[ReviewResult]:
    """Parse a combined dimension review response into one ReviewResult per dimension."""
    dims = dimensions or DIMENSIONS
    results = []
    for dimension in dims:
        pattern = rf"##\s*{re.escape(dimension)}\b(.*?)(?=\n##\s*(?:{'|'.join(dims)})\b|\Z)"
        match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        section_text = match.group(1).strip() if match else ""
        results.append(_parse_single_result(dimension, section_text or raw, file_name))
    return results


def _parse_single_result(dimension: str, raw: str, file_name: str = "") -> ReviewResult:
    summary_match = re.search(
        r"##?\s*Summary\s*(.*?)(?=\n##|\Z)", raw, re.DOTALL | re.IGNORECASE
    )
    summary = summary_match.group(1).strip() if summary_match else raw[:250]

    findings: list[ReviewFinding] = []
    row_re = re.compile(
        r"\|\s*(CRITICAL|WARNING|INFO)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|",
        re.IGNORECASE,
    )
    for m in row_re.finditer(raw):
        try:
            sev = Severity(m.group(1).upper())
        except ValueError:
            sev = Severity.INFO
        findings.append(ReviewFinding(
            severity=sev,
            check_name=m.group(2).strip(),
            file_name=m.group(3).strip() or file_name,
            description=m.group(4).strip(),
            suggested_fix=m.group(5).strip(),
        ))

    # Derive verdict from actual findings — FAIL requires at least one CRITICAL.
    # This overrides whatever the LLM wrote in the Verdict section so the rule
    # "0 CRITICAL findings = never FAIL" is enforced in code, not just in the prompt.
    has_critical = any(f.severity == Severity.CRITICAL for f in findings)
    has_warning  = any(f.severity == Severity.WARNING  for f in findings)

    if has_critical:
        verdict = Verdict.FAIL
    elif has_warning:
        verdict = Verdict.CONDITIONAL_PASS
    else:
        verdict = Verdict.PASS

    return ReviewResult(
        dimension=dimension,
        verdict=verdict,
        summary=summary,
        findings=findings,
    )


def _merge_results(
    per_artifact: list[ReviewResult], dimensions: list[str] | None = None
) -> list[ReviewResult]:
    """Merge per-artifact ReviewResults into one ReviewResult per dimension."""
    from collections import defaultdict
    dims = dimensions or DIMENSIONS
    buckets: dict[str, list[ReviewResult]] = defaultdict(list)
    for r in per_artifact:
        buckets[r.dimension].append(r)

    merged: list[ReviewResult] = []
    for dimension in dims:
        group = buckets.get(dimension, [])
        if not group:
            merged.append(ReviewResult(
                dimension=dimension, verdict=Verdict.PASS, summary="No findings."
            ))
            continue

        all_findings = [f for r in group for f in r.findings]
        if any(r.verdict == Verdict.FAIL for r in group):
            verdict = Verdict.FAIL
        elif any(r.verdict == Verdict.CONDITIONAL_PASS for r in group):
            verdict = Verdict.CONDITIONAL_PASS
        else:
            verdict = Verdict.PASS

        summaries = "; ".join(r.summary for r in group if r.summary)
        merged.append(ReviewResult(
            dimension=dimension,
            verdict=verdict,
            summary=summaries,
            findings=all_findings,
        ))
    return merged
