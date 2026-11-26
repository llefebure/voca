"""Drift guard: the DB's supported-language list is the single canonical definition.

The `public.language_code` domain in the baseline migration pins the supported
target-language codes; both app maps must mirror it exactly. If someone adds a
language to `services/languages.py` (or the frontend's `lib/languages.ts`)
without a domain migration — or moves the list — this test fails loudly.
"""

import re
from pathlib import Path

from voca.services.languages import SUPPORTED_LANGUAGES

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "supabase" / "migrations"

# The whole list lives on one line: CREATE DOMAIN public.language_code AS TEXT CHECK (VALUE IN ('es'));
DOMAIN_LINE = re.compile(
    r"CREATE\s+DOMAIN\s+public\.language_code\s+AS\s+TEXT\s+CHECK\s*\(\s*VALUE\s+IN\s*\((?P<values>[^)]*)\)\)",
    re.IGNORECASE,
)


def domain_codes() -> set[str]:
    """The codes in the migration's language_code domain VALUE IN (...) list."""
    lines = [
        line
        for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
        for line in path.read_text().splitlines()
    ]
    matches = [DOMAIN_LINE.match(line) for line in lines]
    domain_lines = [match for match in matches if match]
    assert domain_lines, (
        "no `CREATE DOMAIN public.language_code ... CHECK (VALUE IN (...))` line found "
        f"in {MIGRATIONS_DIR} — the canonical language definition moved?"
    )
    assert len(domain_lines) == 1, "the language_code domain must be defined exactly once"
    return {code.strip().strip("'\"") for code in domain_lines[0]["values"].split(",")}


def test_supported_languages_mirror_the_language_code_domain():
    assert set(SUPPORTED_LANGUAGES) == domain_codes()


def test_domain_is_the_only_language_list_definition():
    """CHECK-listed language columns must all use the domain, not their own lists."""
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        for line in path.read_text().splitlines():
            lowered = line.lower()
            if "language" in lowered and "check" in lowered and "value in" in lowered:
                assert "language_code" in lowered, (
                    f"{path.name}: language list defined outside the domain: {line!r}"
                )
