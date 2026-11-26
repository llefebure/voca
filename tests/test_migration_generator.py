"""Offline tests for scripts/new_migration.py — the migration filename generator.

Filenames are generated, never hand-typed (see `uv run task migration:new`);
these tests pin the CLI-canonical stamp format, name sanitization, and
collision refusal against fixture directories.

The filename contract matters beyond formatting: the Supabase CLI keys
migrations by the leading digit-run of the filename, so non-canonical names
(e.g. underscore-dated `YYYY_MM_DD_<seq>_<name>`) degenerate to a shared
version and any second migration of the day fails to apply. The stamp test
below keeps the generator on the CLI-canonical format permanently.
"""

import re
from datetime import datetime
from pathlib import Path

from scripts.new_migration import create_migration, sanitize_name


def make_dir(tmp_path: Path, *files: str) -> Path:
    migrations = tmp_path / "migrations"
    migrations.mkdir(exist_ok=True)
    for name in files:
        (migrations / name).touch()
    return migrations


# --- filename contract -------------------------------------------------------------------


def test_created_filenames_are_cli_canonical(tmp_path):
    """A 14-digit timestamp, then underscore, then a snake_case name."""
    migrations = make_dir(tmp_path)
    target = create_migration("add card reviews", migrations, datetime(2026, 11, 26, 14, 5, 9))
    assert re.fullmatch(r"20261126140509_add_card_reviews\.sql", target.name)
    assert target.exists()
    assert target.stat().st_size == 0  # `supabase migration new` semantics: empty


def test_existing_migrations_never_shift_the_stamp(tmp_path):
    """The stamp is the clock, not a per-directory counter (the CLI sorts by it)."""
    migrations = make_dir(tmp_path, "20260101000000_old.sql")
    target = create_migration("new thing", migrations, datetime(2026, 11, 26, 14, 5, 9))
    assert target.name == "20261126140509_new_thing.sql"


# --- collision refusal ---------------------------------------------------------------


def test_create_migration_never_overwrites_an_existing_target(tmp_path):
    """Same `now` twice (same second-stamp) ⇒ refuse, don't overwrite."""
    migrations = make_dir(tmp_path)
    now = datetime(2026, 11, 26, 9, 41, 5)
    create_migration("initial schema", migrations, now)
    try:
        create_migration("initial schema", migrations, now)
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing target was silently overwritten")


# --- name sanitization ----------------------------------------------------------------


def test_sanitize_name_snake_cases():
    assert sanitize_name("Add Card Reviews") == "add_card_reviews"
    assert sanitize_name("  Multi-Language & SRS!  ") == "multi_language_srs"
    assert sanitize_name("already_snake_case") == "already_snake_case"


def test_sanitize_name_rejects_an_empty_result():
    for bad in ("", "   ", "---", "///"):
        try:
            sanitize_name(bad)
        except ValueError:
            continue
        raise AssertionError(f"empty-ish name {bad!r} was accepted")
