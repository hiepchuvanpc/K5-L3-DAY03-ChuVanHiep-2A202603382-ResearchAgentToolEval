from __future__ import annotations

from typing import Any

from tools._shared import err


def summarize(text: str = "", max_chars: int = 500) -> dict[str, Any]:
    try:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Text must not be empty")

        limit = int(max_chars)
        if limit < 1:
            raise ValueError("max_chars must be positive")

        normalized = " ".join(text.split())
        summary = normalized[:limit]
        if len(normalized) > limit:
            summary = summary.rstrip() + "..."

        return {
            "tool": "summarize",
            "summary": summary,
            "original_chars": len(text),
        }
    except Exception as exc:
        return err("summarize", exc)