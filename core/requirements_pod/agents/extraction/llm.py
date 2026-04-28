"""Stage 3 — Parallel LLM extraction with retry and concurrency control."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import anthropic

from core.utilities.llm.provider_base import BaseLLMProvider
from .chunker import Chunk
from .config import ExtractionConfig
from .exceptions import LLMAuthError, LLMQuotaError

logger = logging.getLogger(__name__)

# Exact system prompt from spec — do not paraphrase or shorten
SYSTEM_PROMPT = """\
You are a precise Jira task extraction expert analyzing conversations, call transcripts, and documents.
Extract every actionable task from the text.
Return ONLY a valid JSON array with no markdown fences, no preamble, no explanation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY FIELD DETECTION — CONVERSATIONAL INTELLIGENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The input may be a conversation, call transcript, meeting note, or unstructured document.
Mandatory fields are often NOT labeled — they appear naturally in speech and sentences.
For EACH mandatory field, scan the ENTIRE input for implicit or indirect mentions:

  projectName
    Detect: any named initiative, system, platform, product, workstream, or programme.
    Examples: "in the Network Ops platform", "for the VZ billing project",
              "we're building the onboarding portal" → projectName = "onboarding portal"

  requirementType
    Detect: the INTENT behind the task, not the word itself.
    Map natural language to one of [New_Dvlp, Enhancement, Bug_Fix, Integration, Migration, Configuration, Maintenance]:
    • "it's broken / throws an error / not working" → Bug_Fix
    • "add a new feature / build from scratch / we don't have this yet" → New_Dvlp
    • "improve / speed up / extend / add to existing" → Enhancement
    • "connect to / integrate with / sync data from" → Integration
    • "move from / upgrade / switch to / port to" → Migration
    • "set up / configure / enable / deploy settings" → Configuration
    • "routine / scheduled / cleanup / monitor" → Maintenance

  stakeholderName
    Detect: any person, role, team, or department who owns, requests, approves, or is affected.
    Examples: "Alice needs this done", "the finance team is waiting",
              "David from compliance raised this", "PM requested" → extract name/role

  assignee
    Detect: the developer, engineer, or implementer who will BUILD or implement the task.
    This is NOT the reporter or stakeholder — it is the person doing the technical work.
    Examples: "Shailendra will implement this", "assigned to John",
              "dev team: Alice will handle it", "Shailendra from development" → assignee = "Shailendra"
    Look for: developer names, "will implement", "will handle", "assigned to", "dev/engineer name"

  startDate
    Detect: any explicit story level start date for the work or sprint.
    Only extract dates that apply to the overall work, project, or sprint.
    Do NOT extract task-level start dates (dates for individual implementation steps).
    Examples: "sprint starts April 21", "begins on 2026-04-21", "starting next Monday (April 21)"
    SPRINT RULE: If the text explicitly says "sprint starts [date]" or "sprint begins [date]"
    → set startDate = that date AND set dueDate = startDate + 13 days.
    Examples: "sprint starts April 21" → startDate="2026-04-21", dueDate="2026-05-05"
    Format: YYYY-MM-DD or null if not mentioned.

  dueDate
    Detect: any explicit story level deadline, story level end date, or sprint end.
    Only extract dates that apply to the overall work, project, or sprint.
    Do NOT extract task-level end dates (dates for individual implementation steps).
    Examples: "deadline May 1", "must be delivered by April 30", "sprint ends May 4"
    If there are no explicit end date then SPRINT RULE: If the text explicitly says "sprint starts [date]" or "sprint begins [date]"
    → set startDate = that date AND set dueDate = startDate + 13 days.
    Examples: "sprint starts April 21" → startDate="2026-04-21", dueDate="2026-05-05"
    Format: YYYY-MM-DD or null if not mentioned.


  objective
    Detect: the WHY behind the task — problem being solved, goal, or need.
    Examples: "users are unable to log in", "we're losing data during export",
              "the dashboard is too slow", "we need to support EU customers"

  expectedOutcome
    Detect: what DONE looks like — desired state, deliverable, or result.
    Examples: "once fixed, login should work", "the report should download in under 2s",
              "customers should receive an email confirmation"

  connectionsDbDetails
    Detect: any database, table, schema, API, service, pipeline, or system name mentioned.
    Examples: "hits the users table", "calls the payments API", "reads from S3",
              "syncs with Salesforce", "queries the reporting schema"

  successConditions
    Detect: conditions that CONFIRM the task is working correctly.
    Examples: "it should return a 200", "all tests must pass", "the file must download"

  validationRules
    Detect: constraints, rules, or checks that must hold.
    Examples: "only admins can access", "must not exceed 5MB", "date cannot be in the past"

  priority
    Detect: urgency, criticality, or deadline language even if the word "priority" is never used.
    • "blocking everyone / production is down / critical" → Critical
    • "needed by end of week / important / high impact" → High
    • "when you get a chance / nice to have / low urgency" → Low
    • anything else → Medium

