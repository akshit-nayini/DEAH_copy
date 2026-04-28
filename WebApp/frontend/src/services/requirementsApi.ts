import { SESSION_ID } from "../constants";
import { loadAdminConfig } from "../adminConfig";

// ── Request types ──────────────────────────────────────────────────────────

export type DocumentSource = "GITHUB" | "GOOGLE_DRIVE";

export interface GitHubSourceDetails {
  org: string;
  repo: string;
  branch: string;
  file_path: string;
  pat_token?: string;
}

export interface GoogleDriveSourceDetails {
  drive_url_or_id: string;
  oauth_token: string;
}

export interface ProcessRequirementsRequest {
  session_id: string;
  document_source: DocumentSource;
  github_source?: GitHubSourceDetails;
  google_drive_source?: GoogleDriveSourceDetails;
  additional_context?: string;
}

// ── Response types ────────────────────────────────────────────────────────

export interface JiraTicket {
  pod_task_id?: string;
  issue_key?: string;
  jira_url?: string;
  issue_type: string;
  summary: string;
  description?: string;
  priority?: string;
  story_points?: number;
  labels?: string[];
  acceptance_criteria?: string[];
  sprint_target?: string;
  parent_epic_key?: string;
}

export interface JiraPushResultItem {
  task_id: string;
  success: boolean;
  jira_id?: string;
  jira_url?: string;
  action?: string;
  error?: string;
}

export interface RequirementsDocument {
  project_name?: string;
  executive_summary?: string;
  feature_type?: string;
  priority?: string;
  key_requirements?: string[];
  acceptance_criteria?: string[];
  stakeholders?: string[];
  estimated_effort?: string;
  assigned_team?: string;
  sprint_target?: string;
  tags?: string[];
  decisions_made?: string[];
  action_items?: string[];
  raw_document?: string;
}

export interface AgentResponse {
  session_id?: string;
  status?: string;
  message?: string;
  jira_tickets?: JiraTicket[];
  requirements_document?: RequirementsDocument;
  processed_at?: string;
  agent_duration_ms?: number;
}

// ── Source selection (returned by SourceModal) ────────────────────────────

export type SourceSelection =
  | { type: "text";         content: string }
  | { type: "file";         content: string }
  | { type: "github";       org: string; repo: string; branch: string; filePath: string; patToken: string }
  | { type: "google_drive"; driveUrlOrId: string; oauthToken: string };

// ── API call ──────────────────────────────────────────────────────────────

export async function processRequirements(
  source: Extract<SourceSelection, { type: "github" | "google_drive" }>,
  additionalContext?: string,
): Promise<AgentResponse> {
  const body: ProcessRequirementsRequest = {
    session_id: SESSION_ID,
    document_source: source.type === "github" ? "GITHUB" : "GOOGLE_DRIVE",
    additional_context: additionalContext,
  };

  if (source.type === "github") {
    body.github_source = {
      org:       source.org,
      repo:      source.repo,
      branch:    source.branch || "main",
      file_path: source.filePath,
      pat_token: source.patToken || undefined,
    };
  } else {
    body.google_drive_source = {
      drive_url_or_id: source.driveUrlOrId,
      oauth_token:     source.oauthToken,
    };
  }

  const base = loadAdminConfig()?.pods?.requirements || "http://35.209.107.68:8001";
  const r = await fetch(`${base}/api/v1/requirements/process`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(body),
  });

  const text = await r.text();
  if (!text.trim()) throw new Error(`Server returned an empty response (HTTP ${r.status})`);
  let d: { success?: boolean; data?: AgentResponse; error?: string };
  try { d = JSON.parse(text); }
  catch { throw new Error(`Server returned non-JSON (HTTP ${r.status}): ${text.slice(0, 200)}`); }
  if (!d.success || !d.data) throw new Error(d.error || "Requirements processing failed");
  return d.data as AgentResponse;
}

export async function pushToJira(taskIds: string[]): Promise<JiraPushResultItem[]> {
  const base = loadAdminConfig()?.pods?.requirements || "http://35.209.107.68:8001";
  const r = await fetch(`${base}/api/v1/requirements/push-to-jira`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ task_ids: taskIds }),
  });
  const text = await r.text();
  if (!text.trim()) throw new Error(`Server returned an empty response (HTTP ${r.status})`);
  let d: { success?: boolean; data?: JiraPushResultItem[]; error?: string };
  try { d = JSON.parse(text); }
  catch { throw new Error(`Server returned non-JSON (HTTP ${r.status}): ${text.slice(0, 200)}`); }
  if (!d.success || !d.data) throw new Error(d.error || "Jira push failed");
  return d.data as JiraPushResultItem[];
}

