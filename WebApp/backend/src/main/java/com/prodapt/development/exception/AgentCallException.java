package com.prodapt.development.exception;

public class AgentCallException extends RuntimeException {

    public AgentCallException(String message) {
        super(message);
    }

    public AgentCallException(String message, Throwable cause) {
        super(message, cause);
    }
}
