# Parallelize Agents + Schema Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Stage 1→Checkpoint 2 wall time from ~27 min to ~10 min, and eliminate cross-artifact schema mismatches by parallelising Generator/Optimizer/Reviewer and adding Planner-emitted schema contracts used by all downstream agents.

**Architecture:** All three parallelisation changes use `concurrent.futures.ThreadPoolExecutor` — LLM calls are I/O-bound network requests, thread-safe, and share no mutable state. Schema contracts (Idea D) add a `schema_contracts` field to `ExecutionPlan`; the Planner emits column names/types/nullability for every table; the Generator injects this as a cached ContextBlock into DML and DAG task prompts. The Reviewer gains a `cross_artifact_consistency` dimension (Idea C) that explicitly checks type parity and SP argument counts across files.

**Tech Stack:** Python 3.11+, `concurrent.futures.ThreadPoolExecutor`, Pydantic v2, existing `BaseLLMClient` / `ContextBlock` interfaces.

---

## Files to create / modify

| File | Action | What changes |
|---|---|---|
| `agents/generator/agent.py` | Modify | Run DDL/DML/DAG calls concurrently; inject schema_contracts block into DML+DAG calls |
| `agents/optimizer/agent.py` | Modify | Run per-artifact optimize calls concurrently |
| `agents/reviewer/agent.py` | Modify | Fix dimension names; run dimension calls concurrently; add cross_artifact_consistency |
| `agents/reviewer/prompts.py` | Modify | Add `cross_artifact_consistency` focus block |
| `api/models.py` | Modify | Add `ColumnContract`, `TableContract` models; add `schema_contracts` to `ExecutionPlan` |
| `agents/planner/prompts.py` | Modify | Add `schema_contracts` to JSON output format; instruct Planner to populate it |
| `agents/planner/agent.py` | Modify | Parse `schema_contracts` in `_parse_plan_json` |

---

## Task 1: Parallelize Generator (DDL / DML / DAG concurrent)

**Files:**
- Modify: `agents/generator/agent.py`

**Background:** `GeneratorAgent.generate()` makes 3 sequential `complete_with_context` calls (DDL → DML → DAG). Each call uses the same `base_blocks` (cached) and only differs in its `task_prompt`. They are completely independent and can run concurrently.

- [ ] **Step 1: Read the current file**

  Read `agents/generator/agent.py` in full to confirm the current sequential structure before making changes.

- [ ] **Step 2: Replace the sequential calls with a ThreadPoolExecutor**

  In `agents/generator/agent.py`, replace lines 53–93 (the three sequential `complete_with_context` calls) with the following parallel implementation:

  ```python
  import concurrent.futures

  # ... keep everything above generate() unchanged ...

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
      human_notes = ctx.human_notes_block()

      tasks = [
          ("DDL", build_ddl_task(ctx.plan, human_notes), ArtifactType.DDL),
          ("DML", build_dml_task(ctx.plan, human_notes), ArtifactType.DML),
          ("DAG", build_dag_task(ctx.plan, human_notes), ArtifactType.DAG),
      ]

      def _call(label_prompt_type):
          label, prompt, art_type = label_prompt_type
          logger.info("Generator: generating %s (reading impl+csv+plan from cache)...", label)
          resp = self._llm.complete_with_context(
              context_blocks=base_blocks,
              task_prompt=prompt,
              system=GENERATOR_SYSTEM,
              max_tokens=8192,
          )
          arts = _extract_artifacts(resp.content, art_type)
          logger.info(
              "Generator %s: %d artifact(s) | %d input tokens (%d cached)",
              label, len(arts), resp.input_tokens, resp.cache_read_tokens,
          )
          return arts

      artifacts: list[GeneratedArtifact] = []
      with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
          futures = [executor.submit(_call, t) for t in tasks]
          for future in concurrent.futures.as_completed(futures):
              artifacts.extend(future.result())

      return artifacts
  ```