If a field was NOT mentioned at all — explicitly or implicitly — set it to null or [].
Do NOT fabricate or infer beyond what the text states.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ISSUE TYPE CLASSIFICATION — USE THESE RULES STRICTLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  "Bug"   — something is broken, failing, or incorrect RIGHT NOW.
            Signals: "it's broken", "throws an error", "not working", "fix the bug", "regression"

  "Epic"  — a large initiative or programme that CONTAINS multiple stories/tasks.
            Signals: "Q2 programme", "platform initiative", "major release", used to group other work.
            Use sparingly — only when explicitly framed as a container or programme.

  "Story" — the TOP-LEVEL REQUIREMENT describing WHAT the business or system needs to achieve.
            This is the overall goal or capability being delivered — not the individual steps.
            Signals: overall project goal, business capability, system-level requirement,
                     "we need X system/pipeline/platform/integration", "the business needs",
                     "as a [role] I need", "users should be able to"
            Examples: "Build MySQL to BigQuery data ingestion pipeline" → Story
                        (this is the overall capability; the Implement X tasks are HOW to do it)
                      "Build a dashboard showing pipeline status" → Story
                      "Create a self-service portal for data requests" → Story
                      "Integrate CRM data with the data warehouse" → Story
                      "Migrate legacy billing system to the new platform" → Story

            STORY vs TASK TEST: Ask — "Is this the overall goal, or a specific step inside the goal?"
            • Overall goal → Story    • Specific technical step → Task

  "Task"  — a SPECIFIC TECHNICAL STEP performed to deliver a Story. Describes HOW.
            Signals: "implement [specific load/sync/pipeline]", "set up [specific component]",
                     "configure [specific service]", "write [specific script/test]",
                     "deploy [specific service]", "load data from X to Y table"
            Examples: "Implement one-time full historical load from MySQL to BigQuery" → Task
                      "Implement scheduled incremental load pipeline" → Task
                      "Configure Cloud Composer DAG for daily sync" → Task
                      "Set up monitoring and alerting for pipeline failures" → Task
                      "Write unit tests for the extraction module" → Task

            ALWAYS ask: is there a broader Story that this task is a step toward?
            If yes → this is a Task. Create the Story separately if not already extracted.

  KEY RULE: "Implement [specific step]", "Set up [component]", "Configure [service]",
  "Deploy [service]", "Write [script/test]" → always "Task".
  "Build [system/pipeline/platform]", "Create [capability/integration]",
  "Migrate [system] to [system]" at the PROJECT GOAL level → "Story".
  The same word ("Build", "Create") can mean Story (overall goal) or Task (specific step)
  depending on scope — use the STORY vs TASK TEST above to decide.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK CONSOLIDATION — AVOID OVER-FRAGMENTATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Create the FEWEST tasks that still cover all requirements.
  Each task should represent 1–3 days of developer work with independently
  deliverable value. Do NOT split a coherent concern into micro-tasks.

  CONSOLIDATION RULES:
  1. Sub-steps implied by a larger task → merge into the parent.
     BAD:  "Implement full historical load from MySQL"
           "Implement chunking and batching strategy for large MySQL table load"
           "Implement retry logic for failed MySQL extractions"
     GOOD: "Implement full historical load from MySQL to BigQuery"
           (chunking, batching, retries are implementation details — not separate tasks)

  2. Same concern, different angles → one task.
     BAD:  "Set up pipeline monitoring"
           "Configure alerting for pipeline failures"
           "Add audit logging for pipeline runs"
     GOOD: "Set up pipeline monitoring, alerting, and audit logging"

  3. Data quality / validation concerns → one task per pipeline stage.
     BAD:  "Validate row counts after load"
           "Check for null values in required fields"
           "Validate schema compatibility between source and target"
     GOOD: "Implement data quality validation for the load pipeline"
           (row count checks, null checks, schema validation are sub-criteria)

  4. Configuration that is part of a larger setup → include in the setup task.
     BAD:  "Set up Cloud Composer DAG"
           "Configure DAG retry policy"
           "Set up DAG scheduling"
     GOOD: "Set up and configure Cloud Composer DAG for daily sync"

  STORY + TASKS STRUCTURE — every output should have at least one Story:
    • If the document describes a project or initiative, extract ONE Story for the
      overall goal, then extract Tasks for each major implementation step.
    • If you find only Tasks and no Story, create a Story for the overall project
      goal derived from the document's main purpose.
    • Example for a MySQL→BigQuery pipeline document:
        Story : "Build MySQL to BigQuery data ingestion pipeline"
        Task  : "Implement one-time full historical load from MySQL to BigQuery"
        Task  : "Implement scheduled incremental load pipeline"
        Task  : "Set up pipeline monitoring, alerting, and data quality validation"

  GRANULARITY TEST — before emitting a task, ask:
    • Could a senior engineer complete this in less than half a day?
      If YES and it belongs to a larger task already on the list → merge it in.
    • Is this task's only purpose to implement a detail of another task?
      If YES → merge it in as an acceptance criterion, not a separate task.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Each element must have exactly these fields:
