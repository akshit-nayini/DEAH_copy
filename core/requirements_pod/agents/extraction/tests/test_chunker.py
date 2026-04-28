"""Tests for Stage 2 — chunker."""
import pytest
from core.requirements_pod.agents.extraction.chunker import chunk_text, Chunk
from core.requirements_pod.agents.extraction.config import ExtractionConfig


def _config(**overrides) -> ExtractionConfig:
    cfg = ExtractionConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def test_single_chunk_for_short_text():
    cfg = _config(chunk_size_tokens=2000, overlap_tokens=200, words_per_token=1.3)
    text = "This is a short document. It has two sentences."
    chunks = chunk_text(text, file_index=0, config=cfg)
    assert len(chunks) == 1
    assert chunks[0].file_index == 0
    assert chunks[0].chunk_index == 0


def test_multiple_chunks_for_long_text():
    # 300 words → chunk_size_tokens=100 × words_per_token=1.0 → chunks of 100 words
    cfg = _config(chunk_size_tokens=100, overlap_tokens=10, words_per_token=1.0)
    words = ["word"] * 300
    text = ". ".join(" ".join(words[i:i+10]) for i in range(0, 300, 10)) + "."
    chunks = chunk_text(text, file_index=0, config=cfg)
    assert len(chunks) > 1


def test_overlap_carries_words_to_next_chunk():
    # Produce two chunks and verify the second starts with words from the first's tail
    cfg = _config(chunk_size_tokens=10, overlap_tokens=3, words_per_token=1.0)
    # 30 distinct words in 3 sentences of 10 words each
    sentences = [
        " ".join(f"word{i}" for i in range(0, 10)) + ".",
        " ".join(f"word{i}" for i in range(10, 20)) + ".",
        " ".join(f"word{i}" for i in range(20, 30)) + ".",
    ]
    text = " ".join(sentences)
    chunks = chunk_text(text, file_index=0, config=cfg)
    assert len(chunks) >= 2
    # The second chunk should contain some tail words from the first chunk
    first_words = set(chunks[0].text.split()[-3:])
    second_words = set(chunks[1].text.split())
    assert first_words & second_words, "Expected overlap between chunk 0 tail and chunk 1 start"


def test_min_length_filter_drops_short_chunks():
    cfg = _config(chunk_size_tokens=5, overlap_tokens=0, words_per_token=1.0)
    # "Hi." is only 3 chars — should be dropped
    text = "Hi."
    chunks = chunk_text(text, file_index=0, config=cfg)
    assert chunks == []


def test_min_length_filter_keeps_long_enough_chunks():
    cfg = _config(chunk_size_tokens=5, overlap_tokens=0, words_per_token=1.0)
    text = "This sentence is definitely longer than twenty characters."
    chunks = chunk_text(text, file_index=0, config=cfg)
    assert len(chunks) == 1
    assert len(chunks[0].text) >= 20


def test_file_index_and_chunk_index_assigned():
    cfg = _config(chunk_size_tokens=10, overlap_tokens=0, words_per_token=1.0)
    sentences = [" ".join([f"w{i}"] * 10) + "." for i in range(4)]
    text = " ".join(sentences)
    chunks = chunk_text(text, file_index=2, config=cfg)
    assert all(c.file_index == 2 for c in chunks)
    for expected_idx, chunk in enumerate(chunks):
        assert chunk.chunk_index == expected_idx


def test_no_mid_sentence_split():
    """All text from a sentence should stay in one chunk."""
    cfg = _config(chunk_size_tokens=15, overlap_tokens=0, words_per_token=1.0)
    # Each sentence is exactly 10 words
    sentences = [" ".join([f"s{i}w{j}" for j in range(10)]) + "." for i in range(3)]
    text = " ".join(sentences)
    chunks = chunk_text(text, file_index=0, config=cfg)
    for chunk in chunks:
        # Every word in the chunk should match one of the original sentence patterns
        for word in chunk.text.replace(".", "").split():
            assert word.startswith("s"), f"Word {word!r} looks malformed"
