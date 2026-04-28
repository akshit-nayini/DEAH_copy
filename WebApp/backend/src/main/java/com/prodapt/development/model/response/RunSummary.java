package com.prodapt.development.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RunSummary {

    @JsonProperty("request_id")
    private String requestId;

    @JsonProperty("status")
    private RunStatus status;

    @JsonProperty("checkpoint_number")
    private Integer checkpointNumber;

    @JsonProperty("checkpoint_prompt")
    private String checkpointPrompt;

    @JsonProperty("plan_summary")
    private String planSummary;

    @Builder.Default
    @JsonProperty("artifacts")
    private List<GeneratedArtifact> artifacts = List.of();

    @JsonProperty("quality_score")
    private Double qualityScore;

    @JsonProperty("git_branch")
    private String gitBranch;

    @JsonProperty("error")
    private String error;

    @JsonProperty("output_directory")
    private String outputDirectory;

    @JsonProperty("current_task")
    private String currentTask;

    @Builder.Default
    @JsonProperty("log_messages")
    private List<String> logMessages = List.of();
}