- [ ] **Step 3: Verify the import is at the top of the file**

  Ensure `import concurrent.futures` is added at the top of `agents/generator/agent.py`, below the existing `from __future__ import annotations` line and above the other imports. Do NOT add it inside the function.

- [ ] **Step 4: Manual smoke-check**

  From `/home/varun_akarapu/DEAH/core/development/`, run:
  ```bash
  python -c "from agents.generator.agent import GeneratorAgent; print('import OK')"
  ```
  Expected output: `import OK`

- [ ] **Step 5: Commit**

  ```bash
  cd /home/varun_akarapu/DEAH
  git add core/development/agents/generator/agent.py
  git commit -m "perf: parallelize Generator DDL/DML/DAG calls with ThreadPoolExecutor"
  ```

---

## Task 2: Parallelize Optimizer

**Files:**
- Modify: `agents/optimizer/agent.py`

**Background:** `OptimizerAgent.optimize()` has a `for artifact in artifacts` loop where each iteration makes one independent LLM call. For 6+ artifacts this is the single biggest time sink (~13 min sequential). Each call is independent — parallelising with `ThreadPoolExecutor` makes all calls run concurrently.

- [ ] **Step 1: Read the current file**

  Read `agents/optimizer/agent.py` in full.

- [ ] **Step 2: Replace the sequential loop with a concurrent map**

  Replace the `optimize` method body in `agents/optimizer/agent.py` with:

  ```python
  import concurrent.futures

  class OptimizerAgent:
      def __init__(self, llm: BaseLLMClient) -> None:
          self._llm = llm

      def optimize(
          self,
          ctx: SessionContext,
          artifacts: list[GeneratedArtifact],
      ) -> list[GeneratedArtifact]:

          base_blocks: list[ContextBlock] = []
          if ctx.plan is not None:
              base_blocks = [
                  ContextBlock(
                      text=f"## Approved Execution Plan\n{ctx.plan.raw_plan}",
                      label="plan",
                      cacheable=True,
                  )
              ]

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
                  task_prompt=build_optimizer_task(artifact, ctx.human_notes_block()),
                  system=OPTIMIZER_SYSTEM,
                  max_tokens=4096,
              )
              improved = _extract_code(resp.content) or artifact.content
              logger.info(
                  "Optimizer %s: %d input tokens (%d cached)",
                  artifact.file_name, resp.input_tokens, resp.cache_read_tokens,
              )
              return artifact.model_copy(update={"content": improved})

          max_workers = min(len(artifacts), 8)  # cap at 8 to avoid API rate limits
          with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
              futures = {executor.submit(_optimize_one, a): i for i, a in enumerate(artifacts)}
              # Collect results in original order
              results: list[GeneratedArtifact | None] = [None] * len(artifacts)
              for future, idx in futures.items():
                  results[idx] = future.result()

          return [r for r in results if r is not None]
  ```

- [ ] **Step 3: Add the import at the top of the file**

  Ensure `import concurrent.futures` is at the top of `agents/optimizer/agent.py`.

- [ ] **Step 4: Verify import**

  ```bash
  cd /home/varun_akarapu/DEAH/core/development
  python -c "from agents.optimizer.agent import OptimizerAgent; print('import OK')"
  ```
  Expected: `import OK`

- [ ] **Step 5: Commit**

  ```bash
  cd /home/varun_akarapu/DEAH
  git add core/development/agents/optimizer/agent.py
  git commit -m "perf: parallelize Optimizer per-artifact LLM calls with ThreadPoolExecutor"
  ```

---

## Task 3: Parallelize Reviewer + add cross_artifact_consistency dimension (Idea C)

**Files:**
- Modify: `agents/reviewer/prompts.py`
- Modify: `agents/reviewer/agent.py`

