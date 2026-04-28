package com.prodapt.requirements.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * Represents a single JIRA ticket returned by the Requirements Agent.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class JiraTicket {

    /** JIRA issue key, e.g. "PROJ-101" — populated if the agent creates it directly */
    @JsonProperty("issue_key")
    private String issueKey;

    /** Issue type: Epic, Story, Sub-task, Bug, Spike */
    @JsonProperty("issue_type")
    private String issueType;

    /** One-line summary/title of the ticket */
    @JsonProperty("summary")
    private String summary;

    /** Full description in JIRA markdown / ADF format */
    @JsonProperty("description")
    private String description;

    /** Priority: Critical, High, Medium, Low */
    @JsonProperty("priority")
    private String priority;

    /** Story-point estimate */
    @JsonProperty("story_points")
    private Integer storyPoints;

    /** Labels to apply to the ticket */
    @JsonProperty("labels")
    private List<String> labels;

    /** Acceptance criteria lines */
    @JsonProperty("acceptance_criteria")
    private List<String> acceptanceCriteria;

    /** Sprint name or target sprint */
    @JsonProperty("sprint_target")
    private String sprintTarget;

    /** Parent epic key, if this is a story/sub-task */
    @JsonProperty("parent_epic_key")
    private String parentEpicKey;

    /** Internal pod task ID (SRC-NNN) — used by the frontend to call push-to-jira */
    @JsonProperty("pod_task_id")
    private String podTaskId;

    /** Jira browse URL — populated once the ticket has been pushed to Jira */
    @JsonProperty("jira_url")
    private String jiraUrl;
}
