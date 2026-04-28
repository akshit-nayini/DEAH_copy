package com.prodapt.development.exception;

public class DocumentFetchException extends RuntimeException {

    public DocumentFetchException(String message) {
        super(message);
    }

    public DocumentFetchException(String message, Throwable cause) {
        super(message, cause);
    }
}