**Background:** Two issues to fix simultaneously:
1. `DIMENSIONS` in `agent.py` is `["assumption_audit", "correctness", "security", "performance"]` — these names do NOT match the `_FOCUS` dict keys in `prompts.py` (`syntax`, `audit_compliance`, `data_integrity`, `pii_encryption`). The fallback in `build_review_task` returns "general code quality" for unrecognised names, making the review generic and weak.
2. All 4 (now 5) dimension calls are sequential and independent — parallelize them.
3. Add `cross_artifact_consistency` as a new 5th dimension that explicitly checks SP arg counts, column type parity, and NOT NULL columns across all artifacts.

- [ ] **Step 1: Add `cross_artifact_consistency` focus block to `agents/reviewer/prompts.py`**

  In `agents/reviewer/prompts.py`, add the following entry to the `_FOCUS` dict, after the `"pii_encryption"` entry and before `"logic_preservation"`:

  ```python
  "cross_artifact_consistency": """\
    Compare all artifacts against each other for schema and interface consistency.
    This dimension ONLY looks for cross-file mismatches — do NOT re-flag issues
    already reported in other dimensions.

    CRITICAL:
    - A column's data type in a DDL CREATE TABLE differs from the type declared
      for the same column in a Beam/Dataflow schema dict, BigQuery schema list,
      or pipeline write call in any .py artifact
    - A stored procedure has N IN-parameters but a DAG CALL site passes a
      different number of positional arguments to that procedure
    - A column defined as NOT NULL (REQUIRED mode) in a DDL artifact is never
      written by any INSERT statement, stored procedure, or pipeline write — it
      will cause an INSERT failure at runtime
    - A quarantine / dead-letter table column name in the DDL does not match the
      column name written by the pipeline's dead-letter output (e.g. DDL has
      'error_reason' but pipeline writes 'error_message')
    - A table or column referenced in DML / SP / DAG does not exist in any DDL
      artifact in this set

    WARNING:
    - A column present in the DDL is absent from the Dataflow/Beam schema dict —
      it will default to NULL even if declared NOT NULL in DDL
    - Partition column name or type in DDL differs from the partition field
      specified in Dataflow BigQuery write parameters
    - SP parameter names differ from the variable names passed at the CALL site
      (correctness risk if BigQuery enforces positional matching)

    DO NOT FLAG:
    - Standard ETL metadata columns (source_system, batch_id, load_timestamp,
      load_date) that are in the DDL but absent from source-column mappings —
      these are expected pipeline-added fields
    - Differences between files that belong to separate pipelines / tickets
    - Style differences (camelCase vs snake_case) in comments only""",
  ```