- "summary": string ≤80 chars, starts with imperative verb (Build/Fix/Create/Add/Implement/Update/Remove/Design/Write/Test/Configure/Migrate/Refactor/Integrate)
- "description": string with specific details
- "issuetype": "Story"|"Task"|"Bug"|"Epic" — apply ISSUE TYPE CLASSIFICATION rules above
- "priority": "Critical"|"High"|"Medium"|"Low"
- "labels": string[] ≤5 items, no spaces (use hyphens)
- "storyPoints": Fibonacci integer (1,2,3,5,8,13,21)
- "acceptanceCriteria": string[] of specific testable criteria
- "extractionConfidence": float 0.0–1.0
- "temporalMarkers": string[] of temporal language found in the text
- "supersedes": boolean, true if this task clearly overrides a prior statement
- "reporter": string or null, name of the person who reported or created this task if explicitly mentioned
- "assignee": string or null — use MANDATORY FIELD DETECTION rules above (the developer/implementer)
- "sprint": string or null, sprint or iteration name if explicitly mentioned in the text
- "fixVersion": string or null, release or version name if explicitly mentioned in the text
- "startDate": string or null, STORY-LEVEL start date YYYY-MM-DD — sprint/initiative scope only, not task-level; null if not explicitly stated
- "dueDate": string or null, STORY-LEVEL due date YYYY-MM-DD — sprint/initiative scope only, not task-level; null if not explicitly stated
- "projectName": string or null — use MANDATORY FIELD DETECTION rules above
- "requirementType": one of ["New_Dvlp","Enhancement","Bug_Fix","Integration","Migration","Configuration","Maintenance"] or null — use MANDATORY FIELD DETECTION rules above
- "stakeholderName": string or null — use MANDATORY FIELD DETECTION rules above
- "objective": string or null — use MANDATORY FIELD DETECTION rules above
- "expectedOutcome": string or null — use MANDATORY FIELD DETECTION rules above
- "connectionsDbDetails": string or null — use MANDATORY FIELD DETECTION rules above
- "successConditions": string[] — use MANDATORY FIELD DETECTION rules above
- "validationRules": string[] — use MANDATORY FIELD DETECTION rules above
- "scheduleInterval": ALWAYS provide a value — one of ["hourly","daily","weekly","on-demand"]:
    • "every hour / run hourly / real-time / triggered each hour" → "hourly"
    • "daily batch / run every day / nightly / overnight / each day" → "daily"
    • "weekly report / every week / once a week / sprint cadence" → "weekly"
    • "on request / manually triggered / ad hoc / user-initiated / REST call" → "on-demand"
    • if no schedule is mentioned anywhere in the text → "on-demand" (default)
