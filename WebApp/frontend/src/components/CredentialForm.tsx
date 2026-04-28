import { useState } from "react";
import { CRED_FIELDS } from "../credentials";

interface Props {
  subId: string;
  savedCreds?: Record<string, string> | null;
  onSubmit: (vals: Record<string, string>) => void;
}

export function CredentialForm({ subId, savedCreds, onSubmit }: Props) {
  const cfg = CRED_FIELDS[subId];
  const [vals, setVals] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    cfg.fields.forEach(f => { init[f.key] = savedCreds?.[f.key] || ""; });
    return init;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [show,   setShow]   = useState<Record<string, boolean>>({});

  const validate = () => {
    const e: Record<string, string> = {};
    cfg.fields.filter(f => f.required).forEach(f => { if (!vals[f.key]?.trim()) e[f.key] = "Required"; });
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  return (
    <div style={{ background:`${cfg.color}0d`, border:`1.5px solid ${cfg.color}55`, borderRadius:10, overflow:"hidden", margin:"8px 0" }}>
      <div style={{ background:cfg.color, padding:"8px 12px", display:"flex", alignItems:"center", gap:7 }}>
        <span style={{ fontSize:14 }}>{cfg.icon}</span>
        <span style={{ color:"#fff", fontWeight:700, fontSize:12 }}>{cfg.title} Required</span>
        <span style={{ marginLeft:"auto", fontSize:10, color:"rgba(255,255,255,0.75)" }}>Needed to run this sub-module</span>
      </div>
      <div style={{ padding:"12px 14px" }}>
        <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:"8px 12px", marginBottom:10 }}>
          {cfg.fields.map(f => (
            <div key={f.key} style={{ gridColumn: f.key === "jira_url" || f.key === "github_org" ? "1/-1" : "auto" }}>
              <label style={{ fontSize:10, fontWeight:600, color:"#374151", display:"block", marginBottom:3 }}>
                {f.label}{f.required && <span style={{ color:"#ef4444", marginLeft:2 }}>*</span>}
              </label>
              <div style={{ position:"relative" }}>
                <input
                  type={f.type === "password" && show[f.key] ? "text" : (f.type || "text")}
                  value={vals[f.key] || ""}
                  onChange={e => { setVals(p => ({ ...p, [f.key]: e.target.value })); setErrors(p => ({ ...p, [f.key]: "" })); }}
                  placeholder={f.placeholder}
                  style={{ width:"100%", padding: f.type === "password" ? "6px 28px 6px 9px" : "6px 9px", borderRadius:6,
                    border:`1px solid ${errors[f.key] ? "#fca5a5" : "#e2e8f0"}`, fontSize:11, boxSizing:"border-box",
                    background: errors[f.key] ? "#fff5f5" : "#fff", color:"#1e293b" }}
                />
                {f.type === "password" && (
                  <button onClick={() => setShow(p => ({ ...p, [f.key]: !p[f.key] }))}
                    style={{ position:"absolute", right:6, top:"50%", transform:"translateY(-50%)", background:"none", border:"none", cursor:"pointer", fontSize:11, color:"#94a3b8", padding:0, lineHeight:1 }}>
                    {show[f.key] ? "🙈" : "👁️"}
                  </button>
                )}
              </div>
              {errors[f.key] && <div style={{ fontSize:9, color:"#ef4444", marginTop:2 }}>⚠ {errors[f.key]}</div>}
            </div>
          ))}
        </div>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
          <span style={{ fontSize:10, color:"#94a3b8" }}>🔒 Session-only storage</span>
          <button onClick={() => validate() && onSubmit(vals)}
            style={{ padding:"6px 18px", borderRadius:7, border:"none", background:cfg.color, color:"#fff", fontSize:11, fontWeight:700, cursor:"pointer", display:"flex", alignItems:"center", gap:5, boxShadow:`0 2px 8px ${cfg.color}44` }}>
            ✓ Save & Run
          </button>
        </div>
      </div>
    </div>
  );
}
