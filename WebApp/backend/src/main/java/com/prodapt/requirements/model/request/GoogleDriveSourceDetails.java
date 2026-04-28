package com.prodapt.requirements.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Details required to fetch a document from Google Drive.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class GoogleDriveSourceDetails {

    /**
     * Full Google Drive URL or just the file ID.
     * Example: "https://docs.google.com/document/d/FILE_ID/edit"  or  "FILE_ID"
     */
    @NotBlank(message = "Google Drive URL or file ID is required")
    @JsonProperty("drive_url_or_id")
    private String driveUrlOrId;

    /**
     * OAuth 2.0 access token for Google Drive API.
     * Must have at minimum the "drive.readonly" scope.
     */
    @NotBlank(message = "Google Drive OAuth access token is required")
    @JsonProperty("oauth_token")
    private String oauthToken;
}
