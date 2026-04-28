import { SC, RunStatus } from "../constants";
import { fmtDuration } from "../utils";
import { StatusBadge } from "./StatusBadge";
import { Module } from "../modules";

interface Props {
  mod: Module;
  modRunState: { status: RunStatus; duration?: number | null; completedAt?: string | null };
  onSelect: (mod: Module) => void;
  isSelected: boolean;
  onDirectRun: (mod: Module) => void;
}

export function ModTile({ mod, modRunState, onSelect, isSelected, onDirectRun }: Props) {
  const { status, duration, completedAt } = modRunState;
  return (
    <div onClick={() => onSelect(mod)}
      style={{ background:"#fff",
        border:`1.5px solid ${isSelected ? "#4f6ef7" : status === "done" ? "#bbf7d0" : status === "running" ? "#bfdbfe" : status === "error" ? "#fca5a5" : "#e2e8f0"}`,
        borderRadius:12, padding:"14px 12px 11px", cursor:"pointer", transition:"all 0.15s", position:"relative", userSelect:"none",
        boxShadow: isSelected ? "0 4px 20px rgba(79,110,247,0.18)" : status === "done" ? "0 2px 12px rgba(22,163,74,0.12)" : "0 1px 4px rgba(0,0,0,0.06)" }}>
      {status === "running" && <div style={{ position:"absolute", inset:0, borderRadius:12, border:"2px solid #3b82f6", animation:"pulse 1.5s ease-in-out infinite", pointerEvents:"none" }}/>}
      <div style={{ position:"absolute", top:9, right:9 }}>
        <StatusBadge status={status} duration={duration} completedAt={completedAt} small/>
      </div>
      <div style={{ fontSize:26, marginBottom:8, lineHeight:1 }}>{mod.icon}</div>
      <div style={{ color:"#1e293b", fontWeight:700, fontSize:13, marginBottom:3, paddingRight:52 }}>{mod.label}</div>
      <div style={{ color:"#94a3b8", fontSize:11, marginBottom:12, lineHeight:1.4 }}>{mod.desc}</div>
      <button onClick={e => { e.stopPropagation(); onDirectRun(mod); }} disabled={status === "running"}
        style={{ width:"100%", padding:"7px 0", borderRadius:7, border:"none",
          background: status === "running" ? "#93c5fd" : mod.btnColor, color:"#fff", fontSize:11, fontWeight:700,
          cursor: status === "running" ? "not-allowed" : "pointer", display:"flex", alignItems:"center", justifyContent:"center", gap:5,
          boxShadow:`0 2px 6px ${mod.btnColor}44`, transition:"all 0.2s" }}>
        {status === "running"
          ? <><span style={{ display:"inline-block", animation:"spin 0.8s linear infinite", fontSize:11 }}>↻</span> Running…</>
          : status === "done"
            ? <><span>↻</span> Re-run</>
            : <><span>▶</span> Run</>}
      </button>
      {status === "done"  && <div style={{ marginTop:7, height:2, background:"#bbf7d0", borderRadius:1 }}><div style={{ height:"100%", width:"100%", background:"#16a34a", borderRadius:1 }}/></div>}
      {status === "error" && <div style={{ marginTop:7, height:2, background:"#fca5a5", borderRadius:1 }}><div style={{ height:"100%", width:"100%", background:"#ef4444", borderRadius:1 }}/></div>}
    </div>
  );
}
