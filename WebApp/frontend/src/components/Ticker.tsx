import { useState, useEffect } from "react";
import { LIVE_STEPS } from "../constants";

export function Ticker({ running }: { running: boolean }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!running) { setI(0); return; }
    const t = setInterval(() => setI(p => (p + 1) % LIVE_STEPS.length), 750);
    return () => clearInterval(t);
  }, [running]);

  if (!running) return null;
  return (
    <div style={{ display:"flex", alignItems:"center", gap:6, padding:"5px 10px", background:"#eff6ff", border:"1px solid #bfdbfe", borderRadius:6, margin:"6px 0" }}>
      <span style={{ fontSize:12, display:"inline-block", animation:"spin 0.8s linear infinite", color:"#3b82f6" }}>↻</span>
      <span style={{ fontSize:11, color:"#1d4ed8", fontWeight:500 }}>{LIVE_STEPS[i]}</span>
    </div>
  );
}
