package com.prodapt.requirements.service;

import com.prodapt.requirements.exception.DocumentFetchException;
import com.prodapt.requirements.model.request.GitHubSourceDetails;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

/**
 * Fetches a raw file from a GitHub repository.
 *
 * Uses the GitHub Contents API:
 *   GET /repos/{owner}/{repo}/contents/{path}?ref={branch}
 * with the Accept header set to "application/vnd.github.v3.raw" so GitHub
 * returns the raw file bytes directly (no Base64 decoding needed).
 */
@Slf4j
@Service
public class GitHubDocumentService {

    private final WebClient githubWebClient;

    public GitHubDocumentService(@Qualifier("githubWebClient") WebClient githubWebClient) {
        this.githubWebClient = githubWebClient;
    }

    /**
     * Fetches the requirements document from GitHub and returns raw bytes.
     * Fetching as bytes (not String) preserves binary formats such as DOCX and PDF.
     *
     * @param details GitHub source configuration supplied by the UI
     * @return raw bytes of the file
     * @throws DocumentFetchException if the file cannot be retrieved for any reason
     */
    public byte[] fetchDocument(GitHubSourceDetails details) {
        String branch = (details.getBranch() != null && !details.getBranch().isBlank())
                ? details.getBranch()
                : "main";

        // Strip "blob/{branch}/" prefix in case user pasted the GitHub browser URL path
        String filePath = details.getFilePath() != null ? details.getFilePath() : "";
        String blobPrefix = "blob/" + branch + "/";
        if (filePath.startsWith(blobPrefix)) {
            filePath = filePath.substring(blobPrefix.length());
        }

        // Path: /repos/{org}/{repo}/contents/{filePath}?ref={branch}
        String path = String.format("/repos/%s/%s/contents/%s",
                details.getOrg(), details.getRepo(), filePath);
        final String resolvedFilePath = filePath;

        log.info("Fetching GitHub document: org={}, repo={}, branch={}, path={}",
                details.getOrg(), details.getRepo(), branch, resolvedFilePath);

        try {
            byte[] content = githubWebClient.get()
                    .uri(uriBuilder -> uriBuilder
                            .path(path)
                            .queryParam("ref", branch)
                            .build())
                    .headers(headers -> addAuth(headers, details.getPatToken()))
                    .retrieve()
                    .onStatus(
                            status -> status == HttpStatus.NOT_FOUND,
                            response -> response.bodyToMono(String.class).map(body ->
                                    new DocumentFetchException(
                                            String.format("File not found: %s@%s/%s/%s",
                                                    branch, details.getOrg(), details.getRepo(), resolvedFilePath)))
                    )
                    .onStatus(
                            status -> status == HttpStatus.UNAUTHORIZED || status == HttpStatus.FORBIDDEN,
                            response -> response.bodyToMono(String.class).map(body ->
                                    new DocumentFetchException(
                                            "GitHub access denied. Check your PAT token and repository permissions."))
                    )
                    .onStatus(
                            status -> status.is5xxServerError(),
                            response -> response.bodyToMono(String.class).map(body ->
                                    new DocumentFetchException("GitHub API server error. Please try again later."))
                    )
                    .bodyToMono(byte[].class)
                    .block();

            if (content == null || content.length == 0) {
                throw new DocumentFetchException(
                        "GitHub returned an empty file: " + resolvedFilePath);
            }

            log.info("Successfully fetched GitHub document ({} bytes)", content.length);
            return content;

        } catch (DocumentFetchException e) {
            throw e;
        } catch (WebClientResponseException e) {
            throw new DocumentFetchException(
                    String.format("GitHub API error %d: %s", e.getStatusCode().value(), e.getMessage()), e);
        } catch (Exception e) {
            throw new DocumentFetchException("Unexpected error fetching from GitHub: " + e.getMessage(), e);
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private void addAuth(HttpHeaders headers, String patToken) {
        if (patToken != null && !patToken.isBlank()) {
            headers.setBearerAuth(patToken);
        }
        // If no PAT token is provided, the request proceeds unauthenticated
        // (works for public repositories only)
    }
}