- [ ] **Step 2: Fix dimension names and parallelize in `agents/reviewer/agent.py`**

  Replace the entire `agent.py` content with the corrected version below. Key changes:
  - `DIMENSIONS` updated to match `_FOCUS` keys and include `cross_artifact_consistency`
  - Sequential `for dimension in DIMENSIONS` loop replaced with `ThreadPoolExecutor`

  ```python
  """Self-review agent.

  Token strategy
  ──────────────
  The plan block is already cached by the generator.  A compact artifacts
  summary (each artifact capped at 6 KB) is sent as a single non-cached
  block alongside the cached plan.  One LLM call per review dimension,
  all dimensions run concurrently.

  Human notes are appended to the task prompt — the LLM is asked to verify
  that the human's corrections have been addressed in the generated code.
  """
  from __future__ import annotations
  import concurrent.futures
  import logging
  import re

  from common.llm.base import BaseLLMClient, ContextBlock
  from api.models import (
      GeneratedArtifact, ReviewFinding, ReviewResult, SessionContext, Severity, Verdict,
  )
  from agents.reviewer.prompts import REVIEWER_SYSTEM, build_review_task, build_logic_preservation_task

  logger = logging.getLogger("development.reviewer")

  # Dimension names must match keys in agents/reviewer/prompts._FOCUS
  DIMENSIONS = [
      "syntax",
      "audit_compliance",
      "data_integrity",
      "pii_encryption",
      "cross_artifact_consistency",
  ]
  _MAX_PER_ARTIFACT = 6000


  class ReviewerAgent:
      def __init__(self, llm: BaseLLMClient) -> None:
          self._llm = llm

      def review(
          self,
          ctx: SessionContext,
          artifacts: list[GeneratedArtifact],
      ) -> list[ReviewResult]:
          base_blocks: list[ContextBlock] = []
          if ctx.plan is not None:
              base_blocks = [
                  ContextBlock(
                      text=f"## Approved Execution Plan\n{ctx.plan.raw_plan}",
                      label="plan",
                      cacheable=True,
                  )
              ]

          artifacts_text = "\n\n".join(
              f"### {a.file_name} ({a.artifact_type.value})\n```\n{a.content[:_MAX_PER_ARTIFACT]}\n```"
              for a in artifacts
          )
          artifacts_block = ContextBlock(
              text=f"## Generated Artifacts\n{artifacts_text}",
              label="artifacts_summary",
              cacheable=False,
          )

          def _review_dimension(dimension: str) -> ReviewResult:
              logger.info("Reviewer: %s review...", dimension)
              resp = self._llm.complete_with_context(
                  context_blocks=base_blocks + [artifacts_block],
                  task_prompt=build_review_task(dimension, ctx.human_notes_block()),
                  system=REVIEWER_SYSTEM,
                  max_tokens=4096,
              )
              result = _parse_result(dimension, resp.content)
              logger.info(
                  "Reviewer %s: %s (%d finding(s)) | %d input tokens (%d cached)",
                  dimension, result.verdict.value, len(result.findings),
                  resp.input_tokens, resp.cache_read_tokens,
              )
              return result

          results: list[ReviewResult] = []
          with concurrent.futures.ThreadPoolExecutor(max_workers=len(DIMENSIONS)) as executor:
              futures = {executor.submit(_review_dimension, dim): dim for dim in DIMENSIONS}
              # Preserve dimension order in results
              dim_to_result: dict[str, ReviewResult] = {}
              for future, dim in futures.items():
                  dim_to_result[dim] = future.result()
          results = [dim_to_result[dim] for dim in DIMENSIONS]
          return results

      def review_optimized(
          self,
          ctx: SessionContext,
          original_artifacts: list[GeneratedArtifact],
          optimized_artifacts: list[GeneratedArtifact],
      ) -> list[ReviewResult]:
          """Run standard review dimensions on optimized artifacts, then run
          logic_preservation comparing original vs optimized side-by-side."""
          results = self.review(ctx, optimized_artifacts)

          original_text = "\n\n".join(
              f"### ORIGINAL: {a.file_name} ({a.artifact_type.value})\n"
              f"```\n{a.content[:_MAX_PER_ARTIFACT]}\n```"
              for a in original_artifacts
          )
          optimized_text = "\n\n".join(
              f"### OPTIMIZED: {a.file_name} ({a.artifact_type.value})\n"
              f"```\n{a.content[:_MAX_PER_ARTIFACT]}\n```"
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
          lp_result = _parse_result("logic_preservation", resp.content)
          logger.info(
              "Reviewer logic_preservation: %s (%d finding(s)) | %d input tokens (%d cached)",
              lp_result.verdict.value, len(lp_result.findings),
              resp.input_tokens, resp.cache_read_tokens,
          )
          return results + [lp_result]


  def _parse_result(dimension: str, raw: str) -> ReviewResult:
      upper = raw.upper()
      if "FAIL" in upper and "NOT FAIL" not in upper:
          verdict = Verdict.FAIL
      elif any(k in upper for k in ("CONDITIONAL", "WARNING")):
          verdict = Verdict.CONDITIONAL_PASS
      else:
          verdict = Verdict.PASS

      summary_match = re.search(
          r"##\s*Summary\s*(.*?)(?=\n##|\Z)", raw, re.DOTALL | re.IGNORECASE
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
              file_name=m.group(3).strip(),
              description=m.group(4).strip(),
              suggested_fix=m.group(5).strip(),
          ))

      return ReviewResult(
          dimension=dimension,
          verdict=verdict,
          summary=summary,
          findings=findings,
      )
  ```

