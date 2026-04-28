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
public class StartDeployRequest {

    @NotBlank(message = "request_id is required")
    @JsonProperty("request_id")
    private String requestId;

    @NotBlank(message = "artifacts_dir is required")
    @JsonProperty("artifacts_dir")
    private String artifactsDir;

    @JsonProperty("project_id")
    private String projectId;

    @JsonProperty("dataset_id")
    private String datasetId;

    @Builder.Default
    @JsonProperty("environment")
    private String environment = "dev";

    @JsonProperty("dag_bucket")
    private String dagBucket;

    @JsonProperty("composer_environment")
    private String composerEnvironment;

    @Builder.Default
    @JsonProperty("target")
    private String target = "gcp";

    @JsonProperty("source_db_type")
    private String sourceDbType;

    @JsonProperty("source_db_host")
    private String sourceDbHost;

    @JsonProperty("source_db_port")
    private Integer sourceDbPort;

    @JsonProperty("source_db_name")
    private String sourceDbName;

    @JsonProperty("source_db_user")
    private String sourceDbUser;
}
