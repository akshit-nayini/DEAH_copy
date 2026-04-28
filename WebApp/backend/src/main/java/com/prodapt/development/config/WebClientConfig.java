package com.prodapt.development.config;

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

@Configuration
public class WebClientConfig {

    @Value("${development-agent.base-url}")
    private String agentBaseUrl;

    @Value("${development-agent.timeout-seconds:900}")
    private int agentTimeoutSeconds;

    @Value("${development-agent.api-key:}")
    private String agentApiKey;

    @Value("${github.api-base-url:https://api.github.com}")
    private String githubBaseUrl;

    @Value("${github.timeout-seconds:30}")
    private int githubTimeoutSeconds;

    @Value("${google-drive.api-base-url:https://www.googleapis.com/drive/v3}")
    private String googleDriveBaseUrl;

    @Value("${google-drive.timeout-seconds:30}")
    private int googleDriveTimeoutSeconds;

    @Bean("devAgentWebClient")
    public WebClient devAgentWebClient() {
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

    @Bean("devGithubWebClient")
    public WebClient devGithubWebClient() {
        return WebClient.builder()
                .baseUrl(githubBaseUrl)
                .clientConnector(buildConnector(githubTimeoutSeconds))
                .defaultHeader(HttpHeaders.ACCEPT, "application/vnd.github.v3.raw")
                .defaultHeader("X-GitHub-Api-Version", "2022-11-28")
                .build();
    }

    @Bean("devGoogleDriveWebClient")
    public WebClient devGoogleDriveWebClient() {
        return WebClient.builder()
                .baseUrl(googleDriveBaseUrl)
                .clientConnector(buildConnector(googleDriveTimeoutSeconds))
                .defaultHeader(HttpHeaders.ACCEPT, MediaType.APPLICATION_JSON_VALUE)
                .build();
    }

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