- [ ] **Step 3: Verify imports**

  ```bash
  cd /home/varun_akarapu/DEAH/core/development
  python -c "from agents.reviewer.agent import ReviewerAgent, DIMENSIONS; print('Dimensions:', DIMENSIONS)"
  ```
  Expected output:
  ```
  Dimensions: ['syntax', 'audit_compliance', 'data_integrity', 'pii_encryption', 'cross_artifact_consistency']
  ```

- [ ] **Step 4: Commit**

  ```bash
  cd /home/varun_akarapu/DEAH
  git add core/development/agents/reviewer/agent.py core/development/agents/reviewer/prompts.py
  git commit -m "feat: parallelize Reviewer dimensions and add cross_artifact_consistency (Idea C)"
  ```

---

## Task 4: Schema Contracts — Planner emits table/column spec (Idea D)

**Files:**
- Modify: `api/models.py`
- Modify: `agents/planner/prompts.py`
- Modify: `agents/planner/agent.py`
- Modify: `agents/generator/agent.py`

**Background:** The root cause of all 3 SCRUM-75 CRITICALs was that DDL, DML, and DAG were generated without a shared authoritative column spec. The Planner already knows all table schemas from the mapping CSV. Adding a `schema_contracts` field to `ExecutionPlan` creates a single source of truth. The Generator injects it as a ContextBlock into every DML and DAG call so the LLM is forced to match the exact column names and types from the plan.

### Step 4a — Add Pydantic models to `api/models.py`

- [ ] **Step 1: Add `ColumnContract` and `TableContract` models**

  In `api/models.py`, add the following two classes after the existing `ArtifactSpec` class (around line 68) and before `AuditTableSpec`:

  ```python
  class ColumnContract(BaseModel):
      """Authoritative column spec derived from mapping CSV by the Planner."""
      source_column: str = ""
      target_column: str
      target_type: str          # BigQuery type e.g. INT64, STRING, NUMERIC(8,2), TIMESTAMP
      nullable: bool = True     # False = NOT NULL / REQUIRED mode in BigQuery
      transformation: str = ""  # e.g. CAST(EMPLOYEE_ID AS INT64)


  class TableContract(BaseModel):
      """Complete schema for one target table — the single source of truth for all agents."""
      table_fqn: str                          # e.g. verizon-data.verizon_data_deah.stg_employees
      layer: str = ""                         # staging, core, quarantine, audit
      columns: list[ColumnContract] = []
      partition_column: str = ""              # e.g. hire_date
      partition_granularity: str = ""         # DAY, MONTH, YEAR
      cluster_columns: list[str] = []        # e.g. ["employee_id", "job_id"]
  ```

- [ ] **Step 2: Add `schema_contracts` field to `ExecutionPlan`**

  In `api/models.py`, find the `ExecutionPlan` class. Add `schema_contracts` as the last field before `raw_plan`:

  ```python
  class ExecutionPlan(BaseModel):
      """Structured plan produced by the Planner — human-approved before code gen."""
      request_id: str
      sprint: str = ""
      project: str = ""
      summary: str = ""
      services: list[ServiceSpec] = []
      tables: list[TableSpec] = []
      audit_table: AuditTableSpec = Field(default_factory=AuditTableSpec)
      store_proc: StoreProcSpec = Field(default_factory=StoreProcSpec)
      artifacts_to_generate: list[ArtifactSpec] = []
      patterns: list[str] = []
      pii_columns: list[str] = []
      open_blockers: list[str] = []
      clarifying_questions: list[str] = []
      schema_contracts: list[TableContract] = []    # ← NEW
      raw_plan: str = ""
  ```

