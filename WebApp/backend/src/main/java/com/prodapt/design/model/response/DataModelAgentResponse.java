package com.prodapt.design.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

/**
 * Response from the Design pod's Data Model agent ({@code POST /data-model}).
 *
 * <pre>
 * {
 *   "output_files": {
 *     "summary_json":   "agents/data_model/output/model_SCRUM-5_..._summary.json",
 *     "er_diagram_mmd": "agents/data_model/output/model_SCRUM-5_..._er_diagram.mmd",
 *     "mapping_csv":    "agents/data_model/output/model_SCRUM-5_..._mapping.csv"
 *   },
 *   "handoff_summary":       { ... compact JSON for downstream agents ... },
 *   "source_target_mapping": "source_col,target_col\n...",
 *   "er_mermaid_diagram":    "erDiagram\n  ...",
 *   "git": { "pushed": true, ... }
 * }
 * </pre>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class DataModelAgentResponse {

    @JsonProperty("output_files")
    private DataModelOutputFiles outputFiles;

    @JsonProperty("handoff_summary")
    private Map<String, Object> handoffSummary;

    @JsonProperty("source_target_mapping")
    private String sourceTargetMapping;

    @JsonProperty("er_mermaid_diagram")
    private String erMermaidDiagram;

    @JsonProperty("git")
    private Map<String, Object> git;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class DataModelOutputFiles {

        @JsonProperty("summary_json")
        private String summaryJson;

        @JsonProperty("er_diagram_mmd")
        private String erDiagramMmd;

        @JsonProperty("mapping_csv")
        private String mappingCsv;
    }
}
