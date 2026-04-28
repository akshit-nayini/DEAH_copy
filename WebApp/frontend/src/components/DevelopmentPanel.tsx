import { useState, useCallback, useEffect, useRef } from "react";
import {
  startRun, getRun, submitCheckpoint, startDeploy, getDeployRun, listOutputs,
  type RunSummary, type DeployRunSummary, type RunOutputEntry,
  type CheckpointDecision, type StartDeployRequest,
  isTerminal, STATUS_LABEL, STATUS_COLOR, CP_LABEL,
} from "../services/developmentApi";
import { fmtDuration } from "../utils";

// ── Shared atoms ──────────────────────────────────────────────────────────

function Pill({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 20,
      background: color + "22", color, border: `1px solid ${color}55`,
      fontFamily: "monospace", display: "inline-block",
    }}>{label}</span>
  );
}

function Field({ label, value, onChange, placeholder, rows }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; rows?: number;
}) {
  const base: React.CSSProperties = {
    width: "100%", padding: "7px 10px", borderRadius: 7, boxSizing: "border-box",
    border: "1px solid #e2e8f0", background: "#f8fafc", fontSize: 12,
    color: "#1e293b", outline: "none", fontFamily: "inherit",
  };
  return (
    <div style={{ marginBottom: 10 }}>
      <label style={{ fontSize: 11, fontWeight: 600, color: "#475569", display: "block", marginBottom: 4 }}>{label}</label>
      {rows
        ? <textarea rows={rows} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} style={{ ...base, resize: "vertical" }} />
        : <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} style={base} />}
    </div>
  );
}

function Btn({ onClick, disabled, loading, color = "#e07b39", children }: {
  onClick: () => void; disabled?: boolean; loading?: boolean;
  color?: string; children: React.ReactNode;
}) {
  const off = disabled || loading;
  return (
    <button onClick={onClick} disabled={off} style={{
      padding: "8px 18px", borderRadius: 8, border: "none", fontSize: 12, fontWeight: 700,
      background: off ? "#e2e8f0" : color, color: off ? "#94a3b8" : "#fff",
      cursor: off ? "not-allowed" : "pointer",
      display: "flex", alignItems: "center", gap: 6,
      boxShadow: off ? "none" : `0 2px 8px ${color}55`,
    }}>
      {loading && <span style={{ animation: "spin 0.8s linear infinite", display: "inline-block" }}>↻</span>}
      {children}
    </button>
  );
}

// ── Pipeline Run tab ──────────────────────────────────────────────────────

