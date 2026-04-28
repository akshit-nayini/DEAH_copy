package com.prodapt.development.service;

import com.prodapt.development.exception.DocumentFetchException;
import com.prodapt.development.model.request.GitHubSourceDetails;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;

@Service
@Slf4j
public class GitHubDocumentService {

    private final WebClient webClient;

    public GitHubDocumentService(@Qualifier("devGithubWebClient") WebClient webClient) {
        this.webClient = webClient;
    }

    public String fetchDocument(GitHubSourceDetails details) {
        String branch = (details.getBranch() != null && !details.getBranch().isBlank())
                ? details.getBranch() : "main";

        log.info("Fetching GitHub document: {}/{}/{} @ {}", details.getOrg(), details.getRepo(), details.getFilePath(), branch);

        try {
            WebClient.RequestHeadersSpec<?> request = webClient.get()
                    .uri("/repos/{org}/{repo}/contents/{path}?ref={branch}",
                            details.getOrg(), details.getRepo(), details.getFilePath(), branch);

            if (details.getPatToken() != null && !details.getPatToken().isBlank()) {
                request = ((WebClient.RequestHeadersUriSpec<?>) request)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + details.getPatToken());
            }

            return request
                    .retrieve()
                    .onStatus(HttpStatus.NOT_FOUND::equals,
                            resp -> resp.bodyToMono(String.class).map(body ->
                                    new DocumentFetchException("File not found in GitHub: "
                                            + details.getOrg() + "/" + details.getRepo()
                                            + "/" + details.getFilePath() + " @ " + branch)))
                    .onStatus(status -> status == HttpStatus.UNAUTHORIZED || status == HttpStatus.FORBIDDEN,
                            resp -> resp.bodyToMono(String.class).map(body ->
                                    new DocumentFetchException("GitHub access denied — check PAT token permissions")))
                    .onStatus(status -> status.is5xxServerError(),
                            resp -> resp.bodyToMono(String.class).map(body ->
                                    new DocumentFetchException("GitHub server error: " + body)))
                    .bodyToMono(String.class)
                    .block();
        } catch (DocumentFetchException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new DocumentFetchException("Failed to fetch document from GitHub: " + ex.getMessage(), ex);
        }
    }
}
