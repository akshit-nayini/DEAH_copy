package com.prodapt.development.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotNull;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class CheckpointRequest {

    @NotNull
    @JsonProperty("decision")
    private CheckpointDecision decision;

    @Builder.Default
    @JsonProperty("notes")
    private String notes = "";
}