- [ ] **Step 3: Verify models import**

  ```bash
  cd /home/varun_akarapu/DEAH/core/development
  python -c "from api.models import ExecutionPlan, TableContract, ColumnContract; print('models OK')"
  ```
  Expected: `models OK`

### Step 4b — Update Planner system prompt to emit `schema_contracts`

- [ ] **Step 4: Add `schema_contracts` to the JSON output format in `agents/planner/prompts.py`**

  In `agents/planner/prompts.py`, find the `OUTPUT FORMAT — JSON` section inside `PLANNER_SYSTEM`. After the `"open_blockers"` key in the example JSON, add the `schema_contracts` key. The updated JSON skeleton should include:

  ```
  "schema_contracts": [
    {
      "table_fqn": "<project.dataset.table>",
      "layer": "<staging|core|quarantine|audit>",
      "columns": [
        {
          "source_column": "<SOURCE_COL or empty for metadata>",
          "target_column": "<target_col>",
          "target_type": "<BigQuery type e.g. INT64, STRING, NUMERIC(8,2), TIMESTAMP>",
          "nullable": <true|false>,
          "transformation": "<e.g. CAST(EMPLOYEE_ID AS INT64) or empty>"
        }
      ],
      "partition_column": "<col or empty>",
      "partition_granularity": "<DAY|MONTH|YEAR or empty>",
      "cluster_columns": ["<col1>", "<col2>"]
    }
  ],
  ```

  Also add the following rule to the `ENGINEERING GUARDRAILS` section at the bottom of `PLANNER_SYSTEM`:

  ```
  • SCHEMA CONTRACTS — populate schema_contracts for EVERY table in tables[].
    Each column entry must use the target_data_type from the mapping CSV — never
    invent a type. nullable=false only for columns listed as mandatory in the
    implementation document or NOT NULL in the mapping CSV.
    This is the authoritative spec for Generator, Optimizer, and Reviewer — if
    a column's type here differs from what the Generator writes, the Reviewer
    will flag it as CRITICAL.
  ```

  Find the exact location of `"open_blockers": ["<blocker description>"]` in the PLANNER_SYSTEM string (around line 238) and insert the `schema_contracts` key after `open_blockers`:

  The section currently ends with:
  ```python
    "clarifying_questions": ["[BLOCKER|IMPORTANT|NICE-TO-HAVE] <question>?"],
    "open_blockers": ["<blocker description>"]
  }
  ```

  Change it to:
  ```python
    "clarifying_questions": ["[BLOCKER|IMPORTANT|NICE-TO-HAVE] <question>?"],
    "open_blockers": ["<blocker description>"],
    "schema_contracts": [
      {
        "table_fqn": "<project.dataset.table>",
        "layer": "<staging|core|quarantine|audit>",
        "columns": [
          {
            "source_column": "<SOURCE_COL or empty for metadata>",
            "target_column": "<target_col>",
            "target_type": "<BigQuery type e.g. INT64, STRING, NUMERIC(8,2), TIMESTAMP>",
            "nullable": true,
            "transformation": "<CAST(...) or direct copy or empty>"
          }
        ],
        "partition_column": "<col or empty>",
        "partition_granularity": "<DAY|MONTH|YEAR or empty>",
        "cluster_columns": ["<col1>"]
      }
    ]
  }
  ```

  And at the end of the `ENGINEERING GUARDRAILS` block, append:
  ```python
  • SCHEMA CONTRACTS — populate schema_contracts for EVERY table in tables[].
    Derive column types exclusively from the target_data_type column in the mapping CSV.
    nullable=false only when the implementation document explicitly lists the column
    as mandatory or NOT NULL. Include standard ETL metadata columns (source_system STRING
    NOT NULL, batch_id INT64 NOT NULL, load_timestamp TIMESTAMP NOT NULL, load_date DATE
    NOT NULL) in every staging/quarantine table contract.
    This is the single authoritative schema spec used by Generator, Optimizer, and
    Reviewer. Any type mismatch between this contract and generated code is CRITICAL.
  ```

