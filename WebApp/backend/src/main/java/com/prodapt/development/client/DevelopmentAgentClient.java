package com.prodapt.development.client;

import com.prodapt.development.exception.AgentCallException;
import com.prodapt.development.model.request.CheckpointRequest;
import com.prodapt.development.model.request.OptimizeReviewRequest;
import com.prodapt.development.model.request.StartDeployRequest;
import com.prodapt.development.model.response.DeployRunSummary;
import com.prodapt.development.model.response.RunSummary;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.util.List;
import java.util.Map;

@Component
@Slf4j
public class DevelopmentAgentClient {

    private final WebClient webClient;

    @Value("${development-agent.runs-endpoint:/api/v1/runs}")
    private String runsEndpoint;

    @Value("${development-agent.optimize-review-endpoint:/api/v1/optimize-review}")
    private String optimizeReviewEndpoint;

    @Value("${development-agent.deploy-endpoint:/api/v1/deploy}")
    private String deployEndpoint;

    public DevelopmentAgentClient(@Qualifier("devAgentWebClient") WebClient webClient) {
        this.webClient = webClient;
    }

    // ── Code-gen pipeline ─────────────────────────────────────────────────────

    public RunSummary startRun(Map<String, Object> payload) {
        log.info("Forwarding start-run request to development agent");
        try {
            RunSummary summary = webClient.post()
                    .uri(runsEndpoint)
                    .bodyValue(payload)
                    .retrieve()
                    .onStatus(HttpStatus.UNPROCESSABLE_ENTITY::equals,
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Validation error from agent: " + body)))
                    .onStatus(HttpStatus.SERVICE_UNAVAILABLE::equals,
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Development agent unavailable: " + body)))
                    .onStatus(status -> status.is5xxServerError(),
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Agent server error: " + body)))
                    .onStatus(status -> status.is4xxClientError(),
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Agent client error: " + body)))
                    .bodyToMono(RunSummary.class)
                    .block();
            log.info("Run started: requestId={}", summary != null ? summary.getRequestId() : "null");
            return summary;
        } catch (AgentCallException ex) {
            throw ex;
        } catch (WebClientResponseException ex) {
            throw new AgentCallException("Development agent returned HTTP " + ex.getStatusCode() + ": " + ex.getResponseBodyAsString(), ex);
        } catch (Exception ex) {
            throw new AgentCallException("Failed to reach development agent: " + ex.getMessage(), ex);
        }
    }

    public RunSummary getRun(String requestId) {
        log.info("Fetching run status: requestId={}", requestId);
        try {
            return webClient.get()
                    .uri(runsEndpoint + "/{requestId}", requestId)
                    .retrieve()
                    .onStatus(HttpStatus.NOT_FOUND::equals,
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Run not found: " + requestId)))
                    .onStatus(status -> status.is5xxServerError(),
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Agent server error: " + body)))
                    .bodyToMono(RunSummary.class)
                    .block();
        } catch (AgentCallException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new AgentCallException("Failed to fetch run " + requestId + ": " + ex.getMessage(), ex);
        }
    }

    public RunSummary submitCheckpoint(String requestId, CheckpointRequest decision) {
        log.info("Submitting checkpoint decision for run {}: {}", requestId, decision.getDecision());
        try {
            return webClient.post()
                    .uri(runsEndpoint + "/{requestId}/checkpoint", requestId)
                    .bodyValue(decision)
                    .retrieve()
                    .onStatus(HttpStatus.NOT_FOUND::equals,
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Run not found: " + requestId)))
                    .onStatus(HttpStatus.CONFLICT::equals,
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Run is not at a checkpoint: " + body)))
                    .onStatus(status -> status.is5xxServerError(),
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Agent server error: " + body)))
                    .bodyToMono(RunSummary.class)
                    .block();
        } catch (AgentCallException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new AgentCallException("Failed to submit checkpoint for run " + requestId + ": " + ex.getMessage(), ex);
        }
    }

    public List<RunSummary> listRuns() {
        log.info("Listing all development runs");
        try {
            return webClient.get()
                    .uri(runsEndpoint)
                    .retrieve()
                    .onStatus(status -> status.is5xxServerError(),
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Agent server error: " + body)))
                    .bodyToFlux(RunSummary.class)
                    .collectList()
                    .block();
        } catch (AgentCallException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new AgentCallException("Failed to list runs: " + ex.getMessage(), ex);
        }
    }

    public RunSummary startOptimizeReview(OptimizeReviewRequest request) {
        log.info("Forwarding optimize-review request to development agent");
        try {
            return webClient.post()
                    .uri(optimizeReviewEndpoint)
                    .bodyValue(request)
                    .retrieve()
                    .onStatus(HttpStatus.UNPROCESSABLE_ENTITY::equals,
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Validation error from agent: " + body)))
                    .onStatus(status -> status.is5xxServerError(),
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Agent server error: " + body)))
                    .bodyToMono(RunSummary.class)
                    .block();
        } catch (AgentCallException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new AgentCallException("Failed to start optimize-review: " + ex.getMessage(), ex);
        }
    }

    // ── Deploy ────────────────────────────────────────────────────────────────

    public DeployRunSummary startDeploy(StartDeployRequest request) {
        log.info("Forwarding deploy request to development agent: requestId={}", request.getRequestId());
        try {
            DeployRunSummary summary = webClient.post()
                    .uri(deployEndpoint)
                    .bodyValue(request)
                    .retrieve()
                    .onStatus(HttpStatus.BAD_REQUEST::equals,
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Bad deploy request: " + body)))
                    .onStatus(HttpStatus.UNPROCESSABLE_ENTITY::equals,
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Validation error from agent: " + body)))
                    .onStatus(status -> status.is5xxServerError(),
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Agent server error on deploy: " + body)))
                    .bodyToMono(DeployRunSummary.class)
                    .block();
            log.info("Deploy run started: runId={}", summary != null ? summary.getRunId() : "null");
            return summary;
        } catch (AgentCallException ex) {
            throw ex;
        } catch (WebClientResponseException ex) {
            throw new AgentCallException("Deploy call failed HTTP " + ex.getStatusCode() + ": " + ex.getResponseBodyAsString(), ex);
        } catch (Exception ex) {
            throw new AgentCallException("Failed to reach development agent for deploy: " + ex.getMessage(), ex);
        }
    }

    public DeployRunSummary getDeployRun(String runId) {
        log.info("Fetching deploy run status: runId={}", runId);
        try {
            return webClient.get()
                    .uri(deployEndpoint + "/{runId}", runId)
                    .retrieve()
                    .onStatus(HttpStatus.NOT_FOUND::equals,
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Deploy run not found: " + runId)))
                    .onStatus(status -> status.is5xxServerError(),
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Agent server error: " + body)))
                    .bodyToMono(DeployRunSummary.class)
                    .block();
        } catch (AgentCallException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new AgentCallException("Failed to fetch deploy run " + runId + ": " + ex.getMessage(), ex);
        }
    }

    public List<DeployRunSummary> listDeployRuns() {
        log.info("Listing all deploy runs");
        try {
            return webClient.get()
                    .uri(deployEndpoint)
                    .retrieve()
                    .onStatus(status -> status.is5xxServerError(),
                            resp -> resp.bodyToMono(String.class)
                                    .map(body -> new AgentCallException("Agent server error: " + body)))
                    .bodyToFlux(DeployRunSummary.class)
                    .collectList()
                    .block();
        } catch (AgentCallException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new AgentCallException("Failed to list deploy runs: " + ex.getMessage(), ex);
        }
    }
}
