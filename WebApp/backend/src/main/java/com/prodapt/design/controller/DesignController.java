package com.prodapt.design.controller;

import com.prodapt.design.model.request.*;
import com.prodapt.design.model.response.*;
import com.prodapt.design.service.DesignAgentService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * REST controller for the Design module.
 *
 * <pre>
 * ┌──────────────────────────────────────────────────────────────────────────┐
 * │  POST /api/v1/design/requirements/from-jira                              │
 * │     Run the Requirements agent from a Jira ticket.                       │
 * │                                                                          │
 * │  POST /api/v1/design/requirements/from-document                          │
 * │     Run the Requirements agent from a document file (server-side path).  │
 * │                                                                          │
 * │  POST /api/v1/design/data-model                                          │
 * │     Run the Data Model agent (ticket_id or requirements_path).           │
 * │                                                                          │
 * │  POST /api/v1/design/architecture                                        │
 * │     Run the Architecture agent (ticket_id or requirements_path).         │
 * │                                                                          │
 * │  POST /api/v1/design/implementation-steps                                │
 * │     Run the Implementation Steps agent (ticket_id or explicit inputs).   │
 * │                                                                          │
 * │  POST /api/v1/design/pipeline                                            │
 * │     Run the full Design pipeline (Data Model → Architecture →            │
 * │     mermaid2drawio → Implementation Steps).                              │
 * │                                                                          │
 * │  GET  /api/v1/design/outputs                                             │
 * │     List all output files produced by the agents (newest first).         │
 * │                                                                          │
 * │  GET  /api/v1/design/health                                              │
 * │     Liveness probe for the Design controller.                            │
 * └──────────────────────────────────────────────────────────────────────────┘
 * </pre>
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/design")
@RequiredArgsConstructor
public class DesignController {

    private final DesignAgentService designAgentService;

    // ── Requirements ──────────────────────────────────────────────────────────

    /**
     * Run the Requirements agent from a Jira ticket.
     *
     * <p>Request body:
     * <pre>
     * {
     *   "session_id": "SES-ABC123",
     *   "ticket_id":  "SCRUM-5",
     *   "write_back": false
     * }
     * </pre>
     */
    @PostMapping("/requirements/from-jira")
    public ResponseEntity<ApiResponse<RequirementsAgentResponse>> requirementsFromJira(
            @Valid @RequestBody RunRequirementsFromJiraRequest request) {

        log.info("POST /api/v1/design/requirements/from-jira [sessionId={}, ticketId={}]",
                request.getSessionId(), request.getTicketId());

        RequirementsAgentResponse result = designAgentService.runRequirementsFromJira(request);
        return ResponseEntity.ok(ApiResponse.ok(request.getSessionId(), result));
    }

    /**
     * Run the Requirements agent from a server-side document file.
     *
     * <p>Request body:
     * <pre>
     * {
     *   "session_id":    "SES-ABC123",
     *   "document_path": "requirements_gathering/requirements_template.txt"
     * }
     * </pre>
     */
    @PostMapping("/requirements/from-document")
    public ResponseEntity<ApiResponse<RequirementsAgentResponse>> requirementsFromDocument(
            @Valid @RequestBody RunRequirementsFromDocumentRequest request) {

        log.info("POST /api/v1/design/requirements/from-document [sessionId={}, documentPath={}]",
                request.getSessionId(), request.getDocumentPath());

        RequirementsAgentResponse result = designAgentService.runRequirementsFromDocument(request);
        return ResponseEntity.ok(ApiResponse.ok(request.getSessionId(), result));
    }

    // ── Data Model ────────────────────────────────────────────────────────────

    /**
     * Run the Data Model agent.
     *
     * <p>Request body (ticket):
     * <pre>
     * { "session_id": "SES-ABC123", "ticket_id": "SCRUM-5" }
     * </pre>
     *
     * <p>Request body (explicit path):
     * <pre>
     * {
     *   "session_id":        "SES-ABC123",
     *   "requirements_path": "requirements_gathering/output/req_SCRUM-5_....json",
     *   "schema_path":       "data_model/sample_input/table_schema.csv"
     * }
     * </pre>
     */
    @PostMapping("/data-model")
    public ResponseEntity<ApiResponse<DataModelAgentResponse>> dataModel(
            @Valid @RequestBody RunDataModelRequest request) {

        log.info("POST /api/v1/design/data-model [sessionId={}, ticketId={}]",
                request.getSessionId(), request.getTicketId());

        DataModelAgentResponse result = designAgentService.runDataModel(request);
        return ResponseEntity.ok(ApiResponse.ok(request.getSessionId(), result));
    }