### Step 4c — Parse `schema_contracts` in `agents/planner/agent.py`

- [ ] **Step 5: Update `_parse_plan_json` to parse schema_contracts**

  In `agents/planner/agent.py`, find `_parse_plan_json`. After the line that builds `store_proc=StoreProcSpec(...)`, add parsing for `schema_contracts`:

  Find:
  ```python
      return ExecutionPlan(
          request_id=data.get("request_id") or request_id,
          sprint=data.get("sprint", ""),
          project=data.get("project", ""),
          summary=data.get("summary", ""),
          services=[ServiceSpec(**s) for s in data.get("services", [])],
          tables=[TableSpec(**t) for t in data.get("tables", [])],
          audit_table=AuditTableSpec(**audit_data) if audit_data else AuditTableSpec(),
          store_proc=StoreProcSpec(**sp_data) if sp_data else StoreProcSpec(),
          artifacts_to_generate=[ArtifactSpec(**a) for a in data.get("artifacts_to_generate", [])],
          patterns=data.get("patterns", []),
          pii_columns=data.get("pii_columns", []),
          clarifying_questions=data.get("clarifying_questions", []),
          open_blockers=data.get("open_blockers", []),
          raw_plan=_json.dumps(data, indent=2),
      )
  ```

  Replace with:
  ```python
      from api.models import ColumnContract, TableContract

      def _parse_columns(cols: list) -> list[ColumnContract]:
          result = []
          for c in cols:
              if isinstance(c, dict):
                  result.append(ColumnContract(
                      source_column=c.get("source_column", ""),
                      target_column=c.get("target_column", ""),
                      target_type=c.get("target_type", "STRING"),
                      nullable=c.get("nullable", True),
                      transformation=c.get("transformation", ""),
                  ))
          return result

      schema_contracts = []
      for sc in data.get("schema_contracts", []):
          if isinstance(sc, dict):
              schema_contracts.append(TableContract(
                  table_fqn=sc.get("table_fqn", ""),
                  layer=sc.get("layer", ""),
                  columns=_parse_columns(sc.get("columns", [])),
                  partition_column=sc.get("partition_column", ""),
                  partition_granularity=sc.get("partition_granularity", ""),
                  cluster_columns=sc.get("cluster_columns", []),
              ))

      return ExecutionPlan(
          request_id=data.get("request_id") or request_id,
          sprint=data.get("sprint", ""),
          project=data.get("project", ""),
          summary=data.get("summary", ""),
          services=[ServiceSpec(**s) for s in data.get("services", [])],
          tables=[TableSpec(**t) for t in data.get("tables", [])],
          audit_table=AuditTableSpec(**audit_data) if audit_data else AuditTableSpec(),
          store_proc=StoreProcSpec(**sp_data) if sp_data else StoreProcSpec(),
          artifacts_to_generate=[ArtifactSpec(**a) for a in data.get("artifacts_to_generate", [])],
          patterns=data.get("patterns", []),
          pii_columns=data.get("pii_columns", []),
          clarifying_questions=data.get("clarifying_questions", []),
          open_blockers=data.get("open_blockers", []),
          schema_contracts=schema_contracts,
          raw_plan=_json.dumps(data, indent=2),
      )
  ```

- [ ] **Step 6: Verify planner agent imports correctly**

  ```bash
  cd /home/varun_akarapu/DEAH/core/development
  python -c "from agents.planner.agent import PlannerAgent; print('planner OK')"
  ```
  Expected: `planner OK`

### Step 4d — Inject schema_contracts into Generator DML and DAG calls

