package com.prodapt.design.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

/**
 * Response from the Design pod's Implementation Steps agent
 * ({@code POST /implementation-steps}).
 *
 * <pre>
 * {
 *   "project_name": "My Project",
 *   "request_type": "new development",
 *   "output_path":  "agents/implementation_steps/output/impl_SCRUM-5_....md",
 *   "markdown":     "# Implementation Plan\n...",
 *   "git": { "pushed": true, ... }
 * }
 * </pre>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ImplStepsAgentResponse {

    @JsonProperty("project_name")
    private String projectName;

    @JsonProperty("request_type")
    private String requestType;

    @JsonProperty("output_path")
    private String outputPath;

    @JsonProperty("markdown")
    private String markdown;

    @JsonProperty("git")
    private Map<String, Object> git;
}
