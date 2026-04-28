package com.prodapt.development.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class StartDevelopmentRunRequest {

    @JsonProperty("session_id")
    private String sessionId;

    @NotNull
    @JsonProperty("document_source")
    private DocumentSource documentSource;

    // GitHub sources — one for impl doc, one for mapping CSV
    @Valid
    @JsonProperty("github_impl_source")
    private GitHubSourceDetails githubImplSource;

    @Valid
    @JsonProperty("github_mapping_source")
    private GitHubSourceDetails githubMappingSource;

    // Google Drive sources
    @Valid
    @JsonProperty("google_drive_impl_source")
    private GoogleDriveSourceDetails googleDriveImplSource;

    @Valid
    @JsonProperty("google_drive_mapping_source")
    private GoogleDriveSourceDetails googleDriveMappingSource;

    // Jira ticket ID — used when documentSource = TICKET
    @JsonProperty("ticket_id")
    private String ticketId;

    // Raw content — used when documentSource = DIRECT
    @JsonProperty("implementation_md")
    private String implementationMd;

    @JsonProperty("mapping_csv")
    private String mappingCsv;

    // GCP / pipeline target config
    @JsonProperty("project_id")
    private String projectId;

    @JsonProperty("dataset_id")
    private String datasetId;

    @Builder.Default
    @JsonProperty("environment")
    private String environment = "dev";

    @Builder.Default
    @JsonProperty("cloud_provider")
    private String cloudProvider = "gcp";

    @Builder.Default
    @JsonProperty("region")
    private String region = "us-central1";
}
