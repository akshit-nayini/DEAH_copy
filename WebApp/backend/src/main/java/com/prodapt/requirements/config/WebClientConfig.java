package com.prodapt.requirements.config;

import io.netty.channel.ChannelOption;
import io.netty.handler.timeout.ReadTimeoutHandler;
import io.netty.handler.timeout.WriteTimeoutHandler;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;
import java.util.concurrent.TimeUnit;

/**
 * Creates a dedicated {@link WebClient} bean for each remote system:
 *   - Requirements Agent (FastAPI)
 *   - GitHub API
 *   - Google Drive API
 *
 * Each client has its own timeout and base-URL configuration so they can be
 * tuned independently via application.yml / environment variables.
 */
@Configuration
public class WebClientConfig {

    // ── Requirements Agent ────────────────────────────────────────────────────

    @Value("${requirements-agent.base-url}")
    private String agentBaseUrl;

    @Value("${requirements-agent.timeout-seconds:120}")
    private int agentTimeoutSeconds;

    @Value("${requirements-agent.api-key:}")
    private String agentApiKey;

    // ── GitHub ────────────────────────────────────────────────────────────────

    @Value("${github.api-base-url:https://api.github.com}")
    private String githubApiBaseUrl;

    @Value("${github.timeout-seconds:30}")
    private int githubTimeoutSeconds;

    // ── Google Drive ──────────────────────────────────────────────────────────

    @Value("${google-drive.api-base-url:https://www.googleapis.com/drive/v3}")
    private String googleDriveBaseUrl;

    @Value("${google-drive.timeout-seconds:30}")
    private int googleDriveTimeoutSeconds;

    // ── Bean definitions ──────────────────────────────────────────────────────

    /**
     * WebClient pre-configured for the Requirements Agent (FastAPI).
     * Adds the optional API-key header when one is configured.
     */
    @Bean("agentWebClient")
    public WebClient agentWebClient() {
        WebClient.Builder builder = WebClient.builder()
                .baseUrl(agentBaseUrl)
                .clientConnector(buildConnector(agentTimeoutSeconds))
                .defaultHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                .defaultHeader(HttpHeaders.ACCEPT, MediaType.APPLICATION_JSON_VALUE);

        if (agentApiKey != null && !agentApiKey.isBlank()) {
            builder.defaultHeader("X-API-Key", agentApiKey);
        }

        return builder.build();
    }

    /**
     * WebClient for the GitHub REST API.
     * Callers should add "Authorization: Bearer <PAT>" per-request.
     */
    @Bean("githubWebClient")
    public WebClient githubWebClient() {
        return WebClient.builder()
                .baseUrl(githubApiBaseUrl)
                .clientConnector(buildConnector(githubTimeoutSeconds))
                .defaultHeader(HttpHeaders.ACCEPT, "application/vnd.github.v3.raw")
                .defaultHeader("X-GitHub-Api-Version", "2022-11-28")
                .build();
    }

    /**
     * WebClient for the Google Drive API.
     * Callers should add "Authorization: Bearer <OAuth-token>" per-request.
     */
    @Bean("googleDriveWebClient")
    public WebClient googleDriveWebClient() {
        return WebClient.builder()
                .baseUrl(googleDriveBaseUrl)
                .clientConnector(buildConnector(googleDriveTimeoutSeconds))
                .defaultHeader(HttpHeaders.ACCEPT, MediaType.APPLICATION_JSON_VALUE)
                .build();
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private ReactorClientHttpConnector buildConnector(int timeoutSeconds) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 10_000)
                .responseTimeout(Duration.ofSeconds(timeoutSeconds))
                .doOnConnected(conn -> conn
                        .addHandlerLast(new ReadTimeoutHandler(timeoutSeconds, TimeUnit.SECONDS))
                        .addHandlerLast(new WriteTimeoutHandler(10, TimeUnit.SECONDS)));
        return new ReactorClientHttpConnector(httpClient);
    }
}
