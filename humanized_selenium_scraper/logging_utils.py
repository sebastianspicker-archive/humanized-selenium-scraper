from __future__ import annotations


def redact_query(query: str) -> str:
    tokens = [token for token in query.split() if token]
    return f"<redacted len={len(query)} tokens={len(tokens)}>"
