package com.prodapt.requirements.client;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.prodapt.requirements.exception.AgentCallException;
import com.prodapt.requirements.model.pod.PodFileOut;
import com.prodapt.requirements.model.pod.PodJiraPushResultItem;
import com.prodapt.requirements.model.pod.PodTaskOut;
import com.prodapt.requirements.model.request.AgentProcessRequest;
import com.prodapt.requirements.model.response.JiraPushResultItem;
import com.prodapt.requirements.model.response.AgentResponse;
import com.prodapt.requirements.model.response.JiraTicket;
import com.prodapt.requirements.model.response.RequirementsDocument;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Calls the Requirements Pod (FastAPI) using its two-step API:
 *
 *   1. POST /api/v1/files/upload        — upload document as multipart/form-data
 *   2. POST /api/v1/files/{id}/parse    — trigger AI extraction, returns list[TaskOut]
 */
@Slf4j
@Component
public class RequirementsAgentClient {

    private static final String UPLOAD_ENDPOINT = "/api/v1/files/upload";
    private static final String PARSE_ENDPOINT  = "/api/v1/files/{fileId}/parse";

    private final WebClient agentWebClient;
    private final ObjectMapper objectMapper;

    public RequirementsAgentClient(@Qualifier("agentWebClient") WebClient agentWebClient,
                                   ObjectMapper objectMapper) {
        this.agentWebClient = agentWebClient;
        this.objectMapper = objectMapper;
    }

    public AgentResponse process(AgentProcessRequest request) {
        long start = System.currentTimeMillis();

        log.info("Uploading document to requirements pod [sessionId={}, name={}, length={}]",
                request.getSessionId(),
                request.getDocumentName(),
                request.getDocumentContent() != null ? request.getDocumentContent().length() : 0);

        PodFileOut fileOut = uploadDocument(request);
        log.info("Document uploaded [fileId={}, filename={}]", fileOut.getId(), fileOut.getFilename());

        List<PodTaskOut> tasks = parseFile(fileOut.getId(), request.getSessionId());
        log.info("Parse complete [fileId={}, taskCount={}]", fileOut.getId(), tasks.size());

        return toAgentResponse(tasks, request.getSessionId(), System.currentTimeMillis() - start);
    }

    public List<JiraPushResultItem> pushToJira(List<String> taskIds) {
        log.info("Pushing {} task(s) to Jira via requirements pod", taskIds.size());
        try {
            Map<String, Object> body = Map.of("task_ids", taskIds);
            Map<?, ?> response = agentWebClient.post()
                    .uri("/api/v1/tasks/jira-push")
                    .contentType(MediaType.APPLICATION_JSON)
                    .bodyValue(body)
                    .retrieve()
                    .onStatus(s -> s.is4xxClientError() || s.is5xxServerError(),
                            r -> r.bodyToMono(String.class).map(b ->
                                    new AgentCallException("Jira push failed: " + b)))
                    .bodyToMono(Map.class)
                    .block();

            if (response == null) return List.of();

            List<?> results = (List<?>) response.get("results");
            if (results == null) return List.of();

            return results.stream()
                    .map(item -> objectMapper.convertValue(item, PodJiraPushResultItem.class))
                    .map(r -> JiraPushResultItem.builder()
                            .taskId(r.getTaskId())
                            .success(r.isSuccess())
                            .jiraId(r.getJiraId())
                            .jiraUrl(r.getJiraUrl())
                            .action(r.getAction())
                            .error(r.getError())
                            .build())
                    .collect(Collectors.toList());

        } catch (AgentCallException e) {
            throw e;
        } catch (Exception e) {
            throw new AgentCallException("Unexpected error during Jira push: " + e.getMessage(), e);
        }
    }

    // ── Private helpers ───────────────────────────────────────────────────────

    private PodFileOut uploadDocument(AgentProcessRequest request) {
        String filename = deriveFilename(request.getDocumentName());
        byte[] content;
        if (request.getDocumentBytes() != null && request.getDocumentBytes().length > 0) {
            content = request.getDocumentBytes();
        } else if (request.getDocumentContent() != null) {
            content = request.getDocumentContent().getBytes(StandardCharsets.UTF_8);
        } else {
            content = new byte[0];
        }

        MediaType partMediaType = deriveMediaType(filename);
        MultipartBodyBuilder body = new MultipartBodyBuilder();
        body.part("file", new ByteArrayResource(content) {
            @Override public String getFilename() { return filename; }
        }).contentType(partMediaType);

        if (request.getSessionId() != null) {
            body.part("project_name", request.getSessionId());
        }

        try {
            PodFileOut result = agentWebClient.post()
                    .uri(UPLOAD_ENDPOINT)
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(BodyInserters.fromMultipartData(body.build()))
                    .retrieve()
                    .onStatus(HttpStatus.UNPROCESSABLE_ENTITY::equals,
                            r -> r.bodyToMono(String.class).map(b ->
                                    new AgentCallException("Pod rejected upload (422): " + b)))
                    .onStatus(s -> s.is5xxServerError(),
                            r -> r.bodyToMono(String.class).map(b ->
                                    new AgentCallException("Pod server error on upload: " + b)))
                    .bodyToMono(PodFileOut.class)
                    .block();

            if (result == null || result.getId() == null) {
                throw new AgentCallException("Requirements pod returned empty response on upload.");
            }
            return result;

        } catch (AgentCallException e) {
            throw e;
        } catch (WebClientResponseException e) {
            throw new AgentCallException(
                    "Upload failed HTTP " + e.getStatusCode().value() + ": " + e.getResponseBodyAsString(), e);
        } catch (Exception e) {
            throw new AgentCallException("Unexpected error uploading to requirements pod: " + e.getMessage(), e);
        }
    }