function PipelineRunTab({ onStarted }: { onStarted: (r: RunSummary) => void }) {
  const [mode,      setMode]      = useState<"DIRECT" | "TICKET">("DIRECT");
  const [implMd,    setImplMd]    = useState("");
  const [mapping,   setMapping]   = useState("");
  const [ticketId,  setTicketId]  = useState("");
  const [projectId, setProjectId] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [env,       setEnv]       = useState("dev");
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState<string | null>(null);

  const canStart = mode === "TICKET" ? !!ticketId.trim() : !!(implMd.trim() && mapping.trim());

  const handleStart = async () => {
    setError(null); setLoading(true);
    try {
      const run = await startRun({
        document_source:   mode,
        implementation_md: mode === "DIRECT" ? implMd   : undefined,
        mapping_csv:       mode === "DIRECT" ? mapping  : undefined,
        ticket_id:         mode === "TICKET" ? ticketId : undefined,
        project_id:  projectId || undefined,
        dataset_id:  datasetId || undefined,
        environment: env,
        cloud_provider: "gcp",
      });
      onStarted(run);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start run");
    } finally { setLoading(false); }
  };

  return (
    <div>
      {/* Mode toggle */}
      <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
        {(["DIRECT", "TICKET"] as const).map(m => (
          <button key={m} onClick={() => setMode(m)} style={{
            padding: "5px 14px", borderRadius: 7, border: "none", fontSize: 11, fontWeight: 700,
            background: mode === m ? "#e07b39" : "#f1f5f9",
            color: mode === m ? "#fff" : "#64748b", cursor: "pointer",
          }}>
            {m === "DIRECT" ? "📄 Direct Content" : "🎫 Jira Ticket"}
          </button>
        ))}
      </div>

      {mode === "TICKET"
        ? <Field label="Ticket ID" value={ticketId} onChange={setTicketId} placeholder="e.g. SCRUM-149" />
        : <>
            <Field label="Implementation.md content" value={implMd} onChange={setImplMd} placeholder="Paste the full Implementation.md from the Design Pod…" rows={5} />
            <Field label="mapping.csv content" value={mapping} onChange={setMapping} placeholder="source_table,source_column,target_table,target_column…" rows={3} />
          </>
      }

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
        <Field label="GCP Project ID" value={projectId} onChange={setProjectId} placeholder="my-gcp-project" />
        <Field label="BigQuery Dataset" value={datasetId} onChange={setDatasetId} placeholder="customer_360" />
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: "#475569", display: "block", marginBottom: 4 }}>Environment</label>
          <select value={env} onChange={e => setEnv(e.target.value)} style={{
            width: "100%", padding: "7px 10px", borderRadius: 7,
            border: "1px solid #e2e8f0", background: "#f8fafc", fontSize: 12, outline: "none",
          }}>
            <option value="dev">dev</option>
            <option value="uat">uat</option>
            <option value="prod">prod</option>
          </select>
        </div>
      </div>

      {error && <div style={{ padding: "8px 12px", background: "#fee2e2", borderRadius: 8, color: "#dc2626", fontSize: 11, marginBottom: 10, border: "1px solid #fca5a5" }}>⚠ {error}</div>}
      <Btn onClick={handleStart} loading={loading} disabled={!canStart}>▶ Start Pipeline Run</Btn>
    </div>
  );
}

// ── Live run status card ──────────────────────────────────────────────────

function RunCard({ run, onUpdate }: { run: RunSummary; onUpdate: (r: RunSummary) => void }) {
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (isTerminal(run.status) || run.status === "checkpoint") {
      if (timer.current) clearInterval(timer.current);
      return;
    }
    timer.current = setInterval(async () => {
      try {
        const u = await getRun(run.request_id);
        onUpdate(u);
        if (isTerminal(u.status) || u.status === "checkpoint") clearInterval(timer.current!);
      } catch { /* silent */ }
    }, 4000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [run.request_id, run.status]);

  const color = STATUS_COLOR[run.status] ?? "#94a3b8";
  const active = !isTerminal(run.status) && run.status !== "checkpoint";

  return (
    <div style={{ background: "#f8fafc", borderRadius: 10, border: "1px solid #e2e8f0", padding: 12, marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        {active && <div style={{ width: 9, height: 9, borderRadius: "50%", background: color, boxShadow: `0 0 0 3px ${color}33`, animation: "pulse 1.5s ease-in-out infinite", flexShrink: 0 }} />}
        <Pill label={STATUS_LABEL[run.status] ?? run.status} color={color} />
        <span style={{ fontSize: 10, color: "#94a3b8", fontFamily: "monospace" }}>{run.request_id.slice(0, 10)}…</span>
        {run.quality_score != null && (
          <span style={{ marginLeft: "auto", fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 8,
            background: run.quality_score >= 70 ? "#dcfce7" : "#fef9c3",
            color: run.quality_score >= 70 ? "#16a34a" : "#a16207",
            border: `1px solid ${run.quality_score >= 70 ? "#bbf7d0" : "#fde68a"}` }}>
            Score: {run.quality_score}/100
          </span>
        )}
      </div>
      {run.current_task && <div style={{ fontSize: 11, color: "#64748b", fontStyle: "italic", marginBottom: 6 }}>{run.current_task}</div>}
      {run.artifacts.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 8 }}>
          {run.artifacts.map(a => (
            <span key={a.file_name} style={{ fontSize: 10, padding: "2px 7px", borderRadius: 5, background: "#eff6ff", color: "#3b82f6", border: "1px solid #bfdbfe", fontFamily: "monospace" }}>
              {a.artifact_type === "ddl" ? "🗄️" : a.artifact_type === "dag" ? "🌀" : a.artifact_type === "sp" ? "⚙️" : "📄"} {a.file_name}
            </span>
          ))}
        </div>
      )}
      {run.log_messages.length > 0 && (
        <div style={{ maxHeight: 100, overflowY: "auto", background: "#fff", borderRadius: 6, border: "1px solid #f1f5f9", padding: "6px 8px" }}>
          {[...run.log_messages].slice(-10).reverse().map((l, i) => (
            <div key={i} style={{ fontSize: 10, color: "#64748b", lineHeight: 1.7, fontFamily: "monospace" }}>{l}</div>
          ))}
        </div>
      )}
      {run.git_branch && <div style={{ marginTop: 6, fontSize: 10, color: "#16a34a", fontFamily: "monospace" }}>🌿 {run.git_branch}</div>}
      {run.error && <div style={{ marginTop: 6, color: "#dc2626", fontSize: 11 }}>⚠ {run.error}</div>}
    </div>
  );
}

