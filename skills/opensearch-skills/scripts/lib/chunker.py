"""Text chunker with configurable size and overlap."""


def chunk_text(text: str, chunk_size: int = 512, chunk_overlap: int = 64) -> list[str]:
    """Split text into overlapping chunks measured in approximate word tokens."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap cannot be negative")
    if not text or not text.strip():
        return []

    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    # Only text long enough to be split needs a forward step. An overlap that
    # meets or exceeds the chunk size leaves a step of zero words, which would
    # loop forever.
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be smaller than "
            f"chunk_size ({chunk_size}) to split text of {len(words)} words"
        )

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end == len(words):
            break
        start += chunk_size - chunk_overlap

    return chunks
