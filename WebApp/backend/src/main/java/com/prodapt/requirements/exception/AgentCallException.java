package com.prodapt.requirements.exception;

/**
 * Thrown when the call to the Requirements Agent (FastAPI) fails.
 */
public class AgentCallException extends RuntimeException {

    public AgentCallException(String message) {
        super(message);
    }

    public AgentCallException(String message, Throwable cause) {
        super(message, cause);
    }
}
