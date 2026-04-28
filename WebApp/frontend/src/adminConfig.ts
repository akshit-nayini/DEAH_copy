export type UserRole = "admin" | "developer";

export interface UserProfile {
  id: string;
  name: string;
  username: string;
  password: string;
  roles: UserRole[];
}

export interface JiraConfig {
  url: string;
  projectKey: string;
  email: string;
  token: string;
}

export interface GitHubConfig {
  org: string;
  repo: string;
  branch: string;
  token: string;
}

export interface ConfluenceConfig {
  url: string;
  spaceKey: string;
  email: string;
  token: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  owner: string;
  developers: string[];
  jira: JiraConfig;
  github: GitHubConfig;
  confluence: ConfluenceConfig;
}

export interface Swimlane {
  id: string;
  name: string;
  description: string;
  owner: string;
  projects: Project[];
}

export interface Product {
  id: string;
  name: string;
  description: string;
  owner: string;
  swimlanes: Swimlane[];
}

export interface AdminConfig {
  products: Product[];
  pods:     { requirements: string; design: string; development: string; }
  ai:       { apiKey: string; model: string; }
  users?:   UserProfile[];
}

const KEY = "deah_admin_cfg";

export function loadAdminConfig(): AdminConfig | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as AdminConfig) : null;
  } catch {
    return null;
  }
}

export function saveAdminConfig(cfg: AdminConfig): void {
  localStorage.setItem(KEY, JSON.stringify(cfg));
}

export function clearAdminConfig(): void {
  localStorage.removeItem(KEY);
}

export async function fetchRemoteConfig(): Promise<AdminConfig | null> {
  try {
    const res = await fetch("/admin-config.json");
    if (!res.ok) return null;
    return (await res.json()) as AdminConfig;
  } catch {
    return null;
  }
}

export function projectToCredentials(project: Project): Record<string, Record<string, string>> {
  const jira = {
    jira_url:         project.jira.url,
    jira_project_key: project.jira.projectKey,
    jira_email:       project.jira.email,
    jira_token:       project.jira.token,
    filled:           "1",
  };
  const github = {
    github_org:    project.github.org,
    github_repo:   project.github.repo,
    github_branch: project.github.branch,
    github_token:  project.github.token,
    filled:        "1",
  };
  return {
    jira_integrator: jira,
    jira_reviewer:   jira,
    git_processor:   github,
    self_reviewer:   github,
  };
}

export function adminConfigToCredentials(cfg: AdminConfig): Record<string, Record<string, string>> {
  for (const product of cfg.products || []) {
    for (const swimlane of product.swimlanes || []) {
      for (const project of swimlane.projects || []) {
        return projectToCredentials(project);
      }
    }
  }
  return {};
}
