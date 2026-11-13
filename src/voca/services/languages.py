"""Supported target (learning) languages.

The app's interface stays English; only the language the user is *learning*
is configurable here. Adding a future language means adding one entry to
`SUPPORTED_LANGUAGES` (and enabling it in the frontend picker once its models
exist) — no code-level assumptions about Spanish remain anywhere.
"""

DEFAULT_LANGUAGE = "es"

# Language code -> display name, in picker order.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "es": "Spanish",
}


def language_name(code: str | None) -> str:
    """Display name for a language code, falling back to the default language."""
    return SUPPORTED_LANGUAGES.get(code or "", SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE])
