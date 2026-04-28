package com.prodapt.development.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * Response from {@code GET /api/v1/development/outputs}.
 *
 * <p>Lists all output runs found under {@code core/development/output/},
 * each with its artifact files grouped by type — matching the folder structure
 * the Python agent writes:
 *
 * <pre>
 * core/development/output/
 *   SCRUM-149/
 *     ddl/      ← CREATE TABLE SQL
 *     dml/      ← merge / insert SQL
 *     sp/       ← stored procedures
 *     dag/      ← Airflow DAG Python files
 *     config/   ← pipeline_config.py
 *     plan.json
 *     REVIEW_REPORT.md
 *     MANIFEST.json
 * </pre>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OutputsListResponse {

    @JsonProperty("runs")
    private List<RunEntry> runs;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class RunEntry {

        /** Folder name under output/ — ticket ID or UUID */
        @JsonProperty("run_id")
        private String runId;

        @JsonProperty("ddl")
        private List<String> ddl;

        @JsonProperty("dml")
        private List<String> dml;

        @JsonProperty("sp")
        private List<String> sp;

        @JsonProperty("dag")
        private List<String> dag;

        @JsonProperty("config")
        private List<String> config;

        @JsonProperty("plan")
        private List<String> plan;

        @JsonProperty("review")
        private List<String> review;

        @JsonProperty("manifest")
        private List<String> manifest;
    }
}
