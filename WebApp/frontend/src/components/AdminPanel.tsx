import { useState, useEffect, useRef } from "react";
import {
  AdminConfig, UserProfile, UserRole,
  Product, Swimlane, Project, JiraConfig, GitHubConfig, ConfluenceConfig,
  loadAdminConfig, saveAdminConfig, clearAdminConfig, fetchRemoteConfig,
} from "../adminConfig";

interface Props {
  mode?:    "modal" | "page";
  onClose?: () => void;
  onBack?:  () => void;
  onSave:   (cfg: AdminConfig) => void;
}

type Section = "products" | "users" | "system";

const uid = () => `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;

const EMPTY_JIRA:       JiraConfig       = { url: "", projectKey: "", email: "", token: "" };
const EMPTY_GITHUB:     GitHubConfig     = { org: "", repo: "", branch: "main", token: "" };
const EMPTY_CONFLUENCE: ConfluenceConfig = { url: "", spaceKey: "", email: "", token: "" };

const EMPTY: AdminConfig = {
  products: [],
  pods: { requirements: "http://35.209.107.68:8001", design: "http://35.209.107.68:8082", development: "http://35.209.107.68:8000" },
  ai:   { apiKey: "", model: "" },
  users: [],
};

interface ProjFormData {
  name: string; description: string; owner: string; developers: string[];
  jira: JiraConfig; github: GitHubConfig; confluence: ConfluenceConfig;
}
const EMPTY_PROJ_FORM: ProjFormData = {
  name: "", description: "", owner: "", developers: [],
  jira: { ...EMPTY_JIRA }, github: { ...EMPTY_GITHUB }, confluence: { ...EMPTY_CONFLUENCE },
};

function Field({ label, value, onChange, placeholder, type = "text", span = false }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string; span?: boolean;
}) {
  const [show, setShow] = useState(false);
  return (
    <div style={{ gridColumn: span ? "1/-1" : "auto" }}>
      <label style={{ fontSize: 10, fontWeight: 600, color: "#374151", display: "block", marginBottom: 3 }}>{label}</label>
      <div style={{ position: "relative" }}>
        <input
          type={type === "password" && show ? "text" : type}
          value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
          style={{ width: "100%", padding: type === "password" ? "6px 28px 6px 9px" : "6px 9px", borderRadius: 6, border: "1px solid #e2e8f0", fontSize: 11, boxSizing: "border-box", background: "#fff", color: "#1e293b" }}
        />
        {type === "password" && (
          <button onClick={() => setShow(p => !p)} style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "#94a3b8", padding: 0 }}>
            {show ? "🙈" : "👁️"}
          </button>
        )}
      </div>
    </div>
  );
}

function ItemCard({ icon, title, subtitle, badge, onDrill, onEdit, onDelete }: {
  icon: string; title: string; subtitle?: string; badge?: string;
  onDrill?: () => void; onEdit: () => void; onDelete: () => void;
}) {
  return (
    <div style={{ padding: "10px 14px", background: "#f8fafc", borderRadius: 8, border: "1px solid #e2e8f0", display: "flex", alignItems: "center", gap: 10 }}>
      <span style={{ fontSize: 20 }}>{icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#1e293b" }}>{title}</div>
        {subtitle && <div style={{ fontSize: 10, color: "#64748b", marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{subtitle}</div>}
        {badge && <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 8, background: "#eff6ff", color: "#4f6ef7", fontWeight: 700 }}>{badge}</span>}
      </div>
      {onDrill && (
        <button onClick={onDrill} style={{ background: "#4f6ef7", border: "none", borderRadius: 5, padding: "4px 10px", fontSize: 10, color: "#fff", cursor: "pointer", fontWeight: 600, flexShrink: 0 }}>
          Open →
        </button>
      )}
      <button onClick={onEdit} style={{ background: "none", border: "1px solid #e2e8f0", borderRadius: 5, padding: "3px 8px", fontSize: 10, cursor: "pointer", color: "#64748b", flexShrink: 0 }}>Edit</button>
      <button onClick={onDelete} style={{ background: "none", border: "1px solid #fca5a5", borderRadius: 5, padding: "3px 8px", fontSize: 10, cursor: "pointer", color: "#ef4444", flexShrink: 0 }}>✕</button>
    </div>
  );
}

function SimpleForm({ title, values, onChange, onSave, onCancel }: {
  title: string;
  values: { name: string; description: string; owner: string };
  onChange: (f: "name" | "description" | "owner", v: string) => void;
  onSave: () => void; onCancel: () => void;
}) {
  return (
    <div style={{ padding: "14px 16px", background: "#f0f9ff", borderRadius: 8, border: "1px solid #bae6fd", marginBottom: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: "#1e293b", marginBottom: 10 }}>{title}</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 12px" }}>
        <Field label="Name *"       value={values.name}        onChange={v => onChange("name", v)}        placeholder="e.g. My Product" span />
        <Field label="Description"  value={values.description} onChange={v => onChange("description", v)} placeholder="Short description" />
        <Field label="Owner"        value={values.owner}       onChange={v => onChange("owner", v)}       placeholder="Owner name or team" />
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 10, justifyContent: "flex-end" }}>
        <button onClick={onCancel} style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid #e2e8f0", background: "#fff", color: "#64748b", fontSize: 11, cursor: "pointer" }}>Cancel</button>
        <button onClick={onSave} disabled={!values.name.trim()} style={{ padding: "5px 14px", borderRadius: 6, border: "none", background: !values.name.trim() ? "#93c5fd" : "#4f6ef7", color: "#fff", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
          Save
        </button>
      </div>
    </div>
  );
}

export function AdminPanel({ mode = "modal", onClose, onBack, onSave }: Props) {
  const [cfg, setCfg] = useState<AdminConfig>(() => {
    const saved = loadAdminConfig();
    return saved ? { ...EMPTY, ...saved, products: saved.products ?? [], users: saved.users ?? [] } : { ...EMPTY };
  });

  // Auto-persist every cfg change so inner-form saves don't require a separate global save
  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) { isFirstRender.current = false; return; }
    saveAdminConfig(cfg);
  }, [cfg]);

  // Navigation
  const [section, setSection]               = useState<Section>("products");
  const [selectedProductId,  setSelectedProductId]  = useState<string | null>(null);
  const [selectedSwimlaneId, setSelectedSwimlaneId] = useState<string | null>(null);
  const [selectedProjectId,  setSelectedProjectId]  = useState<string | null>(null);

  // Product form
  const [productForm,   setProductForm]   = useState<{ name: string; description: string; owner: string; editId: string | null } | null>(null);
  // Swimlane form
  const [swimlaneForm,  setSwimlaneForm]  = useState<{ name: string; description: string; owner: string; editId: string | null } | null>(null);
  // Project form / project tab
  const [projectForm,   setProjectForm]   = useState<{ data: ProjFormData; editId: string | null } | null>(null);
  const [projTab,       setProjTab]       = useState<"general" | "jira" | "github" | "confluence">("general");

  // User management
  const emptyUserForm = { name: "", username: "", password: "", roles: ["developer"] as UserRole[] };
  const [userForm,      setUserForm]      = useState(emptyUserForm);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [showUserForm,  setShowUserForm]  = useState(false);

  // UI state
  const [confirmClear, setConfirmClear] = useState(false);
  const [syncMsg,      setSyncMsg]      = useState("");

  // Derived
  const selectedProduct  = cfg.products.find(p => p.id === selectedProductId) ?? null;
  const selectedSwimlane = selectedProduct?.swimlanes.find(s => s.id === selectedSwimlaneId) ?? null;
  const selectedProject  = selectedSwimlane?.projects.find(p => p.id === selectedProjectId) ?? null;

  // ── CRUD helpers ──────────────────────────────────────────────────────────────

  const mutateProducts = (fn: (ps: Product[]) => Product[]) =>
    setCfg(c => ({ ...c, products: fn(c.products || []) }));

  const saveProduct = (name: string, description: string, owner: string, editId: string | null) => {
    if (!name.trim()) return;
    if (editId) {
      mutateProducts(ps => ps.map(p => p.id === editId ? { ...p, name, description, owner } : p));
    } else {
      mutateProducts(ps => [...ps, { id: uid(), name, description, owner, swimlanes: [] }]);
    }
    setProductForm(null);
  };

  const removeProduct = (id: string) => {
    mutateProducts(ps => ps.filter(p => p.id !== id));
    if (selectedProductId === id) { setSelectedProductId(null); setSelectedSwimlaneId(null); setSelectedProjectId(null); }
  };

  const saveSwimlane = (name: string, description: string, owner: string, editId: string | null) => {
    if (!name.trim() || !selectedProductId) return;
    if (editId) {
      mutateProducts(ps => ps.map(p => p.id === selectedProductId
        ? { ...p, swimlanes: p.swimlanes.map(s => s.id === editId ? { ...s, name, description, owner } : s) }
        : p));
    } else {
      mutateProducts(ps => ps.map(p => p.id === selectedProductId
        ? { ...p, swimlanes: [...p.swimlanes, { id: uid(), name, description, owner, projects: [] }] }
        : p));
    }
    setSwimlaneForm(null);
  };

  const removeSwimlane = (id: string) => {
    if (!selectedProductId) return;
    mutateProducts(ps => ps.map(p => p.id === selectedProductId
      ? { ...p, swimlanes: p.swimlanes.filter(s => s.id !== id) } : p));
    if (selectedSwimlaneId === id) { setSelectedSwimlaneId(null); setSelectedProjectId(null); }
  };

  const saveProject = (data: ProjFormData, editId: string | null) => {
    if (!data.name.trim() || !selectedProductId || !selectedSwimlaneId) return;
    if (editId) {
      mutateProducts(ps => ps.map(p => p.id === selectedProductId
        ? { ...p, swimlanes: p.swimlanes.map(s => s.id === selectedSwimlaneId
            ? { ...s, projects: s.projects.map(pr => pr.id === editId ? { ...pr, ...data } : pr) } : s) } : p));
    } else {
      mutateProducts(ps => ps.map(p => p.id === selectedProductId
        ? { ...p, swimlanes: p.swimlanes.map(s => s.id === selectedSwimlaneId
            ? { ...s, projects: [...s.projects, { id: uid(), ...data }] } : s) } : p));
    }
    setProjectForm(null);
    setSelectedProjectId(null);
  };

  const removeProject = (id: string) => {
    if (!selectedProductId || !selectedSwimlaneId) return;
    mutateProducts(ps => ps.map(p => p.id === selectedProductId
      ? { ...p, swimlanes: p.swimlanes.map(s => s.id === selectedSwimlaneId
          ? { ...s, projects: s.projects.filter(pr => pr.id !== id) } : s) } : p));
    if (selectedProjectId === id) setSelectedProjectId(null);
  };

  // ── User CRUD ─────────────────────────────────────────────────────────────────

  const setUsers = (users: UserProfile[]) => setCfg(c => ({ ...c, users }));

  const addUser = () => {
    if (!userForm.name.trim() || !userForm.username.trim() || userForm.roles.length === 0) return;
    setUsers([...(cfg.users || []), { id: uid(), name: userForm.name.trim(), username: userForm.username.trim(), password: userForm.password, roles: userForm.roles }]);
    setUserForm(emptyUserForm); setShowUserForm(false);
  };

  const updateUser = () => {
    if (!editingUserId || !userForm.name.trim()) return;
    setUsers((cfg.users || []).map(u => u.id === editingUserId
      ? { ...u, name: userForm.name.trim(), username: userForm.username.trim(), password: userForm.password, roles: userForm.roles }
      : u));
    setEditingUserId(null); setUserForm(emptyUserForm); setShowUserForm(false);
  };

  const deleteUser = (id: string) => setUsers((cfg.users || []).filter(u => u.id !== id));

  // ── Global actions ────────────────────────────────────────────────────────────

  const [saveMsg, setSaveMsg] = useState("");
  const handleSave = () => {
    saveAdminConfig(cfg);
    setSaveMsg("✓ Saved!");
    setTimeout(() => setSaveMsg(""), 2500);
    onSave(cfg);
  };

  const handleSync = () => {
    fetchRemoteConfig().then(remote => {
      if (!remote) { setSyncMsg("⚠ admin-config.json not found"); setTimeout(() => setSyncMsg(""), 3000); return; }
      setCfg(c => ({
        ...remote,
        pods:     { ...remote.pods,  ...c.pods  },
        ai:       { ...remote.ai,    ...c.ai    },
        products: c.products.length ? c.products : (remote.products ?? []),
        users:    remote.users ?? c.users,
      }));
      setSyncMsg("✓ Synced from file"); setTimeout(() => setSyncMsg(""), 3000);
    });
  };

  const handleClear = () => {
    if (!confirmClear) { setConfirmClear(true); return; }
    clearAdminConfig(); setCfg({ ...EMPTY }); setConfirmClear(false);
    setSelectedProductId(null); setSelectedSwimlaneId(null); setSelectedProjectId(null);
  };

  // ── Render: breadcrumb ────────────────────────────────────────────────────────

  const renderBreadcrumb = () => {
    const crumbs: { label: string; onClick: () => void }[] = [
      { label: "Products", onClick: () => { setSelectedProductId(null); setSelectedSwimlaneId(null); setSelectedProjectId(null); setProductForm(null); setSwimlaneForm(null); setProjectForm(null); } },
    ];
    if (selectedProduct) crumbs.push({ label: selectedProduct.name, onClick: () => { setSelectedSwimlaneId(null); setSelectedProjectId(null); setSwimlaneForm(null); setProjectForm(null); } });
    if (selectedSwimlane) crumbs.push({ label: selectedSwimlane.name, onClick: () => { setSelectedProjectId(null); setProjectForm(null); } });
    if (selectedProject) crumbs.push({ label: selectedProject.name, onClick: () => {} });

    return (
      <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 14, flexWrap: "wrap" }}>
        {crumbs.map((c, i) => (
          <span key={i} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {i > 0 && <span style={{ color: "#cbd5e1", fontSize: 12 }}>›</span>}
            <button onClick={c.onClick} style={{ background: "none", border: "none", cursor: i < crumbs.length - 1 ? "pointer" : "default", fontSize: 12, fontWeight: 600, color: i < crumbs.length - 1 ? "#4f6ef7" : "#1e293b", padding: 0 }}>
              {c.label}
            </button>
          </span>
        ))}
      </div>
    );
  };

  // ── Render: Products list ─────────────────────────────────────────────────────

  const renderProductList = () => (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#1e293b" }}>Products ({cfg.products.length})</div>
        <button onClick={() => setProductForm({ name: "", description: "", owner: "", editId: null })}
          style={{ padding: "5px 12px", borderRadius: 6, border: "1px dashed #bfdbfe", background: "#eff6ff", color: "#4f6ef7", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
          + Add Product
        </button>
      </div>

      {productForm && (
        <SimpleForm title={productForm.editId ? "Edit Product" : "New Product"}
          values={{ name: productForm.name, description: productForm.description, owner: productForm.owner }}
          onChange={(f, v) => setProductForm(p => p ? { ...p, [f]: v } : null)}
          onSave={() => saveProduct(productForm.name, productForm.description, productForm.owner, productForm.editId)}
          onCancel={() => setProductForm(null)} />
      )}

      {cfg.products.length === 0 && !productForm && (
        <div style={{ padding: 20, textAlign: "center", background: "#f8fafc", borderRadius: 8, border: "1px dashed #e2e8f0", fontSize: 11, color: "#94a3b8" }}>
          No products yet — add your first product to get started
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {cfg.products.map(p => (
          <ItemCard key={p.id} icon="📦" title={p.name}
            subtitle={[p.description, p.owner ? `Owner: ${p.owner}` : ""].filter(Boolean).join(" · ")}
            badge={`${p.swimlanes.length} swimlane${p.swimlanes.length !== 1 ? "s" : ""}`}
            onDrill={() => { setSelectedProductId(p.id); setSwimlaneForm(null); }}
            onEdit={() => setProductForm({ name: p.name, description: p.description, owner: p.owner, editId: p.id })}
            onDelete={() => removeProduct(p.id)} />
        ))}
      </div>
    </div>
  );

  // ── Render: Swimlanes list ────────────────────────────────────────────────────

  const renderSwimlaneList = () => {
    if (!selectedProduct) return null;
    return (
      <div>
        <div style={{ padding: "10px 14px", background: "#eff6ff", borderRadius: 8, border: "1px solid #bfdbfe", marginBottom: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#1e293b" }}>📦 {selectedProduct.name}</div>
          {selectedProduct.description && <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{selectedProduct.description}</div>}
          {selectedProduct.owner && <div style={{ fontSize: 10, color: "#4f6ef7", marginTop: 4, fontWeight: 600 }}>Owner: {selectedProduct.owner}</div>}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#1e293b" }}>Swimlanes ({selectedProduct.swimlanes.length})</div>
          <button onClick={() => setSwimlaneForm({ name: "", description: "", owner: "", editId: null })}
            style={{ padding: "5px 12px", borderRadius: 6, border: "1px dashed #bfdbfe", background: "#eff6ff", color: "#4f6ef7", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
            + Add Swimlane
          </button>
        </div>

        {swimlaneForm && (
          <SimpleForm title={swimlaneForm.editId ? "Edit Swimlane" : "New Swimlane"}
            values={{ name: swimlaneForm.name, description: swimlaneForm.description, owner: swimlaneForm.owner }}
            onChange={(f, v) => setSwimlaneForm(p => p ? { ...p, [f]: v } : null)}
            onSave={() => saveSwimlane(swimlaneForm.name, swimlaneForm.description, swimlaneForm.owner, swimlaneForm.editId)}
            onCancel={() => setSwimlaneForm(null)} />
        )}

        {selectedProduct.swimlanes.length === 0 && !swimlaneForm && (
          <div style={{ padding: 20, textAlign: "center", background: "#f8fafc", borderRadius: 8, border: "1px dashed #e2e8f0", fontSize: 11, color: "#94a3b8" }}>
            No swimlanes — add one to group projects
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {selectedProduct.swimlanes.map(s => (
            <ItemCard key={s.id} icon="🏊" title={s.name}
              subtitle={[s.description, s.owner ? `Owner: ${s.owner}` : ""].filter(Boolean).join(" · ")}
              badge={`${s.projects.length} project${s.projects.length !== 1 ? "s" : ""}`}
              onDrill={() => { setSelectedSwimlaneId(s.id); setProjectForm(null); }}
              onEdit={() => setSwimlaneForm({ name: s.name, description: s.description, owner: s.owner, editId: s.id })}
              onDelete={() => removeSwimlane(s.id)} />
          ))}
        </div>
      </div>
    );
  };

  // ── Render: Projects list ─────────────────────────────────────────────────────

  const renderProjectList = () => {
    if (!selectedSwimlane) return null;
    const isFormOpen = projectForm !== null && projectForm.editId === null && !selectedProjectId;
    return (
      <div>
        <div style={{ padding: "10px 14px", background: "#f0fdf4", borderRadius: 8, border: "1px solid #bbf7d0", marginBottom: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#1e293b" }}>🏊 {selectedSwimlane.name}</div>
          {selectedSwimlane.description && <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{selectedSwimlane.description}</div>}
          {selectedSwimlane.owner && <div style={{ fontSize: 10, color: "#16a34a", marginTop: 4, fontWeight: 600 }}>Owner: {selectedSwimlane.owner}</div>}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#1e293b" }}>Projects ({selectedSwimlane.projects.length})</div>
          <button onClick={() => { setProjTab("general"); setProjectForm({ data: { ...EMPTY_PROJ_FORM }, editId: null }); setSelectedProjectId(null); }}
            style={{ padding: "5px 12px", borderRadius: 6, border: "1px dashed #bfdbfe", background: "#eff6ff", color: "#4f6ef7", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
            + Add Project
          </button>
        </div>

        {isFormOpen && renderProjectFormPanel()}

        {selectedSwimlane.projects.length === 0 && !isFormOpen && (
          <div style={{ padding: 20, textAlign: "center", background: "#f8fafc", borderRadius: 8, border: "1px dashed #e2e8f0", fontSize: 11, color: "#94a3b8" }}>
            No projects — add one to configure integrations
          </div>
        )}

        {!isFormOpen && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {selectedSwimlane.projects.map(pr => (
              <ItemCard key={pr.id} icon="🗂️" title={pr.name}
                subtitle={[pr.description, pr.owner ? `Owner: ${pr.owner}` : "", pr.developers.length ? `${pr.developers.length} dev(s)` : ""].filter(Boolean).join(" · ")}
                onDrill={() => { setSelectedProjectId(pr.id); setProjTab("general"); setProjectForm({ data: { name: pr.name, description: pr.description, owner: pr.owner, developers: pr.developers, jira: pr.jira, github: pr.github, confluence: pr.confluence }, editId: pr.id }); }}
                onEdit={() => { setSelectedProjectId(pr.id); setProjTab("general"); setProjectForm({ data: { name: pr.name, description: pr.description, owner: pr.owner, developers: pr.developers, jira: pr.jira, github: pr.github, confluence: pr.confluence }, editId: pr.id }); }}
                onDelete={() => removeProject(pr.id)} />
            ))}
          </div>
        )}
      </div>
    );
  };

  // ── Render: Project form panel ────────────────────────────────────────────────

  const renderProjectFormPanel = () => {
    if (!projectForm) return null;
    const { data } = projectForm;
    const isEdit = !!projectForm.editId;

    const setField = (field: keyof ProjFormData, value: unknown) =>
      setProjectForm(f => f ? { ...f, data: { ...f.data, [field]: value } } : null);
    const setJira    = (p: Partial<JiraConfig>)        => setProjectForm(f => f ? { ...f, data: { ...f.data, jira:       { ...f.data.jira,       ...p } } } : null);
    const setGithub  = (p: Partial<GitHubConfig>)      => setProjectForm(f => f ? { ...f, data: { ...f.data, github:     { ...f.data.github,     ...p } } } : null);
    const setConf    = (p: Partial<ConfluenceConfig>)  => setProjectForm(f => f ? { ...f, data: { ...f.data, confluence: { ...f.data.confluence, ...p } } } : null);

    const allUsers = cfg.users || [];
    const projTabs = [
      { id: "general",    label: "General",    icon: "📋" },
      { id: "jira",       label: "Jira",       icon: "🎫" },
      { id: "github",     label: "GitHub",     icon: "🌿" },
      { id: "confluence", label: "Confluence", icon: "📄" },
    ] as const;

    return (
      <div style={{ background: "#f8fafc", borderRadius: 10, border: "1px solid #e2e8f0", overflow: "hidden", marginBottom: 12 }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #e2e8f0", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#1e293b" }}>{isEdit ? `Edit: ${data.name || "Project"}` : "New Project"}</div>
        </div>

        {/* Mini tabs */}
        <div style={{ display: "flex", borderBottom: "1px solid #e2e8f0", background: "#f1f5f9" }}>
          {projTabs.map(t => (
            <button key={t.id} onClick={() => setProjTab(t.id as typeof projTab)}
              style={{ flex: 1, padding: "8px 4px", border: "none", background: projTab === t.id ? "#fff" : "transparent", borderBottom: projTab === t.id ? "2px solid #4f6ef7" : "2px solid transparent", cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
              <span style={{ fontSize: 13 }}>{t.icon}</span>
              <span style={{ fontSize: 9, fontWeight: 600, color: projTab === t.id ? "#4f6ef7" : "#64748b" }}>{t.label}</span>
            </button>
          ))}
        </div>

        <div style={{ padding: "14px 16px" }}>
          {projTab === "general" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 12px" }}>
              <Field label="Project Name *" value={data.name} onChange={v => setField("name", v)} placeholder="e.g. Auth Service" span />
              <Field label="Description"   value={data.description} onChange={v => setField("description", v)} placeholder="What this project does" span />
              <Field label="Owner"         value={data.owner} onChange={v => setField("owner", v)} placeholder="Owner name or team" />
              <div>
                <label style={{ fontSize: 10, fontWeight: 600, color: "#374151", display: "block", marginBottom: 3 }}>Developers Assigned</label>
                {allUsers.filter(u => u.roles.includes("developer")).length === 0 ? (
                  <div style={{ fontSize: 10, color: "#94a3b8", padding: "6px 9px", border: "1px solid #e2e8f0", borderRadius: 6 }}>No developers configured yet</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {allUsers.filter(u => u.roles.includes("developer")).map(u => (
                      <label key={u.id} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, cursor: "pointer" }}>
                        <input type="checkbox" checked={data.developers.includes(u.id)}
                          onChange={e => setField("developers", e.target.checked ? [...data.developers, u.id] : data.developers.filter(id => id !== u.id))}
                          style={{ margin: 0 }} />
                        {u.name}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {projTab === "jira" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 12px" }}>
              <Field label="Jira URL"       value={data.jira.url}        onChange={v => setJira({ url: v })}        placeholder="https://org.atlassian.net" span />
              <Field label="Project Key"    value={data.jira.projectKey} onChange={v => setJira({ projectKey: v })} placeholder="e.g. PROJ" />
              <Field label="Email"          value={data.jira.email}      onChange={v => setJira({ email: v })}      placeholder="you@company.com" type="email" />
              <Field label="API Token"      value={data.jira.token}      onChange={v => setJira({ token: v })}      placeholder="••••••••" type="password" />
            </div>
          )}

          {projTab === "github" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 12px" }}>
              <Field label="Org / Username" value={data.github.org}    onChange={v => setGithub({ org: v })}    placeholder="e.g. my-org" />
              <Field label="Repository"     value={data.github.repo}   onChange={v => setGithub({ repo: v })}   placeholder="e.g. my-repo" />
              <Field label="Branch"         value={data.github.branch} onChange={v => setGithub({ branch: v })} placeholder="main" />
              <Field label="PAT Token"      value={data.github.token}  onChange={v => setGithub({ token: v })}  placeholder="ghp_••••••••" type="password" />
            </div>
          )}

          {projTab === "confluence" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 12px" }}>
              <Field label="Confluence URL" value={data.confluence.url}      onChange={v => setConf({ url: v })}      placeholder="https://org.atlassian.net/wiki" span />
              <Field label="Space Key"      value={data.confluence.spaceKey} onChange={v => setConf({ spaceKey: v })} placeholder="e.g. ENG" />
              <Field label="Email"          value={data.confluence.email}    onChange={v => setConf({ email: v })}    placeholder="you@company.com" type="email" />
              <Field label="API Token"      value={data.confluence.token}    onChange={v => setConf({ token: v })}    placeholder="••••••••" type="password" />
            </div>
          )}
        </div>

        <div style={{ padding: "10px 16px", borderTop: "1px solid #e2e8f0", display: "flex", justifyContent: "flex-end", gap: 6 }}>
          <button onClick={() => { setProjectForm(null); setSelectedProjectId(null); }}
            style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid #e2e8f0", background: "#fff", color: "#64748b", fontSize: 11, cursor: "pointer" }}>
            Cancel
          </button>
          <button onClick={() => saveProject(data, projectForm.editId)} disabled={!data.name.trim()}
            style={{ padding: "5px 14px", borderRadius: 6, border: "none", background: !data.name.trim() ? "#93c5fd" : "#4f6ef7", color: "#fff", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
            {isEdit ? "Save Changes" : "Create Project"}
          </button>
        </div>
      </div>
    );
  };

  // ── Render: Users section ─────────────────────────────────────────────────────

  const renderUsersSection = () => (
    <div>
      <div style={{ fontSize: 13, fontWeight: 700, color: "#1e293b", marginBottom: 4 }}>Users</div>
      <p style={{ fontSize: 11, color: "#64748b", margin: "0 0 14px" }}>
        Manage who can log in and what they can access. Credentials are username + password.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
        {(cfg.users || []).length === 0 && (
          <div style={{ padding: 12, background: "#f8fafc", borderRadius: 7, fontSize: 11, color: "#94a3b8", textAlign: "center", border: "1px dashed #e2e8f0" }}>
            No users configured — everyone can access both views (legacy mode)
          </div>
        )}
        {(cfg.users || []).map(user => (
          <div key={user.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", background: "#f8fafc", borderRadius: 7, border: "1px solid #e2e8f0" }}>
            <div style={{ width: 32, height: 32, borderRadius: "50%", background: "#eff6ff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800, color: "#4f6ef7", flexShrink: 0 }}>
              {user.name.charAt(0).toUpperCase()}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#1e293b" }}>{user.name}</div>
              <div style={{ fontSize: 10, color: "#64748b" }}>@{user.username}{user.password ? "" : " · ⚠ no password"}</div>
              <div style={{ display: "flex", gap: 4, marginTop: 3, flexWrap: "wrap" }}>
                {user.roles.map(r => (
                  <span key={r} style={{ fontSize: 9, padding: "1px 7px", borderRadius: 10, fontWeight: 700, background: r === "admin" ? "#eff6ff" : "#f0fdf4", color: r === "admin" ? "#4f6ef7" : "#16a34a" }}>
                    {r === "admin" ? "🔧 Admin" : "👨‍💻 Developer"}
                  </span>
                ))}
              </div>
            </div>
            <button onClick={() => { setEditingUserId(user.id); setUserForm({ name: user.name, username: user.username, password: user.password, roles: user.roles }); setShowUserForm(true); }}
              style={{ background: "none", border: "1px solid #e2e8f0", borderRadius: 5, padding: "3px 8px", fontSize: 10, cursor: "pointer", color: "#64748b", flexShrink: 0 }}>Edit</button>
            <button onClick={() => deleteUser(user.id)}
              style={{ background: "none", border: "1px solid #fca5a5", borderRadius: 5, padding: "3px 8px", fontSize: 10, cursor: "pointer", color: "#ef4444", flexShrink: 0 }}>✕</button>
          </div>
        ))}
      </div>

      {!showUserForm ? (
        <button onClick={() => { setShowUserForm(true); setEditingUserId(null); setUserForm(emptyUserForm); }}
          style={{ padding: "7px 14px", borderRadius: 7, border: "1px dashed #bfdbfe", background: "#eff6ff", color: "#4f6ef7", fontSize: 11, fontWeight: 600, cursor: "pointer", width: "100%" }}>
          + Add User
        </button>
      ) : (
        <div style={{ padding: "12px 14px", background: "#f8fafc", borderRadius: 8, border: "1px solid #e2e8f0" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#374151", marginBottom: 10 }}>{editingUserId ? "Edit User" : "New User"}</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 12px" }}>
            <Field label="Display Name *" value={userForm.name} onChange={v => setUserForm(p => ({ ...p, name: v }))} placeholder="e.g. Alice Smith" />
            <Field label="Username *"     value={userForm.username} onChange={v => setUserForm(p => ({ ...p, username: v }))} placeholder="e.g. alice" />
            <Field label="Password"       value={userForm.password} onChange={v => setUserForm(p => ({ ...p, password: v }))} placeholder="Leave blank for no password" type="password" span />
            <div style={{ gridColumn: "1/-1" }}>
              <label style={{ fontSize: 10, fontWeight: 600, color: "#374151", display: "block", marginBottom: 5 }}>Roles *</label>
              <div style={{ display: "flex", gap: 8 }}>
                {(["admin", "developer"] as UserRole[]).map(r => (
                  <label key={r} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, cursor: "pointer", padding: "5px 10px", borderRadius: 6, border: `1px solid ${userForm.roles.includes(r) ? (r === "admin" ? "#bfdbfe" : "#bbf7d0") : "#e2e8f0"}`, background: userForm.roles.includes(r) ? (r === "admin" ? "#eff6ff" : "#f0fdf4") : "#fff" }}>
                    <input type="checkbox" checked={userForm.roles.includes(r)}
                      onChange={e => setUserForm(p => ({ ...p, roles: e.target.checked ? [...p.roles, r] : p.roles.filter(x => x !== r) }))}
                      style={{ margin: 0, cursor: "pointer" }} />
                    {r === "admin" ? "🔧 Admin" : "👨‍💻 Developer"}
                  </label>
                ))}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 10, justifyContent: "flex-end" }}>
            <button onClick={() => { setShowUserForm(false); setEditingUserId(null); setUserForm(emptyUserForm); }}
              style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid #e2e8f0", background: "#fff", color: "#64748b", fontSize: 11, cursor: "pointer" }}>Cancel</button>
            <button onClick={editingUserId ? updateUser : addUser}
              disabled={!userForm.name.trim() || !userForm.username.trim() || userForm.roles.length === 0}
              style={{ padding: "5px 14px", borderRadius: 6, border: "none", background: (!userForm.name.trim() || !userForm.username.trim() || userForm.roles.length === 0) ? "#93c5fd" : "#4f6ef7", color: "#fff", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
              {editingUserId ? "Save Changes" : "Add User"}
            </button>
          </div>
        </div>
      )}

      {(cfg.users || []).length > 0 && (
        <div style={{ marginTop: 12, padding: "8px 10px", background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 7, fontSize: 10, color: "#92400e" }}>
          ⚠ Ensure at least one user has the Admin role so you can access this panel after saving.
        </div>
      )}
    </div>
  );

  // ── Render: System section (Pods + AI) ────────────────────────────────────────

  const renderSystemSection = () => (
    <div>
      <div style={{ fontSize: 13, fontWeight: 700, color: "#1e293b", marginBottom: 14 }}>System Settings</div>

      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#374151", marginBottom: 8 }}>🔌 Agent Pod URLs</div>
        <p style={{ fontSize: 11, color: "#64748b", margin: "0 0 10px" }}>Base URLs for the AI agent pods. Update if pods move to a different server.</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <Field label="Requirements Pod" value={cfg.pods.requirements} onChange={v => setCfg(c => ({ ...c, pods: { ...c.pods, requirements: v } }))} placeholder="http://35.209.107.68:8001" span />
          <Field label="Design Pod"       value={cfg.pods.design}       onChange={v => setCfg(c => ({ ...c, pods: { ...c.pods, design: v } }))}       placeholder="http://35.209.107.68:8082" span />
          <Field label="Development Pod"  value={cfg.pods.development}  onChange={v => setCfg(c => ({ ...c, pods: { ...c.pods, development: v } }))}  placeholder="http://35.209.107.68:8000" span />
        </div>
        <div style={{ marginTop: 10, padding: "8px 10px", background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 7, fontSize: 10, color: "#92400e" }}>
          ⚠ Direct pod calls require CORS enabled on each pod (ALLOWED_ORIGINS=*).
        </div>
      </div>

      <div>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#374151", marginBottom: 8 }}>🤖 AI Model</div>
        <p style={{ fontSize: 11, color: "#64748b", margin: "0 0 10px" }}>Anthropic API key and model override. Leave blank to use Agent SDK defaults.</p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 12px" }}>
          <Field label="Anthropic API Key" value={cfg.ai.apiKey} onChange={v => setCfg(c => ({ ...c, ai: { ...c.ai, apiKey: v } }))} placeholder="sk-ant-•••• (leave blank for Agent SDK)" type="password" span />
          <Field label="Model ID"          value={cfg.ai.model}  onChange={v => setCfg(c => ({ ...c, ai: { ...c.ai, model: v } }))}  placeholder="claude-sonnet-4-6 (default)" span />
        </div>
      </div>
    </div>
  );

  // ── Main render ───────────────────────────────────────────────────────────────

  const navItems: { id: Section; label: string; icon: string }[] = [
    { id: "products", label: "Products",       icon: "📦" },
    { id: "users",    label: "Users",          icon: "👥" },
    { id: "system",   label: "System",         icon: "⚙️" },
  ];

  const inner = (
    <div style={{ background: "#fff", borderRadius: mode === "page" ? 0 : 14, width: mode === "page" ? "min(900px, 95vw)" : "min(620px, 95vw)", maxHeight: mode === "page" ? "none" : "92vh", height: mode === "page" ? "100%" : "auto", display: "flex", flexDirection: "column", boxShadow: mode === "page" ? "none" : "0 20px 60px rgba(0,0,0,0.25)", overflow: "hidden" }}>

      {/* Header */}
      <div style={{ padding: "14px 20px", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "center", gap: 12, background: "#f8fafc", flexShrink: 0 }}>
        {mode === "page" && onBack && (
          <button onClick={onBack} style={{ background: "none", border: "1px solid #e2e8f0", borderRadius: 7, padding: "4px 10px", cursor: "pointer", fontSize: 11, color: "#64748b", fontWeight: 600 }}>← Back</button>
        )}
        <span style={{ fontSize: 22 }}>⚙️</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: "#1e293b" }}>Admin Settings</div>
          <div style={{ fontSize: 10, color: "#94a3b8" }}>Manage products, swimlanes, projects and integrations</div>
        </div>
        {mode === "modal" && onClose && (
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18, color: "#94a3b8" }}>✕</button>
        )}
      </div>

      {/* Body: left nav + content */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

        {/* Left nav */}
        <div style={{ width: 140, borderRight: "1px solid #e2e8f0", display: "flex", flexDirection: "column", background: "#f8fafc", flexShrink: 0, padding: "10px 0" }}>
          {navItems.map(n => (
            <button key={n.id} onClick={() => setSection(n.id)}
              style={{ padding: "10px 14px", border: "none", background: section === n.id ? "#fff" : "transparent", borderLeft: section === n.id ? "3px solid #4f6ef7" : "3px solid transparent", cursor: "pointer", display: "flex", alignItems: "center", gap: 8, textAlign: "left", width: "100%" }}>
              <span style={{ fontSize: 16 }}>{n.icon}</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: section === n.id ? "#4f6ef7" : "#64748b" }}>{n.label}</span>
            </button>
          ))}
        </div>

        {/* Main content */}
        <div style={{ flex: 1, overflowY: "auto", padding: "18px 22px" }}>
          {section === "products" && (
            <>
              {renderBreadcrumb()}
              {!selectedProductId  && renderProductList()}
              {selectedProductId && !selectedSwimlaneId && renderSwimlaneList()}
              {selectedSwimlaneId && !selectedProjectId && !projectForm && renderProjectList()}
              {selectedSwimlaneId && !selectedProjectId && projectForm && projectForm.editId === null && renderProjectList()}
              {selectedProjectId && projectForm && renderProjectFormPanel()}
            </>
          )}
          {section === "users"   && renderUsersSection()}
          {section === "system"  && renderSystemSection()}
        </div>
      </div>

      {/* Footer */}
      <div style={{ padding: "12px 20px", borderTop: "1px solid #e2e8f0", display: "flex", justifyContent: "space-between", alignItems: "center", background: "#f8fafc", flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button onClick={handleSync} style={{ padding: "6px 12px", borderRadius: 7, border: "1px solid #bfdbfe", background: "#eff6ff", color: "#4f6ef7", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
            ↻ Sync from file
          </button>
          {syncMsg && <span style={{ fontSize: 10, color: syncMsg.startsWith("✓") ? "#16a34a" : "#ef4444", fontWeight: 600 }}>{syncMsg}</span>}
          <button onClick={handleClear} style={{ padding: "6px 14px", borderRadius: 7, border: "1px solid #fca5a5", background: confirmClear ? "#fee2e2" : "#fff", color: confirmClear ? "#b91c1c" : "#64748b", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
            {confirmClear ? "⚠ Confirm clear?" : "🗑 Clear All"}
          </button>
          {confirmClear && (
            <button onClick={() => setConfirmClear(false)} style={{ padding: "6px 10px", borderRadius: 7, border: "1px solid #e2e8f0", background: "#fff", color: "#64748b", fontSize: 11, cursor: "pointer" }}>Cancel</button>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {saveMsg && <span style={{ fontSize: 11, fontWeight: 600, color: "#16a34a" }}>{saveMsg}</span>}
          <button onClick={handleSave} style={{ padding: "7px 22px", borderRadius: 7, border: "none", background: "#4f6ef7", color: "#fff", fontSize: 11, fontWeight: 700, cursor: "pointer", boxShadow: "0 2px 8px rgba(79,110,247,0.35)" }}>
            ✓ Save Settings
          </button>
        </div>
      </div>
    </div>
  );

  if (mode === "page") {
    return (
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "center", minHeight: "100vh", background: "#f1f5f9", padding: 24 }}>
        {inner}
      </div>
    );
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
      {inner}
    </div>
  );
}
