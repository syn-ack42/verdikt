from __future__ import annotations

import re


class TextChunker:
    """Splits text into paragraph-respecting chunks within a word-count window.

    Paragraphs are never split unless a single paragraph exceeds max_words,
    in which case sentence boundaries are used as a fallback.
    """

    _SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

    def __init__(self, min_words: int = 600, max_words: int = 800) -> None:
        self._min = min_words
        self._max = max_words

    def chunk(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []

        paragraphs = self._split_paragraphs(text)
        # Expand any paragraph that exceeds max_words into sentence-level pieces
        expanded: list[str] = []
        for para in paragraphs:
            if self._word_count(para) > self._max:
                expanded.extend(self._split_oversized(para))
            else:
                expanded.append(para)

        chunks: list[str] = []
        buffer: list[str] = []
        buffer_words = 0

        for para in expanded:
            para_words = self._word_count(para)
            if buffer_words >= self._min and buffer_words + para_words > self._max:
                chunks.append("\n\n".join(buffer))
                buffer = [para]
                buffer_words = para_words
            else:
                buffer.append(para)
                buffer_words += para_words

        if buffer:
            chunks.append("\n\n".join(buffer))

        return chunks

    def _split_oversized(self, para: str) -> list[str]:
        sentences = self._SENTENCE_SPLIT.split(para)
        groups: list[str] = []
        current: list[str] = []
        current_words = 0
        for sentence in sentences:
            s_words = self._word_count(sentence)
            if current_words >= self._min and current_words + s_words > self._max:
                groups.append(" ".join(current))
                current = [sentence]
                current_words = s_words
            else:
                current.append(sentence)
                current_words += s_words
        if current:
            groups.append(" ".join(current))
        return groups

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        parts = re.split(r"\r?\n\r?\n+", text)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _word_count(text: str) -> int:
        return len(text.split())
