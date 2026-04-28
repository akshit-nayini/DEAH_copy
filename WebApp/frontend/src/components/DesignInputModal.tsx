import { useState } from "react";
import { DesignSource } from "../services/designApi";

interface Props {
  onClose: () => void;
  onSelect: (source: DesignSource) => void;
}

export function DesignInputModal({ onClose, onSelect }: Props) {
  const [tab,          setTab]          = useState<"ticket" | "document">("ticket");
  const [ticketId,     setTicketId]     = useState("");
  const [documentPath, setDocumentPath] = useState("");
  const [error,        setError]        = useState("");

  const handleSubmit = () => {
    if (tab === "ticket") {
      if (!ticketId.trim()) { setError("Jira ticket ID is required"); return; }
      onSelect({ type: "ticket", ticketId: ticketId.trim().toUpperCase() });
    } else {
      if (!documentPath.trim()) { setError("Document path is required"); return; }
      onSelect({ type: "document", documentPath: documentPath.trim() });
    }
  };

  const inputStyle = (hasError: boolean) => ({
    width: "100%", padding: "9px 12px", borderRadius: 8,
    border: `1px solid ${hasError ? "#fca5a5" : "#e2e8f0"}`,
    fontSize: 13, outline: "none", boxSizing: "border-box" as const,
  });

  return (
    <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.4)", zIndex:1000, display:"flex", alignItems:"center", justifyContent:"center" }}>
      <div style={{ background:"#fff", borderRadius:14, width:420, maxWidth:"calc(100vw - 32px)", padding:24, boxShadow:"0 8px 32px rgba(0,0,0,0.18)" }}>

        {/* Header */}
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:18 }}>
          <div style={{ fontWeight:700, fontSize:15, color:"#1e293b" }}>🗄️ Design — Select Input</div>
          <button onClick={onClose} style={{ background:"none", border:"none", fontSize:20, cursor:"pointer", color:"#94a3b8", lineHeight:1 }}>×</button>
        </div>

        {/* Tabs */}
        <div style={{ display:"flex", gap:8, marginBottom:16 }}>
          {(["ticket", "document"] as const).map(t => (
            <button key={t} onClick={() => { setTab(t); setError(""); }}
              style={{ flex:1, padding:"8px 0", borderRadius:8,
                border:`2px solid ${tab === t ? "#e07b39" : "#e2e8f0"}`,
                background: tab === t ? "#fff7ed" : "#fff",
                color: tab === t ? "#c2600a" : "#64748b",
                fontWeight:700, fontSize:12, cursor:"pointer", transition:"all 0.15s" }}>
              {t === "ticket" ? "🎫 Jira Ticket" : "📄 Document Path"}
            </button>
          ))}
        </div>

        {/* Ticket input */}
        {tab === "ticket" && (
          <div>
            <label style={{ fontSize:11, fontWeight:600, color:"#374151", display:"block", marginBottom:5 }}>
              Jira Ticket ID <span style={{ color:"#e07b39" }}>*</span>
            </label>
            <input
              autoFocus
              value={ticketId}
              onChange={e => { setTicketId(e.target.value); setError(""); }}
              onKeyDown={e => e.key === "Enter" && handleSubmit()}
              placeholder="e.g. SCRUM-5"
              style={inputStyle(!!error && tab === "ticket")}
            />
            <div style={{ fontSize:10, color:"#94a3b8", marginTop:4 }}>
              The pipeline runs: requirements → data model → architecture → impl steps
            </div>
          </div>
        )}

        {/* Document path input */}
        {tab === "document" && (
          <div>
            <label style={{ fontSize:11, fontWeight:600, color:"#374151", display:"block", marginBottom:5 }}>
              Document Path <span style={{ color:"#e07b39" }}>*</span>
            </label>
            <input
              autoFocus
              value={documentPath}
              onChange={e => { setDocumentPath(e.target.value); setError(""); }}
              onKeyDown={e => e.key === "Enter" && handleSubmit()}
              placeholder="e.g. requirements/my-doc.md"
              style={inputStyle(!!error && tab === "document")}
            />
            <div style={{ fontSize:10, color:"#94a3b8", marginTop:4 }}>
              Path relative to the agents/ directory on the server
            </div>
          </div>
        )}

        {error && (
          <div style={{ color:"#dc2626", fontSize:11, marginTop:6, display:"flex", alignItems:"center", gap:4 }}>
            <span>⚠</span>{error}
          </div>
        )}

        {/* Buttons */}
        <div style={{ display:"flex", gap:8, marginTop:20 }}>
          <button onClick={onClose}
            style={{ flex:1, padding:"10px 0", borderRadius:8, border:"1px solid #e2e8f0",
              background:"#fff", color:"#64748b", fontSize:13, fontWeight:600, cursor:"pointer" }}>
            Cancel
          </button>
          <button onClick={handleSubmit}
            style={{ flex:2, padding:"10px 0", borderRadius:8, border:"none",
              background:"#e07b39", color:"#fff", fontSize:13, fontWeight:700,
              cursor:"pointer", boxShadow:"0 2px 8px rgba(224,123,57,0.3)" }}>
            ▶ Run Pipeline
          </button>
        </div>
      </div>
    </div>
  );
}
