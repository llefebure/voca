"""Supported target (learning) languages.

The interface stays English; only the language the user is *learning* is
configurable here. The single canonical definition of the supported list is
the DB's `public.language_code` domain (see the baseline migration in
`supabase/migrations/`) — `SUPPORTED_LANGUAGES` must mirror it exactly, which
a drift-guard test (tests/test_language_domain.py) enforces by parsing the
migration. Adding a language = one ALTER DOMAIN migration plus entries here
and in `frontend/lib/languages.ts` (plus its TTS/model config).
"""

DEFAULT_LANGUAGE = "es"

# Language code -> display name, in picker order.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "es": "Spanish",
}


def language_name(code: str | None) -> str:
    """Display name for a language code, falling back to the default language."""
    return SUPPORTED_LANGUAGES.get(code or "", SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE])