// ── Checkpoint tab ────────────────────────────────────────────────────────

function CheckpointTab({ run, onUpdate }: { run: RunSummary | null; onUpdate: (r: RunSummary) => void }) {
  const [notes,   setNotes]   = useState("");
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  if (!run) return (
    <div style={{ color: "#94a3b8", fontSize: 12, fontStyle: "italic", textAlign: "center", paddingTop: 24 }}>
      Start a pipeline run first — checkpoint decisions will appear here.
    </div>
  );

  if (run.status !== "checkpoint") return (
    <div>
      <RunCard run={run} onUpdate={onUpdate} />
      <div style={{ color: "#94a3b8", fontSize: 12, fontStyle: "italic", textAlign: "center" }}>
        {isTerminal(run.status)
          ? `Pipeline ${run.status}. Start a new run to see checkpoints.`
          : "Pipeline is running — waiting for checkpoint…"}
      </div>
    </div>
  );

  const cpNum   = run.checkpoint_number ?? 0;
  const cpLabel = CP_LABEL[cpNum] ?? `Checkpoint ${cpNum}`;

  const decide = async (decision: CheckpointDecision) => {
    if (decision === "revise" && !notes.trim()) { setError("Revision notes are required."); return; }
    setError(null); setLoading(true);
    try {
      const u = await submitCheckpoint(run.request_id, decision, notes);
      onUpdate(u); setNotes("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Checkpoint submission failed");
    } finally { setLoading(false); }
  };

  return (
    <div>
      {/* CP header */}
      <div style={{ padding: "10px 14px", background: "#fffbeb", borderRadius: 10, border: "1px solid #fcd34d", marginBottom: 14, display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 20 }}>⏸️</span>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#92400e" }}>Checkpoint {cpNum}: {cpLabel}</div>
          <div style={{ fontSize: 10, color: "#b45309" }}>Human approval required to continue</div>
        </div>
        <Pill label={`CP ${cpNum}`} color="#f59e0b" />
      </div>

      {run.checkpoint_prompt && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>Checkpoint Prompt</div>
          <pre style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px", fontSize: 11, lineHeight: 1.8, whiteSpace: "pre-wrap", wordBreak: "break-word", color: "#334155", maxHeight: 180, overflowY: "auto", fontFamily: "monospace", margin: 0 }}>{run.checkpoint_prompt}</pre>
        </div>
      )}

      {run.plan_summary && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>Plan Summary</div>
          <pre style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 8, padding: "10px 12px", fontSize: 11, lineHeight: 1.8, whiteSpace: "pre-wrap", wordBreak: "break-word", color: "#166534", maxHeight: 160, overflowY: "auto", fontFamily: "monospace", margin: 0 }}>{run.plan_summary}</pre>
        </div>
      )}

      {run.quality_score != null && (
        <div style={{ marginBottom: 12, padding: "8px 12px", borderRadius: 8,
          background: run.quality_score >= 70 ? "#f0fdf4" : "#fef9c3",
          border: `1px solid ${run.quality_score >= 70 ? "#bbf7d0" : "#fde68a"}` }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: run.quality_score >= 70 ? "#15803d" : "#a16207" }}>
            Quality Score: {run.quality_score}/100 {run.quality_score >= 70 ? "✓ Meets threshold" : "⚠ Below 70"}
          </span>
        </div>
      )}

      <Field label="Notes (required for Revise; optional otherwise)" value={notes} onChange={setNotes} rows={3}
        placeholder='e.g. "Add PARTITION BY date to stg_customers_ddl.sql"' />

      {error && <div style={{ padding: "8px 12px", background: "#fee2e2", borderRadius: 8, color: "#dc2626", fontSize: 11, marginBottom: 10, border: "1px solid #fca5a5" }}>⚠ {error}</div>}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Btn onClick={() => decide("approve")} loading={loading} color="#16a34a">✓ Approve</Btn>
        <Btn onClick={() => decide("revise")}  loading={loading} color="#e07b39">↻ Revise</Btn>
        {cpNum === 3 && <>
          <Btn onClick={() => decide("deploy")} loading={loading} color="#4f6ef7">🚀 Approve + Deploy</Btn>
          <Btn onClick={() => decide("skip")}   loading={loading} color="#6b7280">⏭ Skip Git Push</Btn>
        </>}
        <Btn onClick={() => decide("abort")} loading={loading} color="#ef4444">✕ Abort</Btn>
      </div>
    </div>
  );
}