- [ ] **Step 7: Add schema_contracts ContextBlock to `_base_context_blocks` in `agents/generator/agent.py`**

  In `agents/generator/agent.py`, find the `_base_context_blocks` function. Add a 4th block for schema_contracts when they are present:

  Replace:
  ```python
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
  ```

  Replace with:
  ```python
  def _base_context_blocks(ctx: SessionContext) -> list[ContextBlock]:
      blocks = [
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

      # Schema contracts — inject as authoritative spec so DML/DAG LLM calls
      # cannot deviate from the column names and types the Planner established.
      if ctx.plan and ctx.plan.schema_contracts:
          import json as _json
          contracts_text = _json.dumps(
              [sc.model_dump() for sc in ctx.plan.schema_contracts],
              indent=2,
          )
          blocks.append(ContextBlock(
              text=(
                  "## Schema Contracts — AUTHORITATIVE COLUMN SPEC\n"
                  "These are the exact column names, BigQuery types, and nullability for every "
                  "table in this pipeline. You MUST use these types exactly in all DDL, DML, "
                  "stored procedures, and pipeline schema definitions. Any deviation is a bug.\n\n"
                  f"```json\n{contracts_text}\n```"
              ),
              label="schema_contracts",
              cacheable=True,
          ))

      return blocks
  ```

- [ ] **Step 8: Verify generator imports correctly**

  ```bash
  cd /home/varun_akarapu/DEAH/core/development
  python -c "from agents.generator.agent import GeneratorAgent, _base_context_blocks; print('generator OK')"
  ```
  Expected: `generator OK`

- [ ] **Step 9: Commit all Task 4 changes**

  ```bash
  cd /home/varun_akarapu/DEAH
  git add core/development/api/models.py \
          core/development/agents/planner/prompts.py \
          core/development/agents/planner/agent.py \
          core/development/agents/generator/agent.py
  git commit -m "feat: add schema_contracts to ExecutionPlan — Planner emits authoritative column spec for all agents (Idea D)"
  ```

---

## Task 5: Final verification and push

- [ ] **Step 1: Full import chain check**

  ```bash
  cd /home/varun_akarapu/DEAH/core/development
  python -c "
  from api.models import ExecutionPlan, TableContract, ColumnContract
  from agents.planner.agent import PlannerAgent
  from agents.generator.agent import GeneratorAgent
  from agents.optimizer.agent import OptimizerAgent
  from agents.reviewer.agent import ReviewerAgent, DIMENSIONS
  print('All imports OK')
  print('Reviewer dimensions:', DIMENSIONS)
  "
  ```
  Expected:
  ```
  All imports OK
  Reviewer dimensions: ['syntax', 'audit_compliance', 'data_integrity', 'pii_encryption', 'cross_artifact_consistency']
  ```

- [ ] **Step 2: Verify schema_contracts field exists on ExecutionPlan**

  ```bash
  cd /home/varun_akarapu/DEAH/core/development
  python -c "
  from api.models import ExecutionPlan
  plan = ExecutionPlan(request_id='test')
  print('schema_contracts field:', plan.schema_contracts)
  "
  ```
  Expected: `schema_contracts field: []`

- [ ] **Step 3: Push to origin/sanay1**

  ```bash
  cd /home/varun_akarapu/DEAH
  git push origin sanay1
  ```

---

## Expected outcome after all tasks

| Metric | Before | After |
|---|---|---|
| Generator wall time | ~6 min (3 sequential) | ~2 min (3 concurrent) |
| Optimizer wall time | ~13 min (7 sequential) | ~2-3 min (7 concurrent) |
| Reviewer wall time | ~7 min (4 sequential) | ~2 min (5 concurrent) |
| **Total Stage 1→CP2** | **~27 min** | **~10-11 min** |
| Cross-artifact type mismatches | Caught only by human | Caught by `cross_artifact_consistency` at Checkpoint 2 |
| SP arg count mismatches | Caught only by human | Caught by `cross_artifact_consistency` at Checkpoint 2 |
| Type drift DDL vs pipeline | Happens silently | Prevented by schema_contracts ContextBlock in Generator |
