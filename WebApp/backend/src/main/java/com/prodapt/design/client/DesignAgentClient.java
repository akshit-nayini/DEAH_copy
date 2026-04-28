package com.prodapt.design.client;

import com.prodapt.design.exception.DesignAgentCallException;
import com.prodapt.design.model.request.*;
import com.prodapt.design.model.response.*;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.util.HashMap;
import java.util.Map;

/**
 * HTTP client for the Design Agent (FastAPI at {@code core/design/api/main.py}).
 *
 * <p>Each method maps 1-to-1 with a FastAPI endpoint:
 * <ul>
 *   <li>{@code POST /requirements/from-jira}</li>
 *   <li>{@code POST /requirements/from-document}</li>
 *   <li>{@code POST /data-model}</li>
 *   <li>{@code POST /architecture}</li>
 *   <li>{@code POST /implementation-steps}</li>
 *   <li>{@code POST /pipeline}</li>
 *   <li>{@code GET  /outputs}</li>
 * </ul>
 */
@Slf4j
@Component
public class DesignAgentClient {

    private final WebClient webClient;

    public DesignAgentClient(@Qualifier("designAgentWebClient") WebClient webClient) {
        this.webClient = webClient;
    }

    // ── Requirements ──────────────────────────────────────────────────────────

    public RequirementsAgentResponse requirementsFromJira(RunRequirementsFromJiraRequest request) {
        log.info("Calling design pod /requirements/from-jira [ticketId={}]", request.getTicketId());

        Map<String, Object> body = new HashMap<>();
        body.put("ticket_id", request.getTicketId());
        body.put("write_back", request.isWriteBack());

        return post("/requirements/from-jira", body, RequirementsAgentResponse.class,
                "requirements/from-jira", request.getTicketId());
    }

    public RequirementsAgentResponse requirementsFromDocument(RunRequirementsFromDocumentRequest request) {
        log.info("Calling design pod /requirements/from-document [documentPath={}]", request.getDocumentPath());

        Map<String, Object> body = Map.of("document_path", request.getDocumentPath());

        return post("/requirements/from-document", body, RequirementsAgentResponse.class,
                "requirements/from-document", request.getDocumentPath());
    }

    // ── Data Model ────────────────────────────────────────────────────────────

    public DataModelAgentResponse dataModel(RunDataModelRequest request) {
        log.info("Calling design pod /data-model [ticketId={}, requirementsPath={}]",
                request.getTicketId(), request.getRequirementsPath());

        Map<String, Object> body = new HashMap<>();
        if (request.getTicketId() != null)         body.put("ticket_id",          request.getTicketId());
        if (request.getRequirementsPath() != null)  body.put("requirements_path",  request.getRequirementsPath());
        if (request.getSchemaPath() != null)        body.put("schema_path",         request.getSchemaPath());

        return post("/data-model", body, DataModelAgentResponse.class,
                "data-model", request.getTicketId());
    }

    // ── Architecture ──────────────────────────────────────────────────────────

    public ArchitectureAgentResponse architecture(RunArchitectureRequest request) {
        log.info("Calling design pod /architecture [ticketId={}, requirementsPath={}]",
                request.getTicketId(), request.getRequirementsPath());

        Map<String, Object> body = new HashMap<>();
        if (request.getTicketId() != null)        body.put("ticket_id",         request.getTicketId());
        if (request.getRequirementsPath() != null) body.put("requirements_path", request.getRequirementsPath());

        return post("/architecture", body, ArchitectureAgentResponse.class,
                "architecture", request.getTicketId());
    }

    // ── Implementation Steps ──────────────────────────────────────────────────

    public ImplStepsAgentResponse implementationSteps(RunImplStepsRequest request) {
        log.info("Calling design pod /implementation-steps [ticketId={}, requestType={}]",
                request.getTicketId(), request.getRequestType());

        Map<String, Object> body = new HashMap<>();
        if (request.getTicketId() != null)        body.put("ticket_id",          request.getTicketId());
        if (request.getRequestType() != null)     body.put("request_type",       request.getRequestType());
        if (request.getProjectName() != null)     body.put("project_name",       request.getProjectName());
        if (request.getArchitecturePath() != null) body.put("architecture_path",  request.getArchitecturePath());
        if (request.getDataModelPath() != null)   body.put("data_model_path",    request.getDataModelPath());
        if (request.getRequirementsPath() != null) body.put("requirements_path",  request.getRequirementsPath());

        return post("/implementation-steps", body, ImplStepsAgentResponse.class,
                "implementation-steps", request.getTicketId());
    }

