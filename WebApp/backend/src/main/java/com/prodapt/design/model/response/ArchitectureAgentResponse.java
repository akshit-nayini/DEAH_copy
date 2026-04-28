package com.prodapt.design.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

/**
 * Response from the Design pod's Architecture agent ({@code POST /architecture}).
 *
 * <pre>
 * {
 *   "run_id":  "20260423_143022",
 *   "skipped": false,
 *   "output_files": {
 *     "summary_json": "agents/architecture/outputs/arc_SCRUM-5_..._summary.json",
 *     "report_md":    "agents/architecture/outputs/arc_SCRUM-5_..._report.md",
 *     "flow_mmd":     "agents/architecture/outputs/arc_SCRUM-5_..._flow.mmd"
 *   },
 *   "handoff_summary":  { ... compact payload (~300 tokens) for impl steps ... },
 *   "manifest_summary": { ... full architecture decision manifest ... },
 *   "git": { "pushed": true, ... }
 * }
 * </pre>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ArchitectureAgentResponse {

    @JsonProperty("run_id")
    private String runId;

    @JsonProperty("skipped")
    private boolean skipped;

    @JsonProperty("output_files")
    private ArchitectureOutputFiles outputFiles;

    @JsonProperty("handoff_summary")
    private Map<String, Object> handoffSummary;

    @JsonProperty("manifest_summary")
    private Map<String, Object> manifestSummary;

    @JsonProperty("git")
    private Map<String, Object> git;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ArchitectureOutputFiles {

        @JsonProperty("summary_json")
        private String summaryJson;

        @JsonProperty("report_md")
        private String reportMd;

        @JsonProperty("flow_mmd")
        private String flowMmd;
    }
}
