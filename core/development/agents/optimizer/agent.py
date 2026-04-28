"""Optimizer agent.

Token strategy
──────────────
The plan block was cached by the generator.  Each artifact is sent as a
small non-cached block alongside the cached plan.  The task prompt describes
what to improve.  Artifacts are kept short (3 KB cap) so per-call cost stays low.

All artifacts are optimized concurrently (ThreadPoolExecutor) so total time
equals the slowest single artifact instead of the sum of all artifacts.

Human notes from checkpoint 1 are included in the task prompt.
"""
from __future__ import annotations
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from core.utilities.llm import BaseLLMClient, ContextBlock
from api.models import GeneratedArtifact, SessionContext
from agents.optimizer.prompts import OPTIMIZER_SYSTEM, build_optimizer_task

logger = logging.getLogger("development.optimizer")

_MAX_ARTIFACT_CHARS = 3000
_MAX_WORKERS = 5


class OptimizerAgent:
    def __init__(self, llm: BaseLLMClient) -> None:
        self._llm = llm

    def optimize(
        self,
        ctx: SessionContext,
        artifacts: list[GeneratedArtifact],
    ) -> list[GeneratedArtifact]:
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

        standalone = ctx.plan is None
        notes_block = ctx.human_notes_block()

        def _optimize_one(artifact: GeneratedArtifact) -> GeneratedArtifact:
            logger.info("Optimizer: %s...", artifact.file_name)
            artifact_block = ContextBlock(
                text=(
                    f"## Artifact to Optimize: {artifact.file_name} "
                    f"({artifact.artifact_type.value.upper()})\n"
                    f"```\n{artifact.content[:_MAX_ARTIFACT_CHARS]}\n```"
                ),
                label=f"artifact:{artifact.file_name}",
                cacheable=False,
            )
            resp = self._llm.complete_with_context(
                context_blocks=base_blocks + [artifact_block],
                task_prompt=build_optimizer_task(artifact, notes_block, standalone=standalone),
                system=OPTIMIZER_SYSTEM,
                max_tokens=4096,
            )
            improved = _extract_code(resp.content) or artifact.content
            logger.info(
                "Optimizer %s: %d input tokens (%d cached)",
                artifact.file_name, resp.input_tokens, resp.cache_read_tokens,
            )
            return artifact.model_copy(update={"content": improved})

        workers = min(_MAX_WORKERS, len(artifacts))
        logger.info("Optimizer: processing %d artifact(s) with %d workers...", len(artifacts), workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_optimize_one, a) for a in artifacts]
            # Preserve input order
            return [f.result() for f in futures]


def _extract_code(llm_output: str) -> str | None:
    match = re.search(
        r"```(?:sql|python|py|json|yaml)?\s*\n(.*?)```",
        llm_output,
        re.DOTALL,
    )
    return match.group(1).strip() if match else None
