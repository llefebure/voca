"""Create a new Supabase migration file with the project's naming convention.

Voca migration filenames are hand-off-limits: this script (via
`uv run task migration:new -- <name>`) is the only documented way to create
one, so date/time stamps are never mistyped.

Filenames are CLI-canonical `YYYYMMDDHHMMSS_<name>.sql` — the format the
Supabase CLI itself stamps and parses. The CLI keys migrations by the *leading
digit-run* of the filename (see `supabase_migrations.schema_migrations.version`),
so anything else — e.g. an underscore-dated `YYYY_MM_DD_<seq>_<name>` —
degenerates to a shared version and any second migration of the day fails
with a duplicate-version error. Verified empirically against the vendored CLI:
underscore-dated files apply once, then `duplicate key value violates unique
constraint "schema_migrations_pkey"` on the next one.

The `<name>` is sanitized to snake_case, an existing target file is refused
(never overwrite), and the file is created EMPTY — matching `supabase
migration new` semantics, which never applies anything. Stdlib-only, offline.

Usage (single argument — through `task migration:new --` the name is best
typed snake_case; this direct call accepts quoted multi-word names too):

    uv run task migration:new -- add_card_reviews
    uv run python scripts/new_migration.py "Add Card Reviews"
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"


def sanitize_name(name: str) -> str:
    """Lowercase and snake-case a migration name (e.g. "Add Card Reviews")."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", name.lower())
    cleaned = cleaned.strip("_")
    if not cleaned:
        raise ValueError("migration name is empty after sanitization")
    return cleaned


def create_migration(name: str, migrations_dir: Path, now: datetime) -> Path:
    """Create the empty migration file and return its path.

    Raises `FileExistsError` if the target already exists (never overwrite) —
    two migrations stamped within the same second or repeated generation share
    a filename by construction.
    """
    target = migrations_dir / f"{now:%Y%m%d%H%M%S}_{sanitize_name(name)}.sql"
    if target.exists():
        raise FileExistsError(f"migration already exists: {target.name}")
    migrations_dir.mkdir(parents=True, exist_ok=True)
    target.touch()
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="migration name; sanitized to snake_case")
    args = parser.parse_args(argv)
    try:
        target = create_migration(args.name, MIGRATIONS_DIR, datetime.now())
    except (ValueError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created {target.relative_to(REPO_ROOT)} (empty — fill in the DDL)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
