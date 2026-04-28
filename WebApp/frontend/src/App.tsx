import { useState, useCallback, useRef, useEffect } from "react";
import { SC, RunStatus, SESSION_ID, API_VERSION } from "./constants";
import { MODULES, Module } from "./modules";
import { callClaude, callLogAPI } from "./services/api";
import { CRED_FIELDS } from "./credentials";
import { useWindowSize } from "./hooks/useWindowSize";
import { ModTile } from "./components/ModTile";
import { DetailPanel } from "./components/DetailPanel";
import { LogDrawer } from "./components/LogDrawer";
import { AdminPanel } from "./components/AdminPanel";
import {
  loadAdminConfig, saveAdminConfig, fetchRemoteConfig,
  adminConfigToCredentials, projectToCredentials,
  AdminConfig, UserProfile, Product, Project,
} from "./adminConfig";

interface SubState {
  status: RunStatus;
  output: string;
  duration: number | null;
  completedAt: string | null;
  startedAt?: string;
  _combined?: string;
}

type Role = "admin" | "developer" | null;
const ROLE_KEY = "deah_role";

// ── Login Screen ──────────────────────────────────────────────────────────────
function LoginScreen({ users, onAuth }: { users: UserProfile[]; onAuth: (u: UserProfile) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw,   setShowPw]   = useState(false);
  const [error,    setError]    = useState("");

  const handleLogin = () => {
    const user = users.find(u => u.username === username.trim() && u.password === password);
    if (user) { onAuth(user); }
    else { setError("Invalid username or password"); }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", background: "linear-gradient(135deg,#eff6ff 0%,#f8fafc 60%,#f0fdf4 100%)", fontFamily: "'Segoe UI',system-ui,sans-serif", padding: 24 }}>
      <div style={{ width: "min(380px,100%)", background: "#fff", borderRadius: 18, boxShadow: "0 20px 60px rgba(0,0,0,0.12)", padding: "36px 32px" }}>
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <div style={{ fontSize: 40, marginBottom: 10 }}>⚙️</div>
          <div style={{ fontSize: 22, fontWeight: 800, color: "#1e293b", letterSpacing: -0.5 }}>Prodapt AI Orchestrator</div>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 6 }}>Sign in to continue</div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, color: "#374151", display: "block", marginBottom: 5 }}>Username</label>
            <input value={username} autoFocus
              onChange={e => { setUsername(e.target.value); setError(""); }}
              onKeyDown={e => e.key === "Enter" && handleLogin()}
              placeholder="Enter your username"
              style={{ width: "100%", padding: "10px 12px", borderRadius: 8, border: `1px solid ${error ? "#fca5a5" : "#e2e8f0"}`, fontSize: 13, boxSizing: "border-box", background: error ? "#fff5f5" : "#fff", color: "#1e293b" }} />
          </div>

          <div>
            <label style={{ fontSize: 11, fontWeight: 600, color: "#374151", display: "block", marginBottom: 5 }}>Password</label>
            <div style={{ position: "relative" }}>
              <input value={password} type={showPw ? "text" : "password"}
                onChange={e => { setPassword(e.target.value); setError(""); }}
                onKeyDown={e => e.key === "Enter" && handleLogin()}
                placeholder="Enter your password"
                style={{ width: "100%", padding: "10px 36px 10px 12px", borderRadius: 8, border: `1px solid ${error ? "#fca5a5" : "#e2e8f0"}`, fontSize: 13, boxSizing: "border-box", background: error ? "#fff5f5" : "#fff", color: "#1e293b" }} />
              <button onClick={() => setShowPw(p => !p)} style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", fontSize: 14, color: "#94a3b8", padding: 0 }}>
                {showPw ? "🙈" : "👁️"}
              </button>
            </div>
          </div>

          {error && (
            <div style={{ fontSize: 11, color: "#ef4444", background: "#fff5f5", border: "1px solid #fca5a5", borderRadius: 6, padding: "7px 10px", textAlign: "center" }}>
              ⚠ {error}
            </div>
          )}

          <button onClick={handleLogin} disabled={!username.trim()}
            style={{ padding: "11px 0", borderRadius: 9, border: "none", background: !username.trim() ? "#93c5fd" : "#4f6ef7", color: "#fff", fontSize: 13, fontWeight: 700, cursor: !username.trim() ? "not-allowed" : "pointer", boxShadow: "0 2px 8px rgba(79,110,247,0.3)", marginTop: 4 }}>
            Sign In →
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Role chooser for multi-role users ─────────────────────────────────────────
function RoleCard({ role, onClick }: { role: "admin" | "developer"; onClick: () => void }) {
  const isAdmin = role === "admin";
  return (
    <div onClick={onClick}
      style={{ width: 240, padding: 28, background: "#fff", borderRadius: 16, border: "2px solid #e2e8f0", cursor: "pointer", textAlign: "center", boxShadow: "0 4px 20px rgba(0,0,0,0.07)", transition: "all 0.18s" }}
      onMouseEnter={e => { const el = e.currentTarget as HTMLDivElement; el.style.borderColor = isAdmin ? "#4f6ef7" : "#16a34a"; el.style.transform = "translateY(-2px)"; }}
      onMouseLeave={e => { const el = e.currentTarget as HTMLDivElement; el.style.borderColor = "#e2e8f0"; el.style.transform = ""; }}>
      <div style={{ fontSize: 36, marginBottom: 12 }}>{isAdmin ? "🔧" : "👨‍💻"}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: "#1e293b", marginBottom: 8 }}>{isAdmin ? "Admin" : "Developer"}</div>
      <div style={{ fontSize: 12, color: "#64748b", lineHeight: 1.5 }}>
        {isAdmin ? "Manage products, swimlanes, projects and team configuration" : "Run the AI pipeline with pre-configured or custom integrations"}
      </div>
      <div style={{ marginTop: 16, padding: "7px 0", background: isAdmin ? "#eff6ff" : "#f0fdf4", borderRadius: 8, fontSize: 11, fontWeight: 600, color: isAdmin ? "#4f6ef7" : "#16a34a" }}>
        {isAdmin ? "Configure →" : "Enter workspace →"}
      </div>
    </div>
  );
}

