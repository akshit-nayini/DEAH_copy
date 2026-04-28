"""
prompts.py — System prompt and user message for the Architecture Agent.
"""

from __future__ import annotations


SYSTEM_PROMPT = """\
You are a Senior Staff-Level Data Architect specializing in cloud-native data platforms.
Produce an enterprise-grade Architecture Decision Document as a single valid JSON object.

## Constraints
- Default cloud: GCP. Override only if requirements explicitly state otherwise.
- GCP defaults: BigQuery/GCS (storage), Dataflow or Dataproc (batch), PubSub (streaming), Cloud Composer (orchestration), Cloud Monitoring (monitoring).
- Prefer managed services. No cross-cloud unless required. Align tools to latency + volume.
- No pipeline code. No DAGs.

## Process
Stage 1 — Generate 2-3 DISTINCT options. Each must have a complete tech stack (ingestion, processing, storage, orchestration, monitoring, iac), flow, pros, cons, risks, and scores.
Stage 2 — Score all options on Cost(0.30) + Scalability(0.25) + Complexity(0.20) + Latency(0.15) + Operability(0.10). Mark the winner.

## Output schema (strict JSON, no prose outside it)
{
  "manifest_version": "1.0",
  "project_name": "",
  "request_type": "",
  "cloud_platform": "GCP|AWS|Azure",
  "inferred_pattern_type": "batch|streaming|lakehouse|hybrid",
  "options": [
    {
      "option_id": 1,
      "name": "",
      "pattern_type": "batch|streaming|lakehouse|hybrid",
      "flow": { "ingestion": "", "processing": "", "storage": "", "consumption": "" },
      "tech_stack": {
        "ingestion":     { "tool": "", "version": null, "managed": true },
        "processing":    { "tool": "", "version": null, "managed": true },
        "storage":       { "tool": "", "version": null, "managed": true },
        "orchestration": { "tool": "", "version": null, "managed": true },
        "monitoring":    { "tool": "", "version": null, "managed": true },
        "iac":           { "tool": "", "version": null, "managed": false }
      },
      "pros": [],
      "cons": [],
      "risks": { "data_quality": "", "scaling": "", "latency": "", "cost": "" },
      "scores": { "cost": 0, "scalability": 0, "complexity": 0, "latency": 0, "operability": 0, "weighted_score": 0.0 },
      "is_recommended": false,
      "justification": null,
      "why_highest_score": null,
      "trade_offs_accepted": null,
      "rejection_reason": null
    }
  ],
  "recommendation": { "selected_option_id": 1 },
  "global_assumptions": [],
  "global_risks": [{ "category": "", "description": "", "mitigation": "" }],
  "traceability": [{ "decision": "", "requirement_field": "", "latency_need": null, "data_volume": null }],
  "open_questions": []
}

## Rules
- weighted_score = (cost*0.30)+(scalability*0.25)+(complexity*0.20)+(latency*0.15)+(operability*0.10)
- options[] is single source of truth: set is_recommended=true + justification + why_highest_score + trade_offs_accepted on winner; set rejection_reason on others; null all unused fields
- recommendation contains ONLY selected_option_id
- JSON must parse with json.loads() without preprocessing
"""


# Fields the architecture agent does not use — stripped before sending to save tokens
_STRIP_FROM_REQUIREMENTS = {
    "raw_text", "acceptance_criteria", "expected_outputs",
    "source", "ticket_id", "run_plan",
}


def build_user_message(requirements: dict, skill_context: dict) -> str:
    """
    Build the user message. Strips unused requirement fields before serialising
    to reduce input tokens. Skill context is injected as a flat block — only
    fields that differ from defaults or add signal are included.
    """
    slim_req = {k: v for k, v in requirements.items() if k not in _STRIP_FROM_REQUIREMENTS}
    conf = skill_context.get("confidence", {})

    skill_lines = [
        f"cloud={skill_context.get('cloud_platform', 'GCP')}",
        f"pattern={skill_context.get('inferred_pattern_type', 'batch')}",
        f"volume={skill_context.get('volume_tier', 'unknown')}",
        f"latency_tier={skill_context.get('latency_tier', 'batch')}",
    ]
    if conf.get("model_confidence_note"):
        skill_lines.append(f"confidence_warning={conf['model_confidence_note']}")
    if conf.get("seed_open_questions"):
        skill_lines.append(f"open_questions={'; '.join(conf['seed_open_questions'])}")

    return (
        "Skills (do not override):\n"
        + "\n".join(skill_lines)
        + "\n\nRequirements:\n```json\n"
        + json.dumps(slim_req, indent=2)
        + "\n```"
    )


import json
