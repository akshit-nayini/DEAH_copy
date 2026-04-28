package com.prodapt.requirements.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Payload forwarded to the Requirements Agent (FastAPI).
 *
 * The Spring Boot backend fetches the raw document from GitHub or Google Drive,
 * then sends this payload to the agent so it can focus purely on AI processing.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AgentProcessRequest {

    /** Session ID for end-to-end correlation */
    @JsonProperty("session_id")
    private String sessionId;

    /**
     * Raw binary bytes of the document (used for binary formats like DOCX/PDF).
     * When set, takes precedence over documentContent in the multipart upload.
     */
    private byte[] documentBytes;

    /**
     * Raw text content of the requirements document fetched from
     * GitHub or Google Drive. The agent does not need to know the source.
     */
    @JsonProperty("document_content")
    private String documentContent;

    /**
     * Original filename or path for context (e.g. "docs/requirements.md")
     */
    @JsonProperty("document_name")
    private String documentName;

    /**
     * Source type label forwarded for agent logging/tracing: "GITHUB" | "GOOGLE_DRIVE"
     */
    @JsonProperty("source_type")
    private String sourceType;

    /**
     * Optional extra context provided by the user in the UI
     * (project notes, team, sprint target, etc.)
     */
    @JsonProperty("additional_context")
    private String additionalContext;
}
