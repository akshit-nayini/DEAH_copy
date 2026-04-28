export const testingModule = {
  id: "testing",
  label: "Testing",
  desc: "Auto-generate & validate test suites",
  icon: "🧪",
  btnColor: "#2e9e5b",
  subModules: [
    {
      id: "test_case_generator",
      label: "Test Case Generator",
      icon: "📝",
      systemPrompt: "You are a QA engineer. Create test cases. Output sections: UNIT_TESTS, INTEGRATION_TESTS, E2E_TESTS, EDGE_CASES, COVERAGE_ESTIMATE (%).",
    },
    {
      id: "synthetic_data_generator",
      label: "Synthetic Data Generator",
      icon: "🔮",
      systemPrompt: "You are a data privacy expert. Generate synthetic test data. Output sections: SAMPLE_DATASETS (JSON, no PII), DATA_SCHEMA, EDGE_CASE_DATASETS, PII_COMPLIANCE_NOTES.",
    },
    {
      id: "result_validator",
      label: "Result Validator",
      icon: "✅",
      systemPrompt: "You are a QA validation expert. Validate results. Output sections: VALIDATION_SUMMARY, PASS_RATE (%), ANOMALIES_DETECTED, CRITICAL_FAILURES, RELEASE_RECOMMENDATION (Go/No-Go).",
    },
    {
      id: "git_processor",
      label: "Git Processor",
      icon: "🌿",
      systemPrompt: "You are a DevOps engineer. Prepare git operations. Output sections: COMMIT_MESSAGE, BRANCH_STRATEGY, PR_DESCRIPTION, CODE_QUALITY_GATE (Pass/Fail), MERGE_CHECKLIST, SIGNOFF_STATUS.",
    },
  ],
};
