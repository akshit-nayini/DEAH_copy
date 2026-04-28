package com.prodapt.requirements.exception;

/**
 * Thrown when the document cannot be fetched from GitHub or Google Drive.
 */
public class DocumentFetchException extends RuntimeException {

    public DocumentFetchException(String message) {
        super(message);
    }

    public DocumentFetchException(String message, Throwable cause) {
        super(message, cause);
    }
}
