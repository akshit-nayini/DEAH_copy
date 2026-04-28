package com.prodapt.requirements.model.pod;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class PodJiraPushResultItem {

    @JsonProperty("task_id")
    private String taskId;

    @JsonProperty("success")
    private boolean success;

    @JsonProperty("jira_id")
    private String jiraId;

    @JsonProperty("jira_url")
    private String jiraUrl;

    @JsonProperty("action")
    private String action;

    @JsonProperty("error")
    private String error;
}
