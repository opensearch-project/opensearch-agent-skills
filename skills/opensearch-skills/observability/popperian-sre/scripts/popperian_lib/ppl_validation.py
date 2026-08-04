import re
from typing import Tuple

class PPLValidator:
    """Validates PPL queries to ensure they are read-only and within budgets."""

    # PPL is inherently read-only, but we still guard against prompt injection
    # or syntax that might be unsafe if passed to other endpoints.
    BANNED_TOKENS = [
        "delete", "drop", "update", "insert", "upsert", "_bulk", "_doc"
    ]

    # Compiled once at import time rather than re.search(pattern_string, ...) on
    # every call, which would implicitly recompile (or hit re's internal cache
    # by the literal string, an indirection the pre-built list just skips).
    _BANNED_TOKEN_PATTERNS = [
        (token, re.compile(r'\b' + re.escape(token) + r'\b')) for token in BANNED_TOKENS
    ]

    @classmethod
    def validate(cls, query: str, max_rows: int = 500) -> Tuple[bool, str]:
        """
        Validates the query.
        Returns (is_valid, error_message_or_normalized_query).
        """
        if not query or not query.strip():
            return False, "Query is empty."

        normalized = query.strip()
        lower_query = normalized.lower()

        for token, pattern in cls._BANNED_TOKEN_PATTERNS:
            # Check for banned tokens as whole words to prevent accidental matches
            if pattern.search(lower_query):
                return False, f"Query contains forbidden token: {token}"

        # Ensure bounded execution
        if "head" not in lower_query:
            normalized = f"{normalized} | head {max_rows}"

        return True, normalized