function RoleSelectScreen({ user, onSelect }: { user: UserProfile; onSelect: (r: "admin" | "developer") => void }) {
  const first = user.name.split(" ")[0];
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", background: "linear-gradient(135deg,#eff6ff 0%,#f8fafc 60%,#f0fdf4 100%)", fontFamily: "'Segoe UI',system-ui,sans-serif", padding: 24 }}>
      <div style={{ marginBottom: 32, textAlign: "center" }}>
        <div style={{ width: 56, height: 56, borderRadius: "50%", background: "#eff6ff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, fontWeight: 800, color: "#4f6ef7", margin: "0 auto 12px" }}>
          {user.name.charAt(0).toUpperCase()}
        </div>
        <div style={{ fontSize: 22, fontWeight: 800, color: "#1e293b" }}>Hello, {first}</div>
        <div style={{ fontSize: 13, color: "#64748b", marginTop: 6 }}>Choose how you want to continue today</div>
      </div>
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap", justifyContent: "center" }}>
        {user.roles.includes("admin")     && <RoleCard role="admin"     onClick={() => onSelect("admin")} />}
        {user.roles.includes("developer") && <RoleCard role="developer" onClick={() => onSelect("developer")} />}
      </div>
    </div>
  );
}

// ── Developer mode choice ─────────────────────────────────────────────────────
function DeveloperModeScreen({ hasProjects, onBrowse, onAdhoc, onBack }: {
  hasProjects: boolean; onBrowse: () => void; onAdhoc: () => void; onBack: () => void;
}) {
  const ModeCard = ({ icon, title, desc, badge, onClick, disabled }: {
    icon: string; title: string; desc: string; badge?: string; onClick: () => void; disabled?: boolean;
  }) => (
    <div onClick={disabled ? undefined : onClick}
      style={{ width: 240, padding: 28, background: disabled ? "#f8fafc" : "#fff", borderRadius: 16, border: `2px solid ${disabled ? "#f1f5f9" : "#e2e8f0"}`, cursor: disabled ? "not-allowed" : "pointer", textAlign: "center", boxShadow: disabled ? "none" : "0 4px 20px rgba(0,0,0,0.07)", transition: "all 0.18s", opacity: disabled ? 0.5 : 1 }}
      onMouseEnter={e => { if (!disabled) { const el = e.currentTarget as HTMLDivElement; el.style.borderColor = "#4f6ef7"; el.style.transform = "translateY(-2px)"; } }}
      onMouseLeave={e => { if (!disabled) { const el = e.currentTarget as HTMLDivElement; el.style.borderColor = "#e2e8f0"; el.style.transform = ""; } }}>
      <div style={{ fontSize: 36, marginBottom: 12 }}>{icon}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: "#1e293b", marginBottom: 8 }}>{title}</div>
      {badge && <div style={{ fontSize: 9, padding: "2px 8px", borderRadius: 8, background: "#f0fdf4", color: "#16a34a", fontWeight: 700, display: "inline-block", marginBottom: 8 }}>{badge}</div>}
      <div style={{ fontSize: 12, color: "#64748b", lineHeight: 1.5 }}>{desc}</div>
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", background: "linear-gradient(135deg,#eff6ff 0%,#f8fafc 60%,#f0fdf4 100%)", fontFamily: "'Segoe UI',system-ui,sans-serif", padding: 24 }}>
      <div style={{ marginBottom: 32, textAlign: "center" }}>
        <div style={{ fontSize: 40, marginBottom: 10 }}>👨‍💻</div>
        <div style={{ fontSize: 24, fontWeight: 800, color: "#1e293b" }}>Developer Workspace</div>
        <div style={{ fontSize: 13, color: "#64748b", marginTop: 6 }}>How would you like to work today?</div>
      </div>
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap", justifyContent: "center" }}>
        <ModeCard icon="📂" title="Browse Projects" badge={hasProjects ? "Pre-filled credentials" : undefined}
          desc={hasProjects ? "Select a configured product, swimlane, and project — credentials pre-filled automatically" : "No projects configured yet — ask your admin to set up products and projects first"}
          onClick={onBrowse} disabled={!hasProjects} />
        <ModeCard icon="⚡" title="Ad Hoc"
          desc="Enter your own configuration and credentials directly — full control"
          onClick={onAdhoc} />
      </div>
      <button onClick={onBack} style={{ marginTop: 24, background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "#94a3b8", fontWeight: 600 }}>← Go back</button>
    </div>
  );
}

// ── Project browser (Products → Swimlanes → Projects) ────────────────────────
function ProjectBrowserScreen({ products, users, onSelect, onBack }: {
  products: Product[]; users: UserProfile[]; onSelect: (p: Project) => void; onBack: () => void;
}) {
  const [selectedProductId,  setSelectedProductId]  = useState<string | null>(null);
  const [selectedSwimlaneId, setSelectedSwimlaneId] = useState<string | null>(null);

  const selectedProduct  = products.find(p => p.id === selectedProductId) ?? null;
  const selectedSwimlane = selectedProduct?.swimlanes.find(s => s.id === selectedSwimlaneId) ?? null;

  const getUserName = (id: string) => users.find(u => u.id === id)?.name ?? id;

  const Card = ({ icon, title, subtitle, onClick }: { icon: string; title: string; subtitle?: string; onClick: () => void }) => (
    <div onClick={onClick}
      style={{ padding: "14px 18px", background: "#fff", borderRadius: 12, border: "2px solid #e2e8f0", cursor: "pointer", boxShadow: "0 2px 10px rgba(0,0,0,0.05)", transition: "all 0.15s", display: "flex", alignItems: "center", gap: 14 }}
      onMouseEnter={e => { const el = e.currentTarget as HTMLDivElement; el.style.borderColor = "#4f6ef7"; el.style.transform = "translateY(-1px)"; }}
      onMouseLeave={e => { const el = e.currentTarget as HTMLDivElement; el.style.borderColor = "#e2e8f0"; el.style.transform = ""; }}>
      <span style={{ fontSize: 24 }}>{icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#1e293b" }}>{title}</div>
        {subtitle && <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{subtitle}</div>}
      </div>
      <span style={{ fontSize: 16, color: "#cbd5e1" }}>›</span>
    </div>
  );

  const crumbs = [
    { label: "Products", onClick: () => { setSelectedProductId(null); setSelectedSwimlaneId(null); } },
    ...(selectedProduct ? [{ label: selectedProduct.name, onClick: () => setSelectedSwimlaneId(null) }] : []),
    ...(selectedSwimlane ? [{ label: selectedSwimlane.name, onClick: () => {} }] : []),
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", background: "linear-gradient(135deg,#eff6ff 0%,#f8fafc 60%,#f0fdf4 100%)", fontFamily: "'Segoe UI',system-ui,sans-serif", padding: 24 }}>
      <div style={{ width: "min(520px,100%)" }}>
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <div style={{ fontSize: 30, marginBottom: 8 }}>📂</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: "#1e293b" }}>Select Project</div>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>Navigate to your project to pre-fill credentials</div>
        </div>

        {/* Breadcrumb */}
        <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 16, flexWrap: "wrap" }}>
          {crumbs.map((c, i) => (
            <span key={i} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              {i > 0 && <span style={{ color: "#cbd5e1", fontSize: 12 }}>›</span>}
              <button onClick={c.onClick} style={{ background: "none", border: "none", cursor: i < crumbs.length - 1 ? "pointer" : "default", fontSize: 12, fontWeight: 600, color: i < crumbs.length - 1 ? "#4f6ef7" : "#1e293b", padding: 0 }}>
                {c.label}
              </button>
            </span>
          ))}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {!selectedProductId && products.map(p => (
            <Card key={p.id} icon="📦" title={p.name}
              subtitle={[p.description, `${p.swimlanes.length} swimlane(s)`].filter(Boolean).join(" · ")}
              onClick={() => setSelectedProductId(p.id)} />
          ))}

          {selectedProductId && !selectedSwimlaneId && selectedProduct?.swimlanes.map(s => (
            <Card key={s.id} icon="🏊" title={s.name}
              subtitle={[s.description, `${s.projects.length} project(s)`].filter(Boolean).join(" · ")}
              onClick={() => setSelectedSwimlaneId(s.id)} />
          ))}

          {selectedSwimlaneId && selectedSwimlane?.projects.map(pr => (
            <div key={pr.id} onClick={() => onSelect(pr)}
              style={{ padding: "14px 18px", background: "#fff", borderRadius: 12, border: "2px solid #e2e8f0", cursor: "pointer", boxShadow: "0 2px 10px rgba(0,0,0,0.05)", transition: "all 0.15s" }}
              onMouseEnter={e => { const el = e.currentTarget as HTMLDivElement; el.style.borderColor = "#16a34a"; el.style.transform = "translateY(-1px)"; }}
              onMouseLeave={e => { const el = e.currentTarget as HTMLDivElement; el.style.borderColor = "#e2e8f0"; el.style.transform = ""; }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <span style={{ fontSize: 24 }}>🗂️</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#1e293b" }}>{pr.name}</div>
                  {pr.description && <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{pr.description}</div>}
                  <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                    {pr.owner && <span style={{ fontSize: 9, padding: "1px 7px", borderRadius: 8, background: "#eff6ff", color: "#4f6ef7", fontWeight: 700 }}>Owner: {pr.owner}</span>}
                    {pr.developers.length > 0 && <span style={{ fontSize: 9, padding: "1px 7px", borderRadius: 8, background: "#f0fdf4", color: "#16a34a", fontWeight: 700 }}>{pr.developers.map(getUserName).join(", ")}</span>}
                    {pr.jira.url && <span style={{ fontSize: 9, padding: "1px 7px", borderRadius: 8, background: "#fefce8", color: "#ca8a04", fontWeight: 700 }}>🎫 Jira</span>}
                    {pr.github.org && <span style={{ fontSize: 9, padding: "1px 7px", borderRadius: 8, background: "#f0fdf4", color: "#16a34a", fontWeight: 700 }}>🌿 GitHub</span>}
                  </div>
                </div>
                <span style={{ fontSize: 12, padding: "5px 12px", borderRadius: 7, background: "#4f6ef7", color: "#fff", fontWeight: 600 }}>Select →</span>
              </div>
            </div>
          ))}
        </div>

        <button onClick={onBack} style={{ marginTop: 20, background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "#94a3b8", fontWeight: 600, display: "block", textAlign: "center", width: "100%" }}>← Back</button>
      </div>
    </div>
  );
}

