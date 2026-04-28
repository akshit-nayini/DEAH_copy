export const SESSION_ID = "SES-" + Math.random().toString(36).slice(2,8).toUpperCase();
export const API_VERSION = "v2";
export const LOG_API = `https://api.sdlc-platform.internal/${API_VERSION}/logs/ingest`;
export const CLAUDE_API = "https://api.anthropic.com/v1/messages";
export const CLAUDE_MODEL = "claude-sonnet-4-20250514";

export const LIVE_STEPS = [
  "Initializing…","Connecting to API…","Processing context…",
  "Running AI inference…","Parsing response…","Writing audit log…","Finalizing…",
];

export const SC = {
  color: { idle:"#94a3b8", running:"#3b82f6", done:"#16a34a", error:"#ef4444" },
  bg:    { idle:"#f1f5f9", running:"#dbeafe", done:"#dcfce7", error:"#fee2e2" },
  bdr:   { idle:"#e2e8f0", running:"#bfdbfe", done:"#bbf7d0", error:"#fca5a5" },
  label: { idle:"Ready",   running:"Running…", done:"Done",   error:"Error"   },
  icon:  { idle:"○",       running:"◌",        done:"✓",      error:"✕"       },
} as const;

export type RunStatus = "idle" | "running" | "done" | "error";
