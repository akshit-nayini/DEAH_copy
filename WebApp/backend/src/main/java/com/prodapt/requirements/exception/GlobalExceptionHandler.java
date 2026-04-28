package com.prodapt.requirements.exception;

import com.prodapt.requirements.model.response.ApiResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.stream.Collectors;

/**
 * Centralised exception handling — translates every exception into a
 * consistent {@link ApiResponse} envelope so the frontend always gets
 * the same shape, even on errors.
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    /**
     * Validation errors from @Valid on request bodies.
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResponse<Void>> handleValidation(MethodArgumentNotValidException ex) {
        String details = ex.getBindingResult().getFieldErrors().stream()
                .map(FieldError::getDefaultMessage)
                .collect(Collectors.joining("; "));
        log.warn("Validation failed: {}", details);
        return ResponseEntity
                .badRequest()
                .body(ApiResponse.error(null, "Validation error: " + details));
    }

    /**
     * Failure fetching the document from GitHub / Google Drive.
     */
    @ExceptionHandler(DocumentFetchException.class)
    public ResponseEntity<ApiResponse<Void>> handleDocumentFetch(DocumentFetchException ex) {
        log.error("Document fetch failed: {}", ex.getMessage());
        return ResponseEntity
                .status(HttpStatus.BAD_GATEWAY)
                .body(ApiResponse.error(null, "Failed to fetch document: " + ex.getMessage()));
    }

    /**
     * Failure communicating with the Requirements Agent.
     */
    @ExceptionHandler(AgentCallException.class)
    public ResponseEntity<ApiResponse<Void>> handleAgentCall(AgentCallException ex) {
        log.error("Requirements Agent call failed: {}", ex.getMessage());
        return ResponseEntity
                .status(HttpStatus.BAD_GATEWAY)
                .body(ApiResponse.error(null, "Requirements Agent error: " + ex.getMessage()));
    }

    /**
     * Catch-all for anything unexpected.
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleGeneral(Exception ex) {
        log.error("Unhandled exception: ", ex);
        return ResponseEntity
                .status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ApiResponse.error(null, "An unexpected error occurred. Please try again."));
    }
}
