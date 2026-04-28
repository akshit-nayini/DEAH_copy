package com.prodapt.development.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class GeneratedArtifact {

    @JsonProperty("file_name")
    private String fileName;

    @JsonProperty("artifact_type")
    private String artifactType;

    @JsonProperty("description")
    private String description;

    @JsonProperty("target_path")
    private String targetPath;

    @JsonProperty("is_alter")
    private boolean isAlter;
}
