export const designModule = {
  id: "design",
  label: "Design",
  desc: "Run design pipeline: requirements → data model → architecture → impl steps",
  icon: "🗄️",
  btnColor: "#e07b39",
  subModules: [
    {
      id: "req_from_jira",
      label: "Requirements",
      icon: "🎫",
      systemPrompt: "You are a requirements analyst. Extract and structure requirements from a Jira ticket for data engineering design.",
    },
    {
      id: "data_model",
      label: "Data Model",
      icon: "🗄️",
      systemPrompt: "You are a data architect. Present the ER diagram, source-target mappings, and data model summary.",
    },
    {
      id: "architecture",
      label: "Architecture",
      icon: "🏗️",
      systemPrompt: "You are a solution architect. Present the architecture decisions, flow diagram, and handoff summary.",
    },
    {
      id: "impl_steps",
      label: "Impl Steps",
      icon: "📋",
      systemPrompt: "You are a technical lead. Present the step-by-step implementation plan generated from the architecture.",
    },
  ],
};