// ── Sub-module formatters ─────────────────────────────────────────────────

function list(items?: string[]): string {
  return items?.length ? items.map((x, i) => `  ${i + 1}. ${x}`).join("\n") : "  (none)";
}

export function formatCallSummary(resp: AgentResponse): string {
  const doc = resp.requirements_document;
  if (!doc) return resp.message || "No summary available.";
  return [
    "CALL_SUMMARY",
    "─────────────",
    doc.executive_summary || "(no summary)",
    "",
    "KEY_REQUIREMENTS",
    "─────────────────",
    list(doc.key_requirements),
    "",
    "DECISIONS_MADE",
    "───────────────",
    list(doc.decisions_made),
    "",
    "ACTION_ITEMS",
    "─────────────",
    list(doc.action_items),
    "",
    "STAKEHOLDERS_MENTIONED",
    "───────────────────────",
    list(doc.stakeholders),
  ].join("\n");
}

export function formatTemplateFiller(resp: AgentResponse): string {
  const doc = resp.requirements_document;
  if (!doc) return "No requirements document available.";
  return [
    `PROJECT_NAME:      ${doc.project_name || "(unknown)"}`,
    `FEATURE_TYPE:      ${doc.feature_type || "(unknown)"}`,
    "",
    "DESCRIPTION",
    "────────────",
    doc.executive_summary || "(none)",
    "",
    "ACCEPTANCE_CRITERIA",
    "────────────────────",
    list(doc.acceptance_criteria),
    "",
    `PRIORITY:          ${doc.priority || "(unknown)"}`,
    `ESTIMATED_EFFORT:  ${doc.estimated_effort || "(unknown)"}`,
    `ASSIGNED_TEAM:     ${doc.assigned_team || "(unknown)"}`,
    `TAGS:              ${doc.tags?.join(", ") || "(none)"}`,
  ].join("\n");
}

export function formatJiraTickets(resp: AgentResponse): string {
  const tickets = resp.jira_tickets;
  if (!tickets?.length) return "No JIRA tickets generated.";

  return tickets.map((t, i) => {
    const lines = [
      `── Ticket ${i + 1}: [${t.issue_type}] ${t.issue_key ? t.issue_key + " – " : ""}${t.summary}`,
      `   Priority:     ${t.priority || "(unknown)"}`,
      `   Story Points: ${t.story_points ?? "(unknown)"}`,
      `   Sprint:       ${t.sprint_target || "(unknown)"}`,
    ];
    if (t.parent_epic_key) lines.push(`   Parent Epic:  ${t.parent_epic_key}`);
    if (t.labels?.length)  lines.push(`   Labels:       ${t.labels.join(", ")}`);
    if (t.description)     lines.push(`\n   Description:\n   ${t.description}`);
    if (t.acceptance_criteria?.length) {
      lines.push(`\n   Acceptance Criteria:`);
      t.acceptance_criteria.forEach((c, j) => lines.push(`     ${j + 1}. ${c}`));
    }
    return lines.join("\n");
  }).join("\n\n");
}

export function formatSmartRouter(resp: AgentResponse): string {
  const doc = resp.requirements_document;
  if (!doc) return "No routing information available.";
  return [
    `CLASSIFICATION:    ${doc.feature_type || "(unknown)"}`,
    `PRIORITY:          ${doc.priority || "(unknown)"}`,
    `ASSIGNED_TEAM:     ${doc.assigned_team || "(unknown)"}`,
    `ESTIMATED_SPRINT:  ${doc.sprint_target || "(unknown)"}`,
    "",
    "SKILL_REQUIREMENTS",
    "───────────────────",
    `  Derived from tags: ${doc.tags?.join(", ") || "(none)"}`,
    "",
    "SIGNOFF_CHECKLIST",
    "──────────────────",
    `  ☐ Requirements reviewed by ${doc.stakeholders?.[0] || "PM"}`,
    "  ☐ Acceptance criteria approved",
    "  ☐ Sprint slot confirmed",
    "  ☐ Team capacity verified",
  ].join("\n");
}
