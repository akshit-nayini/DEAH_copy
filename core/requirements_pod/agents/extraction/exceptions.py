"""Custom exceptions for the extraction pipeline."""


class LLMAuthError(RuntimeError):
    """Raised when the LLM API rejects the request due to an invalid or missing API key (HTTP 401)."""


class LLMQuotaError(RuntimeError):
    """Raised when the LLM API quota or credit balance is exhausted, or the rate limit persists after all retries."""