    // ── Pipeline ──────────────────────────────────────────────────────────────

    public PipelineAgentResponse pipeline(RunPipelineRequest request) {
        log.info("Calling design pod /pipeline [ticketId={}, requestType={}]",
                request.getTicketId(), request.getRequestType());

        Map<String, Object> body = new HashMap<>();
        if (request.getTicketId() != null)        body.put("ticket_id",          request.getTicketId());
        if (request.getRequestType() != null)     body.put("request_type",       request.getRequestType());
        if (request.getProjectName() != null)     body.put("project_name",       request.getProjectName());
        if (request.getRequirementsPath() != null) body.put("requirements_path",  request.getRequirementsPath());
        if (request.getSchemaPath() != null)       body.put("schema_path",         request.getSchemaPath());

        return post("/pipeline", body, PipelineAgentResponse.class,
                "pipeline", request.getTicketId());
    }

    // ── Outputs ───────────────────────────────────────────────────────────────

    public OutputsListResponse listOutputs() {
        log.info("Calling design pod GET /outputs");
        try {
            OutputsListResponse response = webClient.get()
                    .uri("/outputs")
                    .accept(MediaType.APPLICATION_JSON)
                    .retrieve()
                    .onStatus(s -> s.is5xxServerError(),
                            r -> r.bodyToMono(String.class).map(b ->
                                    new DesignAgentCallException("Design pod server error on /outputs: " + b)))
                    .bodyToMono(OutputsListResponse.class)
                    .block();

            if (response == null) {
                throw new DesignAgentCallException("Design pod returned empty response from /outputs.");
            }
            return response;

        } catch (DesignAgentCallException e) {
            throw e;
        } catch (WebClientResponseException e) {
            throw new DesignAgentCallException(
                    "GET /outputs failed HTTP " + e.getStatusCode().value() + ": " + e.getResponseBodyAsString(), e);
        } catch (Exception e) {
            throw new DesignAgentCallException("Unexpected error calling /outputs: " + e.getMessage(), e);
        }
    }

    // ── Private helper ────────────────────────────────────────────────────────

    private <T> T post(String uri, Object body, Class<T> responseType, String endpoint, String identifier) {
        try {
            T response = webClient.post()
                    .uri(uri)
                    .contentType(MediaType.APPLICATION_JSON)
                    .bodyValue(body)
                    .retrieve()
                    .onStatus(HttpStatus.BAD_REQUEST::equals,
                            r -> r.bodyToMono(String.class).map(b ->
                                    new DesignAgentCallException("Bad request to design pod " + endpoint + ": " + b)))
                    .onStatus(HttpStatus.NOT_FOUND::equals,
                            r -> r.bodyToMono(String.class).map(b ->
                                    new DesignAgentCallException("Not found in design pod " + endpoint
                                            + " (ticket/file not yet processed?): " + b)))
                    .onStatus(HttpStatus.UNPROCESSABLE_ENTITY::equals,
                            r -> r.bodyToMono(String.class).map(b ->
                                    new DesignAgentCallException("Validation error from design pod " + endpoint + ": " + b)))
                    .onStatus(s -> s.is5xxServerError(),
                            r -> r.bodyToMono(String.class).map(b ->
                                    new DesignAgentCallException("Design pod server error on " + endpoint + ": " + b)))
                    .bodyToMono(responseType)
                    .block();

            if (response == null) {
                throw new DesignAgentCallException("Design pod returned empty response from " + endpoint + ".");
            }

            log.info("Design pod {} completed [identifier={}]", endpoint, identifier);
            return response;

        } catch (DesignAgentCallException e) {
            throw e;
        } catch (WebClientResponseException e) {
            throw new DesignAgentCallException(
                    endpoint + " failed HTTP " + e.getStatusCode().value() + ": " + e.getResponseBodyAsString(), e);
        } catch (Exception e) {
            String msg = e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName();
            throw new DesignAgentCallException("Unexpected error calling design pod " + endpoint + ": " + msg, e);
        }
    }
}
