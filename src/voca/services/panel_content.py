"""Panel content primitives: a panel is markdown text the tutor composes directly.

The model builds lists, tables, dialogues — whatever it needs — by just writing
markdown, so there are no block types to coerce or validate. What survives from
the earlier block era is one thing that stays necessary regardless of content
shape: decoding the escape sequences gemma double-escapes inside tool-arg
strings (verified live: literal ``\\n``/``\\r``/``\\t`` sequences instead of
real line breaks).
"""

from typing import Any


def _clean_strings(value: Any) -> Any:
    """Decode escape sequences gemma double-escapes inside tool-arg strings.

    Verified live: panel text arrives with literal ``\\n`` (and occasionally
    ``\\r``/``\\t``) sequences instead of real line breaks; decode them.
    """
    if isinstance(value, str):
        return (
            value.replace("\\r\\n", "\n")
            .replace("\\r", "\n")
            .replace("\\n", "\n")
            .replace("\\t", "\t")
        )
    if isinstance(value, dict):
        return {key: _clean_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_strings(item) for item in value]
    return value


def normalize_panel(title: str, markdown: str) -> dict:
    """Tool-call payload → the panel dict persisted to `transcripts.payload`.

    A falsy title keeps the neutral default; markdown is escape-decoded but
    otherwise taken verbatim (the model composes markdown directly).
    """
    cleaned = _clean_strings({"title": title or "", "markdown": markdown or ""})
    clean_title = cleaned["title"].strip()
    return {"title": clean_title or "Panel", "markdown": cleaned["markdown"]}
