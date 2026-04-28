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
public class DeployStepResult {

    @JsonProperty("step")
    private String step;

    /** success | failed | skipped */
    @JsonProperty("status")
    private String status;

    @JsonProperty("message")
    private String message;
}
