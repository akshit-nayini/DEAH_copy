"""Stage 2 — Token-aware chunker that splits text into overlapping sentence windows."""
import re
from dataclasses import dataclass

from .config import ExtractionConfig

_SENTENCE_RE = re.compile(r'[^.!?\n]+[.!?\n]+|[^.!?\n]+')


@dataclass
class Chunk:
    text: str
    file_index: int   # index of the source document (0-based)
    chunk_index: int  # position within the document


def chunk_text(text: str, file_index: int, config: ExtractionConfig) -> list[Chunk]:
    """Split text into overlapping sentence-aware windows."""
    sentences = _SENTENCE_RE.findall(text)

    target_words = int(config.chunk_size_tokens * config.words_per_token)
    overlap_words = int(config.overlap_tokens * config.words_per_token)

    chunks: list[Chunk] = []
    current_words: list[str] = []
    chunk_idx = 0

    for sentence in sentences:
        current_words.extend(sentence.split())

        if len(current_words) >= target_words:
            chunk_str = " ".join(current_words)
            if len(chunk_str) >= 20:
                chunks.append(Chunk(text=chunk_str, file_index=file_index, chunk_index=chunk_idx))
                chunk_idx += 1
            # Seed the next chunk with the overlap window
            current_words = current_words[-overlap_words:] if overlap_words > 0 else []

    # Final (possibly short) chunk
    if current_words:
        chunk_str = " ".join(current_words)
        if len(chunk_str) >= 20:
            chunks.append(Chunk(text=chunk_str, file_index=file_index, chunk_index=chunk_idx))

    return chunks
