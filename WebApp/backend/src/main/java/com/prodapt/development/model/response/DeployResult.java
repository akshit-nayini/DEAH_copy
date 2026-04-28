package com.prodapt.development.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class DeployResult {

    @JsonProperty("request_id")
    private String requestId;

    @JsonProperty("target")
    private String target;

    /** Pre-deploy connectivity checks: [{check, status, message}, ...] */
    @JsonProperty("validation")
    private List<Map<String, String>> validation;

    /** Ordered deploy step results */
    @JsonProperty("steps")
    private List<DeployStepResult> steps;

    /** success | failed | partial */
    @JsonProperty("overall_status")
    private String overallStatus;
}
