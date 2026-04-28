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
public class DeployRunSummary {

    @JsonProperty("run_id")
    private String runId;

    @JsonProperty("request_id")
    private String requestId;

    /** pending | running | success | failed | skipped */
    @JsonProperty("status")
    private String status;

    @JsonProperty("environment")
    private String environment;

    @JsonProperty("project_id")
    private String projectId;

    @JsonProperty("dataset_id")
    private String datasetId;

    @JsonProperty("created_at")
    private String createdAt;

    /** Populated once the run completes; null while pending/running */
    @JsonProperty("result")
    private DeployResult result;

    @JsonProperty("error")
    private String error;
}
