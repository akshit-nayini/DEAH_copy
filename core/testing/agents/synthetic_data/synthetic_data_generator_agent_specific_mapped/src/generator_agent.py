"""
generator_agent.py
------------------
Claude-powered synthetic data generator for mapping-based profiles.

Key difference from previous version:
  - No sample data available — Claude generates purely from:
      * column name
      * BQ target data type
      * transformation_logic (e.g. CAST(EMAIL AS STRING))
      * notes (semantic description)
      * is_partition_column / is_cluster_column flags

Uses core/utilities/llm factory (AnthropicLLMClient) instead of
calling the Anthropic SDK directly — consistent with team standards.

The llm client is injected — generator never imports a specific provider.
"""

import json
from datetime import date, timedelta
from typing import Any, Dict, List

# core/utilities/llm — team's provider-agnostic LLM utility
from core.utilities.llm.base import BaseLLMClient, ContextBlock


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_context_blocks(profile: List[Dict], table_name: str) -> List[ContextBlock]:
    """
    Build cacheable context blocks for the column profile.
    These are cached server-side by Anthropic so subsequent
    batch calls for the same table reuse the cached context.
    """
    profile_summary = []
    for col in profile:
        profile_summary.append({
            "column":               col["name"],
            "bq_type":              col["bq_type"],
            "base_type":            col["base_type"],
            "transformation_logic": col["transformation_logic"],
            "is_partition_column":  col["is_partition_column"],
            "is_cluster_column":    col["is_cluster_column"],
            "notes":                col["notes"],
            "source_column":        col.get("source_column", ""),
        })

    return [
        ContextBlock(
            text=(
                f"## Target Table\n{table_name}\n\n"
                f"## Column Profile (from design team mapping)\n"
                f"{json.dumps(profile_summary, indent=2)}"
            ),
            label="column_profile",
            cacheable=True,   # cached — same for all batches of this table
        )
    ]


def _build_task_prompt(
    count: int,
    table_name: str,
    from_date: str,
    to_date: str,
) -> str:
    return f"""Generate exactly {count} realistic synthetic data rows for BigQuery table "{table_name}".

DATE RANGE: {from_date} to {to_date}

GENERATION RULES — follow strictly:

1. DATA TYPES — use exact BQ types from the profile:
   - INT64          → integer numbers
   - NUMERIC/FLOAT64→ decimal numbers (2 decimal places)
   - STRING         → text values
   - DATE           → "YYYY-MM-DD" format
   - DATETIME       → "YYYY-MM-DD HH:MM:SS" format
   - TIMESTAMP      → "YYYY-MM-DD HH:MM:SS" format
   - BOOL           → true or false

2. TRANSFORMATION LOGIC — understand and respect it:
   - CAST(X AS INT64)    → value must be a valid integer
   - CAST(X AS NUMERIC)  → value must be a valid decimal
   - CAST(X AS DATE)     → value must be a valid date in YYYY-MM-DD
   - CAST(X AS TIMESTAMP)→ value must be a valid timestamp
   - CAST(X AS STRING)   → value is a string
   - Direct mapping (no CAST) → value matches source type

3. COLUMN SEMANTICS — use notes + column name to generate realistic values:
   - employee_id     → unique sequential integers (e.g. 1001, 1002...)
   - first_name      → real human first names
   - last_name       → real human last names
   - email           → realistic email format (firstname.lastname@company.com)
   - phone_number    → proper phone format (+1-XXX-XXX-XXXX)
   - hire_date       → dates within {from_date} to {to_date}
   - salary          → realistic salary range (30000.00 to 250000.00)
   - commission_pct  → decimal between 0.00 and 0.40 (nullable — some can be null)
   - manager_id      → integer referencing another employee_id (nullable for top-level)
   - department_id   → integer 10–200 range
   - status          → one of: active, inactive, on_leave, terminated
   - job_id          → realistic job codes (e.g. IT_PROG, SA_MAN, FI_ACCOUNT)
   - created_date    → timestamp within date range
   - updated_date    → timestamp >= created_date

4. PARTITION columns → dates/timestamps must be within {from_date} to {to_date}

5. CLUSTER columns → values should have good cardinality (not all the same)

6. NULLABLE columns (noted in notes as "nullable") → ~10% of values can be JSON null

7. DIVERSITY → do not repeat the same value across rows — keep data realistic and varied

8. DO NOT use military alphabet words (no foxtrot, tango, bravo, kilo, alpha etc.)

Return ONLY a JSON array of exactly {count} row objects.
Keys must exactly match the column names from the profile.
No markdown fences, no explanation — raw JSON array only.
"""


# ── Main generator ─────────────────────────────────────────────────────────────

def generate_rows(
    profile: List[Dict],
    table_name: str,
    num_records: int,
    from_date: str,
    to_date: str,
    llm: BaseLLMClient,
    batch_size: int = 50,
) -> List[Dict[str, Any]]:
    """
    Generate synthetic rows using Claude via the team's LLM utility.

    Parameters
    ----------
    profile     : column profile from schema_builder.build_profile()
    table_name  : BQ target table name
    num_records : total rows to generate
    from_date   : start of date range (YYYY-MM-DD)
    to_date     : end of date range (YYYY-MM-DD)
    llm         : BaseLLMClient instance from core/utilities/llm factory
    batch_size  : rows per API call (default 50)

    Returns
    -------
    List of row dicts — keys = column names from mapping.
    """
    all_rows: List[Dict[str, Any]] = []
    batches = (num_records + batch_size - 1) // batch_size

    # Build cacheable context blocks once — reused across all batches
    context_blocks = _build_context_blocks(profile, table_name)

    system_prompt = (
        "You are a BigQuery synthetic data generation expert. "
        "You generate realistic, properly typed data based on column definitions "
        "from design team mapping files. You always respect BQ data types and "
        "transformation logic. You never use placeholder or gibberish values."
    )

    for b in range(batches):
        count = min(batch_size, num_records - len(all_rows))
        print(f"    Batch {b + 1}/{batches}  —  generating {count} rows via Claude...")

        task_prompt = _build_task_prompt(count, table_name, from_date, to_date)

        # Use complete_with_context — large context cached, small task prompt fresh
        response = llm.complete_with_context(
            context_blocks = context_blocks,
            task_prompt    = task_prompt,
            system         = system_prompt,
            max_tokens     = 8192,
            temperature    = 0.3,
        )

        raw = response.content.strip()

        # Strip markdown fences if Claude wraps anyway
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])
        raw = raw.strip()

        batch_rows = json.loads(raw)
        if not isinstance(batch_rows, list):
            batch_rows = [batch_rows]

        all_rows.extend(batch_rows)

        # Log cache usage if available
        if hasattr(response, "cache_read_tokens") and response.cache_read_tokens:
            print(
                f"    Batch {b+1} done  —  {len(batch_rows)} rows  "
                f"[cache hit: {response.cache_read_tokens} tokens saved]"
            )
        else:
            print(f"    Batch {b+1} done  —  {len(batch_rows)} rows received")

    return all_rows[:num_records]
