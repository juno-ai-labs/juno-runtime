#!/usr/bin/env python3
"""Runtime launcher for the Juno stack."""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent
BASE_COMPOSE = ROOT_DIR / "docker-compose.yml"
RUNTIME_COMPOSE = ROOT_DIR / "docker-compose.runtime.yml"
PROJECT_NAME = os.environ.get("COMPOSE_PROJECT_NAME", ROOT_DIR.name)
SETUP_SCRIPT = ROOT_DIR / "setup-jetson.py"
SETUP_STATE_FILE = ROOT_DIR / ".setup_complete.toml"
RUNTIME_SERVICES = ["stt-stream", "llm", "tts"]


def parse_version(value: str) -> Optional[Tuple[int, ...]]:
    """Parse a dot-delimited semantic version into an integer tuple.

    Using integer tuples allows natural comparisons such as
    ``(2025, 10, 12) < (2025, 10, 13)``, so date-styled versions like
    "2025.10.12" work as expected without custom comparison logic.
    """

    parts = value.strip().split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def read_setup_version(path: Path) -> Optional[str]:
    """Extract the current setup script version without modifying the file."""
    if not path.is_file():
        return None
    version_pattern = re.compile(r'^VERSION\s*=\s*"([^"]+)"')
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = version_pattern.match(line.strip())
            if match:
                return match.group(1)
    except OSError:
        return None
    return None


def read_recorded_version(path: Path) -> Optional[str]:
    """Load the last applied setup version from the state marker if present."""
    if not path.is_file():
        return None
    version_pattern = re.compile(r'^version\s*=\s*"([^"]+)"', re.IGNORECASE)
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = version_pattern.match(line.strip())
            if match:
                return match.group(1)
    except OSError:
        return None
    return None


def ensure_jetson_setup() -> None:
    """Run the setup script when the persisted version is missing or outdated."""
    if not SETUP_SCRIPT.is_file():
        return

    setup_version_str = read_setup_version(SETUP_SCRIPT)
    if not setup_version_str:
        print("Unable to determine setup script version; skipping automatic setup.", file=sys.stderr)
        return

    setup_version = parse_version(setup_version_str)
    if setup_version is None:
        print(
            "Unrecognized setup script version format; skipping automatic setup.",
            file=sys.stderr,
        )
        return

    recorded_version_str = read_recorded_version(SETUP_STATE_FILE)
    state_exists = SETUP_STATE_FILE.is_file()
    recorded_version = (
        parse_version(recorded_version_str) if recorded_version_str else None
    )
    needs_setup = (
        not state_exists
        or recorded_version is None
        or recorded_version < setup_version
    )

    if needs_setup:
        if not state_exists:
            print("Jetson setup state not found; running setup script...")
        elif recorded_version is None:
            print("Jetson setup state is unreadable; running setup script...")
        else:
            print(
                "Recorded Jetson setup version is outdated; running setup script..."
            )
        print(f"Running Jetson setup script (version {setup_version_str})...")
        result = subprocess.run([str(SETUP_SCRIPT)], cwd=str(ROOT_DIR))
        if result.returncode != 0:
            sys.exit(result.returncode)



def ensure_compose_file(path: Path) -> None:
    """Abort execution when required compose manifests are missing."""
    if not path.is_file():
        print(f"Compose file not found: {path}", file=sys.stderr)
        sys.exit(1)



def build_combined_compose() -> Path:
    """Generate a temporary merged compose file for runtime deployment."""
    with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        cmd = [
            "docker",
            "compose",
            "-p",
            PROJECT_NAME,
            "-f",
            str(BASE_COMPOSE),
            "-f",
            str(RUNTIME_COMPOSE),
            "config",
        ]
        proc = subprocess.run(cmd, stdout=tmp, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        sys.stderr.write(proc.stderr or "")
        sys.exit(proc.returncode)
    return tmp_path



def main() -> int:
    """Entry point that ensures provisioning and launches runtime services."""
    ensure_jetson_setup()

    ensure_compose_file(BASE_COMPOSE)
    ensure_compose_file(RUNTIME_COMPOSE)

    combined_file = build_combined_compose()
    try:
        pull_cmd = [
            "docker",
            "compose",
            "-p",
            PROJECT_NAME,
            "-f",
            str(combined_file),
            "pull",
            "--ignore-pull-failures",
            *RUNTIME_SERVICES,
        ]
        subprocess.run(pull_cmd, check=True)

        setup_echo = ROOT_DIR / "setup-echo.sh"
        subprocess.run([str(setup_echo)], check=True)

        up_cmd = [
            "docker",
            "compose",
            "-p",
            PROJECT_NAME,
            "-f",
            str(combined_file),
            "up",
            "--remove-orphans",
            *RUNTIME_SERVICES,
        ]
        result = subprocess.run(up_cmd)
        return result.returncode
    finally:
        try:
            combined_file.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    sys.exit(main())