// ── Landing (no users configured — legacy) ────────────────────────────────────
function LandingScreen({ onSelect }: { onSelect: (r: "admin" | "developer") => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", background: "linear-gradient(135deg,#eff6ff 0%,#f8fafc 60%,#f0fdf4 100%)", fontFamily: "'Segoe UI',system-ui,sans-serif", padding: 24 }}>
      <div style={{ marginBottom: 32, textAlign: "center" }}>
        <div style={{ fontSize: 40, marginBottom: 10 }}>⚙️</div>
        <div style={{ fontSize: 26, fontWeight: 800, color: "#1e293b", letterSpacing: -0.5 }}>Prodapt AI Orchestrator</div>
        <div style={{ fontSize: 13, color: "#64748b", marginTop: 6 }}>Select how you want to continue</div>
      </div>
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap", justifyContent: "center" }}>
        <RoleCard role="admin"     onClick={() => onSelect("admin")} />
        <RoleCard role="developer" onClick={() => onSelect("developer")} />
      </div>
    </div>
  );
}

// ── App router ────────────────────────────────────────────────────────────────
export function App() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    fetchRemoteConfig().then(remote => {
      const local = loadAdminConfig();
      if (local) {
        if (remote?.users?.length && !local.users?.length) {
          saveAdminConfig({ ...local, users: remote.users });
        }
      } else if (remote) {
        saveAdminConfig(remote);
      }
      setReady(true);
    }).catch(() => { setReady(true); });
  }, []);

  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);
  const [currentRole, setCurrentRole] = useState<"admin" | "developer" | null>(null);
  const [devMode,     setDevMode]     = useState<"browse" | "adhoc" | null>(null);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);

  const [legacyRole, setLegacyRole] = useState<Role>(() => localStorage.getItem(ROLE_KEY) as Role || null);

  if (!ready) return null;

  const cfg   = loadAdminConfig();
  const users = cfg?.users ?? [];
  const useUserFlow = users.length > 0;

  if (useUserFlow) {
    const handleAuth = (u: UserProfile) => {
      setCurrentUser(u);
      if (u.roles.length === 1) setCurrentRole(u.roles[0]);
    };

    const handleLogout = () => {
      setCurrentUser(null); setCurrentRole(null);
      setDevMode(null); setSelectedProject(null);
    };

    const handleSwitchOrLogout = () => {
      if (currentUser && currentUser.roles.length > 1) {
        setCurrentRole(null); setDevMode(null); setSelectedProject(null);
      } else {
        handleLogout();
      }
    };

    if (!currentUser) return <LoginScreen users={users} onAuth={handleAuth} />;
    if (!currentRole) return <RoleSelectScreen user={currentUser} onSelect={r => setCurrentRole(r)} />;

    if (currentRole === "admin") {
      return (
        <AdminPanel mode="page" onBack={handleLogout}
          onSave={saveCfg => {
            saveAdminConfig(saveCfg);
            if (currentUser.roles.includes("developer")) {
              setCurrentRole("developer"); setDevMode(null); setSelectedProject(null);
            }
          }}
        />
      );
    }

    // Developer role
    const products = cfg?.products ?? [];
    const hasProjects = products.some(p => p.swimlanes.some(s => s.projects.length > 0));

    if (!devMode) {
      return (
        <DeveloperModeScreen
          hasProjects={hasProjects}
          onBrowse={() => setDevMode("browse")}
          onAdhoc={() => { setDevMode("adhoc"); setSelectedProject(null); }}
          onBack={handleSwitchOrLogout}
        />
      );
    }

    if (devMode === "browse" && !selectedProject) {
      return (
        <ProjectBrowserScreen
          products={products}
          users={users}
          onSelect={p => setSelectedProject(p)}
          onBack={() => setDevMode(null)}
        />
      );
    }

    return <DeveloperApp currentUser={currentUser} onSwitchRole={handleSwitchOrLogout} selectedProject={selectedProject} />;
  }

  // ── Legacy flow (no users configured) ────────────────────────────────────────
  const handleLegacySelect = (r: "admin" | "developer") => { localStorage.setItem(ROLE_KEY, r); setLegacyRole(r); };
  const handleLegacyBack   = () => { localStorage.removeItem(ROLE_KEY); setLegacyRole(null); };

  if (!legacyRole) return <LandingScreen onSelect={handleLegacySelect} />;

  if (legacyRole === "admin") {
    return (
      <AdminPanel mode="page" onBack={handleLegacyBack}
        onSave={saveCfg => { saveAdminConfig(saveCfg); handleLegacySelect("developer"); }}
      />
    );
  }

  return <DeveloperApp currentUser={null} onSwitchRole={handleLegacyBack} selectedProject={null} />;
}

