"""Generate per-worktree env files for a stack-mode local Supabase project.

With `experimental.stack = true` (see supabase/config.toml), every git
worktree / branch gets its own local Supabase project with auto-assigned,
stable ports and its own keys. This script starts (or attaches to) the
current project and rewrites the untracked env files from its real values:

- ``.worktree.env``        -> FRONTEND_PORT / BACKEND_PORT (Taskfile dotenv)
- ``src/voca/.env``        -> SUPABASE_URL / service key + frontend CORS ports
- ``frontend/.env.local``  -> anon key / supabase URL / backend URL

Preserved across runs: any ``LLM_*`` / ``LOGFIRE_*`` lines already present
in ``src/voca/.env`` (they are worktree-independent and usually copied from the
main checkout once).

Usage (all paths relative to the repo root whose env files are written):

    uv run python scripts/worktree_env.py sync [--frontend-port N] [--backend-port N] [--name NAME]

``sync`` runs ``supabase start --output-format json`` (idempotent; in stack
mode the project identity is worktree path + git branch) and writes the
files. Exit 0 on success, 1 with a readable message otherwise.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import zlib
from pathlib import Path

DEFAULT_FRONTEND_PORT = 3000
DEFAULT_BACKEND_PORT = 8000

# Worktree dev-server port band. Below 10000 (tools), below 11000 (common
# dev defaults), and away from Supabase's auto-assign range (20000-32767).
PORT_BAND_START = 11000
PORT_BAND_SIZE = 2000

ENV_PATH = Path("src/voca/.env")
FRONTEND_ENV_PATH = Path("frontend/.env.local")
PORTS_ENV_PATH = Path(".worktree.env")

LLM_ENV_DEFAULTS: dict[str, str] = {
    "LLM_BASE_URL": "http://localhost:11434/v1",
    "LLM_MODEL": "gemma4:31b-cloud",
}
LOGFIRE_ENV_DEFAULTS: dict[str, str] = {
    "LOGFIRE_SERVICE_NAME": "voca-backend",
}
# Keys kept from an existing src/voca/.env across syncs.
PRESERVE_PREFIXES = ("LLM_", "LOGFIRE_")


def _say(msg: str) -> None:
    print(msg, file=sys.stderr)


def read_kv(path: Path) -> dict[str, str]:
    """Parse a dotenv-style file into a dict (comments/blank lines ignored)."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def write_kv(path: Path, pairs: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k}={v}\n" for k, v in pairs))


def hash_ports(name: str) -> tuple[int, int]:
    """Deterministic per-name frontend/backend ports in the worktree band."""
    n = zlib.crc32(name.encode())
    return PORT_BAND_START + n % PORT_BAND_SIZE, PORT_BAND_START + n % PORT_BAND_SIZE + 1


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def is_git_worktree() -> bool:
    """True when run inside a linked git worktree (not the primary checkout)."""
    try:
        git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"], capture_output=True, text=True, timeout=30
        ).stdout.strip()
        common_dir = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except FileNotFoundError, subprocess.SubprocessError:
        return False
    if not git_dir or not common_dir:
        return False
    return Path.cwd().joinpath(git_dir).resolve() != Path.cwd().joinpath(common_dir).resolve()


def pick_ports(name: str, existing: dict[str, str]) -> tuple[int, int]:
    """Stable ports: explicit file > hashed band port, skipping busy ports.

    The primary checkout keeps the classic dev ports (3000/8000); only worktrees
    hash into the 11000+ band so parallel worktrees never collide there.
    """
    if existing.get("FRONTEND_PORT", "").isdigit() and existing.get("BACKEND_PORT", "").isdigit():
        return int(existing["FRONTEND_PORT"]), int(existing["BACKEND_PORT"])
    if not is_git_worktree():
        return DEFAULT_FRONTEND_PORT, DEFAULT_BACKEND_PORT
    frontend, backend = hash_ports(name)
    for offset in range(0, PORT_BAND_SIZE - 2, 2):
        if port_free(frontend + offset) and port_free(backend + offset):
            return frontend + offset, backend + offset
    raise SystemExit(
        f"No free port pair found in [{PORT_BAND_START}, {PORT_BAND_START + PORT_BAND_SIZE})"
    )


