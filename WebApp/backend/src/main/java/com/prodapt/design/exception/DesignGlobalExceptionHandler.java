package com.prodapt.design.exception;

import com.prodapt.design.model.response.ApiResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.stream.Collectors;

/**
 * Centralised exception handling for the Design module.
 * Scoped to design controllers only to avoid conflicts with the
 * Requirements module's GlobalExceptionHandler.
 */
@Slf4j
@RestControllerAdvice(basePackages = "com.prodapt.design.controller")
public class DesignGlobalExceptionHandler {

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResponse<Void>> handleValidation(MethodArgumentNotValidException ex) {
        String details = ex.getBindingResult().getFieldErrors().stream()
                .map(FieldError::getDefaultMessage)
                .collect(Collectors.joining("; "));
        log.warn("Design validation failed: {}", details);
        return ResponseEntity
                .badRequest()
                .body(ApiResponse.error(null, "Validation error: " + details));
    }

    @ExceptionHandler(DesignValidationException.class)
    public ResponseEntity<ApiResponse<Void>> handleDesignValidation(DesignValidationException ex) {
        log.warn("Design request validation failed: {}", ex.getMessage());
        return ResponseEntity
                .badRequest()
                .body(ApiResponse.error(null, ex.getMessage()));
    }

    @ExceptionHandler(DesignAgentCallException.class)
    public ResponseEntity<ApiResponse<Void>> handleAgentCall(DesignAgentCallException ex) {
        log.error("Design Agent call failed: {}", ex.getMessage());
        return ResponseEntity
                .status(HttpStatus.BAD_GATEWAY)
                .body(ApiResponse.error(null, "Design Agent error: " + ex.getMessage()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleGeneral(Exception ex) {
        log.error("Unhandled exception in Design module: ", ex);
        return ResponseEntity
                .status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ApiResponse.error(null, "An unexpected error occurred. Please try again."));
    }
}
