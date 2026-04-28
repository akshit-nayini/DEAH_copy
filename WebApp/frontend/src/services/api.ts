import { CLAUDE_API, CLAUDE_MODEL, LOG_API, API_VERSION, SESSION_ID } from "../constants";
import { loadAdminConfig } from "../adminConfig";

export let globalLogs: object[] = [];

export async function callLogAPI(
  moduleId: string,
  req: unknown,
  res: unknown,
  status: string,
  duration: number
) {
  const e = {
    timestamp: new Date().toISOString(),
    api_version: API_VERSION,
    session: SESSION_ID,
    module_id: moduleId,
    status,
    duration_ms: duration,
    request_summary: String(req).slice(0, 200),
    response_summary: String(res).slice(0, 300),
    log_endpoint: LOG_API,
  };
  globalLogs = [e, ...globalLogs].slice(0, 200);
  return e;
}

export async function callClaude(sys: string, user: string): Promise<string> {
  const admin = loadAdminConfig();
  const apiKey = admin?.ai?.apiKey || undefined;
  const model  = admin?.ai?.model  || CLAUDE_MODEL;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) {
    headers["x-api-key"]         = apiKey;
    headers["anthropic-version"]  = "2023-06-01";
  }

  const r = await fetch(CLAUDE_API, {
    method: "POST",
    headers,
    body: JSON.stringify({
      model,
      max_tokens: 1000,
      system: sys,
      messages: [{ role: "user", content: user }],
    }),
  });
  const d = await r.json();
  if (d.error) throw new Error(d.error.message || "API error");
  return d?.content?.filter((b: { type: string }) => b.type === "text").map((b: { text: string }) => b.text).join("") || "No output.";
}
