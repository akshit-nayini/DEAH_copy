package com.prodapt.requirements.model.pod;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class PodTaskOut {

    @JsonProperty("id")
    private String id;

    @JsonProperty("task_id")
    private String taskId;

    @JsonProperty("task_heading")
    private String taskHeading;

    @JsonProperty("description")
    private String description;

    @JsonProperty("task_type")
    private String taskType;

    @JsonProperty("status")
    private String status;

    @JsonProperty("priority")
    private String priority;

    @JsonProperty("story_points")
    private Integer storyPoints;

    @JsonProperty("assignee")
    private String assignee;

    @JsonProperty("reporter")
    private String reporter;

    @JsonProperty("sprint")
    private String sprint;

    @JsonProperty("fix_version")
    private String fixVersion;

    @JsonProperty("start_date")
    private String startDate;

    @JsonProperty("due_date")
    private String dueDate;

    @JsonProperty("acceptance_criteria")
    private String acceptanceCriteria;

    @JsonProperty("schedule_interval")
    private String scheduleInterval;

    @JsonProperty("jira_id")
    private String jiraId;

    @JsonProperty("jira_url")
    private String jiraUrl;

    @JsonProperty("confidence_score")
    private Double confidenceScore;

    @JsonProperty("gap_report")
    private String gapReport;

    @JsonProperty("source_file_id")
    private String sourceFileId;

    @JsonProperty("task_source")
    private String taskSource;

    @JsonProperty("user_name")
    private String userName;

    @JsonProperty("location")
    private String location;

    @JsonProperty("created_at")
    private String createdAt;

    @JsonProperty("updated_at")
    private String updatedAt;
}
