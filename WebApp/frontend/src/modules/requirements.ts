export const requirementsModule = {
  id: "requirements",
  label: "Requirements",
  desc: "Gather & define project requirements",
  icon: "📋",
  btnColor: "#4f6ef7",
  subModules: [
    {
      id: "source_docs",
      label: "Source Document",
      icon: "🎙️",
      systemPrompt: "You are a requirements analyst. Auto-transcribe and summarize stakeholder calls. Output sections: CALL_SUMMARY, KEY_REQUIREMENTS (numbered), DECISIONS_MADE, ACTION_ITEMS, STAKEHOLDERS_MENTIONED.",
    },
    {
      id: "jira_integrator",
      label: "Jira Tickets",
      icon: "🎫",
      systemPrompt: "",
    },
    {
      id: "template_filler",
      label: "Requirements Doc",
      icon: "📄",
      systemPrompt: "",
    },
  ]
};
