export const knowledgeBuildModule = {
  id: "knowledge_build",
  label: "Knowledge Build",
  desc: "Document & publish workflow knowledge",
  icon: "📚",
  btnColor: "#6b4fbb",
  subModules: [
    {
      id: "document_generator",
      label: "Document Generator",
      icon: "📄",
      systemPrompt: "You are a technical writer. Generate end-to-end docs. Output sections: EXECUTIVE_SUMMARY, TECHNICAL_DOCUMENTATION, RELEASE_NOTES, KNOWN_LIMITATIONS, NEXT_STEPS, CHANGELOG.",
    },
    {
      id: "document_uploaded",
      label: "Document Uploaded",
      icon: "☁️",
      systemPrompt: "You are a knowledge management expert. Prepare docs for Confluence/JIRA. Output sections: CONFLUENCE_PAGE_STRUCTURE, JIRA_ATTACHMENT_LIST, TAGGING_TAXONOMY, SEARCH_KEYWORDS, UPLOAD_STATUS.",
    },
  ],
};
