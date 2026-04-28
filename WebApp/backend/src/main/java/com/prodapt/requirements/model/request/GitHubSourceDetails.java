package com.prodapt.requirements.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Details required to fetch a document from GitHub.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class GitHubSourceDetails {

    /** GitHub organisation or username, e.g. "my-org" */
    @NotBlank(message = "GitHub organisation/username is required")
    @JsonProperty("org")
    private String org;

    /** Repository name, e.g. "my-repo" */
    @NotBlank(message = "GitHub repository name is required")
    @JsonProperty("repo")
    private String repo;

    /**
     * Branch name. Defaults to "main" when null/blank.
     */
    @JsonProperty("branch")
    @Builder.Default
    private String branch = "main";

    /**
     * Path to the requirements file within the repository,
     * e.g. "docs/requirements.md"
     */
    @NotBlank(message = "File path within the repository is required")
    @JsonProperty("file_path")
    private String filePath;

    /**
     * GitHub Personal Access Token (PAT).
     * Required for private repositories; optional for public ones.
     */
    @JsonProperty("pat_token")
    private String patToken;
}
