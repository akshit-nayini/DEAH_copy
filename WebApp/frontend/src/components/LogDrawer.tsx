import { SC } from "../constants";
import { fmtDuration, fmtTime } from "../utils";

interface LogEntry {
  module_id: string;
  status: string;
  duration_ms?: number | null;
  timestamp: string;
  request_summary: string;
  response_summary: string;
}

interface Props {
  logs: LogEntry[];
  onClose: () => void;
}

export function LogDrawer({ logs, onClose }: Props) {
  return (
    <div style={{ position:"fixed", right:0, top:0, bottom:0, width:"min(420px,100vw)", background:"#fff", zIndex:2000, boxShadow:"-8px 0 32px rgba(0,0,0,0.12)", display:"flex", flexDirection:"column", borderLeft:"1px solid #e2e8f0" }}>
      <div style={{ padding:"12px 16px", borderBottom:"1px solid #e2e8f0", display:"flex", justifyContent:"space-between", alignItems:"center", background:"#f8fafc" }}>
        <span style={{ color:"#1e293b", fontWeight:700, fontSize:13 }}>📋 Audit Log</span>
        <div style={{ display:"flex", gap:8, alignItems:"center" }}>
          <span style={{ fontSize:9, color:"#94a3b8" }}>{logs.length} entries</span>
          <button onClick={onClose} style={{ background:"none", border:"none", color:"#94a3b8", fontSize:18, cursor:"pointer" }}>×</button>
        </div>
      </div>
      <div style={{ flex:1, overflowY:"auto", padding:12 }}>
        {!logs.length && <div style={{ color:"#cbd5e1", fontSize:11, textAlign:"center", marginTop:36 }}>No logs yet.</div>}
        {logs.map((l, i) => (
          <div key={i} style={{ marginBottom:7, padding:"8px 10px", background:"#f8fafc", borderRadius:7, borderLeft:`3px solid ${l.status === "done" ? "#22c55e" : "#ef4444"}`, border:"1px solid #e2e8f0", borderLeftWidth:3 }}>
            <div style={{ display:"flex", justifyContent:"space-between", marginBottom:2 }}>
              <span style={{ fontSize:10, fontWeight:700, color:"#334155" }}>{l.module_id}</span>
              <div style={{ display:"flex", gap:6, alignItems:"center" }}>
                {l.duration_ms != null && <span style={{ fontSize:9, color:"#6b7280" }}>⏱ {fmtDuration(l.duration_ms)}</span>}
                <span style={{ fontSize:9, color:"#94a3b8" }}>{fmtTime(l.timestamp)}</span>
              </div>
            </div>
            <div style={{ fontSize:9, color:"#64748b", lineHeight:1.7 }}>
              <div><span style={{ color:"#3b82f6", fontWeight:600 }}>REQ:</span> {l.request_summary}</div>
              <div><span style={{ color:"#16a34a", fontWeight:600 }}>RES:</span> {l.response_summary}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
