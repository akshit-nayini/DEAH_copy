package com.prodapt.requirements.controller;

import com.prodapt.requirements.client.RequirementsAgentClient;
import com.prodapt.requirements.model.request.JiraPushRequest;
import com.prodapt.requirements.model.request.ProcessRequirementsRequest;
import com.prodapt.requirements.model.response.AgentResponse;
import com.prodapt.requirements.model.response.ApiResponse;
import com.prodapt.requirements.model.response.JiraPushResultItem;
import com.prodapt.requirements.service.RequirementsProcessingService;

import java.util.List;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * REST controller for the Requirements module.
 *
 * ┌─────────────────────────────────────────────────────────────────┐
 * │  POST /api/v1/requirements/process                              │
 * │     Accepts a GitHub or Google Drive document reference,        │
 * │     fetches the document, forwards it to the Requirements Agent │
 * │     and returns two payloads:                                   │
 * │       1. jira_tickets           (list of JIRA tickets)          │
 * │       2. requirements_document  (structured requirements doc)   │
 * │                                                                 │
 * │  GET  /api/v1/requirements/health                               │
 * │     Quick liveness probe for the controller layer.              │
 * └─────────────────────────────────────────────────────────────────┘
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/requirements")
@RequiredArgsConstructor
public class RequirementsController {

    private final RequirementsProcessingService processingService;
    private final RequirementsAgentClient agentClient;

    // ── Process ───────────────────────────────────────────────────────────────

    /**
     * Main endpoint: receive a document reference, call the Requirements Agent,
     * and return JIRA tickets + requirements document.
     *
     * <p>Request body example (GitHub):
     * <pre>
     * {
     *   "session_id": "SES-ABC123",
     *   "document_source": "GITHUB",
     *   "github_source": {
     *     "org": "my-org",
     *     "repo": "my-repo",
     *     "branch": "main",
     *     "file_path": "docs/requirements.md",
     *     "pat_token": "ghp_xxx"
     *   },
     *   "additional_context": "Sprint 24, Platform team"
     * }
     * </pre>
     *
     * <p>Request body example (Google Drive):
     * <pre>
     * {
     *   "session_id": "SES-ABC123",
     *   "document_source": "GOOGLE_DRIVE",
     *   "google_drive_source": {
     *     "drive_url_or_id": "https://docs.google.com/document/d/FILE_ID/edit",
     *     "oauth_token": "ya29.xxx"
     *   }
     * }
     * </pre>
     *
     * <p>Response:
     * <pre>
     * {
     *   "success": true,
     *   "session_id": "SES-ABC123",
     *   "timestamp": "2025-04-16T10:00:00Z",
     *   "data": {
     *     "jira_tickets": [ ... ],
     *     "requirements_document": { ... }
     *   }
     * }
     * </pre>
     */
    @PostMapping("/process")
    public ResponseEntity<ApiResponse<AgentResponse>> process(
            @Valid @RequestBody ProcessRequirementsRequest request) {

        log.info("POST /api/v1/requirements/process [sessionId={}, source={}]",
                request.getSessionId(), request.getDocumentSource());

        AgentResponse agentResponse = processingService.process(request);

        return ResponseEntity.ok(
                ApiResponse.ok(request.getSessionId(), agentResponse));
    }

    // ── Push to Jira ──────────────────────────────────────────────────────────

    @PostMapping("/push-to-jira")
    public ResponseEntity<ApiResponse<List<JiraPushResultItem>>> pushToJira(
            @RequestBody JiraPushRequest request) {

        log.info("POST /api/v1/requirements/push-to-jira [taskCount={}]",
                request.getTaskIds() != null ? request.getTaskIds().size() : 0);

        List<JiraPushResultItem> results = agentClient.pushToJira(request.getTaskIds());
        return ResponseEntity.ok(ApiResponse.ok("push-to-jira", results));
    }

    // ── Health ────────────────────────────────────────────────────────────────

    /**
     * Simple liveness check for the Requirements controller.
     * The full health endpoint is at /actuator/health.
     */
    @GetMapping("/health")
    public ResponseEntity<ApiResponse<String>> health() {
        return ResponseEntity.ok(ApiResponse.ok("system", "Requirements module is up"));
    }
}
