package com.prodapt.design.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

/**
 * Response from the Design pod's full pipeline ({@code POST /pipeline}).
 *
 * <p>Aggregates results from all four agents run in sequence:
 * Data Model → Architecture → mermaid2drawio → Implementation Steps.
 * Each agent result may contain an {@code "error"} key if that step failed
 * (the pipeline is fault-tolerant and continues on partial failures).
 *
 * <pre>
 * {
 *   "data_model_path":   "agents/data_model/output/model_..._summary.json",
 *   "architecture_path": "agents/architecture/outputs/arc_..._summary.json",
 *   "data_model":           { ... DataModelAgent handoff_summary or {"error": "..."} },
 *   "architecture":         { ... ArchitectureAgent handoff_summary or {"error": "..."} },
 *   "mermaid2drawio":       { "drawio_files": [...], "git": {...} } or {"error": "..."},
 *   "implementation_steps": { "output_path": "...", "markdown": "...", "git": {...} } or {"error": "..."},
 *   "git": {
 *     "data_model": {...},
 *     "architecture": {...},
 *     "mermaid2drawio": {...},
 *     "implementation_steps": {...}
 *   }
 * }
 * </pre>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class PipelineAgentResponse {

    @JsonProperty("data_model_path")
    private String dataModelPath;

    @JsonProperty("architecture_path")
    private String architecturePath;

    @JsonProperty("data_model")
    private Map<String, Object> dataModel;

    @JsonProperty("architecture")
    private Map<String, Object> architecture;

    @JsonProperty("mermaid2drawio")
    private Map<String, Object> mermaid2drawio;

    @JsonProperty("implementation_steps")
    private Map<String, Object> implementationSteps;

    @JsonProperty("git")
    private Map<String, Object> git;
}
