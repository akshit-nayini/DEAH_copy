package com.prodapt.requirements.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.prodapt.requirements.exception.DocumentFetchException;
import com.prodapt.requirements.model.request.GoogleDriveSourceDetails;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

/**
 * Fetches a document from Google Drive using the Drive REST API v3.
 *
 * Flow:
 *   1. Extract the file ID from the supplied URL or use it directly.
 *   2. Call  GET /files/{fileId}/export?mimeType=text/plain  for Google Docs.
 *      Call  GET /files/{fileId}?alt=media                   for uploaded files (MD, TXT, etc.)
 *   3. Return the raw text content.
 */
@Slf4j
@Service
public class GoogleDriveDocumentService {

    private final WebClient googleDriveWebClient;

    public GoogleDriveDocumentService(@Qualifier("googleDriveWebClient") WebClient googleDriveWebClient) {
        this.googleDriveWebClient = googleDriveWebClient;
    }

    /**
     * Fetches the requirements document from Google Drive.
     *
     * @param details Google Drive source configuration from the UI
     * @return raw text content of the document
     * @throws DocumentFetchException if the document cannot be fetched
     */
    public String fetchDocument(GoogleDriveSourceDetails details) {
        String fileId = extractFileId(details.getDriveUrlOrId());

        log.info("Fetching Google Drive document: fileId={}", fileId);

        // Step 1 — determine the MIME type so we know which endpoint to use
        String mimeType = getFileMimeType(fileId, details.getOauthToken());

        // Step 2 — fetch the content
        String content;
        if (isGoogleDoc(mimeType)) {
            content = exportGoogleDoc(fileId, details.getOauthToken());
        } else {
            content = downloadFile(fileId, details.getOauthToken());
        }

        if (content == null || content.isBlank()) {
            throw new DocumentFetchException("Google Drive returned an empty document for file ID: " + fileId);
        }

        log.info("Successfully fetched Google Drive document ({} chars)", content.length());
        return content;
    }

    // ── Private helpers ───────────────────────────────────────────────────────

    /**
     * Resolves a raw file ID or full Google Drive URL to just the file ID.
     *
     * Handles formats:
     *   - Plain file ID:  "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
     *   - Docs edit URL: "https://docs.google.com/document/d/FILE_ID/edit"
     *   - Drive URL:     "https://drive.google.com/file/d/FILE_ID/view"
     */
    public String extractFileId(String input) {
        if (input == null || input.isBlank()) {
            throw new DocumentFetchException("Google Drive URL or file ID must not be blank");
        }
        input = input.trim();

        // Already a plain file ID (no slashes or dots after trimming common URL parts)
        if (!input.contains("/")) {
            return input;
        }

        // Extract from /d/{FILE_ID}/ pattern used by both Docs and Drive URLs
        String[] parts = input.split("/d/");
        if (parts.length >= 2) {
            String afterD = parts[1];
            // Strip anything after the next slash (e.g. "/edit", "/view")
            int slash = afterD.indexOf('/');
            return slash > 0 ? afterD.substring(0, slash) : afterD;
        }

        // Fallback: treat the whole value as a file ID
        return input;
    }

    /**
     * Calls the Drive Files metadata endpoint to retrieve the MIME type of the file.
     */
    private String getFileMimeType(String fileId, String oauthToken) {
        try {
            JsonNode metadata = googleDriveWebClient.get()
                    .uri(uriBuilder -> uriBuilder
                            .path("/files/{fileId}")
                            .queryParam("fields", "mimeType,name")
                            .build(fileId))
                    .headers(h -> h.setBearerAuth(oauthToken))
                    .retrieve()
                    .onStatus(HttpStatus.UNAUTHORIZED::equals, r ->
                            r.bodyToMono(String.class).map(b ->
                                    new DocumentFetchException("Google Drive: OAuth token is invalid or expired.")))
                    .onStatus(HttpStatus.FORBIDDEN::equals, r ->
                            r.bodyToMono(String.class).map(b ->
                                    new DocumentFetchException("Google Drive: access denied. Ensure the token has 'drive.readonly' scope.")))
                    .onStatus(HttpStatus.NOT_FOUND::equals, r ->
                            r.bodyToMono(String.class).map(b ->
                                    new DocumentFetchException("Google Drive: file not found for ID: " + fileId)))
                    .bodyToMono(JsonNode.class)
                    .block();

            if (metadata == null || !metadata.has("mimeType")) {
                throw new DocumentFetchException("Could not determine MIME type for Google Drive file: " + fileId);
            }

            String mimeType = metadata.get("mimeType").asText();
            log.debug("Google Drive file mimeType={}", mimeType);
            return mimeType;

        } catch (DocumentFetchException e) {
            throw e;
        } catch (Exception e) {
            throw new DocumentFetchException("Error retrieving Google Drive file metadata: " + e.getMessage(), e);
        }
    }

    /**
     * Exports a native Google Doc as plain text via the export endpoint.
     */
    private String exportGoogleDoc(String fileId, String oauthToken) {
        try {
            return googleDriveWebClient.get()
                    .uri(uriBuilder -> uriBuilder
                            .path("/files/{fileId}/export")
                            .queryParam("mimeType", "text/plain")
                            .build(fileId))
                    .headers(h -> h.setBearerAuth(oauthToken))
                    .retrieve()
                    .bodyToMono(String.class)
                    .block();
        } catch (WebClientResponseException e) {
            throw new DocumentFetchException(
                    "Failed to export Google Doc " + fileId + ": " + e.getMessage(), e);
        }
    }

    /**
     * Downloads a binary/text file (MD, TXT, PDF, DOCX) using alt=media.
     */
    private String downloadFile(String fileId, String oauthToken) {
        try {
            return googleDriveWebClient.get()
                    .uri(uriBuilder -> uriBuilder
                            .path("/files/{fileId}")
                            .queryParam("alt", "media")
                            .build(fileId))
                    .headers(h -> h.setBearerAuth(oauthToken))
                    .retrieve()
                    .bodyToMono(String.class)
                    .block();
        } catch (WebClientResponseException e) {
            throw new DocumentFetchException(
                    "Failed to download Google Drive file " + fileId + ": " + e.getMessage(), e);
        }
    }

    private boolean isGoogleDoc(String mimeType) {
        return mimeType != null && mimeType.startsWith("application/vnd.google-apps");
    }
}
