package com.prodapt.requirements.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Inbound request from the Prodapt UI.
 *
 * The caller must supply EITHER {@code githubSource} OR {@code googleDriveSource}
 * depending on the chosen {@code documentSource}.
 *
 * Example JSON (GitHub):
 * <pre>
 * {
 *   "session_id": "SES-ABC123",
 *   "document_source": "GITHUB",
 *   "github_source": {
 *     "org": "my-org",
 *     "repo": "my-repo",
 *     "branch": "main",
 *     "file_path": "docs/requirements.md",
 *     "pat_token": "ghp_xxx"
 *   }
 * }
 * </pre>
 *
 * Example JSON (Google Drive):
 * <pre>
 * {
 *   "session_id": "SES-ABC123",
 *   "document_source": "GOOGLE_DRIVE",
 *   "google_drive_source": {
 *     "drive_url_or_id": "https://docs.google.com/document/d/FILE_ID/edit",
 *     "oauth_token": "ya29.xxx"
 *   }
 * }
 * </pre>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ProcessRequirementsRequest {

    /** Unique session identifier passed through from the frontend for correlation. */
    @JsonProperty("session_id")
    private String sessionId;

    /**
     * Identifies which document source to use: GITHUB or GOOGLE_DRIVE.
     */
    @NotNull(message = "document_source must be GITHUB or GOOGLE_DRIVE")
    @JsonProperty("document_source")
    private DocumentSource documentSource;

    /** Populated when documentSource == GITHUB */
    @Valid
    @JsonProperty("github_source")
    private GitHubSourceDetails githubSource;

    /** Populated when documentSource == GOOGLE_DRIVE */
    @Valid
    @JsonProperty("google_drive_source")
    private GoogleDriveSourceDetails googleDriveSource;

    /**
     * Optional free-text context to forward to the Requirements Agent
     * alongside the fetched document (e.g. project name, team notes).
     */
    @JsonProperty("additional_context")
    private String additionalContext;
}