    private List<PodTaskOut> parseFile(String fileId, String sessionId) {
        log.info("Triggering parse [fileId={}, sessionId={}]", fileId, sessionId);
        try {
            List<PodTaskOut> tasks = agentWebClient.post()
                    .uri(PARSE_ENDPOINT, fileId)
                    .contentType(MediaType.APPLICATION_JSON)
                    .retrieve()
                    .onStatus(HttpStatus.NOT_FOUND::equals,
                            r -> r.bodyToMono(String.class).map(b ->
                                    new AgentCallException("File not found in pod (404): fileId=" + fileId)))
                    .onStatus(s -> s.is5xxServerError(),
                            r -> r.bodyToMono(String.class).map(b ->
                                    new AgentCallException("Pod server error on parse: " + b)))
                    .bodyToMono(new ParameterizedTypeReference<List<PodTaskOut>>() {})
                    .block();

            return tasks != null ? tasks : List.of();

        } catch (AgentCallException e) {
            throw e;
        } catch (WebClientResponseException e) {
            throw new AgentCallException(
                    "Parse failed HTTP " + e.getStatusCode().value() + ": " + e.getResponseBodyAsString(), e);
        } catch (Exception e) {
            String msg = e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName();
            throw new AgentCallException("Unexpected error parsing file in requirements pod: " + msg, e);
        }
    }

    private AgentResponse toAgentResponse(List<PodTaskOut> tasks, String sessionId, long durationMs) {
        List<JiraTicket> tickets = tasks.stream()
                .map(t -> JiraTicket.builder()
                        .podTaskId(t.getTaskId())
                        .issueKey(t.getJiraId())
                        .jiraUrl(t.getJiraUrl())
                        .issueType(capitalize(t.getTaskType()))
                        .summary(t.getTaskHeading())
                        .description(t.getDescription())
                        .priority(t.getPriority())
                        .storyPoints(t.getStoryPoints())
                        .acceptanceCriteria(parseAcceptanceCriteria(t.getAcceptanceCriteria()))
                        .sprintTarget(t.getSprint())
                        .build())
                .collect(Collectors.toList());

        RequirementsDocument doc = RequirementsDocument.builder()
                .keyRequirements(tasks.stream()
                        .map(PodTaskOut::getTaskHeading)
                        .collect(Collectors.toList()))
                .build();

        return AgentResponse.builder()
                .sessionId(sessionId)
                .status("success")
                .jiraTickets(tickets)
                .requirementsDocument(doc)
                .processedAt(Instant.now().toString())
                .agentDurationMs(durationMs)
                .build();
    }

    /**
     * The pod stores acceptance_criteria as a JSON-encoded array string e.g.
     * "[\"criterion 1\", \"criterion 2\"]". Parse it back to a List<String>.
     */
    private List<String> parseAcceptanceCriteria(String raw) {
        if (raw == null || raw.isBlank()) return null;
        try {
            return objectMapper.readValue(raw, new TypeReference<List<String>>() {});
        } catch (Exception e) {
            return Collections.singletonList(raw);
        }
    }

    private MediaType deriveMediaType(String filename) {
        if (filename == null) return MediaType.TEXT_PLAIN;
        String lower = filename.toLowerCase();
        if (lower.endsWith(".docx")) return MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.wordprocessingml.document");
        if (lower.endsWith(".pdf"))  return MediaType.APPLICATION_PDF;
        return MediaType.TEXT_PLAIN;
    }

    private String deriveFilename(String documentName) {
        if (documentName == null || documentName.isBlank()) return "requirements.txt";
        String last = documentName.contains("/")
                ? documentName.substring(documentName.lastIndexOf('/') + 1)
                : documentName;
        return last.isBlank() ? "requirements.txt" : last;
    }

    private String capitalize(String s) {
        if (s == null || s.isBlank()) return "Task";
        return Character.toUpperCase(s.charAt(0)) + s.substring(1).toLowerCase();
    }
}
