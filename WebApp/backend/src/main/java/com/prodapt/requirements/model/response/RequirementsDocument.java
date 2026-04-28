package com.prodapt.requirements.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * Structured requirements document returned by the Requirements Agent.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RequirementsDocument {

    /** Project or feature name extracted from the source document */
    @JsonProperty("project_name")
    private String projectName;

    /** One-paragraph executive summary of the requirements */
    @JsonProperty("executive_summary")
    private String executiveSummary;

    /** Feature type: New Feature, Enhancement, Bug, Spike */
    @JsonProperty("feature_type")
    private String featureType;

    /** Overall priority: P1 – Critical, P2 – High, P3 – Medium, P4 – Low */
    @JsonProperty("priority")
    private String priority;

    /** Ordered list of key requirements extracted from the source */
    @JsonProperty("key_requirements")
    private List<String> keyRequirements;

    /** Top-level acceptance criteria (before per-ticket breakdown) */
    @JsonProperty("acceptance_criteria")
    private List<String> acceptanceCriteria;

    /** Stakeholders identified in the document */
    @JsonProperty("stakeholders")
    private List<String> stakeholders;

    /** Estimated effort band: XS, S, M, L, XL */
    @JsonProperty("estimated_effort")
    private String estimatedEffort;

    /** Assigned team suggested by the agent */
    @JsonProperty("assigned_team")
    private String assignedTeam;

    /** Target sprint suggested by the agent */
    @JsonProperty("sprint_target")
    private String sprintTarget;

    /** Tags / labels suggested for the project */
    @JsonProperty("tags")
    private List<String> tags;

    /** Decisions made (relevant for call-summary flows) */
    @JsonProperty("decisions_made")
    private List<String> decisionsMade;

    /** Action items identified (relevant for call-summary flows) */
    @JsonProperty("action_items")
    private List<String> actionItems;

    /** Full raw markdown text of the requirements document as generated */
    @JsonProperty("raw_document")
    private String rawDocument;
}
