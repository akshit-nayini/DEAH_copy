package com.prodapt.design.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Request to run the Implementation Steps agent.
 *
 * <p><b>Option A — ticket_id:</b> auto-resolves {@code request_type},
 * {@code project_name}, and all input JSONs from the metadata DB.
 *
 * <p><b>Option B — explicit:</b> provide {@code request_type} + {@code project_name}
 * and the relevant input paths (relative to agents/).
 *
 * <ul>
 *   <li>{@code architecture_path} — required for "new development" and "enhancement"</li>
 *   <li>{@code data_model_path}   — required for "new development"</li>
 *   <li>{@code requirements_path} — required for "bug"</li>
 * </ul>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RunImplStepsRequest {

    @NotBlank(message = "session_id is required")
    @JsonProperty("session_id")
    private String sessionId;

    @JsonProperty("ticket_id")
    private String ticketId;

    @JsonProperty("request_type")
    private String requestType;

    @JsonProperty("project_name")
    private String projectName;

    @JsonProperty("architecture_path")
    private String architecturePath;

    @JsonProperty("data_model_path")
    private String dataModelPath;

    @JsonProperty("requirements_path")
    private String requirementsPath;
}
