import pytest

from verdikt.pipeline.chunker import TextChunker


def _words(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


def _paragraphs(*word_counts: int) -> str:
    return "\n\n".join(_words(n) for n in word_counts)


def test_empty_string_returns_empty_list():
    assert TextChunker().chunk("") == []


def test_whitespace_only_returns_empty_list():
    assert TextChunker().chunk("   \n\n  ") == []


def test_short_text_produces_one_chunk():
    text = _words(100)
    chunks = TextChunker(min_words=600, max_words=800).chunk(text)
    assert len(chunks) == 1


def test_chunk_sizes_within_bounds():
    # 10 paragraphs of 100 words each → 1000 total words
    # With min=200, max=300 we expect chunks between those sizes (except possibly last)
    text = _paragraphs(*([100] * 10))
    chunker = TextChunker(min_words=200, max_words=300)
    chunks = chunker.chunk(text)
    assert len(chunks) >= 2
    for chunk in chunks[:-1]:  # last chunk may be under min
        wc = len(chunk.split())
        assert wc <= 300, f"Chunk too large: {wc}"
        assert wc >= 100, f"Chunk suspiciously small: {wc}"


def test_paragraph_boundaries_never_split():
    # Use a marker to detect if paragraphs are split
    paras = [f"Para{i} " + _words(80) for i in range(8)]
    text = "\n\n".join(paras)
    chunker = TextChunker(min_words=200, max_words=300)
    chunks = chunker.chunk(text)
    # Each chunk should start cleanly with "Para<N>" — never mid-paragraph
    for chunk in chunks:
        assert chunk.startswith("Para"), f"Chunk doesn't start at paragraph boundary: {chunk[:40]}"


def test_oversized_single_paragraph_split_at_sentence():
    # Single paragraph, no double-newlines, 1200 words of sentences
    sentences = ["This is sentence number %d." % i for i in range(200)]
    text = " ".join(sentences)
    chunker = TextChunker(min_words=100, max_words=150)
    chunks = chunker.chunk(text)
    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        assert len(chunk.split()) <= 150


def test_min_max_configurable():
    text = _paragraphs(*([50] * 20))  # 20 paragraphs × 50 words = 1000 words
    small_chunker = TextChunker(min_words=100, max_words=150)
    large_chunker = TextChunker(min_words=400, max_words=600)
    small_chunks = small_chunker.chunk(text)
    large_chunks = large_chunker.chunk(text)
    assert len(small_chunks) > len(large_chunks)


def test_deterministic():
    text = _paragraphs(*([75] * 12))
    chunker = TextChunker(min_words=200, max_words=300)
    assert chunker.chunk(text) == chunker.chunk(text)


def test_word_count_helper():
    assert TextChunker._word_count("one two three") == 3
    assert TextChunker._word_count("") == 0


def test_paragraph_split_helper():
    text = "First para.\n\nSecond para.\n\n\nThird para."
    parts = TextChunker._split_paragraphs(text)
    assert parts == ["First para.", "Second para.", "Third para."]


def test_paragraph_split_crlf():
    text = "Para one.\r\n\r\nPara two."
    parts = TextChunker._split_paragraphs(text)
    assert len(parts) == 2


def test_single_large_paragraph_does_not_exceed_max():
    # 300 sentences of 10 words each; verify all chunks ≤ max_words
    sentences = [("word " * 10).strip() + "." for _ in range(300)]
    text = " ".join(sentences)
    chunker = TextChunker(min_words=150, max_words=200)
    chunks = chunker.chunk(text)
    for chunk in chunks[:-1]:
        assert len(chunk.split()) <= 200
