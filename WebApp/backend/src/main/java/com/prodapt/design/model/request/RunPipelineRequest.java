package com.prodapt.design.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Request to run the full Design pipeline (Data Model → Architecture →
 * mermaid2drawio → Implementation Steps).
 *
 * <p><b>Option A — ticket_id:</b> auto-resolves Requirements JSON and derives
 * {@code request_type} and {@code project_name} from it.
 *
 * <p><b>Option B — explicit:</b> provide {@code request_type}, {@code project_name},
 * and {@code requirements_path}. {@code schema_path} is always optional.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RunPipelineRequest {

    @NotBlank(message = "session_id is required")
    @JsonProperty("session_id")
    private String sessionId;

    @JsonProperty("ticket_id")
    private String ticketId;

    @JsonProperty("request_type")
    private String requestType;

    @JsonProperty("project_name")
    private String projectName;

    @JsonProperty("requirements_path")
    private String requirementsPath;

    @JsonProperty("schema_path")
    private String schemaPath;
}
