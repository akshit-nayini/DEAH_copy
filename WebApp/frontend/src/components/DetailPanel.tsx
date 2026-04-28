import { useState, useCallback, useEffect, useRef } from "react";
import { SC, RunStatus } from "../constants";
import { CRED_FIELDS } from "../credentials";
import { callClaude, callLogAPI } from "../services/api";
import {
  processRequirements,
  formatCallSummary,
  formatTemplateFiller,
  formatJiraTickets,
  formatSmartRouter,
  type SourceSelection,
  type AgentResponse,
} from "../services/requirementsApi";
import { fmtDuration } from "../utils";
import { useWindowSize } from "../hooks/useWindowSize";
import { Module, SubModule } from "../modules";
import { Ticker } from "./Ticker";
import { StatusBadge } from "./StatusBadge";
import { CompletionCard } from "./CompletionCard";
import { CredentialForm } from "./CredentialForm";
import { SourceModal } from "./SourceModal";
import type { Project } from "../adminConfig";
import { JiraTicketCards } from "./JiraTicketCards";
import { DevelopmentPanel } from "./DevelopmentPanel";

interface SubState {
  status: RunStatus;
  output: string;
  duration: number | null;
  completedAt: string | null;
  startedAt?: string;
  _combined?: string;
}

interface Props {
  mod: Module;
  allOutputs: Record<string, string>;
  onLog: (entry: object) => void;
  onClose: () => void;
  globalSubStates: Record<string, Record<string, SubState>>;
  onSubStateChange: (modId: string, subId: string, state: Partial<SubState> & { _combined?: string }) => void;
  onModStateChange: (modId: string, state: { status: RunStatus; duration: number | null; completedAt: string | null }) => void;
  savedCreds: Record<string, Record<string, string>>;
  onSaveCreds: (subId: string, vals: Record<string, string>) => void;
  pausedSubId: string | null;
  project?: Project | null;
}

// Maps each requirements sub-module id to the formatter that extracts its section.
const REQUIREMENTS_FORMATTERS: Record<string, (resp: AgentResponse) => string> = {
  source_docs:    formatCallSummary,
  template_filler: formatTemplateFiller,
  jira_integrator: formatJiraTickets,
  smart_router:    formatSmartRouter,
};

