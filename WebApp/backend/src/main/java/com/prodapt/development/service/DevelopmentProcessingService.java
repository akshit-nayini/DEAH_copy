package com.prodapt.development.service;

import com.prodapt.development.client.DevelopmentAgentClient;
import com.prodapt.development.exception.DocumentFetchException;
import com.prodapt.development.model.request.CheckpointRequest;
import com.prodapt.development.model.request.DocumentSource;
import com.prodapt.development.model.request.OptimizeReviewRequest;
import com.prodapt.development.model.request.StartDeployRequest;
import com.prodapt.development.model.request.StartDevelopmentRunRequest;
import com.prodapt.development.model.response.DeployRunSummary;
import com.prodapt.development.model.response.OutputsListResponse;
import com.prodapt.development.model.response.OutputsListResponse.RunEntry;
import com.prodapt.development.model.response.RunSummary;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

@Service
@RequiredArgsConstructor
@Slf4j
public class DevelopmentProcessingService {

    private final GitHubDocumentService gitHubDocumentService;
    private final GoogleDriveDocumentService googleDriveDocumentService;
    private final DevelopmentAgentClient agentClient;

    /**
     * Root of the development output directory — matches core/development/output/
     * in the DEAH mono-repo. Override via DEVELOPMENT_OUTPUT_DIR env var.
     */
    @Value("${development.output-dir:core/development/output}")
    private String outputDir;

    // ── Code-gen pipeline ─────────────────────────────────────────────────────

    public RunSummary startRun(StartDevelopmentRunRequest request) {
        log.info("Starting development run: sessionId={}, source={}", request.getSessionId(), request.getDocumentSource());

        String implementationMd;
        String mappingCsv;

        switch (request.getDocumentSource()) {
            case GITHUB -> {
                validatePresent(request.getGithubImplSource(), "github_impl_source is required for GITHUB source");
                validatePresent(request.getGithubMappingSource(), "github_mapping_source is required for GITHUB source");
                implementationMd = gitHubDocumentService.fetchDocument(request.getGithubImplSource());
                mappingCsv = gitHubDocumentService.fetchDocument(request.getGithubMappingSource());
            }
            case GOOGLE_DRIVE -> {
                validatePresent(request.getGoogleDriveImplSource(), "google_drive_impl_source is required for GOOGLE_DRIVE source");
                validatePresent(request.getGoogleDriveMappingSource(), "google_drive_mapping_source is required for GOOGLE_DRIVE source");
                implementationMd = googleDriveDocumentService.fetchDocument(request.getGoogleDriveImplSource());
                mappingCsv = googleDriveDocumentService.fetchDocument(request.getGoogleDriveMappingSource());
            }
            case TICKET -> {
                if (request.getTicketId() == null || request.getTicketId().isBlank()) {
                    throw new DocumentFetchException("ticket_id is required for TICKET source");
                }
                implementationMd = null;
                mappingCsv = null;
            }
            case DIRECT -> {
                if (request.getImplementationMd() == null || request.getImplementationMd().isBlank()) {
                    throw new DocumentFetchException("implementation_md is required for DIRECT source");
                }
                if (request.getMappingCsv() == null || request.getMappingCsv().isBlank()) {
                    throw new DocumentFetchException("mapping_csv is required for DIRECT source");
                }
                implementationMd = request.getImplementationMd();
                mappingCsv = request.getMappingCsv();
            }
            default -> throw new DocumentFetchException("Unsupported document source: " + request.getDocumentSource());
        }

        Map<String, Object> payload = buildAgentPayload(request, implementationMd, mappingCsv);
        RunSummary summary = agentClient.startRun(payload);
        log.info("Development run accepted: requestId={}", summary.getRequestId());
        return summary;
    }

    public RunSummary getRun(String requestId) {
        log.info("Fetching run status: requestId={}", requestId);
        return agentClient.getRun(requestId);
    }

    public RunSummary submitCheckpoint(String requestId, CheckpointRequest decision) {
        log.info("Submitting checkpoint for run {}: decision={}", requestId, decision.getDecision());
        return agentClient.submitCheckpoint(requestId, decision);
    }

    public List<RunSummary> listRuns() {
        return agentClient.listRuns();
    }

    public RunSummary startOptimizeReview(OptimizeReviewRequest request) {
        log.info("Starting optimize-review for {} artifact(s)", request.getArtifacts().size());
        return agentClient.startOptimizeReview(request);
    }

    // ── Deploy ────────────────────────────────────────────────────────────────