// ── Deploy tab ────────────────────────────────────────────────────────────

function DeployTab({ run }: { run: RunSummary | null }) {
  const [artifactsDir, setArtifactsDir] = useState("");
  const [projectId,    setProjectId]    = useState("");
  const [datasetId,    setDatasetId]    = useState("");
  const [env,          setEnv]          = useState("dev");
  const [dagBucket,    setDagBucket]    = useState("");
  const [composerEnv,  setComposerEnv]  = useState("");
  const [deployRun,    setDeployRun]    = useState<DeployRunSummary | null>(null);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (run?.output_directory) setArtifactsDir(run.output_directory);
  }, [run?.output_directory]);

  useEffect(() => {
    if (!deployRun || deployRun.status === "success" || deployRun.status === "failed") {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const u = await getDeployRun(deployRun.run_id);
        setDeployRun(u);
        if (u.status === "success" || u.status === "failed") clearInterval(pollRef.current!);
      } catch { /* silent */ }
    }, 5000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [deployRun?.run_id, deployRun?.status]);

  if (!run) return (
    <div style={{ color: "#94a3b8", fontSize: 12, fontStyle: "italic", textAlign: "center", paddingTop: 24 }}>
      Complete a pipeline run before deploying.
    </div>
  );

  const handleDeploy = async () => {
    setError(null); setLoading(true);
    try {
      const req: StartDeployRequest = {
        request_id:  run.request_id,
        artifacts_dir: artifactsDir || run.output_directory || "",
        project_id:  projectId || undefined,
        dataset_id:  datasetId || undefined,
        environment: env,
        dag_bucket:  dagBucket || undefined,
        composer_environment: composerEnv || undefined,
        target: "gcp",
      };
      const d = await startDeploy(req);
      setDeployRun(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Deploy failed");
    } finally { setLoading(false); }
  };

  const stepColor: Record<string, string> = { success: "#16a34a", failed: "#ef4444", skipped: "#94a3b8" };

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Field label="Artifacts Directory" value={artifactsDir} onChange={setArtifactsDir} placeholder="/mnt/data/development/…" />
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: "#475569", display: "block", marginBottom: 4 }}>Environment</label>
          <select value={env} onChange={e => setEnv(e.target.value)} style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #e2e8f0", background: "#f8fafc", fontSize: 12, outline: "none" }}>
            <option value="dev">dev</option><option value="uat">uat</option><option value="prod">prod</option>
          </select>
        </div>
        <Field label="GCP Project ID"       value={projectId}   onChange={setProjectId}   placeholder="my-gcp-project" />
        <Field label="BigQuery Dataset"      value={datasetId}   onChange={setDatasetId}   placeholder="customer_360" />
        <Field label="DAG Bucket"            value={dagBucket}   onChange={setDagBucket}   placeholder="us-central1-my-composer-…" />
        <Field label="Composer Environment"  value={composerEnv} onChange={setComposerEnv} placeholder="my-composer-env" />
      </div>

      {error && <div style={{ padding: "8px 12px", background: "#fee2e2", borderRadius: 8, color: "#dc2626", fontSize: 11, marginBottom: 10, border: "1px solid #fca5a5" }}>⚠ {error}</div>}

      <Btn onClick={handleDeploy} loading={loading} color="#4f6ef7" disabled={run.status !== "done"}>
        🚀 Trigger Deployment
      </Btn>
      {run.status !== "done" && <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 6 }}>Pipeline must be <code>done</code> to deploy (currently: <strong>{run.status}</strong>)</div>}

      {deployRun && (
        <div style={{ marginTop: 16, background: "#f8fafc", borderRadius: 10, border: "1px solid #e2e8f0", padding: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <Pill label={deployRun.status}
              color={{ success: "#16a34a", failed: "#ef4444", pending: "#94a3b8", running: "#3b82f6", skipped: "#6b7280" }[deployRun.status] ?? "#94a3b8"} />
            <span style={{ fontSize: 10, color: "#64748b", fontFamily: "monospace" }}>{deployRun.run_id.slice(0, 10)}…</span>
          </div>
          {deployRun.result?.validation && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", marginBottom: 4 }}>Pre-deploy Checks</div>
              {deployRun.result.validation.map((v, i) => (
                <div key={i} style={{ display: "flex", gap: 8, fontSize: 11, lineHeight: 1.8 }}>
                  <span style={{ color: v.status === "pass" ? "#16a34a" : v.status === "skipped" ? "#94a3b8" : "#ef4444", fontWeight: 700, minWidth: 12 }}>{v.status === "pass" ? "✓" : v.status === "skipped" ? "—" : "✕"}</span>
                  <span style={{ color: "#64748b", minWidth: 80 }}>{v.check}</span>
                  <span style={{ color: "#475569" }}>{v.message}</span>
                </div>
              ))}
            </div>
          )}
          {deployRun.result?.steps && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", marginBottom: 4 }}>Deploy Steps</div>
              {deployRun.result.steps.map((s, i) => (
                <div key={i} style={{ display: "flex", gap: 8, fontSize: 11, lineHeight: 1.8, padding: "3px 0", borderBottom: "1px solid #f1f5f9" }}>
                  <span style={{ color: stepColor[s.status] ?? "#94a3b8", fontWeight: 700, minWidth: 12 }}>{s.status === "success" ? "✓" : s.status === "failed" ? "✕" : "—"}</span>
                  <span style={{ fontFamily: "monospace", color: "#374151", minWidth: 180 }}>{s.step}</span>
                  <span style={{ color: "#64748b" }}>{s.message}</span>
                </div>
              ))}
            </div>
          )}
          {deployRun.error && <div style={{ marginTop: 8, color: "#dc2626", fontSize: 11 }}>⚠ {deployRun.error}</div>}
        </div>
      )}
    </div>
  );
}

