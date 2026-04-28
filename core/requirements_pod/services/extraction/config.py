import os
from dataclasses import dataclass


@dataclass
class ExtractionConfig:
    chunk_size_tokens: int = 2000
    overlap_tokens: int = 200
    words_per_token: float = 1.3
    max_concurrent: int = 5
    retry_attempts: int = 3
    retry_base_ms: int = 1200
    local_dedup_threshold: float = 0.75
    global_merge_threshold: float = 0.55
    model: str = "claude-sonnet-4-20250514"

    @classmethod
    def from_env(cls) -> "ExtractionConfig":
        """Read overrides from environment variables. Fall back to defaults."""
        obj = cls()
        if v := os.getenv("EXTRACT_CHUNK_SIZE"):
            obj.chunk_size_tokens = int(v)
        if v := os.getenv("EXTRACT_OVERLAP"):
            obj.overlap_tokens = int(v)
        if v := os.getenv("EXTRACT_WORDS_PER_TOKEN"):
            obj.words_per_token = float(v)
        if v := os.getenv("EXTRACT_MAX_CONCURRENT"):
            obj.max_concurrent = int(v)
        if v := os.getenv("EXTRACT_RETRY_ATTEMPTS"):
            obj.retry_attempts = int(v)
        if v := os.getenv("EXTRACT_RETRY_BASE_MS"):
            obj.retry_base_ms = int(v)
        if v := os.getenv("EXTRACT_LOCAL_DEDUP_THRESHOLD"):
            obj.local_dedup_threshold = float(v)
        if v := os.getenv("EXTRACT_GLOBAL_MERGE_THRESHOLD"):
            obj.global_merge_threshold = float(v)
        return obj

    @classmethod
    def from_settings(cls, settings) -> "ExtractionConfig":
        """Build from existing Settings object, with EXTRACT_* env vars taking precedence."""
        obj = cls.from_env()
        # Fall back to existing LLM settings when new env vars are not explicitly set
        if not os.getenv("EXTRACT_CHUNK_SIZE"):
            obj.chunk_size_tokens = settings.LLM_CHUNK_SIZE
        if not os.getenv("EXTRACT_OVERLAP"):
            obj.overlap_tokens = settings.LLM_CHUNK_OVERLAP
        obj.model = settings.LLM_MODEL
        return obj
