package com.prodapt.design.service;

import com.prodapt.design.client.DesignAgentClient;
import com.prodapt.design.exception.DesignValidationException;
import com.prodapt.design.model.request.*;
import com.prodapt.design.model.response.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * Orchestrates calls to the Design Agent (FastAPI).
 *
 * <p>This layer is responsible for:
 * <ol>
 *   <li>Request validation beyond what Bean Validation covers (e.g. mutual-exclusion rules).</li>
 *   <li>Delegating to {@link DesignAgentClient}.</li>
 *   <li>Any future cross-cutting logic (auditing, caching, retries).</li>
 * </ol>
 *
 * <p>Request → Response flow per agent:
 * <pre>
 * UI → DesignController → DesignAgentService (validate) → DesignAgentClient → FastAPI
 *                      ←                               ←                   ←
 * </pre>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DesignAgentService {

    private final DesignAgentClient agentClient;

    // ── Requirements ──────────────────────────────────────────────────────────

    public RequirementsAgentResponse runRequirementsFromJira(RunRequirementsFromJiraRequest request) {
        log.info("runRequirementsFromJira [sessionId={}, ticketId={}]",
                request.getSessionId(), request.getTicketId());
        return agentClient.requirementsFromJira(request);
    }

    public RequirementsAgentResponse runRequirementsFromDocument(RunRequirementsFromDocumentRequest request) {
        log.info("runRequirementsFromDocument [sessionId={}, documentPath={}]",
                request.getSessionId(), request.getDocumentPath());
        return agentClient.requirementsFromDocument(request);
    }

    // ── Data Model ────────────────────────────────────────────────────────────

    public DataModelAgentResponse runDataModel(RunDataModelRequest request) {
        validateTicketOrPath(request.getTicketId(), request.getRequirementsPath(), "data-model");
        log.info("runDataModel [sessionId={}, ticketId={}, requirementsPath={}]",
                request.getSessionId(), request.getTicketId(), request.getRequirementsPath());
        return agentClient.dataModel(request);
    }

    // ── Architecture ──────────────────────────────────────────────────────────

    public ArchitectureAgentResponse runArchitecture(RunArchitectureRequest request) {
        validateTicketOrPath(request.getTicketId(), request.getRequirementsPath(), "architecture");
        log.info("runArchitecture [sessionId={}, ticketId={}, requirementsPath={}]",
                request.getSessionId(), request.getTicketId(), request.getRequirementsPath());
        return agentClient.architecture(request);
    }

    // ── Implementation Steps ──────────────────────────────────────────────────

    public ImplStepsAgentResponse runImplementationSteps(RunImplStepsRequest request) {
        if (request.getTicketId() == null) {
            if (request.getRequestType() == null || request.getRequestType().isBlank()) {
                throw new DesignValidationException(
                        "Provide either ticket_id or request_type for implementation-steps.");
            }
            if (request.getProjectName() == null || request.getProjectName().isBlank()) {
                throw new DesignValidationException(
                        "Provide either ticket_id or project_name for implementation-steps.");
            }
        }
        log.info("runImplementationSteps [sessionId={}, ticketId={}, requestType={}]",
                request.getSessionId(), request.getTicketId(), request.getRequestType());
        return agentClient.implementationSteps(request);
    }

    // ── Pipeline ──────────────────────────────────────────────────────────────

    public PipelineAgentResponse runPipeline(RunPipelineRequest request) {
        if (request.getTicketId() == null) {
            if (request.getRequirementsPath() == null || request.getRequirementsPath().isBlank()) {
                throw new DesignValidationException(
                        "Provide either ticket_id or requirements_path for pipeline.");
            }
            if (request.getRequestType() == null || request.getRequestType().isBlank()) {
                throw new DesignValidationException(
                        "Provide either ticket_id or request_type for pipeline.");
            }
            if (request.getProjectName() == null || request.getProjectName().isBlank()) {
                throw new DesignValidationException(
                        "Provide either ticket_id or project_name for pipeline.");
            }
        }
        log.info("runPipeline [sessionId={}, ticketId={}, requestType={}]",
                request.getSessionId(), request.getTicketId(), request.getRequestType());
        return agentClient.pipeline(request);
    }

    // ── Outputs ───────────────────────────────────────────────────────────────

    public OutputsListResponse listOutputs() {
        log.info("listOutputs");
        return agentClient.listOutputs();
    }

    // ── Private helpers ───────────────────────────────────────────────────────

    private void validateTicketOrPath(String ticketId, String path, String agentName) {
        if ((ticketId == null || ticketId.isBlank()) && (path == null || path.isBlank())) {
            throw new DesignValidationException(
                    "Provide either ticket_id or requirements_path for " + agentName + ".");
        }
    }
}
