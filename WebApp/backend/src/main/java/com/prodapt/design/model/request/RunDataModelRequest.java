package com.prodapt.design.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Request to run the Data Model agent.
 *
 * <p>Provide <b>either</b> {@code ticket_id} (agent auto-resolves the latest
 * Requirements JSON from the metadata DB) <b>or</b> {@code requirements_path}
 * (explicit file path, relative to agents/ on the server).
 * {@code schema_path} is always optional.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RunDataModelRequest {

    @NotBlank(message = "session_id is required")
    @JsonProperty("session_id")
    private String sessionId;

    @JsonProperty("ticket_id")
    private String ticketId;

    @JsonProperty("requirements_path")
    private String requirementsPath;

    @JsonProperty("schema_path")
    private String schemaPath;
}
