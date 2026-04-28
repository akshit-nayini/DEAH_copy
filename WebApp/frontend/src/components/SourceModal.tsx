import { useState, useRef } from "react";
import { parseFile } from "../utils";
import type { SourceSelection } from "../services/requirementsApi";
import type { Project } from "../adminConfig";

interface Props {
  onClose: () => void;
  onSelect: (source: SourceSelection) => void;
  project?: Project | null;
}

export function SourceModal({ onClose, onSelect, project }: Props) {
  const [tab, setTab] = useState("text");

  // text / file
  const [text, setText] = useState("");
  const [fn,   setFn]   = useState("");
  const [fc,   setFc]   = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const [ghOrg,    setGhOrg]    = useState(project?.github.org    ?? "");
  const [ghRepo,   setGhRepo]   = useState(project?.github.repo   ?? "");
  const [ghBranch, setGhBranch] = useState(project?.github.branch ?? "");
  const [ghPath,   setGhPath]   = useState("");
  const [ghToken,  setGhToken]  = useState(project?.github.token  ?? "");
  const [ghShowTk, setGhShowTk] = useState(false);

  const applyGitHubUrl = (raw: string): boolean => {
    const m = raw.match(/^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/blob\/([^/]+)\/(.+)$/);
    if (!m) return false;
    setGhOrg(m[1]); setGhRepo(m[2]); setGhBranch(m[3]); setGhPath(m[4]);
    setErrors({});
    return true;
  };

  const [driveUrl,   setDriveUrl]   = useState("");
  const [driveToken, setDriveToken] = useState("");
  const [driveShow,  setDriveShow]  = useState(false);

  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFn(f.name);
    setFc(await parseFile(f));
  };

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    if (tab === "text"         && !text.trim())      e.text    = "Required";
    if (tab === "github"       && !ghOrg.trim())     e.ghOrg   = "Required";
    if (tab === "github"       && !ghRepo.trim())    e.ghRepo  = "Required";
    if (tab === "github"       && !ghPath.trim())    e.ghPath  = "Required";
    if (tab === "google_drive" && !driveUrl.trim())  e.driveUrl    = "Required";
    if (tab === "google_drive" && !driveToken.trim()) e.driveToken = "Required";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const go = () => {
    if (!validate()) return;
    if (tab === "text")         onSelect({ type: "text",         content: text });
    if (tab === "file")         onSelect({ type: "file",         content: fc || `[File:${fn}]` });
    if (tab === "github")       onSelect({ type: "github",       org: ghOrg, repo: ghRepo, branch: ghBranch || "main", filePath: ghPath, patToken: ghToken });
    if (tab === "google_drive") onSelect({ type: "google_drive", driveUrlOrId: driveUrl, oauthToken: driveToken });
  };

  const inputStyle = (errKey?: string): React.CSSProperties => ({
    width: "100%", padding: "7px 10px", borderRadius: 6, fontSize: 12,
    border: `1px solid ${errors[errKey ?? ""] ? "#fca5a5" : "#e2e8f0"}`,
    background: errors[errKey ?? ""] ? "#fff5f5" : "#fff",
    boxSizing: "border-box", color: "#1e293b",
  });

  const field = (label: string, errKey: string, child: React.ReactNode) => (
    <div key={errKey}>
      <label style={{ fontSize: 10, fontWeight: 600, color: "#374151", display: "block", marginBottom: 3 }}>
        {label}
      </label>
      {child}
      {errors[errKey] && <div style={{ fontSize: 9, color: "#ef4444", marginTop: 2 }}>⚠ {errors[errKey]}</div>}
    </div>
  );

  const tabs = [
    { id: "text",         l: "📝 Text"          },
    { id: "file",         l: "📁 File"          },
    { id: "github",       l: "🌿 GitHub"        },
    { id: "google_drive", l: "🌐 Google Drive"  },
  ];

  const backendBadge = (tab === "github" || tab === "google_drive") && (
    <div style={{ marginBottom: 10, padding: "6px 10px", background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 6, fontSize: 10, color: "#15803d", fontWeight: 600 }}>
      ⚡ Uses backend pipeline — fetches doc and runs Requirements Agent
    </div>
  );

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 3000, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div style={{ background: "#fff", borderRadius: 14, width: "min(520px,100%)", maxHeight: "90vh", overflowY: "auto", boxShadow: "0 20px 60px rgba(0,0,0,0.18)" }}>

        {/* Header */}
        <div style={{ padding: "14px 18px", borderBottom: "1px solid #e2e8f0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <div style={{ fontWeight: 700, fontSize: 14, color: "#1e293b" }}>Select Requirements Source</div>
            <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "#94a3b8" }}>×</button>
          </div>
          <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
            {tabs.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                style={{ padding: "5px 10px", fontSize: 11, fontWeight: 600, border: "none", borderRadius: "5px 5px 0 0", cursor: "pointer",
                  background: tab === t.id ? "#4f6ef7" : "#f1f5f9", color: tab === t.id ? "#fff" : "#475569" }}>
                {t.l}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div style={{ padding: 18 }}>
          {backendBadge}

          {/* ── Text ── */}
          {tab === "text" && (
            <>
              {field("Requirements / Transcript", "text",
                <textarea value={text} onChange={e => { setText(e.target.value); setErrors(p => ({ ...p, text: "" })); }}
                  placeholder="Paste stakeholder transcript or requirements…" rows={6}
                  style={{ ...inputStyle("text"), resize: "vertical" }}/>
              )}
            </>
          )}

          {/* ── File ── */}
          {tab === "file" && (
            <div>
              <div onClick={() => fileRef.current?.click()}
                style={{ border: "2px dashed #bfdbfe", borderRadius: 10, padding: 24, textAlign: "center", cursor: "pointer", background: "#eff6ff" }}>
                <div style={{ fontSize: 26, marginBottom: 4 }}>📂</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#2563eb" }}>Click to upload</div>
                <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>PDF · DOCX · TXT · MD</div>
              </div>
              <input ref={fileRef} type="file" accept=".txt,.md,.pdf,.docx,.doc" onChange={handleFile} style={{ display: "none" }}/>
              {fn && <div style={{ marginTop: 8, padding: "6px 12px", background: "#f0fdf4", borderRadius: 5, fontSize: 11, color: "#16a34a", border: "1px solid #bbf7d0" }}>✅ {fn}</div>}
            </div>
          )}

          {/* ── GitHub ── */}
          {tab === "github" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {field("Organisation / Username *  (or paste full GitHub URL here)", "ghOrg",
                <input value={ghOrg} onChange={e => { if (!applyGitHubUrl(e.target.value)) { setGhOrg(e.target.value); setErrors(p => ({ ...p, ghOrg: "" })); } }}
                  placeholder="e.g. my-org  or  https://github.com/org/repo/blob/main/path/file.docx" style={inputStyle("ghOrg")}/>
              )}
              {field("Repository *", "ghRepo",
                <input value={ghRepo} onChange={e => { setGhRepo(e.target.value); setErrors(p => ({ ...p, ghRepo: "" })); }}
                  placeholder="e.g. my-repo" style={inputStyle("ghRepo")}/>
              )}
              {field("Branch  (your feature branch, or leave blank for main)", "ghBranch",
                <input value={ghBranch} onChange={e => setGhBranch(e.target.value)}
                  placeholder="main" style={inputStyle()}/>
              )}
              {field("File Path *", "ghPath",
                <input value={ghPath} onChange={e => { if (!applyGitHubUrl(e.target.value)) { setGhPath(e.target.value); setErrors(p => ({ ...p, ghPath: "" })); } }}
                  placeholder="core/requirements_pod/transcripts/file.docx" style={inputStyle("ghPath")}/>
              )}
              {field("Personal Access Token (optional for public repos)", "ghToken",
                <div style={{ position: "relative" }}>
                  <input value={ghToken} onChange={e => setGhToken(e.target.value)} type={ghShowTk ? "text" : "password"}
                    placeholder="ghp_••••••••" style={{ ...inputStyle(), paddingRight: 32 }}/>
                  <button onClick={() => setGhShowTk(p => !p)}
                    style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "#94a3b8", padding: 0 }}>
                    {ghShowTk ? "🙈" : "👁️"}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* ── Google Drive ── */}
          {tab === "google_drive" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {field("Drive URL or File ID *", "driveUrl",
                <input value={driveUrl} onChange={e => { setDriveUrl(e.target.value); setErrors(p => ({ ...p, driveUrl: "" })); }}
                  placeholder="https://docs.google.com/document/d/FILE_ID/edit" style={inputStyle("driveUrl")}/>
              )}
              {field("OAuth 2.0 Access Token *", "driveToken",
                <div style={{ position: "relative" }}>
                  <input value={driveToken} onChange={e => { setDriveToken(e.target.value); setErrors(p => ({ ...p, driveToken: "" })); }}
                    type={driveShow ? "text" : "password"} placeholder="ya29.••••••••"
                    style={{ ...inputStyle("driveToken"), paddingRight: 32 }}/>
                  <button onClick={() => setDriveShow(p => !p)}
                    style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "#94a3b8", padding: 0 }}>
                    {driveShow ? "🙈" : "👁️"}
                  </button>
                </div>
              )}
              <div style={{ padding: "6px 10px", background: "#f0f9ff", borderRadius: 6, fontSize: 10, color: "#0369a1", border: "1px solid #bae6fd" }}>
                ℹ️ Token requires <strong>drive.readonly</strong> scope.
              </div>
            </div>
          )}

          {/* Actions */}
          <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "flex-end" }}>
            <button onClick={onClose} style={{ padding: "7px 16px", borderRadius: 7, border: "1px solid #e2e8f0", background: "#fff", cursor: "pointer", fontSize: 12, color: "#64748b" }}>Cancel</button>
            <button onClick={go}
              style={{ padding: "7px 18px", borderRadius: 7, border: "none", background: "#4f6ef7", color: "#fff", cursor: "pointer", fontSize: 12, fontWeight: 700 }}>
              {tab === "github" || tab === "google_drive" ? "Fetch & Process →" : "Load & Run →"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