- "assumedFields": string[] — list the camelCase names of every field you populated based on
    ASSUMPTION or INFERENCE rather than an EXPLICIT statement in the text.
    Include a field name here if you:
    • Used a default because nothing was mentioned  (e.g. scheduleInterval → "on-demand")
    • Guessed or inferred a value from implied context  (e.g. priority → "Medium" because unstated)
    • Derived a name/value from indirect clues  (e.g. projectName from a product acronym)
    Do NOT include a field if the text directly and clearly states its value.
    Examples: ["scheduleInterval","priority"]  or  []  if everything was explicitly stated.
If project context is provided, use it to expand acronyms, assign labels, calibrate priority.
Return [] if no tasks found. Never return null.\
"""

_FIBONACCI = {1, 2, 3, 5, 8, 13, 21}

# Keywords that indicate exhausted billing credit rather than a transient rate limit
_BILLING_KEYWORDS = ("credit balance", "usage limit", "billing", "quota", "insufficient_quota")


def _is_billing_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in _BILLING_KEYWORDS)

_ISSUETYPE_NORM: dict[str, str] = {
    "bug": "Bug", "story": "Story", "task": "Task",
    "subtask": "Task", "sub-task": "Task", "epic": "Epic",
}


@dataclass
class RawTask:
    summary: str
    description: str
    issuetype: str
    priority: str
    labels: list[str]
    story_points: int
    acceptance_criteria: list[str]
    extraction_confidence: float
    temporal_markers: list[str]
    supersedes: bool
    file_index: int
    chunk_index: int
    source_indices: list[int]  # starts as [file_index]
    reporter: Optional[str] = None
    assignee: Optional[str] = None
    sprint: Optional[str] = None
    fix_version: Optional[str] = None
    start_date: Optional[str] = None    # ISO format YYYY-MM-DD
    due_date: Optional[str] = None      # ISO format YYYY-MM-DD
    project_name: Optional[str] = None
    requirement_type: Optional[str] = None
    stakeholder_name: Optional[str] = None
    objective: Optional[str] = None
    expected_outcome: Optional[str] = None
    connections_db_details: Optional[str] = None
    success_conditions: list[str] = field(default_factory=list)
    validation_rules: list[str] = field(default_factory=list)
    schedule_interval: Optional[str] = None
    assumed_fields: list[str] = field(default_factory=list)   # snake_case field names assumed by LLM


def _build_user_message(chunk: Chunk, project_context: str) -> str:
    if project_context and project_context.strip():
        return (
            f"PROJECT CONTEXT:\n{project_context}\n\n"
            f"---\nEXTRACT TASKS FROM:\n{chunk.text}"
        )
    return f"EXTRACT TASKS FROM:\n{chunk.text}"


def _nearest_fibonacci(val) -> int:
    try:
        n = int(val)
        return min(_FIBONACCI, key=lambda x: abs(x - n)) if n not in _FIBONACCI else n
    except (TypeError, ValueError):
        return 3


def _parse_item(item: dict, file_index: int, chunk_index: int) -> RawTask:
    """Parse one dict from LLM response into a RawTask.

    Handles both the new pipeline schema (summary/issuetype/storyPoints)
    and the legacy schema (task_heading/task_type) so that existing mock
    fixtures continue to work without modification.
    """
    summary = item.get("summary") or item.get("task_heading") or "Untitled Task"
    summary = str(summary)[:80]

    raw_issuetype = item.get("issuetype") or item.get("task_type") or "task"
    issuetype = _ISSUETYPE_NORM.get(str(raw_issuetype).lower(), "Task")

    priority = item.get("priority", "Medium")
    if priority not in ("Critical", "High", "Medium", "Low"):
        priority = "Medium"

    labels = [str(l) for l in (item.get("labels") or [])][:5]
    story_points = _nearest_fibonacci(item.get("storyPoints") or item.get("story_points"))

    ac = item.get("acceptanceCriteria") or item.get("acceptance_criteria") or []
    acceptance_criteria = [str(c) for c in ac]

    conf = item.get("extractionConfidence") or item.get("extraction_confidence") or 0.5
    try:
        extraction_confidence = max(0.0, min(1.0, float(conf)))
    except (TypeError, ValueError):
        extraction_confidence = 0.5

    tm = item.get("temporalMarkers") or item.get("temporal_markers") or []
    temporal_markers = [str(m) for m in tm]

    supersedes = bool(item.get("supersedes", False))

    reporter = item.get("reporter") or None
    if reporter:
        reporter = str(reporter)[:256]

    assignee = item.get("assignee") or None
    if assignee:
        assignee = str(assignee)[:256]

    start_date = item.get("startDate") or item.get("start_date") or None
    if start_date:
        start_date = str(start_date)[:32]

    due_date = item.get("dueDate") or item.get("due_date") or None
    if due_date:
        due_date = str(due_date)[:32]


    sprint = item.get("sprint") or None
    if sprint:
        sprint = str(sprint)[:256]

    fix_version = item.get("fixVersion") or item.get("fix_version") or None
    if fix_version:
        fix_version = str(fix_version)[:256]

    project_name = item.get("projectName") or None
    if project_name:
        project_name = str(project_name)[:256]

    _REQ_TYPES = {"New_Dvlp", "Enhancement", "Bug_Fix", "Integration", "Migration", "Configuration", "Maintenance"}
    requirement_type = item.get("requirementType") or None
    if requirement_type and str(requirement_type) not in _REQ_TYPES:
        requirement_type = None

    stakeholder_name = item.get("stakeholderName") or None
    if stakeholder_name:
        stakeholder_name = str(stakeholder_name)[:256]

    objective = item.get("objective") or None
    expected_outcome = item.get("expectedOutcome") or None
    connections_db_details = item.get("connectionsDbDetails") or None

    success_conditions = [str(c) for c in (item.get("successConditions") or [])]
    validation_rules = [str(r) for r in (item.get("validationRules") or [])]

    _SCHEDULE_VALUES = {"hourly", "daily", "weekly", "on-demand"}
    schedule_interval = item.get("scheduleInterval") or None
    if schedule_interval and str(schedule_interval).lower() not in _SCHEDULE_VALUES:
        schedule_interval = None
    elif schedule_interval:
        schedule_interval = str(schedule_interval).lower()

    # Convert camelCase assumed field names to snake_case
    _CAMEL_TO_SNAKE = {
        "scheduleInterval": "schedule_interval",
        "projectName": "project_name",
        "requirementType": "requirement_type",
        "stakeholderName": "stakeholder_name",
        "objective": "objective",
        "expectedOutcome": "expected_outcome",
        "connectionsDbDetails": "connections_db_details",
        "successConditions": "success_conditions",
        "validationRules": "validation_rules",
        "priority": "priority",
        "assignee": "assignee",
        "storyPoints": "story_points",
        "acceptanceCriteria": "acceptance_criteria",
        "startDate": "start_date",
        "dueDate": "due_date",
        "reporter": "reporter",
        "sprint": "sprint",
        "fixVersion": "fix_version",
    }
    raw_assumed = item.get("assumedFields") or []
    assumed_fields = [
        _CAMEL_TO_SNAKE.get(f, f) for f in raw_assumed
        if isinstance(f, str)
    ]

    return RawTask(
        summary=summary,
        description=str(item.get("description", "")),
        issuetype=issuetype,
        priority=priority,
        labels=labels,
        story_points=story_points,
        acceptance_criteria=acceptance_criteria,
        extraction_confidence=extraction_confidence,
        temporal_markers=temporal_markers,
        supersedes=supersedes,
        file_index=file_index,
        chunk_index=chunk_index,
        source_indices=[file_index],
        reporter=reporter,
        assignee=assignee,
        sprint=sprint,
        fix_version=fix_version,
        start_date=start_date,
        due_date=due_date,
        project_name=project_name,
        requirement_type=requirement_type,
        stakeholder_name=stakeholder_name,
        objective=objective,
        expected_outcome=expected_outcome,
        connections_db_details=connections_db_details,
        success_conditions=success_conditions,
        validation_rules=validation_rules,
        schedule_interval=schedule_interval,
        assumed_fields=assumed_fields,
    )


async def extract_chunk(
    chunk: Chunk,
    project_context: str,
    config: ExtractionConfig,
    llm: BaseLLMProvider,
    semaphore: asyncio.Semaphore,
) -> list[RawTask]:
    """Extract tasks from a single chunk, with exponential-backoff retry."""
    user_msg = _build_user_message(chunk, project_context)

    for attempt in range(config.retry_attempts):
        try:
            async with semaphore:
                raw_text = await llm.call_raw(SYSTEM_PROMPT, user_msg)

            # Strip accidental markdown fences
            stripped = raw_text.strip()
            logger.info(
                "extract_chunk fi=%d ci=%d: call_raw returned %d chars, first 200: %r",
                chunk.file_index, chunk.chunk_index, len(stripped), stripped[:200],
            )
            if stripped.startswith("```"):
                lines = stripped.split("\n")
                lines = [ln for ln in lines if not ln.strip().startswith("```")]
                stripped = "\n".join(lines).strip()

            if not stripped:
                logger.warning(
                    "extract_chunk fi=%d ci=%d: empty response from LLM",
                    chunk.file_index, chunk.chunk_index,
                )
                return []

            # Use raw_decode so trailing text after the JSON array (e.g. explanation
            # text appended by the Claude Agent SDK) does not cause "Extra data" errors.
            # If the response has preamble text before the JSON (e.g. "Here are the tasks:\n[...]"),
            # scan forward to find the first '[' or '{' and start parsing from there.
            decoder = json.JSONDecoder()
            parse_start = 0
            if stripped and stripped[0] not in ("[", "{"):
                bracket_pos = stripped.find("[")
                if bracket_pos == -1:
                    bracket_pos = stripped.find("{")
                if bracket_pos != -1:
                    logger.info(
                        "extract_chunk fi=%d ci=%d: preamble detected, skipping %d chars to JSON start",
                        chunk.file_index, chunk.chunk_index, bracket_pos,
                    )
                    parse_start = bracket_pos
            items, _ = decoder.raw_decode(stripped, parse_start)
            if not isinstance(items, list):
                logger.warning(
                    "Chunk fi=%d ci=%d: expected JSON array, got %s — treating as empty",
                    chunk.file_index, chunk.chunk_index, type(items).__name__,
                )
                return []
            logger.info(
                "extract_chunk fi=%d ci=%d: parsed %d task(s) from response",
                chunk.file_index, chunk.chunk_index, len(items),
            )

            return [_parse_item(item, chunk.file_index, chunk.chunk_index) for item in items]

        except json.JSONDecodeError as exc:
            logger.warning(
                "Chunk fi=%d ci=%d JSON parse failed: %s",
                chunk.file_index, chunk.chunk_index, exc,
            )
            return []

        except anthropic.AuthenticationError as exc:
            # Non-retryable: a wrong key will not fix itself across attempts.
            raise LLMAuthError(
                "Invalid Anthropic API key. Verify ANTHROPIC_API_KEY in your .env configuration."
            ) from exc

        except anthropic.RateLimitError as exc:
            if _is_billing_error(exc):
                # Non-retryable: account has no credits remaining.
                raise LLMQuotaError(
                    "Anthropic account credits are exhausted. "
                    "Add credits at console.anthropic.com and retry."
                ) from exc
            # Transient rate limit — retry with backoff.
            if attempt < config.retry_attempts - 1:
                wait_s = config.retry_base_ms * (2 ** attempt) / 1000
                logger.warning(
                    "Chunk fi=%d ci=%d attempt %d/%d rate-limited — retrying in %.1fs",
                    chunk.file_index, chunk.chunk_index,
                    attempt + 1, config.retry_attempts, wait_s,
                )
                await asyncio.sleep(wait_s)
            else:
                raise LLMQuotaError(
                    "Anthropic API rate limit exceeded after all retry attempts. "
                    "Wait a moment and try again."
                ) from exc

        except (anthropic.APIError, OSError) as exc:
            if attempt < config.retry_attempts - 1:
                wait_s = config.retry_base_ms * (2 ** attempt) / 1000
                logger.warning(
                    "Chunk fi=%d ci=%d attempt %d/%d failed (%s) — retrying in %.1fs",
                    chunk.file_index, chunk.chunk_index,
                    attempt + 1, config.retry_attempts, exc, wait_s,
                )
                await asyncio.sleep(wait_s)
            else:
                logger.error(
                    "Chunk fi=%d ci=%d failed after %d attempts: %s",
                    chunk.file_index, chunk.chunk_index, config.retry_attempts, exc,
                )
                return []

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Unexpected error in chunk fi=%d ci=%d: %s",
                chunk.file_index, chunk.chunk_index, exc,
            )
            return []

    return []


async def extract_all(
    chunks: list[Chunk],
    project_context: str,
    config: ExtractionConfig,
    llm: BaseLLMProvider,
    on_chunk_done: Optional[Callable[[int, int], None]] = None,
) -> list[RawTask]:
    """Fan out extraction across all chunks with a shared semaphore.

    Fatal errors (LLMAuthError, LLMQuotaError) from any chunk are re-raised
    immediately so the caller can surface them to the user.

    on_chunk_done(done, total) is called after each chunk completes.
    """
    semaphore = asyncio.Semaphore(config.max_concurrent)
    total = len(chunks)
    done_counter = [0]

    async def _wrapped(chunk: Chunk) -> list[RawTask]:
        result = await extract_chunk(chunk, project_context, config, llm, semaphore)
        done_counter[0] += 1
        if on_chunk_done:
            on_chunk_done(done_counter[0], total)
        return result

    results = await asyncio.gather(
        *(_wrapped(chunk) for chunk in chunks),
        return_exceptions=True,
    )
    # Re-raise the first fatal error encountered (auth / quota), which should
    # abort the whole pipeline rather than silently returning 0 tasks.
    for result in results:
        if isinstance(result, (LLMAuthError, LLMQuotaError)):
            raise result
    return [task for chunk_tasks in results if isinstance(chunk_tasks, list) for task in chunk_tasks]