def ensure_supabase_stack() -> dict:
    """Start (or attach to) the stack-mode project; return its JSON status."""
    _say("==> supabase start (stack mode; may take a while on first run)...")
    proc = subprocess.run(
        ["supabase", "start", "--output-format", "json"],
        capture_output=True,
        text=True,
        timeout=1200,
    )
    if proc.returncode != 0:
        _say(proc.stderr.strip() or proc.stdout.strip())
        raise SystemExit(f"supabase start failed ({proc.returncode}); aborting env sync")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit("supabase start did not return valid JSON; aborting env sync") from exc


def find_stack_env(status: dict) -> dict[str, str]:
    """Locate the stack's env map: top-level 'env', or under each project entry."""
    if isinstance(status.get("env"), dict):
        return status["env"]
    for value in status.values():
        if isinstance(value, dict) and isinstance(value.get("env"), dict):
            return value["env"]
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict) and isinstance(entry.get("env"), dict):
                    return entry["env"]
    raise SystemExit(f"No env map in supabase status output; keys found: {list(status)}")


def write_env_files(frontend_port: int, backend_port: int, stack_env: dict[str, str]) -> None:
    try:
        api_url = stack_env["API_URL"].rstrip("/")
        anon_key = stack_env["ANON_KEY"]
        service_key = stack_env["SERVICE_ROLE_KEY"]
    except KeyError as exc:
        raise SystemExit(
            f"Stack env map is missing {exc}; keys present: {sorted(stack_env)}"
        ) from exc

    front_urls = f"http://localhost:{frontend_port},http://127.0.0.1:{frontend_port}"

    preserved = {
        k: v
        for k, v in read_kv(ENV_PATH).items()
        if any(k.startswith(p) for p in PRESERVE_PREFIXES)
    }
    backend_env: list[tuple[str, str]] = [
        ("SUPABASE_URL", api_url),
        ("SUPABASE_SERVICE_ROLE_KEY", service_key),
        ("FRONTEND_PORT", str(frontend_port)),
        ("BACKEND_PORT", str(backend_port)),
        ("VOCA_FRONTEND_URLS", front_urls),
        *((k, preserved.get(k, default)) for k, default in LLM_ENV_DEFAULTS.items()),
        *((k, preserved.get(k, default)) for k, default in LOGFIRE_ENV_DEFAULTS.items()),
        *(
            (k, v)
            for k, v in preserved.items()
            if k not in LLM_ENV_DEFAULTS and k not in LOGFIRE_ENV_DEFAULTS
        ),
    ]
    write_kv(ENV_PATH, backend_env)

    write_kv(
        FRONTEND_ENV_PATH,
        [
            ("NEXT_PUBLIC_SUPABASE_URL", api_url),
            ("NEXT_PUBLIC_SUPABASE_ANON_KEY", anon_key),
            ("NEXT_PUBLIC_BACKEND_URL", f"http://localhost:{backend_port}"),
        ],
    )

    write_kv(
        PORTS_ENV_PATH,
        [("FRONTEND_PORT", str(frontend_port)), ("BACKEND_PORT", str(backend_port))],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["sync"], help="sync env files from the local stack")
    parser.add_argument("--frontend-port", type=int, default=None, help="override frontend port")
    parser.add_argument("--backend-port", type=int, default=None, help="override backend port")
    parser.add_argument(
        "--name", default=None, help="identity for hashed port selection (default: cwd name)"
    )
    args = parser.parse_args(argv)

    name = args.name or Path.cwd().name
    frontend_port, backend_port = pick_ports(name, read_kv(PORTS_ENV_PATH))
    if args.frontend_port is not None and args.backend_port is not None:
        frontend_port, backend_port = args.frontend_port, args.backend_port
    if args.frontend_port is not None and args.backend_port is None:
        backend_port = frontend_port + 1

    stack_env = find_stack_env(ensure_supabase_stack())
    write_env_files(frontend_port, backend_port, stack_env)
    _say(f"==> wrote {ENV_PATH}, {FRONTEND_ENV_PATH}, {PORTS_ENV_PATH}")
    _say(
        f"==> frontend :{frontend_port}, backend :{backend_port}, supabase {stack_env.get('API_URL', '?')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