    public DeployRunSummary startDeploy(StartDeployRequest request) {
        log.info("Starting deploy: requestId={}, env={}", request.getRequestId(), request.getEnvironment());
        DeployRunSummary summary = agentClient.startDeploy(request);
        log.info("Deploy run accepted: runId={}", summary.getRunId());
        return summary;
    }

    public DeployRunSummary getDeployRun(String runId) {
        log.info("Fetching deploy run: runId={}", runId);
        return agentClient.getDeployRun(runId);
    }

    public List<DeployRunSummary> listDeployRuns() {
        return agentClient.listDeployRuns();
    }

    // ── Outputs ───────────────────────────────────────────────────────────────

    /**
     * Walks {@code core/development/output/} and returns every run directory with
     * its artifact files grouped by type. Mirrors how DesignAgentService.listOutputs()
     * works, but reads from disk rather than calling the Python agent.
     *
     * Hidden directories (name starts with ".") and "git_workspace" are skipped.
     */
    public OutputsListResponse listOutputs() {
        log.info("Listing development outputs from: {}", outputDir);

        Path root = Paths.get(outputDir);
        if (!Files.exists(root) || !Files.isDirectory(root)) {
            log.warn("Development output directory not found: {}", root.toAbsolutePath());
            return OutputsListResponse.builder().runs(List.of()).build();
        }

        List<RunEntry> runs = new ArrayList<>();
        try (Stream<Path> dirs = Files.list(root)) {
            dirs.filter(Files::isDirectory)
                .filter(p -> !p.getFileName().toString().startsWith("."))
                .filter(p -> !p.getFileName().toString().equals("git_workspace"))
                .sorted(Comparator.reverseOrder())
                .forEach(runDir -> {
                    RunEntry entry = RunEntry.builder()
                            .runId(runDir.getFileName().toString())
                            .ddl(listSubDir(runDir.resolve("ddl")))
                            .dml(listSubDir(runDir.resolve("dml")))
                            .sp(listSubDir(runDir.resolve("sp")))
                            .dag(listSubDir(runDir.resolve("dag")))
                            .config(listSubDir(runDir.resolve("config")))
                            .plan(namedFile(runDir, "plan.json"))
                            .review(namedFile(runDir, "REVIEW_REPORT.md"))
                            .manifest(namedFile(runDir, "MANIFEST.json"))
                            .build();
                    runs.add(entry);
                });
        } catch (IOException e) {
            log.error("Error scanning development output directory: {}", e.getMessage(), e);
        }

        return OutputsListResponse.builder().runs(runs).build();
    }

    // ── Private helpers ───────────────────────────────────────────────────────

    private Map<String, Object> buildAgentPayload(StartDevelopmentRunRequest request,
                                                   String implementationMd, String mappingCsv) {
        Map<String, Object> payload = new HashMap<>();
        if (request.getDocumentSource() == DocumentSource.TICKET) {
            payload.put("ticket_id", request.getTicketId());
        } else {
            payload.put("implementation_md", implementationMd);
            payload.put("mapping_csv", mappingCsv);
        }
        payload.put("project_id", nullToEmpty(request.getProjectId()));
        payload.put("dataset_id", nullToEmpty(request.getDatasetId()));
        payload.put("environment", nullToEmpty(request.getEnvironment(), "dev"));
        payload.put("cloud_provider", nullToEmpty(request.getCloudProvider(), "gcp"));
        payload.put("region", nullToEmpty(request.getRegion(), "us-central1"));
        return payload;
    }

    private void validatePresent(Object value, String message) {
        if (value == null) {
            throw new DocumentFetchException(message);
        }
    }

    private String nullToEmpty(String value) {
        return value != null ? value : "";
    }

    private String nullToEmpty(String value, String fallback) {
        return (value != null && !value.isBlank()) ? value : fallback;
    }

    /** Lists filenames (relative: subdir/filename) inside a sub-directory. Empty list if absent. */
    private List<String> listSubDir(Path dir) {
        if (!Files.exists(dir) || !Files.isDirectory(dir)) {
            return List.of();
        }
        try (Stream<Path> files = Files.list(dir)) {
            return files.filter(Files::isRegularFile)
                        .map(p -> dir.getFileName() + "/" + p.getFileName())
                        .sorted()
                        .toList();
        } catch (IOException e) {
            log.warn("Could not list files in {}: {}", dir, e.getMessage());
            return List.of();
        }
    }

    /** Returns a single-element list if the named file exists in runDir, otherwise empty list. */
    private List<String> namedFile(Path runDir, String fileName) {
        return Files.exists(runDir.resolve(fileName)) ? List.of(fileName) : List.of();
    }
}
