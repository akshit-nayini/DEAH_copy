package com.prodapt.requirements.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

/**
 * Generic wrapper for every API response sent back to the Prodapt UI.
 *
 * <pre>
 * {
 *   "success": true,
 *   "session_id": "SES-ABC123",
 *   "timestamp": "2025-04-16T10:00:00Z",
 *   "data": { ... AgentResponse ... },
 *   "error": null
 * }
 * </pre>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ApiResponse<T> {

    @JsonProperty("success")
    private boolean success;

    @JsonProperty("session_id")
    private String sessionId;

    @JsonProperty("timestamp")
    @Builder.Default
    private String timestamp = Instant.now().toString();

    @JsonProperty("data")
    private T data;

    @JsonProperty("error")
    private String error;

    // ── Convenience factories ─────────────────────────────────────────────────

    public static <T> ApiResponse<T> ok(String sessionId, T data) {
        return ApiResponse.<T>builder()
                .success(true)
                .sessionId(sessionId)
                .data(data)
                .build();
    }

    public static <T> ApiResponse<T> error(String sessionId, String errorMessage) {
        return ApiResponse.<T>builder()
                .success(false)
                .sessionId(sessionId)
                .error(errorMessage)
                .build();
    }
}
