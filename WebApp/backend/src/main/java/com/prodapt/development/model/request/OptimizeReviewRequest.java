package com.prodapt.development.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OptimizeReviewRequest {

    @NotEmpty
    @Valid
    @JsonProperty("artifacts")
    private List<ArtifactPayload> artifacts;

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
    @JsonProperty("human_notes")
    private List<String> humanNotes = List.of();
}
