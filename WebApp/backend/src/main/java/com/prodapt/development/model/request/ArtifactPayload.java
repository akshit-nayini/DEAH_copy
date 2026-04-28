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
public class ArtifactPayload {

    @NotBlank
    @JsonProperty("file_name")
    private String fileName;

    @NotBlank
    @JsonProperty("artifact_type")
    private String artifactType;

    @NotBlank
    @JsonProperty("content")
    private String content;

    @JsonProperty("description")
    private String description;

    @JsonProperty("target_path")
    private String targetPath;
}
