package com.prodapt.design.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Request to run the Architecture agent.
 *
 * <p>Provide <b>either</b> {@code ticket_id} (auto-resolves the latest
 * Requirements JSON from the metadata DB) <b>or</b> {@code requirements_path}
 * (explicit file, relative to agents/).
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RunArchitectureRequest {

    @NotBlank(message = "session_id is required")
    @JsonProperty("session_id")
    private String sessionId;

    @JsonProperty("ticket_id")
    private String ticketId;

    @JsonProperty("requirements_path")
    private String requirementsPath;
}
