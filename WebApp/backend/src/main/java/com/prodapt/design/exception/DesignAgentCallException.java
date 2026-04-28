package com.prodapt.design.exception;

public class DesignAgentCallException extends RuntimeException {

    public DesignAgentCallException(String message) {
        super(message);
    }

    public DesignAgentCallException(String message, Throwable cause) {
        super(message, cause);
    }
}
