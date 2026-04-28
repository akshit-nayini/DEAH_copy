package com.prodapt.design.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RunRequirementsFromJiraRequest {

    @NotBlank(message = "session_id is required")
    @JsonProperty("session_id")
    private String sessionId;

    @NotBlank(message = "ticket_id is required")
    @JsonProperty("ticket_id")
    private String ticketId;

    @Builder.Default
    @JsonProperty("write_back")
    private boolean writeBack = false;
}
