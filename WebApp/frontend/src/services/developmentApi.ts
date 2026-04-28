import { SESSION_ID } from "../constants";
import { loadAdminConfig } from "../adminConfig";

// ── Run status ────────────────────────────────────────────────────────────

export type RunStatus =
  | "pending" | "planning" | "checkpoint" | "generating"
  | "optimizing" | "reviewing" | "committing" | "done"
  | "aborted" | "failed";

export type CheckpointDecision = "approve" | "revise" | "abort" | "deploy" | "skip";

// ── Request shapes ────────────────────────────────────────────────────────

export interface StartRunRequest {
  session_id:        string;
  document_source:   "DIRECT" | "TICKET" | "GITHUB" | "GOOGLE_DRIVE";
  implementation_md?: string;
  mapping_csv?:       string;
  ticket_id?:         string;
  project_id?:        string;
  dataset_id?:        string;
  environment?:       string;
  cloud_provider?:    string;
  region?:            string;
}

export interface StartDeployRequest {
  request_id:            string;
  artifacts_dir:         string;
  project_id?:           string;
  dataset_id?:           string;
  environment?:          string;
  dag_bucket?:           string;
  composer_environment?: string;
  target?:               string;
}

// ── Response shapes ───────────────────────────────────────────────────────

export interface GeneratedArtifact {
  file_name:     string;
  artifact_type: string;
  description?:  string;
}

export interface RunSummary {
  request_id:        string;
  status:            RunStatus;
  checkpoint_number: number | null;
  checkpoint_prompt: string | null;
  plan_summary:      string | null;
  artifacts:         GeneratedArtifact[];
  quality_score:     number | null;
  git_branch:        string | null;
  error:             string | null;
  output_directory:  string | null;
  current_task:      string | null;
  log_messages:      string[];
}

export interface DeployStepResult {
  step:    string;
  status:  string;
  message: string;
}

export interface DeployResult {
  request_id?:    string;
  target?:        string;
  validation?:    { check: string; status: string; message: string }[];
  steps?:         DeployStepResult[];
  overall_status: string;
}

export interface DeployRunSummary {
  run_id:       string;
  request_id:   string;
  status:       string;
  environment?: string;
  project_id?:  string;
  dataset_id?:  string;
  created_at?:  string;
  result?:      DeployResult;
  error?:       string;
}

export interface RunOutputEntry {
  run_id:    string;
  ddl?:      string[];
  dml?:      string[];
  sp?:       string[];
  dag?:      string[];
  config?:   string[];
  plan?:     string[];
  review?:   string[];
  manifest?: string[];
}

export interface OutputsListResponse {
  runs: RunOutputEntry[];
}

// ── API helper ────────────────────────────────────────────────────────────

async function api<T>(path: string, opts?: RequestInit): Promise<T> {
  const base = loadAdminConfig()?.pods?.development || "http://35.209.107.68:8000";
  const r = await fetch(`${base}${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  const d = await r.json();
  // Backend wraps in { success, data, error }
  if (d && "success" in d) {
    if (!d.success) throw new Error(d.error || "Request failed");
    return d.data as T;
  }
  if (!r.ok) throw new Error(d?.detail || `HTTP ${r.status}`);
  return d as T;
}

// ── Code-gen pipeline ─────────────────────────────────────────────────────

export async function startRun(req: Omit<StartRunRequest, "session_id">): Promise<RunSummary> {
  return api<RunSummary>("/api/v1/development/runs", {
    method: "POST",
    body: JSON.stringify({ ...req, session_id: SESSION_ID }),
  });
}

export async function getRun(requestId: string): Promise<RunSummary> {
  return api<RunSummary>(`/api/v1/development/runs/${requestId}`);
}

export async function submitCheckpoint(
  requestId: string,
  decision: CheckpointDecision,
  notes = "",
): Promise<RunSummary> {
  return api<RunSummary>(`/api/v1/development/runs/${requestId}/checkpoint`, {
    method: "POST",
    body: JSON.stringify({ decision, notes }),
  });
}

export async function listRuns(): Promise<RunSummary[]> {
  return api<RunSummary[]>("/api/v1/development/runs");
}

// ── Deployment ────────────────────────────────────────────────────────────

export async function startDeploy(req: StartDeployRequest): Promise<DeployRunSummary> {
  return api<DeployRunSummary>("/api/v1/development/deploy", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function getDeployRun(runId: string): Promise<DeployRunSummary> {
  return api<DeployRunSummary>(`/api/v1/development/deploy/${runId}`);
}

// ── Outputs ───────────────────────────────────────────────────────────────

export async function listOutputs(): Promise<OutputsListResponse> {
  return api<OutputsListResponse>("/api/v1/development/outputs");
}

// ── Helpers ───────────────────────────────────────────────────────────────

export const TERMINAL: RunStatus[] = ["done", "aborted", "failed"];
export const isTerminal = (s: RunStatus) => TERMINAL.includes(s);

export const STATUS_LABEL: Record<RunStatus, string> = {
  pending:    "Queued",
  planning:   "Planning…",
  checkpoint: "Awaiting Review",
  generating: "Generating…",
  optimizing: "Optimizing…",
  reviewing:  "Reviewing…",
  committing: "Committing…",
  done:       "Complete",
  aborted:    "Aborted",
  failed:     "Failed",
};

export const STATUS_COLOR: Record<RunStatus, string> = {
  pending:    "#94a3b8",
  planning:   "#a855f7",
  checkpoint: "#f59e0b",
  generating: "#3b82f6",
  optimizing: "#06b6d4",
  reviewing:  "#8b5cf6",
  committing: "#10b981",
  done:       "#16a34a",
  aborted:    "#6b7280",
  failed:     "#ef4444",
};

export const CP_LABEL: Record<number, string> = {
  1: "Plan Review",
  2: "Code Review",
  3: "Git Push Decision",
};
