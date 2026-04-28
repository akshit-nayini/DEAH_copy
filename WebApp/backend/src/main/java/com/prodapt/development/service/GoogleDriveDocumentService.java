package com.prodapt.development.service;

import com.prodapt.development.exception.DocumentFetchException;
import com.prodapt.development.model.request.GoogleDriveSourceDetails;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
@Slf4j
public class GoogleDriveDocumentService {

    private static final Pattern DRIVE_ID_PATTERN =
            Pattern.compile("/(?:d|folders)/([a-zA-Z0-9_-]+)");

    private final WebClient webClient;

    public GoogleDriveDocumentService(@Qualifier("devGoogleDriveWebClient") WebClient webClient) {
        this.webClient = webClient;
    }

    public String fetchDocument(GoogleDriveSourceDetails details) {
        String fileId = extractFileId(details.getDriveUrlOrId());
        log.info("Fetching Google Drive document: fileId={}", fileId);

        try {
            // Determine MIME type to decide export vs. direct download
            Map<?, ?> meta = webClient.get()
                    .uri("/files/{fileId}?fields=mimeType,name", fileId)
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + details.getOauthToken())
                    .retrieve()
                    .onStatus(HttpStatus.UNAUTHORIZED::equals,
                            resp -> resp.bodyToMono(String.class).map(body ->
                                    new DocumentFetchException("Google Drive access denied — check OAuth token")))
                    .onStatus(HttpStatus.FORBIDDEN::equals,
                            resp -> resp.bodyToMono(String.class).map(body ->
                                    new DocumentFetchException("Insufficient Google Drive permissions for file: " + fileId)))
                    .onStatus(HttpStatus.NOT_FOUND::equals,
                            resp -> resp.bodyToMono(String.class).map(body ->
                                    new DocumentFetchException("File not found in Google Drive: " + fileId)))
                    .bodyToMono(Map.class)
                    .block();

            String mimeType = meta != null ? (String) meta.get("mimeType") : "";

            if (mimeType != null && mimeType.startsWith("application/vnd.google-apps")) {
                // Google Workspace document — export as plain text
                return webClient.get()
                        .uri("/files/{fileId}/export?mimeType=text/plain", fileId)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + details.getOauthToken())
                        .retrieve()
                        .onStatus(status -> status.is4xxClientError(),
                                resp -> resp.bodyToMono(String.class).map(body ->
                                        new DocumentFetchException("Failed to export Google Drive file " + fileId + ": " + body)))
                        .bodyToMono(String.class)
                        .block();
            } else {
                // Binary or plain file — download directly
                return webClient.get()
                        .uri("/files/{fileId}?alt=media", fileId)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + details.getOauthToken())
                        .retrieve()
                        .onStatus(status -> status.is4xxClientError(),
                                resp -> resp.bodyToMono(String.class).map(body ->
                                        new DocumentFetchException("Failed to download Google Drive file " + fileId + ": " + body)))
                        .bodyToMono(String.class)
                        .block();
            }
        } catch (DocumentFetchException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new DocumentFetchException("Failed to fetch document from Google Drive: " + ex.getMessage(), ex);
        }
    }

    public String extractFileId(String driveUrlOrId) {
        if (driveUrlOrId == null || driveUrlOrId.isBlank()) {
            throw new DocumentFetchException("Google Drive URL or file ID must not be blank");
        }
        Matcher matcher = DRIVE_ID_PATTERN.matcher(driveUrlOrId);
        if (matcher.find()) {
            return matcher.group(1);
        }
        // Assume it's already a raw file ID
        return driveUrlOrId.trim();
    }
}