    // ── Architecture ──────────────────────────────────────────────────────────

    /**
     * Run the Architecture agent.
     *
     * <p>Request body (ticket):
     * <pre>
     * { "session_id": "SES-ABC123", "ticket_id": "SCRUM-5" }
     * </pre>
     *
     * <p>Request body (explicit path):
     * <pre>
     * {
     *   "session_id":        "SES-ABC123",
     *   "requirements_path": "requirements_gathering/output/req_SCRUM-5_....json"
     * }
     * </pre>
     */
    @PostMapping("/architecture")
    public ResponseEntity<ApiResponse<ArchitectureAgentResponse>> architecture(
            @Valid @RequestBody RunArchitectureRequest request) {

        log.info("POST /api/v1/design/architecture [sessionId={}, ticketId={}]",
                request.getSessionId(), request.getTicketId());

        ArchitectureAgentResponse result = designAgentService.runArchitecture(request);
        return ResponseEntity.ok(ApiResponse.ok(request.getSessionId(), result));
    }

    // ── Implementation Steps ──────────────────────────────────────────────────

    /**
     * Run the Implementation Steps agent.
     *
     * <p>Request body (ticket — auto-resolves all inputs):
     * <pre>
     * { "session_id": "SES-ABC123", "ticket_id": "SCRUM-5" }
     * </pre>
     *
     * <p>Request body (explicit — new development):
     * <pre>
     * {
     *   "session_id":        "SES-ABC123",
     *   "request_type":      "new development",
     *   "project_name":      "My Project",
     *   "architecture_path": "architecture/outputs/arc_..._summary.json",
     *   "data_model_path":   "data_model/output/model_..._summary.json"
     * }
     * </pre>
     */
    @PostMapping("/implementation-steps")
    public ResponseEntity<ApiResponse<ImplStepsAgentResponse>> implementationSteps(
            @Valid @RequestBody RunImplStepsRequest request) {

        log.info("POST /api/v1/design/implementation-steps [sessionId={}, ticketId={}, requestType={}]",
                request.getSessionId(), request.getTicketId(), request.getRequestType());

        ImplStepsAgentResponse result = designAgentService.runImplementationSteps(request);
        return ResponseEntity.ok(ApiResponse.ok(request.getSessionId(), result));
    }

    // ── Pipeline ──────────────────────────────────────────────────────────────

    /**
     * Run the full Design pipeline.
     *
     * <p>Request body (ticket — recommended):
     * <pre>
     * { "session_id": "SES-ABC123", "ticket_id": "SCRUM-5" }
     * </pre>
     *
     * <p>Request body (explicit):
     * <pre>
     * {
     *   "session_id":        "SES-ABC123",
     *   "request_type":      "new development",
     *   "project_name":      "My Project",
     *   "requirements_path": "requirements_gathering/output/req_SCRUM-5_....json",
     *   "schema_path":       "data_model/sample_input/table_schema.csv"
     * }
     * </pre>
     */
    @PostMapping("/pipeline")
    public ResponseEntity<ApiResponse<PipelineAgentResponse>> pipeline(
            @Valid @RequestBody RunPipelineRequest request) {

        log.info("POST /api/v1/design/pipeline [sessionId={}, ticketId={}, requestType={}]",
                request.getSessionId(), request.getTicketId(), request.getRequestType());

        PipelineAgentResponse result = designAgentService.runPipeline(request);
        return ResponseEntity.ok(ApiResponse.ok(request.getSessionId(), result));
    }

    // ── Outputs ───────────────────────────────────────────────────────────────

    /**
     * List all output files produced by the Design agents, grouped by agent and type,
     * newest first.
     */
    @GetMapping("/outputs")
    public ResponseEntity<ApiResponse<OutputsListResponse>> outputs() {
        log.info("GET /api/v1/design/outputs");
        OutputsListResponse result = designAgentService.listOutputs();
        return ResponseEntity.ok(ApiResponse.ok("outputs", result));
    }

    // ── Health ────────────────────────────────────────────────────────────────

    @GetMapping("/health")
    public ResponseEntity<ApiResponse<String>> health() {
        return ResponseEntity.ok(ApiResponse.ok("system", "Design module is up"));
    }
}
