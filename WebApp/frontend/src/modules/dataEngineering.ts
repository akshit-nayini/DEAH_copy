export const dataEngineeringModule = {
  id: "data_engineering",
  label: "Data Engineering",
  desc: "Design & generate data pipelines",
  icon: "🗄️",
  btnColor: "#e07b39",
  subModules: [
    {
      id: "jira_reviewer",
      label: "JIRA Reviewer",
      icon: "🔎",
      systemPrompt: "You are a data engineer. Review JIRA tickets and create flow sequences. Output sections: FLOW_SEQUENCE (numbered), DATA_SOURCES, TRANSFORMATIONS_NEEDED, DEPENDENCIES, PIPELINE_COMPLEXITY.",
    },
    {
      id: "data_designer",
      label: "Data Designer",
      icon: "🏗️",
      systemPrompt: "You are a data architect. Create optimal data models and pipelines. Output sections: DATA_MODEL, PIPELINE_ARCHITECTURE, DATA_FLOW_DIAGRAM, TECH_STACK_RECOMMENDATION, SIGNOFF_CHECKLIST.",
    },
    {
      id: "code_generator",
      label: "Code Generator & Optimizer",
      icon: "⚡",
      systemPrompt: "You are an expert data engineer. Generate optimized Python/SQL code with imports, main function, error handling, logging, and optimization comments.",
    },
    {
      id: "self_reviewer",
      label: "Self Review Agent",
      icon: "🔍",
      systemPrompt: "You are a senior code reviewer. Output sections: OVERALL_SCORE (1-10), CODE_QUALITY_ISSUES, SECURITY_CONCERNS, PERFORMANCE_ISSUES, VZ_STANDARDS_COMPLIANCE, SIGNOFF_STATUS.",
    },
  ],
};
