export const developmentModule = {
  id: "development",
  label: "Development",
  desc: "AI-driven data pipeline code generation",
  icon: "🗄️",
  btnColor: "#e07b39",
  subModules: [
    { id: "pipeline_run", label: "Pipeline Run", icon: "⚡", systemPrompt: "", desc: "Start a code-gen run from implementation docs" },
    { id: "checkpoint",   label: "Checkpoint",   icon: "🔖", systemPrompt: "", desc: "Review and submit checkpoint decisions" },
    { id: "deploy",       label: "Deploy",       icon: "🚀", systemPrompt: "", desc: "Trigger GCP deployment of approved artifacts" },
    { id: "outputs",      label: "Outputs",      icon: "📦", systemPrompt: "", desc: "Browse generated DDL, DML, DAGs and reports" },
  ],
};

