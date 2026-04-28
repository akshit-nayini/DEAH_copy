package com.prodapt.design.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

/**
 * Response from the Design pod's Requirements agent
 * ({@code POST /requirements/from-jira} or {@code POST /requirements/from-document}).
 *
 * <pre>
 * {
 *   "output_path":   "agents/requirements_gathering/output/req_SCRUM-5_20260423.json",
 *   "markdown_path": "agents/requirements_gathering/output/req_SCRUM-5_20260423.md",
 *   "result": { ... structured requirements dict ... },
 *   "git":    { "pushed": true, "branch": "main", "commit": "..." }
 * }
 * </pre>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RequirementsAgentResponse {

    @JsonProperty("output_path")
    private String outputPath;

    @JsonProperty("markdown_path")
    private String markdownPath;

    @JsonProperty("result")
    private Map<String, Object> result;

    @JsonProperty("git")
    private Map<String, Object> git;
}
