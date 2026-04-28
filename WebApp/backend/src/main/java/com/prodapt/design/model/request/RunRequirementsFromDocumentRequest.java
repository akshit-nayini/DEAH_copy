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
public class RunRequirementsFromDocumentRequest {

    @NotBlank(message = "session_id is required")
    @JsonProperty("session_id")
    private String sessionId;

    /**
     * Path to the document file, relative to the agents/ directory on the server
     * (or absolute). Forwarded directly to the design pod FastAPI.
     */
    @NotBlank(message = "document_path is required")
    @JsonProperty("document_path")
    private String documentPath;
}
