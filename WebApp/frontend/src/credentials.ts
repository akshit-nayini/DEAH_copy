export const CRED_FIELDS: Record<string, {
  title: string; color: string; icon: string;
  fields: { key: string; label: string; placeholder: string; required?: boolean; type?: string }[];
}> = {
  jira_integrator: {
    title:"JIRA Credentials", color:"#e07b39", icon:"🎫",
    fields:[
      { key:"jira_url",         label:"JIRA URL",    placeholder:"https://org.atlassian.net", required:true },
      { key:"jira_project_key", label:"Project Key", placeholder:"e.g. PROJ",                required:true },
      { key:"jira_email",       label:"Email",       placeholder:"you@company.com",           type:"email"  },
      { key:"jira_token",       label:"API Token",   placeholder:"••••••••••••",              type:"password"},
    ]
  },
  jira_reviewer: {
    title:"JIRA Credentials", color:"#e07b39", icon:"🎫",
    fields:[
      { key:"jira_url",         label:"JIRA URL",    placeholder:"https://org.atlassian.net", required:true },
      { key:"jira_project_key", label:"Project Key", placeholder:"e.g. PROJ",                required:true },
      { key:"jira_email",       label:"Email",       placeholder:"you@company.com",           type:"email"  },
      { key:"jira_token",       label:"API Token",   placeholder:"••••••••••••",              type:"password"},
    ]
  },
  git_processor: {
    title:"GitHub Credentials", color:"#2e9e5b", icon:"🌿",
    fields:[
      { key:"github_org",    label:"Org / Username", placeholder:"e.g. my-org",   required:true },
      { key:"github_repo",   label:"Repository",     placeholder:"e.g. my-repo",  required:true },
      { key:"github_branch", label:"Default Branch", placeholder:"main"                        },
      { key:"github_token",  label:"PAT Token",      placeholder:"ghp_••••••••",  type:"password"},
    ]
  },
  self_reviewer: {
    title:"GitHub Credentials", color:"#2e9e5b", icon:"🌿",
    fields:[
      { key:"github_org",    label:"Org / Username", placeholder:"e.g. my-org",   required:true },
      { key:"github_repo",   label:"Repository",     placeholder:"e.g. my-repo",  required:true },
      { key:"github_branch", label:"Default Branch", placeholder:"main"                        },
      { key:"github_token",  label:"PAT Token",      placeholder:"ghp_••••••••",  type:"password"},
    ]
  },
};
