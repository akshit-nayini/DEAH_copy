package com.prodapt.development.controller;

import com.prodapt.development.model.request.CheckpointRequest;
import com.prodapt.development.model.request.OptimizeReviewRequest;
import com.prodapt.development.model.request.StartDeployRequest;
import com.prodapt.development.model.request.StartDevelopmentRunRequest;
import com.prodapt.development.model.response.ApiResponse;
import com.prodapt.development.model.response.DeployRunSummary;
import com.prodapt.development.model.response.OutputsListResponse;
import com.prodapt.development.model.response.RunSummary;
import com.prodapt.development.service.DevelopmentProcessingService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * REST controller for the Development module.
 *
 * <pre>
 * Code-gen pipeline
 *   POST  /api/v1/development/runs                        start pipeline run
 *   GET   /api/v1/development/runs/{requestId}            poll run status
 *   POST  /api/v1/development/runs/{requestId}/checkpoint submit checkpoint decision
 *   GET   /api/v1/development/runs                        list all runs
 *   POST  /api/v1/development/optimize-review             Mode 2: optimize existing artifacts
 *
 * Deployment
 *   POST  /api/v1/development/deploy                      trigger GCP deployment
 *   GET   /api/v1/development/deploy/{runId}              get deploy run status
 *   GET   /api/v1/development/deploy                      list all deploy runs
 *
 * Outputs
 *   GET   /api/v1/development/outputs                     list generated files from core/development/output/
 *
 * Health
 *   GET   /api/v1/development/health
 * </pre>
 */
@RestController
@RequestMapping("/api/v1/development")
@RequiredArgsConstructor
@Slf4j
public class DevelopmentController {

    private final DevelopmentProcessingService processingService;

    // ── Code-gen pipeline ─────────────────────────────────────────────────────

    @PostMapping("/runs")
    public ResponseEntity<ApiResponse<RunSummary>> startRun(
            @Valid @RequestBody StartDevelopmentRunRequest request) {
        log.info("POST /api/v1/development/runs — sessionId={}, source={}",
                request.getSessionId(), request.getDocumentSource());
        RunSummary summary = processingService.startRun(request);
        return ResponseEntity.accepted()
                .body(ApiResponse.ok(request.getSessionId(), summary));
    }

    @GetMapping("/runs/{requestId}")
    public ResponseEntity<ApiResponse<RunSummary>> getRun(@PathVariable String requestId) {
        log.info("GET /api/v1/development/runs/{}", requestId);
        RunSummary summary = processingService.getRun(requestId);
        return ResponseEntity.ok(ApiResponse.ok(requestId, summary));
    }

    /**
     * Submit a human decision at a checkpoint.
     * decisions: approve | revise | abort | deploy (CP3 only) | skip (CP3 only)
     */
    @PostMapping("/runs/{requestId}/checkpoint")
    public ResponseEntity<ApiResponse<RunSummary>> submitCheckpoint(
            @PathVariable String requestId,
            @Valid @RequestBody CheckpointRequest decision) {
        log.info("POST /api/v1/development/runs/{}/checkpoint — decision={}",
                requestId, decision.getDecision());
        RunSummary summary = processingService.submitCheckpoint(requestId, decision);
        return ResponseEntity.ok(ApiResponse.ok(requestId, summary));
    }

    @GetMapping("/runs")
    public ResponseEntity<ApiResponse<List<RunSummary>>> listRuns() {
        log.info("GET /api/v1/development/runs");
        List<RunSummary> runs = processingService.listRuns();
        return ResponseEntity.ok(ApiResponse.ok(null, runs));
    }

    @PostMapping("/optimize-review")
    public ResponseEntity<ApiResponse<RunSummary>> optimizeReview(
            @Valid @RequestBody OptimizeReviewRequest request) {
        log.info("POST /api/v1/development/optimize-review — {} artifact(s)",
                request.getArtifacts().size());
        RunSummary summary = processingService.startOptimizeReview(request);
        return ResponseEntity.accepted()
                .body(ApiResponse.ok(null, summary));
    }

    // ── Deployment ────────────────────────────────────────────────────────────

    @PostMapping("/deploy")
    public ResponseEntity<ApiResponse<DeployRunSummary>> startDeploy(
            @Valid @RequestBody StartDeployRequest request) {
        log.info("POST /api/v1/development/deploy — requestId={}, env={}",
                request.getRequestId(), request.getEnvironment());
        DeployRunSummary summary = processingService.startDeploy(request);
        return ResponseEntity.accepted()
                .body(ApiResponse.ok(null, summary));
    }

    @GetMapping("/deploy/{runId}")
    public ResponseEntity<ApiResponse<DeployRunSummary>> getDeployRun(@PathVariable String runId) {
        log.info("GET /api/v1/development/deploy/{}", runId);
        DeployRunSummary summary = processingService.getDeployRun(runId);
        return ResponseEntity.ok(ApiResponse.ok(runId, summary));
    }

    @GetMapping("/deploy")
    public ResponseEntity<ApiResponse<List<DeployRunSummary>>> listDeployRuns() {
        log.info("GET /api/v1/development/deploy");
        List<DeployRunSummary> runs = processingService.listDeployRuns();
        return ResponseEntity.ok(ApiResponse.ok(null, runs));
    }

    // ── Outputs ───────────────────────────────────────────────────────────────

    /**
     * Lists all artifact files from core/development/output/, grouped by run and type.
     * Mirrors GET /api/v1/design/outputs from the Design module.
     */
    @GetMapping("/outputs")
    public ResponseEntity<ApiResponse<OutputsListResponse>> listOutputs() {
        log.info("GET /api/v1/development/outputs");
        OutputsListResponse response = processingService.listOutputs();
        return ResponseEntity.ok(ApiResponse.ok("outputs", response));
    }

    // ── Health ────────────────────────────────────────────────────────────────

    @GetMapping("/health")
    public ResponseEntity<ApiResponse<String>> health() {
        return ResponseEntity.ok(ApiResponse.ok(null, "Development Pod is running"));
    }
}
