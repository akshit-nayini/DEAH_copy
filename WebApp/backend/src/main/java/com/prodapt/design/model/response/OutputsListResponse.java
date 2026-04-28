package com.prodapt.design.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

/**
 * Response from {@code GET /api/v1/design/outputs}.
 *
 * <p>Lists all output files produced by each agent, newest first.
 *
 * <pre>
 * {
 *   "requirements": { "json": [...], "markdown": [...] },
 *   "data_model": { "summary_json": [...], "er_diagram_mmd": [...], "mapping_csv": [...] },
 *   "architecture": { "summary_json": [...], "report_md": [...], "flow_mmd": [...] },
 *   "mermaid2drawio": [...],
 *   "implementation_steps": [...]
 * }
 * </pre>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OutputsListResponse {

    @JsonProperty("requirements")
    private Map<String, List<String>> requirements;

    @JsonProperty("data_model")
    private Map<String, List<String>> dataModel;

    @JsonProperty("architecture")
    private Map<String, List<String>> architecture;

    @JsonProperty("mermaid2drawio")
    private List<String> mermaid2drawio;

    @JsonProperty("implementation_steps")
    private List<String> implementationSteps;
}
