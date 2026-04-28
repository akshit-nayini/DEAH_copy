package com.prodapt.design.config;

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
 * Creates a {@link WebClient} bean pre-configured for the Design Agent (FastAPI).
 *
 * <p>The timeout is intentionally generous (default 600 s) because the design
 * agents invoke Claude and can take several minutes per run.
 */
@Configuration
public class DesignWebClientConfig {

    @Value("${design-agent.base-url:http://localhost:8000}")
    private String agentBaseUrl;

    @Value("${design-agent.timeout-seconds:600}")
    private int agentTimeoutSeconds;

    @Value("${design-agent.api-key:}")
    private String agentApiKey;

    @Bean("designAgentWebClient")
    public WebClient designAgentWebClient() {
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

    private ReactorClientHttpConnector buildConnector(int timeoutSeconds) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 10_000)
                .responseTimeout(Duration.ofSeconds(timeoutSeconds))
                .doOnConnected(conn -> conn
                        .addHandlerLast(new ReadTimeoutHandler(timeoutSeconds, TimeUnit.SECONDS))
                        .addHandlerLast(new WriteTimeoutHandler(30, TimeUnit.SECONDS)));
        return new ReactorClientHttpConnector(httpClient);
    }
}
