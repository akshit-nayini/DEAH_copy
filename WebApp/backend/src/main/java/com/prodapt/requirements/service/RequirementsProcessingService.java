package com.prodapt.requirements.service;

import com.prodapt.requirements.client.RequirementsAgentClient;
import com.prodapt.requirements.exception.DocumentFetchException;
import com.prodapt.requirements.model.request.AgentProcessRequest;
import com.prodapt.requirements.model.request.DocumentSource;
import com.prodapt.requirements.model.request.ProcessRequirementsRequest;
import com.prodapt.requirements.model.response.AgentResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * Orchestrates the full requirements-processing pipeline:
 *
 *   1. Validate which document source was requested (GitHub or Google Drive).
 *   2. Fetch the raw document content from the appropriate source.
 *   3. Build the agent request payload.
 *   4. Call the Requirements Agent (FastAPI) and return the two responses:
 *        - JIRA tickets
 *        - Requirements document
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RequirementsProcessingService {

    private final GitHubDocumentService gitHubDocumentService;
    private final GoogleDriveDocumentService googleDriveDocumentService;
    private final RequirementsAgentClient agentClient;

    /**
     * Entry point called by the REST controller.
     *
     * @param request inbound request from the Prodapt UI
     * @return {@link AgentResponse} containing JIRA tickets + requirements document
     */
    public AgentResponse process(ProcessRequirementsRequest request) {
        log.info("Starting requirements processing [sessionId={}, source={}]",
                request.getSessionId(), request.getDocumentSource());

        // ── Step 1: Validate source-specific fields ───────────────────────────
        validateSourceDetails(request);

        // ── Step 2: Fetch the document ────────────────────────────────────────
        DocumentFetchResult fetchResult = fetchDocument(request);

        log.info("Document fetched [sessionId={}, name={}, bytes={}, chars={}]",
                request.getSessionId(), fetchResult.documentName(),
                fetchResult.bytes() != null ? fetchResult.bytes().length : 0,
                fetchResult.content() != null ? fetchResult.content().length() : 0);

        // ── Step 3: Build the agent payload ───────────────────────────────────
        AgentProcessRequest agentRequest = AgentProcessRequest.builder()
                .sessionId(request.getSessionId())
                .documentBytes(fetchResult.bytes())
                .documentContent(fetchResult.content())
                .documentName(fetchResult.documentName())
                .sourceType(request.getDocumentSource().name())
                .additionalContext(request.getAdditionalContext())
                .build();

        // ── Step 4: Call the Requirements Agent ───────────────────────────────
        AgentResponse agentResponse = agentClient.process(agentRequest);

        log.info("Requirements processing complete [sessionId={}, jiraTickets={}, hasDocument={}]",
                request.getSessionId(),
                agentResponse.getJiraTickets() != null ? agentResponse.getJiraTickets().size() : 0,
                agentResponse.getRequirementsDocument() != null);

        return agentResponse;
    }

    // ── Private helpers ───────────────────────────────────────────────────────

    /**
     * Validates that the correct source details object is present
     * for the declared document source.
     */
    private void validateSourceDetails(ProcessRequirementsRequest request) {
        if (request.getDocumentSource() == DocumentSource.GITHUB) {
            if (request.getGithubSource() == null) {
                throw new DocumentFetchException(
                        "document_source is GITHUB but github_source details are missing.");
            }
        } else if (request.getDocumentSource() == DocumentSource.GOOGLE_DRIVE) {
            if (request.getGoogleDriveSource() == null) {
                throw new DocumentFetchException(
                        "document_source is GOOGLE_DRIVE but google_drive_source details are missing.");
            }
        }
    }

    /**
     * Dispatches to the correct fetcher based on the document source
     * and returns both the raw content and a descriptive document name.
     */
    private DocumentFetchResult fetchDocument(ProcessRequirementsRequest request) {
        return switch (request.getDocumentSource()) {
            case GITHUB -> {
                byte[] bytes = gitHubDocumentService.fetchDocument(request.getGithubSource());
                String name = String.format("%s/%s@%s/%s",
                        request.getGithubSource().getOrg(),
                        request.getGithubSource().getRepo(),
                        request.getGithubSource().getBranch() != null
                                ? request.getGithubSource().getBranch() : "main",
                        request.getGithubSource().getFilePath());
                yield new DocumentFetchResult(bytes, null, name);
            }
            case GOOGLE_DRIVE -> {
                String content = googleDriveDocumentService.fetchDocument(request.getGoogleDriveSource());
                String name = "google-drive/" + request.getGoogleDriveSource().getDriveUrlOrId();
                yield new DocumentFetchResult(null, content, name);
            }
        };
    }

    private record DocumentFetchResult(byte[] bytes, String content, String documentName) {}
}
