import { SC, RunStatus } from "../constants";
import { fmtDuration, fmtTime } from "../utils";

interface SubResult {
  label: string;
  icon: string;
  status: RunStatus;
  duration: number | null;
}

interface Props {
  status: RunStatus;
  duration?: number | null;
  completedAt?: string | null;
  subResults?: Record<string, SubResult> | null;
}

export function CompletionCard({ status, duration, completedAt, subResults }: Props) {
  if (status === "idle") return null;

  if (status === "running") return (
    <div style={{ background:"#eff6ff", border:"1px solid #bfdbfe", borderRadius:8, padding:"10px 14px", display:"flex", alignItems:"center", gap:8 }}>
      <span style={{ fontSize:14, display:"inline-block", animation:"spin 0.8s linear infinite", color:"#3b82f6" }}>↻</span>
      <div>
        <div style={{ fontSize:12, fontWeight:600, color:"#1d4ed8" }}>Module Running…</div>
        <div style={{ fontSize:10, color:"#60a5fa" }}>Processing with AI</div>
      </div>
    </div>
  );

  if (status === "error") return (
    <div style={{ background:"#fee2e2", border:"1px solid #fca5a5", borderRadius:8, padding:"10px 14px" }}>
      <div style={{ fontSize:12, fontWeight:700, color:"#dc2626" }}>✕ Module Failed</div>
    </div>
  );

  const passed = subResults ? Object.values(subResults).filter(r => r.status === "done").length : 0;
  const total  = subResults ? Object.keys(subResults).length : 0;

  return (
    <div style={{ background:"#f0fdf4", border:"1px solid #bbf7d0", borderRadius:8, padding:"10px 14px" }}>
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:6 }}>
        <div style={{ display:"flex", alignItems:"center", gap:6 }}>
          <span>✅</span>
          <span style={{ fontSize:12, fontWeight:700, color:"#15803d" }}>Completed Successfully</span>
        </div>
        <span style={{ fontSize:11, fontWeight:700, color:"#16a34a", background:"#dcfce7", borderRadius:6, padding:"2px 8px" }}>⏱ {fmtDuration(duration)}</span>
      </div>
      <div style={{ display:"flex", gap:16, fontSize:10, color:"#166534", flexWrap:"wrap" }}>
        <span>🕐 {fmtTime(completedAt)}</span>
        {subResults && <span>📋 {passed}/{total} passed</span>}
      </div>
      {subResults && (
        <div style={{ marginTop:8, display:"flex", flexDirection:"column", gap:3 }}>
          {Object.entries(subResults).map(([id, r]) => (
            <div key={id} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"3px 8px", background:"#fff", borderRadius:5, border:"1px solid #bbf7d0" }}>
              <span style={{ fontSize:10, color:"#374151", fontWeight:500 }}>{r.icon} {r.label}</span>
              <div style={{ display:"flex", gap:6, alignItems:"center" }}>
                <span style={{ fontSize:9, color:SC.color[r.status], fontWeight:700 }}>{SC.icon[r.status]} {SC.label[r.status]}</span>
                {r.duration != null && <span style={{ fontSize:9, color:"#6b7280" }}>⏱ {fmtDuration(r.duration)}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
