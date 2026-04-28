package com.prodapt.development.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ApiResponse<T> {

    @JsonProperty("success")
    private boolean success;

    @JsonProperty("session_id")
    private String sessionId;

    @Builder.Default
    @JsonProperty("timestamp")
    private String timestamp = Instant.now().toString();

    @JsonProperty("data")
    private T data;

    @JsonProperty("error")
    private String error;

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
