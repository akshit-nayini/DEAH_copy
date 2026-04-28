import { useState } from "react";
import type { JiraTicket, JiraPushResultItem } from "../services/requirementsApi";
import { pushToJira } from "../services/requirementsApi";

const TYPE_COLOR: Record<string, string> = {
  story:   "#3b82f6",
  task:    "#8b5cf6",
  bug:     "#ef4444",
  epic:    "#f97316",
  subtask: "#6b7280",
  "sub-task": "#6b7280",
};

const PRIORITY_COLOR: Record<string, string> = {
  critical: "#ef4444",
  high:     "#f97316",
  medium:   "#eab308",
  low:      "#22c55e",
};

function typeColor(t: string) { return TYPE_COLOR[t?.toLowerCase()] ?? "#64748b"; }
function priorityColor(p: string) { return PRIORITY_COLOR[p?.toLowerCase()] ?? "#64748b"; }

function Chip({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 10,
      background: color + "18", color, border: `1px solid ${color}44`,
    }}>{label}</span>
  );
}

function TicketCard({
  ticket, index, pushed,
}: {
  ticket: JiraTicket;
  index: number;
  pushed?: JiraPushResultItem;
}) {
  const [open, setOpen] = useState(false);
  const tc = typeColor(ticket.issue_type);

  const jiraId  = pushed?.jira_id  ?? ticket.issue_key;
  const jiraUrl = pushed?.jira_url ?? ticket.jira_url;

  return (
    <div style={{
      border: "1px solid #e2e8f0", borderRadius: 8, overflow: "hidden",
      borderLeft: `3px solid ${tc}`, background: "#fff",
      boxShadow: "0 1px 4px rgba(0,0,0,0.05)",
    }}>
      {/* Header row */}
      <div style={{ padding: "8px 10px", display: "flex", alignItems: "flex-start", gap: 8 }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", flexShrink: 0, marginTop: 1 }}>
          #{index + 1}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 4, alignItems: "center" }}>
            <Chip label={ticket.issue_type} color={tc} />
            {jiraId && (
              jiraUrl
                ? <a href={jiraUrl} target="_blank" rel="noreferrer" style={{
                    fontSize: 9, fontWeight: 700, color: "#2563eb", background: "#eff6ff",
                    borderRadius: 4, padding: "1px 5px", border: "1px solid #bfdbfe",
                    textDecoration: "none",
                  }}>{jiraId} ↗</a>
                : <span style={{ fontSize: 9, fontWeight: 600, color: "#64748b", background: "#f1f5f9", borderRadius: 4, padding: "1px 5px" }}>
                    {jiraId}
                  </span>
            )}
            {!jiraId && ticket.pod_task_id && (
              <span style={{ fontSize: 9, fontWeight: 600, color: "#94a3b8", background: "#f8fafc", borderRadius: 4, padding: "1px 5px", border: "1px solid #e2e8f0" }}>
                {ticket.pod_task_id}
              </span>
            )}
            {ticket.priority && <Chip label={ticket.priority} color={priorityColor(ticket.priority)} />}
            {ticket.story_points != null && (
              <span style={{ fontSize: 9, fontWeight: 600, color: "#7c3aed", background: "#f5f3ff", borderRadius: 4, padding: "1px 5px", border: "1px solid #ddd6fe" }}>
                {ticket.story_points} pts
              </span>
            )}
            {ticket.sprint_target && (
              <span style={{ fontSize: 9, color: "#0369a1", background: "#f0f9ff", borderRadius: 4, padding: "1px 5px", border: "1px solid #bae6fd" }}>
                {ticket.sprint_target}
              </span>
            )}
            {pushed && !pushed.success && (
              <span style={{ fontSize: 9, color: "#dc2626", background: "#fef2f2", borderRadius: 4, padding: "1px 5px", border: "1px solid #fca5a5" }}>
                Push failed
              </span>
            )}
          </div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#1e293b", lineHeight: 1.4 }}>
            {ticket.summary}
          </div>
        </div>
        {(ticket.description || ticket.acceptance_criteria?.length) && (
          <button onClick={() => setOpen(o => !o)} style={{
            background: "none", border: "none", cursor: "pointer", color: "#94a3b8",
            fontSize: 14, flexShrink: 0, padding: 0, lineHeight: 1,
          }}>
            {open ? "▲" : "▼"}
          </button>
        )}
      </div>

      {/* Expandable detail */}
      {open && (
        <div style={{ padding: "0 10px 8px 10px", borderTop: "1px solid #f1f5f9" }}>
          {ticket.description && (
            <div style={{ marginTop: 6 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", marginBottom: 3 }}>Description</div>
              <div style={{ fontSize: 11, color: "#475569", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{ticket.description}</div>
            </div>
          )}
          {ticket.acceptance_criteria?.length ? (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", marginBottom: 3 }}>Acceptance Criteria</div>
              <ol style={{ margin: 0, paddingLeft: 16 }}>
                {ticket.acceptance_criteria.map((c, i) => (
                  <li key={i} style={{ fontSize: 11, color: "#475569", lineHeight: 1.5, marginBottom: 2 }}>{c}</li>
                ))}
              </ol>
            </div>
          ) : null}
          {ticket.parent_epic_key && (
            <div style={{ marginTop: 6, fontSize: 10, color: "#64748b" }}>
              Parent Epic: <strong>{ticket.parent_epic_key}</strong>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function JiraTicketCards({ tickets }: { tickets: JiraTicket[] }) {
  const [pushing, setPushing]   = useState(false);
  const [pushError, setPushError] = useState<string | null>(null);
  const [pushedMap, setPushedMap] = useState<Record<string, JiraPushResultItem>>({});

  if (!tickets.length) return (
    <div style={{ color: "#94a3b8", fontSize: 12, fontStyle: "italic", padding: 8 }}>No Jira tickets generated.</div>
  );

  const unpushedIds = tickets
    .filter(t => t.pod_task_id && !pushedMap[t.pod_task_id!] && !t.issue_key)
    .map(t => t.pod_task_id!);

  const allPushed = unpushedIds.length === 0 && Object.keys(pushedMap).length > 0;

  const handlePush = async () => {
    if (!unpushedIds.length) return;
    setPushing(true);
    setPushError(null);
    try {
      const results = await pushToJira(unpushedIds);
      const map: Record<string, JiraPushResultItem> = {};
      results.forEach(r => { map[r.task_id] = r; });
      setPushedMap(prev => ({ ...prev, ...map }));
    } catch (e: unknown) {
      setPushError(e instanceof Error ? e.message : String(e));
    } finally {
      setPushing(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {/* Toolbar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 2 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: "#64748b" }}>
          {tickets.length} ticket{tickets.length !== 1 ? "s" : ""} — click ▼ to expand
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {allPushed && (
            <span style={{ fontSize: 10, fontWeight: 600, color: "#15803d", background: "#f0fdf4", borderRadius: 8, padding: "2px 8px", border: "1px solid #bbf7d0" }}>
              ✓ Pushed to Jira
            </span>
          )}
          {unpushedIds.length > 0 && (
            <button
              onClick={handlePush}
              disabled={pushing}
              style={{
                fontSize: 10, fontWeight: 700, padding: "3px 10px", borderRadius: 6,
                background: pushing ? "#e2e8f0" : "#2563eb",
                color: pushing ? "#94a3b8" : "#fff",
                border: "none", cursor: pushing ? "not-allowed" : "pointer",
                display: "flex", alignItems: "center", gap: 4,
              }}
            >
              {pushing
                ? <><span style={{ display: "inline-block", animation: "spin 0.8s linear infinite" }}>↻</span> Pushing…</>
                : <>🎫 Push to Jira ({unpushedIds.length})</>}
            </button>
          )}
        </div>
      </div>

      {pushError && (
        <div style={{ fontSize: 10, color: "#dc2626", background: "#fef2f2", borderRadius: 6, padding: "4px 8px", border: "1px solid #fca5a5" }}>
          Push error: {pushError}
        </div>
      )}

      {tickets.map((t, i) => (
        <TicketCard
          key={i}
          ticket={t}
          index={i}
          pushed={t.pod_task_id ? pushedMap[t.pod_task_id] : undefined}
        />
      ))}
    </div>
  );
}
