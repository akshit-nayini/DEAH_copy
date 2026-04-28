package com.prodapt.requirements.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class JiraPushResultItem {

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
