package com.prodapt.development.model.request;

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
public class GitHubSourceDetails {

    @NotBlank
    @JsonProperty("org")
    private String org;

    @NotBlank
    @JsonProperty("repo")
    private String repo;

    @Builder.Default
    @JsonProperty("branch")
    private String branch = "main";

    @NotBlank
    @JsonProperty("file_path")
    private String filePath;

    @JsonProperty("pat_token")
    private String patToken;
}