function DeveloperApp({ currentUser, onSwitchRole, selectedProject }: {
  currentUser: UserProfile | null;
  onSwitchRole: () => void;
  selectedProject: Project | null;
}) {
  const [globalSubStates, setGlobalSubStates] = useState<Record<string, Record<string, SubState>>>({});
  const [modRunStates,    setModRunStates]     = useState<Record<string, { status: RunStatus; duration: number | null; completedAt: string | null }>>({});
  const [allOutputs,      setAllOutputs]       = useState<Record<string, string>>({});
  const [allLogs,         setAllLogs]          = useState<object[]>([]);
  const [selectedMod,     setSelectedMod]      = useState<Module | null>(null);
  const [showLog,         setShowLog]          = useState(false);
  const [showAdmin,       setShowAdmin]        = useState(false);
  const [adminConfigured, setAdminConfigured]  = useState(false);
  const [runAllActive,    setRunAllActive]      = useState(false);
  const [runAllPausedOn,  setRunAllPausedOn]    = useState<{ modId: string; subId: string } | null>(null);
  const [savedCreds,      setSavedCreds]        = useState<Record<string, Record<string, string>>>({});
  const credResolverRef = useRef<((v: Record<string, string>) => void) | null>(null);
  const w = useWindowSize();

  useEffect(() => {
    if (selectedProject) {
      setSavedCreds(projectToCredentials(selectedProject));
      setAdminConfigured(true);
    } else {
      const cfg = loadAdminConfig();
      if (cfg) {
        setSavedCreds(adminConfigToCredentials(cfg));
        setAdminConfigured(true);
      }
    }
  }, [selectedProject]);

  const handleSubStateChange = useCallback((modId: string, subId: string, state: Partial<SubState>) => {
    setGlobalSubStates(p => ({ ...p, [modId]: { ...(p[modId] || {}), [subId]: { ...(p[modId]?.[subId] || {}), ...state } as SubState } }));
    if (state.output) {
      setAllOutputs(p => ({ ...p, [modId]: (p[modId] || "") + `\n[${subId}]:\n${state.output}` }));
    }
  }, []);

  const handleModStateChange = useCallback((modId: string, state: { status: RunStatus; duration: number | null; completedAt: string | null }) => {
    setModRunStates(p => ({ ...p, [modId]: { ...(p[modId] || {}), ...state } }));
  }, []);

  const handleLog = useCallback((e: object) => setAllLogs(p => [e, ...p].slice(0, 200)), []);

  const handleSaveCreds = useCallback((subId: string, vals: Record<string, string>) => {
    setSavedCreds(p => ({ ...p, [subId]: vals }));
    if (credResolverRef.current) { credResolverRef.current(vals); credResolverRef.current = null; }
  }, []);

  const handleAdminSave = useCallback((cfg: AdminConfig) => {
    setSavedCreds(adminConfigToCredentials(cfg));
    setAdminConfigured(true);
    setShowAdmin(false);
  }, []);

  const runSubCore = useCallback(async (
    mod: Module, sub: Module["subModules"][number],
    inputOverride: string | null, currentAllOutputs: Record<string, string>
  ) => {
    const t0 = Date.now();
    handleSubStateChange(mod.id, sub.id, { status: "running", output: "", duration: null, completedAt: null });
    handleModStateChange(mod.id, { status: "running", duration: null, completedAt: null });

    const modCtx   = Object.entries(currentAllOutputs || {}).filter(([, v]) => v).map(([k, v]) => `[${k}]:\n${String(v).slice(0, 250)}`).join("\n\n");
    const credNote = savedCreds[sub.id] ? `\nCredentials: ${Object.keys(savedCreds[sub.id]).filter(k => k !== "filled").join(", ")}` : "";
    const userMsg  = inputOverride
      ? `Input:\n${inputOverride}${credNote}\n\nContext:\n${modCtx || "None."}`
      : `Execute: ${sub.label}${credNote}\n\nContext:\n${modCtx || "None."}`;

    try {
      const result = await callClaude(sub.systemPrompt, userMsg);
      const dur = Date.now() - t0;
      const finAt = new Date().toISOString();
      const entry = await callLogAPI(`${mod.id}/${sub.id}`, userMsg, result, "done", dur);
      handleLog(entry);
      handleSubStateChange(mod.id, sub.id, { status: "done", output: result, duration: dur, completedAt: finAt });
      handleModStateChange(mod.id, { status: "done", duration: dur, completedAt: finAt });
      return result;
    } catch (err: unknown) {
      const dur = Date.now() - t0;
      const msg = err instanceof Error ? err.message : String(err);
      const entry = await callLogAPI(`${mod.id}/${sub.id}`, userMsg, msg, "error", dur);
      handleLog(entry);
      handleSubStateChange(mod.id, sub.id, { status: "error", output: `Error: ${msg}`, duration: dur, completedAt: new Date().toISOString() });
      handleModStateChange(mod.id, { status: "error", duration: dur, completedAt: new Date().toISOString() });
      return null;
    }
  }, [handleSubStateChange, handleModStateChange, handleLog, savedCreds]);

  const handleRunAll = useCallback(async () => {
    if (runAllActive) return;
    setRunAllActive(true);
    let currentAllOutputs = { ...allOutputs };
    let currentSavedCreds = { ...savedCreds };

    for (const mod of MODULES) {
      setSelectedMod(mod);
      for (const sub of mod.subModules) {
        if (sub && 'id' in sub && (sub as { id: string }).id && !currentSavedCreds[(sub as { id: string }).id]?.filled) {
          const subId = (sub as { id: string }).id;
          if (CRED_FIELDS[subId]) {
            setRunAllPausedOn({ modId: mod.id, subId });
            const creds = await new Promise<Record<string, string>>(resolve => { credResolverRef.current = resolve; });
            currentSavedCreds = { ...currentSavedCreds, [subId]: creds };
            setRunAllPausedOn(null);
          }
        }
        const result = await runSubCore(mod, sub, null, currentAllOutputs);
        if (result) currentAllOutputs = { ...currentAllOutputs, [mod.id]: (currentAllOutputs[mod.id] || "") + `\n[${(sub as { id: string }).id}]:\n${result}` };
      }
    }
    setRunAllActive(false);
    setRunAllPausedOn(null);
  }, [runAllActive, allOutputs, savedCreds, runSubCore]);

  const BACKEND_MODULES = new Set(["requirements", "design"]);

  const handleDirectRun = useCallback((mod: Module) => {
    setSelectedMod(mod);
    if (BACKEND_MODULES.has(mod.id)) return;
    const firstSub = mod.subModules?.[0];
    if (firstSub && (!('id' in firstSub) || !savedCreds[(firstSub as { id: string }).id]?.filled)) {
      setTimeout(() => runSubCore(mod, firstSub, null, allOutputs), 50);
    }
  }, [allOutputs, runSubCore, savedCreds]);

  const canAccessAdmin = !currentUser || currentUser.roles.includes("admin");
  const isMultiRole    = currentUser && currentUser.roles.length > 1;
  const userInitials   = currentUser
    ? currentUser.name.split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2)
    : "AK";

  const totalDone    = Object.values(modRunStates).filter(s => s.status === "done").length;
  const totalRunning = Object.values(modRunStates).filter(s => s.status === "running").length;
  const isMobile     = w < 640;
  const isDesktop    = w >= 1024;
  const tileGridCols = selectedMod ? (isMobile ? "1fr" : "repeat(2,1fr)") : (isMobile ? "1fr" : w < 900 ? "repeat(2,1fr)" : "repeat(4,1fr)");
  const mainGridCols = selectedMod && isDesktop ? "1fr 1.15fr" : "1fr";
  const sideIcons    = ["🗂️", "🔍", "🔗", "⚡", "🛡️", "◈", "⬇️"];
  const pausedSubId  = runAllPausedOn && selectedMod && runAllPausedOn.modId === selectedMod.id ? runAllPausedOn.subId : null;

  return (
    <div style={{ display: "flex", height: "100vh", background: "#f1f5f9", fontFamily: "'Segoe UI',system-ui,sans-serif", overflow: "hidden" }}>
      <style>{`
        @keyframes spin{to{transform:rotate(360deg)}}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
        @keyframes pulseRing{0%{transform:scale(1);opacity:1}100%{transform:scale(1.8);opacity:0}}
        *{box-sizing:border-box}
        ::-webkit-scrollbar{width:4px;height:4px}
        ::-webkit-scrollbar-track{background:#f1f5f9}
        ::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:3px}
      `}</style>

      {/* Sidebar */}
      {!isMobile && (
        <div style={{ width: 48, background: "#fff", borderRight: "1px solid #e2e8f0", display: "flex", flexDirection: "column", alignItems: "center", padding: "10px 0", gap: 3, flexShrink: 0, boxShadow: "2px 0 8px rgba(0,0,0,0.04)" }}>
          {canAccessAdmin && (
            <div onClick={() => setShowAdmin(true)} title="Admin Settings"
              style={{ width: 30, height: 30, background: "#4f6ef7", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, marginBottom: 12, boxShadow: "0 2px 8px rgba(79,110,247,0.4)", cursor: "pointer", position: "relative" }}>
              ⚙
              {adminConfigured && <span style={{ position: "absolute", top: -3, right: -3, width: 8, height: 8, borderRadius: "50%", background: "#16a34a", border: "1.5px solid #fff" }} />}
            </div>
          )}
          {sideIcons.map((ic, i) => (
            <div key={i} style={{ width: 34, height: 34, borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15, cursor: "pointer", color: "#94a3b8", transition: "all 0.15s" }}
              onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = "#f1f5f9"; (e.currentTarget as HTMLDivElement).style.color = "#475569"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = "transparent"; (e.currentTarget as HTMLDivElement).style.color = "#94a3b8"; }}>{ic}</div>
          ))}
          <div style={{ flex: 1 }} />
          <div title={currentUser?.name || ""} style={{ width: 28, height: 28, borderRadius: "50%", background: "#4f6ef7", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#fff", fontWeight: 700 }}>{userInitials}</div>
        </div>
      )}

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

        {/* Top bar */}
        <div style={{ padding: isMobile ? "8px 12px" : "10px 18px", borderBottom: "1px solid #e2e8f0", display: "flex", justifyContent: "space-between", alignItems: "center", background: "#fff", flexShrink: 0, boxShadow: "0 1px 4px rgba(0,0,0,0.05)", gap: 8, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
            <div style={{ width: 34, height: 34, background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: 9, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, flexShrink: 0 }}>⚙️</div>
            <div style={{ minWidth: 0 }}>
              <div style={{ color: "#1e293b", fontWeight: 700, fontSize: isMobile ? 13 : 15, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>Prodapt AI Orchestrator</div>
              {!isMobile && <div style={{ color: "#94a3b8", fontSize: 10, marginTop: 1 }}>API-driven · Versioned · Session: {SESSION_ID}</div>}
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
            {runAllPausedOn && <span style={{ fontSize: 10, color: "#92400e", fontWeight: 600, background: "#fffbeb", borderRadius: 6, padding: "3px 8px", border: "1px solid #fcd34d" }}>⏸ Awaiting credentials</span>}
            {totalRunning > 0 && !runAllPausedOn && <span style={{ fontSize: 10, color: "#3b82f6", fontWeight: 600, display: "flex", alignItems: "center", gap: 3 }}><span style={{ display: "inline-block", animation: "spin 0.8s linear infinite" }}>↻</span>{totalRunning} running</span>}
            <button onClick={() => setShowLog(p => !p)} style={{ display: "flex", alignItems: "center", gap: 4, padding: isMobile ? "5px 8px" : "6px 12px", borderRadius: 7, border: "1px solid #e2e8f0", background: "#fff", color: "#475569", fontSize: 11, cursor: "pointer", fontWeight: 600 }}>
              🗂️{!isMobile && " Audit Log"}{allLogs.length > 0 && <span style={{ background: "#4f6ef7", color: "#fff", borderRadius: 10, padding: "0 5px", fontSize: 9, fontWeight: 700 }}>{allLogs.length}</span>}
            </button>
            {!isMobile && <button style={{ display: "flex", alignItems: "center", gap: 4, padding: "6px 12px", borderRadius: 7, border: "1px solid #e2e8f0", background: "#fff", color: "#475569", fontSize: 11, cursor: "pointer", fontWeight: 600 }}>⚡ Registry</button>}
            {canAccessAdmin && (
              <button onClick={() => setShowAdmin(true)}
                style={{ display: "flex", alignItems: "center", gap: 4, padding: isMobile ? "5px 8px" : "6px 12px", borderRadius: 7, border: `1px solid ${adminConfigured ? "#bbf7d0" : "#e2e8f0"}`, background: adminConfigured ? "#f0fdf4" : "#fff", color: adminConfigured ? "#16a34a" : "#475569", fontSize: 11, cursor: "pointer", fontWeight: 600 }}>
                🔧{!isMobile && (adminConfigured ? " Admin ✓" : " Admin")}
              </button>
            )}
            {!isMobile && (
              <button onClick={onSwitchRole}
                style={{ display: "flex", alignItems: "center", gap: 4, padding: "6px 10px", borderRadius: 7, border: "1px solid #e2e8f0", background: "#fff", color: "#94a3b8", fontSize: 11, cursor: "pointer", fontWeight: 600 }}
                title={isMultiRole ? "Switch role" : "Log out"}>
                {isMultiRole ? "⇄" : "↩"}
              </button>
            )}
            <button onClick={handleRunAll} disabled={runAllActive}
              style={{ display: "flex", alignItems: "center", gap: 4, padding: isMobile ? "5px 10px" : "6px 14px", borderRadius: 7, border: "none", background: runAllActive ? "#93c5fd" : "#4f6ef7", color: "#fff", fontSize: 11, cursor: runAllActive ? "not-allowed" : "pointer", fontWeight: 700, boxShadow: "0 2px 8px rgba(79,110,247,0.3)" }}>
              {runAllActive ? <span style={{ display: "inline-block", animation: "spin 0.8s linear infinite" }}>↻</span> : "▶"}
              {!isMobile && (runAllActive ? " Running All…" : " Run All")}
            </button>
          </div>
        </div>

        {/* Pipeline bar */}
        <div style={{ padding: isMobile ? "7px 12px" : "8px 18px", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "center", gap: 12, background: "#fff", flexShrink: 0, flexWrap: "wrap" }}>
          <span style={{ color: "#475569", fontSize: 11, fontWeight: 600, whiteSpace: "nowrap" }}>Pipeline — {totalDone}/{MODULES.length} complete</span>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {MODULES.map(m => {
              const ms = modRunStates[m.id] || { status: "idle" as RunStatus };
              const isPaused = runAllPausedOn?.modId === m.id;
              return (
                <div key={m.id} onClick={() => setSelectedMod(m)} title={m.label} style={{ position: "relative", cursor: "pointer", display: "flex", alignItems: "center" }}>
                  <span style={{ fontSize: 15, opacity: ms.status === "idle" && !isPaused ? 0.35 : 1, transition: "all 0.2s" }}>{m.icon}</span>
                  {isPaused && <span style={{ position: "absolute", top: -2, right: -2, width: 7, height: 7, borderRadius: "50%", background: "#f59e0b" }} />}
                  {!isPaused && ms.status !== "idle" && <span style={{ position: "absolute", top: -2, right: -2, width: 6, height: 6, borderRadius: "50%", background: SC.color[ms.status] }} />}
                  {ms.status === "running" && <span style={{ position: "absolute", top: -3, right: -3, width: 8, height: 8, borderRadius: "50%", border: "1.5px solid #3b82f6", animation: "pulseRing 1.2s ease-in-out infinite" }} />}
                </div>
              );
            })}
          </div>
          <div style={{ flex: 1, minWidth: 60, height: 4, background: "#e2e8f0", borderRadius: 2, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${(totalDone / MODULES.length) * 100}%`, background: "#4f6ef7", borderRadius: 2, transition: "width 0.4s" }} />
          </div>
          <span style={{ fontSize: 10, color: "#94a3b8", whiteSpace: "nowrap" }}>{totalDone}/{MODULES.length}</span>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflow: "auto", padding: isMobile ? "12px" : "16px 18px" }}>
          <div style={{ display: "grid", gridTemplateColumns: mainGridCols, gap: 14, alignItems: "start" }}>
            <div style={{ display: "grid", gridTemplateColumns: tileGridCols, gap: 10 }}>
              {MODULES.map(m => (
                <ModTile key={m.id} mod={m} modRunState={modRunStates[m.id] || { status: "idle" }} onSelect={setSelectedMod} isSelected={selectedMod?.id === m.id} onDirectRun={handleDirectRun} />
              ))}
            </div>
            {selectedMod && (
              <div style={{ gridColumn: isDesktop ? "2/3" : "1/-1" }}>
                <DetailPanel key={selectedMod.id} mod={selectedMod} allOutputs={allOutputs} onLog={handleLog} onClose={() => setSelectedMod(null)} globalSubStates={globalSubStates} onSubStateChange={handleSubStateChange} onModStateChange={handleModStateChange} savedCreds={savedCreds} onSaveCreds={handleSaveCreds} pausedSubId={pausedSubId} project={selectedProject} />
              </div>
            )}
          </div>
        </div>

        {/* Status bar */}
        <div style={{ padding: "4px 16px", borderTop: "1px solid #e2e8f0", background: "#4f6ef7", display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0, flexWrap: "wrap", gap: 4 }}>
          <div style={{ display: "flex", gap: 10, fontSize: 10, color: "rgba(255,255,255,0.85)", flexWrap: "wrap" }}>
            <span>🔵 {SESSION_ID}</span><span>API {API_VERSION}</span>
            <span>{totalDone}/{MODULES.length} done</span>
            {currentUser && <span style={{ color: "#bfdbfe" }}>👤 {currentUser.name}</span>}
            {selectedProject && <span style={{ color: "#86efac" }}>📂 {selectedProject.name}</span>}
            {adminConfigured && <span style={{ color: "#86efac" }}>🔧 Admin configured</span>}
            {runAllPausedOn && <span style={{ color: "#fcd34d" }}>⏸ paused for creds</span>}
            {totalRunning > 0 && !runAllPausedOn && <span style={{ color: "#93c5fd" }}>↻ {totalRunning} running</span>}
          </div>
          <div style={{ fontSize: 10, color: "rgba(255,255,255,0.7)" }}>{new Date().toLocaleString()}</div>
        </div>
      </div>

      {showLog && <LogDrawer logs={allLogs as Parameters<typeof LogDrawer>[0]["logs"]} onClose={() => setShowLog(false)} />}
      {showAdmin && <AdminPanel mode="modal" onClose={() => setShowAdmin(false)} onSave={handleAdminSave} />}
    </div>
  );
}