export function DetailPanel({ mod, allOutputs, onLog, onClose, globalSubStates, onSubStateChange, onModStateChange, savedCreds, onSaveCreds, pausedSubId, project }: Props) {
  const [activeSubId, setActiveSubId] = useState(mod.subModules?.[0]?.id || null);
  const [showSource,  setShowSource]  = useState(false);
  const [isSourcedocumentuploading,  setisSourcedocumentuploading]  = useState(false);
  const [pendingRun,  setPendingRun]  = useState<Record<string, boolean>>({});
  const backendCacheRef = useRef<AgentResponse | null>(null);
  const w = useWindowSize();

  const isRequirements = mod.id === "requirements";

  // ── Development module: dedicated backend-driven panel ────────────────────
  if (mod.id === "development") {
    return (
      <>
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 14, display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 4px 24px rgba(0,0,0,0.08)", minHeight: 520 }}>
          {/* Header */}
          <div style={{ padding: "12px 14px", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "center", gap: 10, background: "#f8fafc" }}>
            <div style={{ width: 34, height: 34, borderRadius: 9, background: "#fff7ed", border: "1px solid #fed7aa", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0 }}>{mod.icon}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: "#1e293b", fontWeight: 700, fontSize: 14 }}>{mod.label}</div>
              <div style={{ color: "#94a3b8", fontSize: 10, marginTop: 1 }}>{mod.desc}</div>
            </div>
            <button onClick={onClose} style={{ background: "none", border: "none", color: "#94a3b8", fontSize: 18, cursor: "pointer", flexShrink: 0 }}>×</button>
          </div>
          <DevelopmentPanel onLog={onLog} />
        </div>
      </>
    );
  }

  const modSubStates   = globalSubStates[mod.id] || {};
  const activeSub      = mod.subModules?.find(s => s.id === activeSubId);
  const activeSubState = modSubStates[activeSubId!] || { status: "idle" as RunStatus, output: "", duration: null, completedAt: null };
  const needsCreds     = !!(activeSub && CRED_FIELDS[activeSub.id]);
  const hasCreds       = !needsCreds || !!savedCreds[activeSub?.id!]?.filled;
  const isPausedHere   = pausedSubId === activeSubId && needsCreds && !hasCreds;

  useEffect(() => {
    const runningSub = mod.subModules?.find(s => modSubStates[s.id]?.status === "running");
    if (runningSub) { setActiveSubId(runningSub.id); return; }
    if (pausedSubId) setActiveSubId(pausedSubId);
  }, [modSubStates, pausedSubId]);

  const buildCtx = (currentSubId: string) => {
    const modCtx = Object.entries(allOutputs).filter(([k, v]) => v && k !== mod.id).map(([k, v]) => `[Module:${k}]:\n${String(v).slice(0, 250)}`).join("\n\n");
    const subCtx = Object.entries(modSubStates).filter(([k, v]) => v?.output && k !== currentSubId).map(([k, v]) => `[Sub:${k}]:\n${String(v.output).slice(0, 200)}`).join("\n\n");
    return [modCtx, subCtx].filter(Boolean).join("\n\n");
  };

  // ── Backend path (GitHub / Google Drive source) ───────────────────────────

  const doRunWithBackend = useCallback(async (source: Extract<SourceSelection, { type: "github" | "google_drive" }>) => {
    const t0 = Date.now();

    // Mark all sub-modules as running
    mod.subModules.forEach(s => {
      onSubStateChange(mod.id, s.id, { status: "running", output: "", duration: null, completedAt: null });
    });
    onModStateChange(mod.id, { status: "running", duration: null, completedAt: null });
    setActiveSubId("source_docs");

    try {
      setisSourcedocumentuploading(true);
      const resp = await processRequirements(source);
      setisSourcedocumentuploading(false);
      backendCacheRef.current = resp;
      const dur   = Date.now() - t0;
      const finAt = new Date().toISOString();

      // Populate each sub-module from the single response
      mod.subModules.forEach(s => {
        const formatter = REQUIREMENTS_FORMATTERS[s.id];
        const output    = formatter ? formatter(resp) : JSON.stringify(resp, null, 2);
        onSubStateChange(mod.id, s.id, { status: "done", output, duration: dur, completedAt: finAt });
      });
      onModStateChange(mod.id, { status: "done", duration: dur, completedAt: finAt });

      const entry = await callLogAPI(`${mod.id}/backend`, JSON.stringify(source), "AgentResponse", "done", dur);
      onLog(entry);
    } catch (err: unknown) {
      const dur = Date.now() - t0;
      const msg = err instanceof Error ? err.message : String(err);
      mod.subModules.forEach(s => {
        onSubStateChange(mod.id, s.id, { status: "error", output: `Error: ${msg}`, duration: dur, completedAt: new Date().toISOString() });
      });
      onModStateChange(mod.id, { status: "error", duration: dur, completedAt: new Date().toISOString() });
      const entry = await callLogAPI(`${mod.id}/backend`, JSON.stringify(source), msg, "error", dur);
      onLog(entry);
    }
  }, [mod, onSubStateChange, onModStateChange, onLog]);

  // ── Claude path (text / file source, or non-requirements modules) ─────────

  const doRunSub = useCallback(async (sub: SubModule, inputOverride?: string) => {
    const t0 = Date.now();
    onSubStateChange(mod.id, sub.id, { status: "running", output: "", duration: null, completedAt: null, startedAt: new Date().toISOString() });
    onModStateChange(mod.id, { status: "running", duration: null, completedAt: null });
    setActiveSubId(sub.id);

    const ctx      = buildCtx(sub.id);
    const credNote = savedCreds[sub.id] ? `\nCredentials configured: ${Object.keys(savedCreds[sub.id]).filter(k => k !== "filled").join(", ")}` : "";
    const userMsg  = inputOverride
      ? `Input:\n${inputOverride}${credNote}\n\nContext:\n${ctx || "None."}`
      : `Execute: ${sub.label}${credNote}\n\nContext:\n${ctx || "None."}`;

    try {
      const result = await callClaude(sub.systemPrompt, userMsg);
      const dur    = Date.now() - t0;
      const finAt  = new Date().toISOString();
      const entry  = await callLogAPI(`${mod.id}/${sub.id}`, userMsg, result, "done", dur);
      onLog(entry);
      onSubStateChange(mod.id, sub.id, { status: "done", output: result, duration: dur, completedAt: finAt });
      onModStateChange(mod.id, { status: "done", duration: dur, completedAt: finAt });
      const newSub    = { ...modSubStates, [sub.id]: { output: result } };
      const combined  = Object.entries(newSub).filter(([, v]) => v?.output).map(([k, v]) => `[${k}]:\n${v.output}`).join("\n\n");
      onSubStateChange(mod.id, "_combined", { _combined: combined });
    } catch (err: unknown) {
      const dur  = Date.now() - t0;
      const msg  = err instanceof Error ? err.message : String(err);
      const entry = await callLogAPI(`${mod.id}/${sub.id}`, userMsg, msg, "error", dur);
      onLog(entry);
      onSubStateChange(mod.id, sub.id, { status: "error", output: `Error: ${msg}`, duration: dur, completedAt: new Date().toISOString() });
      onModStateChange(mod.id, { status: "error", duration: dur, completedAt: new Date().toISOString() });
    }
  }, [mod, modSubStates, allOutputs, savedCreds, onSubStateChange, onModStateChange, onLog]);

  // ── Source modal callback ─────────────────────────────────────────────────

  const handleSourceSelect = useCallback((source: SourceSelection) => {
    setShowSource(false);
    if (source.type === "github" || source.type === "google_drive") {
      doRunWithBackend(source);
    } else {
      const content = source.type === "text" ? source.content : source.content;
      doRunSub(activeSub!, content);
    }
  }, [activeSub, doRunWithBackend, doRunSub]);

  // ── For non-call_summary requirements subs: re-format from cache ──────────

  const doRunFromCache = useCallback((sub: SubModule) => {
    if (!backendCacheRef.current) return;
    const formatter = REQUIREMENTS_FORMATTERS[sub.id];
    const output    = formatter ? formatter(backendCacheRef.current) : "";
    const finAt     = new Date().toISOString();
    onSubStateChange(mod.id, sub.id, { status: "done", output, duration: 0, completedAt: finAt });
  }, [mod, onSubStateChange]);

  // ── Credential handling ───────────────────────────────────────────────────

  const handleCredSave = (subId: string, vals: Record<string, string>) => {
    const filled = { ...vals, filled: "true" };
    onSaveCreds(subId, filled);
    setPendingRun(p => ({ ...p, [subId]: false }));
    if (!pausedSubId) {
      const sub = mod.subModules?.find(s => s.id === subId);
      if (sub) doRunSub(sub);
    }
  };

  // ── Run button click ──────────────────────────────────────────────────────

  const handleRunClick = () => {
    if (!activeSub) return;

    // Requirements: call_summary → show source modal (text/file/GitHub/Drive)
    if (isRequirements && activeSub.id === "source_docs") {
      setShowSource(true);
      return;
    }

    // Requirements: other subs → re-format from cache if available
    if (isRequirements && backendCacheRef.current) {
      doRunFromCache(activeSub);
      return;
    }

    // Credentials required
    if (needsCreds && !hasCreds) {
      setPendingRun(p => ({ ...p, [activeSub.id]: true }));
      return;
    }

    doRunSub(activeSub);
  };

  const showCredForm    = activeSub && needsCreds && !hasCreds && (isPausedHere || pendingRun[activeSub.id] || activeSubState.status === "idle");
  const cacheAvailable  = isRequirements && !!backendCacheRef.current;
  const subCols         = w < 500 ? "repeat(2,1fr)" : "repeat(4,1fr)";

  const overallStatus: RunStatus =
    Object.values(modSubStates).some(s => s.status === "running") ? "running" :
    Object.values(modSubStates).some(s => s.status === "error")   ? "error"   :
    mod.subModules.every(s => modSubStates[s.id]?.status === "done") ? "done" : "idle";

  const subResults = Object.fromEntries(mod.subModules.map(s => [s.id, {
    label:    s.label,
    icon:     s.icon,
    status:   (modSubStates[s.id]?.status   || "idle") as RunStatus,
    duration: modSubStates[s.id]?.duration || null,
  }]));

  // Run button label
  const runLabel = () => {
    if (activeSubState.status === "running") return <><span style={{ display: "inline-block", animation: "spin 0.8s linear infinite" }}>↻</span> Running…</>;
    if (isRequirements && activeSub?.id === "source_docs") return <><span>▶</span> Select Source & Process</>;
    if (isRequirements && cacheAvailable)  return <><span>↻</span> Re-format from Cache</>;
    if (isRequirements && !cacheAvailable && activeSub?.id !== "source_docs") return <><span>⚠</span> Run Call Summary first</>;
    if (needsCreds && !hasCreds)           return <><span>🔑</span> Enter Credentials to Run</>;
    return <><span>▶</span>{activeSub ? `Run: ${activeSub.label}` : "Run Module"}</>;
  };

  const runDisabled = activeSubState.status === "running" ||
    (isRequirements && !cacheAvailable && activeSub?.id !== "source_docs");

  return (
    <>
      {showSource && <SourceModal onClose={() => setShowSource(false)} onSelect={handleSourceSelect} project={project} />}
      <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 14, display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 4px 24px rgba(0,0,0,0.08)" }}>

        {/* Header */}
        <div style={{ padding: "12px 14px", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "center", gap: 10, background: "#f8fafc" }}>
          <div style={{ width: 34, height: 34, borderRadius: 9, background: "#eff6ff", border: "1px solid #bfdbfe", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0 }}>{mod.icon}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ color: "#1e293b", fontWeight: 700, fontSize: 14 }}>{mod.label}</div>
            <div style={{ display: "flex", gap: 6, marginTop: 3, flexWrap: "wrap", alignItems: "center" }}>
              <span style={{ fontSize: 10, fontWeight: 600, color: SC.color[overallStatus], background: SC.bg[overallStatus], borderRadius: 10, padding: "1px 8px", border: `1px solid ${SC.bdr[overallStatus]}` }}>
                {overallStatus === "running" && <span style={{ display: "inline-block", animation: "spin 0.8s linear infinite", marginRight: 3 }}>↻</span>}
                {SC.icon[overallStatus]} {SC.label[overallStatus]}
              </span>
              {pausedSubId && <span style={{ fontSize: 10, fontWeight: 600, color: "#92400e", background: "#fffbeb", borderRadius: 10, padding: "1px 8px", border: "1px solid #fcd34d" }}>⏸ Pipeline Paused</span>}
              {cacheAvailable && <span style={{ fontSize: 10, fontWeight: 600, color: "#15803d", background: "#f0fdf4", borderRadius: 10, padding: "1px 8px", border: "1px solid #bbf7d0" }}>⚡ Backend data cached</span>}
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#94a3b8", fontSize: 18, cursor: "pointer", flexShrink: 0 }}>×</button>
        </div>

        {/* Paused banner */}
        {isPausedHere && (
          <div style={{ margin: "8px 12px 0", padding: "8px 12px", background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 8, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 16 }}>⏸️</span>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#92400e" }}>Pipeline Paused — Credentials Required</div>
              <div style={{ fontSize: 10, color: "#b45309" }}>Fill in credentials below and click Save & Run to continue.</div>
            </div>
          </div>
        )}

        {/* Sub-module tabs */}
        <div style={{ padding: "10px 12px", borderBottom: "1px solid #e2e8f0", background: "#fafbfc" }}>
          <div style={{ display: "grid", gridTemplateColumns: subCols, gap: 7 }}>
            {mod.subModules.map(sub => {
              const ss         = modSubStates[sub.id] || { status: "idle" as RunStatus };
              const active     = activeSubId === sub.id;
              const isRunning  = ss.status === "running";
              const subHasCred = !CRED_FIELDS[sub.id] || !!savedCreds[sub.id]?.filled;
              const isPaused   = pausedSubId === sub.id;
              return (
                <button key={sub.id} onClick={() => setActiveSubId(sub.id)}
                  style={{ padding: "9px 6px", borderRadius: 9,
                    border: `2px solid ${active ? "#4f6ef7" : isPaused ? "#fcd34d" : isRunning ? "#bfdbfe" : ss.status === "done" ? "#bbf7d0" : ss.status === "error" ? "#fca5a5" : "#e2e8f0"}`,
                    background: active ? "#eff6ff" : isPaused ? "#fffbeb" : isRunning ? "#f0f7ff" : ss.status === "done" ? "#f0fdf4" : "#fff",
                    cursor: "pointer", textAlign: "center", transition: "all 0.15s", position: "relative",
                    boxShadow: active ? "0 2px 8px rgba(79,110,247,0.15)" : isRunning ? "0 0 0 3px rgba(59,130,246,0.15)" : "none" }}>
                  <div style={{ position: "absolute", top: 4, right: 4, width: 7, height: 7, borderRadius: "50%", background: isPaused ? "#f59e0b" : SC.color[ss.status] }}/>
                  {isRunning && <div style={{ position: "absolute", top: 3, right: 3, width: 9, height: 9, borderRadius: "50%", border: "2px solid #3b82f6", animation: "pulseRing 1.2s ease-in-out infinite" }}/>}
                  {CRED_FIELDS[sub.id] && !subHasCred && ss.status === "idle" && !isPaused && <div style={{ position: "absolute", top: 4, left: 4, fontSize: 8 }}>🔑</div>}
                  {CRED_FIELDS[sub.id] && subHasCred  && <div style={{ position: "absolute", top: 4, left: 4, fontSize: 8 }}>✓</div>}
                  {isPaused && <div style={{ position: "absolute", top: 3, left: 4, fontSize: 9 }}>⏸</div>}
                  <div style={{ fontSize: 18, marginBottom: 3 }}>{sub.icon}</div>
                  <div style={{ fontSize: 10, fontWeight: 600, color: active ? "#4f6ef7" : isPaused ? "#92400e" : isRunning ? "#1d4ed8" : ss.status === "done" ? "#15803d" : "#64748b", lineHeight: 1.3 }}>{sub.label}</div>
                  <div style={{ marginTop: 3, fontSize: 9, fontWeight: 700, color: isPaused ? "#f59e0b" : SC.color[ss.status], display: "flex", alignItems: "center", justifyContent: "center", gap: 2 }}>
                    {isRunning && <span style={{ display: "inline-block", animation: "spin 0.8s linear infinite" }}>↻</span>}
                    {isPaused ? "⏸ Waiting" : `${SC.icon[ss.status]} ${SC.label[ss.status]}`}
                  </div>
                  {ss.status === "done" && ss.duration != null && <div style={{ fontSize: 8, color: "#6b7280" }}>⏱ {fmtDuration(ss.duration)}</div>}
                </button>
              );
            })}
          </div>
        </div>

        {/* Active sub info bar */}
        {activeSub && (
          <div style={{ padding: "6px 12px", borderBottom: "1px solid #e2e8f0", background: "#fff", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: "#374151" }}>{activeSub.icon} {activeSub.label}</span>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              {needsCreds && hasCreds  && <span style={{ fontSize: 9, color: "#16a34a", background: "#dcfce7", borderRadius: 10, padding: "1px 7px", border: "1px solid #bbf7d0", fontWeight: 600 }}>🔑 Saved</span>}
              {needsCreds && !hasCreds && <span style={{ fontSize: 9, color: "#e07b39", background: "#fff7ed", borderRadius: 10, padding: "1px 7px", border: "1px solid #fed7aa", fontWeight: 600 }}>🔑 Needed</span>}
              {isRequirements && cacheAvailable && activeSub.id !== "source_docs" &&
                <span style={{ fontSize: 9, color: "#15803d", background: "#f0fdf4", borderRadius: 10, padding: "1px 7px", border: "1px solid #bbf7d0", fontWeight: 600 }}>⚡ From backend</span>}
              <StatusBadge status={activeSubState.status} duration={activeSubState.duration} completedAt={activeSubState.completedAt} small/>
            </div>
          </div>
        )}

        {/* Inline credential form */}
        {showCredForm && activeSub && (
          <div style={{ padding: "0 12px" }}>
            <CredentialForm subId={activeSub.id} savedCreds={savedCreds[activeSub.id]} onSubmit={vals => handleCredSave(activeSub.id, vals)} />
          </div>
        )}

        {/* Output */}
        <div style={{ padding: 12, overflowY: "auto", background: "#fff", minHeight: 80, maxHeight: 340 }}>
          <Ticker running={activeSubState.status === "running"}/>
          {isRequirements && activeSubId === "jira_integrator" && backendCacheRef.current?.jira_tickets?.length
            ? <JiraTicketCards tickets={backendCacheRef.current.jira_tickets} />
            : activeSubState.output
              ? <pre style={{ margin: 0, fontSize: 11, lineHeight: 1.8, whiteSpace: "pre-wrap", wordBreak: "break-word", color: "#334155", fontFamily: "monospace" }}>{activeSubState.output}</pre>
              : <div style={{ color: "#cbd5e1", fontSize: 12, fontStyle: "italic" }}>
                  {showCredForm
                    ? "Fill in credentials above and click Save & Run…"
                    : isRequirements && activeSub?.id !== "source_docs" && !cacheAvailable
                      ? "Run the Source Document sub-module first to fetch data from the backend."
                      : "Select a sub-module and click Run to see output…"}
                </div>}
        </div>

        {/* Completion card */}
        <div style={{ padding: "0 12px 10px" }}>
          <CompletionCard
            status={overallStatus}
            duration={Object.values(modSubStates).reduce((a, s) => a + (s.duration || 0), 0) || null}
            completedAt={Object.values(modSubStates).map(s => s.completedAt).filter(Boolean).sort().pop()}
            subResults={subResults}/>
        </div>

        {/* Run button */}
        <div style={{ padding: "10px 12px", borderTop: "1px solid #e2e8f0", background: "#f8fafc" }}>
          {showCredForm
            ? <div style={{ textAlign: "center", fontSize: 11, color: "#b45309", padding: "6px 0", fontWeight: 500 }}>👆 Enter credentials above to run this sub-module</div>
            : <button onClick={handleRunClick} disabled={runDisabled}
                style={{ width: "100%", padding: "10px 0", borderRadius: 8, border: "none",
                  background: runDisabled ? "#e2e8f0" : mod.btnColor,
                  color: runDisabled ? "#94a3b8" : "#fff", fontSize: 13, fontWeight: 700,
                  cursor: runDisabled ? "not-allowed" : "pointer",
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 7,
                  boxShadow: runDisabled ? "none" : `0 2px 8px ${mod.btnColor}55`, transition: "background 0.2s" }}>
                {runLabel()}
              </button>}
        </div>
      </div>
    </>
  );
}