// ── Outputs tab ───────────────────────────────────────────────────────────

function OutputsTab() {
  const [runs,     setRuns]     = useState<RunOutputEntry[]>([]);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const resp = await listOutputs();
      setRuns(resp.runs);
      if (resp.runs.length > 0) setExpanded(resp.runs[0].run_id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load outputs");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, []);

  const groups: { key: keyof RunOutputEntry; label: string; icon: string }[] = [
    { key: "ddl",      label: "DDL",               icon: "🗄️" },
    { key: "dml",      label: "DML",               icon: "🔄" },
    { key: "sp",       label: "Stored Procedures",  icon: "⚙️" },
    { key: "dag",      label: "Airflow DAGs",        icon: "🌀" },
    { key: "config",   label: "Config",             icon: "📋" },
    { key: "plan",     label: "Plan",               icon: "📝" },
    { key: "review",   label: "Review Report",      icon: "🔍" },
    { key: "manifest", label: "Manifest",           icon: "📦" },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: "#64748b" }}>Generated Artifacts — core/development/output/</span>
        <button onClick={load} style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid #e2e8f0", background: "#fff", color: "#475569", fontSize: 11, cursor: "pointer" }}>↻ Refresh</button>
      </div>

      {loading && <div style={{ color: "#94a3b8", fontSize: 12, textAlign: "center", padding: 16 }}>Loading…</div>}
      {error   && <div style={{ color: "#dc2626", fontSize: 11, padding: "8px 12px", background: "#fee2e2", borderRadius: 8 }}>⚠ {error}</div>}
      {!loading && !error && runs.length === 0 && (
        <div style={{ color: "#94a3b8", fontSize: 12, fontStyle: "italic", textAlign: "center", padding: 20 }}>
          No output runs found in core/development/output/
        </div>
      )}

      {runs.map(run => {
        const isOpen = expanded === run.run_id;
        const total  = groups.reduce((n, g) => n + ((run[g.key] as string[] | undefined)?.length ?? 0), 0);
        return (
          <div key={run.run_id} style={{ marginBottom: 8, borderRadius: 10, border: "1px solid #e2e8f0", overflow: "hidden" }}>
            <button onClick={() => setExpanded(isOpen ? null : run.run_id)} style={{
              width: "100%", padding: "10px 14px", background: isOpen ? "#eff6ff" : "#f8fafc",
              border: "none", cursor: "pointer", textAlign: "left",
              display: "flex", alignItems: "center", gap: 10,
            }}>
              <span style={{ fontSize: 12 }}>{isOpen ? "▼" : "▶"}</span>
              <span style={{ fontSize: 12, fontWeight: 700, color: "#1e293b", fontFamily: "monospace" }}>{run.run_id}</span>
              <span style={{ fontSize: 10, color: "#94a3b8" }}>{total} files</span>
              <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                {groups.filter(g => (run[g.key] as string[] | undefined)?.length).map(g => (
                  <span key={g.key} style={{ fontSize: 10, padding: "1px 6px", borderRadius: 4, background: "#e0f2fe", color: "#0369a1" }}>
                    {g.icon} {(run[g.key] as string[]).length}
                  </span>
                ))}
              </div>
            </button>
            {isOpen && (
              <div style={{ padding: "10px 14px", background: "#fff", borderTop: "1px solid #f1f5f9" }}>
                {groups.map(g => {
                  const files = (run[g.key] as string[] | undefined) ?? [];
                  if (!files.length) return null;
                  return (
                    <div key={g.key} style={{ marginBottom: 10 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
                        {g.icon} {g.label}
                      </div>
                      {files.map(f => (
                        <div key={f} style={{ padding: "3px 8px", background: "#f8fafc", borderRadius: 5, marginBottom: 3, fontSize: 11, color: "#374151", fontFamily: "monospace", border: "1px solid #f1f5f9" }}>{f}</div>
                      ))}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Main DevelopmentPanel ─────────────────────────────────────────────────

type Tab = "pipeline_run" | "checkpoint" | "deploy" | "outputs";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "pipeline_run", label: "Pipeline Run", icon: "⚡" },
  { id: "checkpoint",   label: "Checkpoint",   icon: "🔖" },
  { id: "deploy",       label: "Deploy",       icon: "🚀" },
  { id: "outputs",      label: "Outputs",      icon: "📦" },
];

interface Props {
  onLog: (e: object) => void;
}

export function DevelopmentPanel({ onLog }: Props) {
  const [tab,       setTab]       = useState<Tab>("pipeline_run");
  const [activeRun, setActiveRun] = useState<RunSummary | null>(null);

  const handleStarted = useCallback((run: RunSummary) => {
    setActiveRun(run);
    setTab("checkpoint");
    onLog({ timestamp: new Date().toISOString(), module: "development", event: "run_started", request_id: run.request_id });
  }, [onLog]);

  const handleUpdate = useCallback((run: RunSummary) => {
    setActiveRun(run);
  }, []);

  const cpBadge = activeRun?.status === "checkpoint"
    ? <span style={{ fontSize: 9, fontWeight: 800, padding: "1px 5px", borderRadius: 8, background: "#fef9c3", color: "#a16207", border: "1px solid #fde68a", marginLeft: 4 }}>CP{activeRun.checkpoint_number}</span>
    : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Tab bar */}
      <div style={{ display: "flex", borderBottom: "1px solid #e2e8f0", background: "#f8fafc", padding: "0 4px" }}>
        {TABS.map(t => {
          const active = tab === t.id;
          return (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              padding: "9px 14px", border: "none",
              borderBottom: active ? "2px solid #e07b39" : "2px solid transparent",
              background: "transparent", color: active ? "#e07b39" : "#64748b",
              fontSize: 11, fontWeight: active ? 700 : 500, cursor: "pointer",
              display: "flex", alignItems: "center", gap: 5,
            }}>
              {t.icon} {t.label}
              {t.id === "checkpoint" && cpBadge}
            </button>
          );
        })}
        {activeRun && (
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", paddingRight: 8 }}>
            <Pill label={STATUS_LABEL[activeRun.status] ?? activeRun.status} color={STATUS_COLOR[activeRun.status] ?? "#94a3b8"} />
          </div>
        )}
      </div>

      {/* Active run strip (shown when not on checkpoint tab) */}
      {activeRun && tab !== "checkpoint" && (
        <div style={{ padding: "5px 12px", background: "#f0f7ff", borderBottom: "1px solid #e0eeff", display: "flex", alignItems: "center", gap: 8, fontSize: 10 }}>
          <span style={{ color: "#3b82f6", fontFamily: "monospace" }}>Run: {activeRun.request_id.slice(0, 12)}…</span>
          <Pill label={STATUS_LABEL[activeRun.status]} color={STATUS_COLOR[activeRun.status]} />
          {activeRun.status === "checkpoint" && (
            <button onClick={() => setTab("checkpoint")} style={{ marginLeft: "auto", fontSize: 10, padding: "2px 8px", borderRadius: 6, border: "1px solid #fcd34d", background: "#fffbeb", color: "#92400e", cursor: "pointer", fontWeight: 700 }}>
              ⏸ Action Required →
            </button>
          )}
        </div>
      )}

      {/* Tab content */}
      <div style={{ flex: 1, overflowY: "auto", padding: 14 }}>
        {tab === "pipeline_run" && <PipelineRunTab onStarted={handleStarted} />}
        {tab === "checkpoint"   && <CheckpointTab  run={activeRun} onUpdate={handleUpdate} />}
        {tab === "deploy"       && <DeployTab       run={activeRun} />}
        {tab === "outputs"      && <OutputsTab />}
      </div>
    </div>
  );
}
