import { SESSION_ID } from "../constants";
import { loadAdminConfig } from "../adminConfig";

// ── Source selection ───────────────────────────────────────────────────────

export type DesignSource =
  | { type: "ticket";   ticketId: string }
  | { type: "document"; documentPath: string };

// ── Request types ──────────────────────────────────────────────────────────

interface RunPipelineRequest {
  session_id: string;
  ticket_id?: string;
  request_type?: string;
  project_name?: string;
  requirements_path?: string;
  schema_path?: string;
}

// ── Response types ─────────────────────────────────────────────────────────

export interface RequirementsAgentResponse {
  output_path?: string;
  markdown_path?: string;
  result?: Record<string, unknown>;
  git?: Record<string, unknown>;
}

export interface DataModelOutputFiles {
  summary_json?: string;
  er_diagram_mmd?: string;
  mapping_csv?: string;
}

export interface DataModelAgentResponse {
  output_files?: DataModelOutputFiles;
  handoff_summary?: Record<string, unknown>;
  source_target_mapping?: string;
  er_mermaid_diagram?: string;
  git?: Record<string, unknown>;
}

export interface ArchitectureOutputFiles {
  summary_json?: string;
  report_md?: string;
  flow_mmd?: string;
}

export interface ArchitectureAgentResponse {
  run_id?: string;
  skipped?: boolean;
  output_files?: ArchitectureOutputFiles;
  handoff_summary?: Record<string, unknown>;
  manifest_summary?: Record<string, unknown>;
  git?: Record<string, unknown>;
}

export interface ImplStepsAgentResponse {
  project_name?: string;
  request_type?: string;
  output_path?: string;
  markdown?: string;
  git?: Record<string, unknown>;
}

export interface PipelineAgentResponse {
  data_model_path?: string;
  architecture_path?: string;
  data_model?: Record<string, unknown>;
  architecture?: Record<string, unknown>;
  mermaid2drawio?: Record<string, unknown>;
  implementation_steps?: Record<string, unknown>;
  git?: Record<string, unknown>;
}

// ── Internal JSON-safe fetch helper ───────────────────────────────────────

async function parseResponse<T>(r: Response): Promise<T> {
  const text = await r.text();
  if (!text.trim()) throw new Error(`Server returned an empty response (HTTP ${r.status})`);
  let d: { success?: boolean; data?: T; error?: string };
  try { d = JSON.parse(text); }
  catch { throw new Error(`Server returned non-JSON (HTTP ${r.status}): ${text.slice(0, 200)}`); }
  if (!d.success || !d.data) throw new Error(d.error || "Design agent call failed");
  return d.data as T;
}

// ── API calls ──────────────────────────────────────────────────────────────

export async function runDesignPipeline(source: DesignSource): Promise<PipelineAgentResponse> {
  const body: RunPipelineRequest = { session_id: SESSION_ID };
  if (source.type === "ticket") {
    body.ticket_id = source.ticketId;
  } else {
    body.requirements_path = source.documentPath;
  }
  const base = loadAdminConfig()?.pods?.design || "http://35.209.107.68:8082";
  const r = await fetch(`${base}/api/v1/design/pipeline`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseResponse<PipelineAgentResponse>(r);
}

// ── Sub-module formatters ──────────────────────────────────────────────────

function kv(obj: Record<string, unknown>, indent = "  "): string {
  return Object.entries(obj)
    .map(([k, v]) => `${indent}${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
    .join("\n");
}

export function formatReqFromJira(resp: PipelineAgentResponse): string {
  const lines: string[] = ["PIPELINE_STARTED", "─────────────────"];
  if (resp.data_model_path)   lines.push(`Data Model:       ${resp.data_model_path}`);
  if (resp.architecture_path) lines.push(`Architecture:     ${resp.architecture_path}`);

  const impl = resp.implementation_steps as Record<string, unknown> | undefined;
  if (impl?.output_path) lines.push(`Impl Steps:       ${impl.output_path}`);

  const drawio = resp.mermaid2drawio as Record<string, unknown> | undefined;
  if (Array.isArray(drawio?.drawio_files)) {
    lines.push(`DrawIO Files:     ${(drawio!.drawio_files as string[]).length} generated`);
  }

  if (lines.length === 2) lines.push("(no path data returned — check agent logs)");
  return lines.join("\n");
}

export function formatDataModel(resp: PipelineAgentResponse): string {
  const dm = resp.data_model as Record<string, unknown> | undefined;
  if (!dm) return "No data model output available.\n\nRun the pipeline first.";

  const lines: string[] = ["DATA_MODEL", "──────────"];
  if (resp.data_model_path) { lines.push(`Output: ${resp.data_model_path}`, ""); }

  const handoff = dm.handoff_summary as Record<string, unknown> | undefined;
  if (handoff && Object.keys(handoff).length) {
    lines.push("HANDOFF_SUMMARY", "────────────────", kv(handoff), "");
  }

  const er = dm.er_mermaid_diagram as string | undefined;
  if (er) { lines.push("ER_DIAGRAM (Mermaid)", "─────────────────────", er); }

  return lines.join("\n");
}

export function formatArchitecture(resp: PipelineAgentResponse): string {
  const arch = resp.architecture as Record<string, unknown> | undefined;
  if (!arch) return "No architecture output available.\n\nRun the pipeline first.";

  const lines: string[] = ["ARCHITECTURE", "─────────────"];
  if (resp.architecture_path) { lines.push(`Output: ${resp.architecture_path}`, ""); }

  const handoff = arch.handoff_summary as Record<string, unknown> | undefined;
  if (handoff && Object.keys(handoff).length) {
    lines.push("HANDOFF_SUMMARY", "────────────────", kv(handoff), "");
  }

  const manifest = arch.manifest_summary as Record<string, unknown> | undefined;
  if (manifest && Object.keys(manifest).length) {
    lines.push("ARCHITECTURE_DECISIONS", "───────────────────────", kv(manifest));
  }

  return lines.join("\n");
}

export function formatImplSteps(resp: PipelineAgentResponse): string {
  const impl = resp.implementation_steps as Record<string, unknown> | undefined;
  if (!impl) return "No implementation steps available.\n\nRun the pipeline first.";

  const md = impl.markdown as string | undefined;
  if (md) return md;

  const lines: string[] = ["IMPLEMENTATION_STEPS", "─────────────────────"];
  Object.entries(impl).forEach(([k, v]) => {
    if (k !== "git") lines.push(`${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`);
  });
  return lines.join("\n");
}
