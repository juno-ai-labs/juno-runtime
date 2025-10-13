#!/usr/bin/env python3
"""Jetson setup utility.

When modifying this script, update VERSION to the new release identifier and
append the previous VERSION value to PREV_VERSIONS so the history remains
traceable.
"""

import argparse
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

VERSION = "2025.10.12"
PREV_VERSIONS: List[str] = []


def parse_args() -> argparse.Namespace:
    """Collect CLI options without mutating environment state."""
    parser = argparse.ArgumentParser(
        description="Configure NVIDIA Jetson settings in an idempotent manner."
    )
    parser.add_argument(
        "--power-mode",
        metavar="MODE",
        default="0",
        help="Power mode index to set with nvpmodel",
    )
    parser.add_argument(
        "--user",
        metavar="USER",
        default=None,
        help="User to add to the docker group (default: detected caller)",
    )
    return parser.parse_args()


def detect_target_user(provided_user: Optional[str]) -> str:
    """Resolve which user account should receive docker group membership changes."""
    if provided_user:
        return provided_user
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        return sudo_user
    env_user = os.environ.get("USER")
    if env_user:
        return env_user
    try:
        import getpass

        return getpass.getuser()
    except Exception:
        return "root"


class PrivilegeManager:
    def __init__(self) -> None:
        """Determine whether privileged commands can be executed directly or via sudo."""
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.have_priv = True
            self.prefix: List[str] = []
        else:
            sudo_path = shutil.which("sudo")
            if sudo_path:
                self.have_priv = True
                self.prefix = [sudo_path]
            else:
                self.have_priv = False
                self.prefix = []

    def run(
        self,
        cmd: List[str],
        *,
        capture_output: bool = False,
        text: bool = True,
        check: bool = False,
    ) -> Optional[subprocess.CompletedProcess]:
        """Execute a command with the best available privilege escalation, if any."""
        if not self.have_priv:
            return None
        full_cmd = self.prefix + cmd
        return subprocess.run(
            full_cmd,
            capture_output=capture_output,
            text=text,
            check=check,
        )


class JetsonSetup:
    def __init__(self, args: argparse.Namespace) -> None:
        """Initialise setup state tracking without applying any system changes."""
        self.args = args
        self.target_user = detect_target_user(args.user)
        self.power_mode = args.power_mode
        self.state_file = Path.cwd() / ".setup_complete.toml"
        self.priv = PrivilegeManager()
        self.root_missing_actions: List[str] = []
        self.changes_made = False
        self.power_mode_change_requested = False
        self.power_mode_auto_reboot = False
        self.docker_restarted = False
        self.needs_restart = False

    def note_root_required(self, message: str) -> None:
        """Record an action needing elevated permissions so users can address it manually."""
        self.root_missing_actions.append(message)
        print(f"⚠️  Root privileges are required: {message}")

    def _read_file_with_priv(self, path: str) -> Optional[str]:
        """Fetch file contents using available privilege helpers without altering the file."""
        result = self.priv.run(["cat", path], capture_output=True)
        if result and getattr(result, "returncode", 0) == 0:
            return (result.stdout or "")
        return None

    def ensure_docker_default_runtime(self) -> None:
        """Inspect Docker's default runtime and remind the user to set it to NVIDIA if needed."""
        if shutil.which("docker") is None:
            print("Docker is not installed; skipping docker runtime check.")
            return

        info_proc = subprocess.run(
            ["docker", "info", "--format", "{{.DefaultRuntime}}"],
            capture_output=True,
            text=True,
        )
        if info_proc.returncode == 0:
            # ``docker info --format '{{.DefaultRuntime}}'`` outputs the current
            # default runtime on a single line, such as ``runc`` or
            # ``nvidia``.  The script compares that token to ``nvidia`` and
            # instructs the user to update ``/etc/docker/daemon.json`` if it
            # differs.
            default_runtime = (info_proc.stdout or "").strip()
        else:
            default_runtime = ""

        if default_runtime == "nvidia":
            print("Docker default runtime already set to nvidia.")
            return

        print(
            "Docker default runtime is not 'nvidia'. Please update /etc/docker/daemon.json "
            "to include the NVIDIA runtime configuration manually."
        )
        if self.priv.have_priv:
            print(
                """Example configuration:
{
    "default-runtime": "nvidia",
    "runtimes": {
        "nvidia": {
            "path": "nvidia-container-runtime",
            "runtimeArgs": []
        }
    }
}"""
            )


    def ensure_docker_group_membership(self) -> None:
        """Add the target user to the docker group when necessary."""
        if self.target_user == "root":
            print("Target user resolved to root. Docker group membership changes will be skipped.")
            return

        try:
            import pwd

            pwd.getpwnam(self.target_user)
        except KeyError:
            print(
                f"User {self.target_user} does not exist; skipping docker group membership."
            )
            return

        groups_proc = subprocess.run(
            ["id", "-nG", self.target_user],
            capture_output=True,
            text=True,
        )
        if groups_proc.returncode == 0:
            # ``id -nG <user>`` prints the space-delimited list of group names on a
            # single line, for example ``ubuntu adm dialout cdrom sudo docker``.
            # The docker membership check relies on splitting that line into
            # individual group tokens and looking for ``docker``.
            groups = groups_proc.stdout.strip().split()
            if "docker" in groups:
                print(f"User {self.target_user} is already in the docker group.")
                return

        if not self.priv.have_priv:
            self.note_root_required(
                f"Add user {self.target_user} to the docker group (usermod -aG docker {self.target_user})"
            )
            return

        print(f"Adding user {self.target_user} to docker group...")
        result = self.priv.run(["usermod", "-aG", "docker", self.target_user])
        if result and getattr(result, "returncode", 0) == 0:
            self.changes_made = True
            print(
                f"User {self.target_user} added to docker group. Log out and back in for the change to take effect."
            )
        else:
            print(
                f"Failed to add user {self.target_user} to docker group.", file=sys.stderr
            )

    def ensure_power_mode(self) -> None:
        """Apply the requested nvpmodel power profile, triggering reboot notices if changed."""
        if shutil.which("nvpmodel") is None:
            print("nvpmodel command not found; skipping power mode configuration.")
            return

        query_output = ""
        if self.priv.have_priv:
            result = self.priv.run(["nvpmodel", "-q"], capture_output=True)
            if result and getattr(result, "returncode", 0) == 0:
                query_output = (result.stdout or "") + (result.stderr or "")
        if not query_output:
            probe = subprocess.run(
                ["nvpmodel", "-q"], capture_output=True, text=True
            )
            if probe.returncode == 0:
                query_output = (probe.stdout or "") + (probe.stderr or "")

        current_mode = None
        # ``nvpmodel -q`` prints two lines summarising the current profile, for
        # example ``NV Power Mode: MAXN`` followed by the numeric selector
        # ``0``.  The setup logic scans the output for the numeric line so it
        # can compare the active index with the requested mode value.
        for line in query_output.splitlines():
            stripped = line.strip()
            if stripped.isdigit():
                current_mode = stripped
                break

        if current_mode == self.power_mode:
            print(f"Power mode already set to {self.power_mode}.")
            return

        if not self.priv.have_priv:
            self.note_root_required(f"Set power mode to {self.power_mode} with nvpmodel")
            return

        self.power_mode_change_requested = True
        print(
            "Changing power mode from {} to {} requires a reboot and the system will automatically restart if needed.".format(
                current_mode or "unknown", self.power_mode
            )
        )
        print(f"Setting power mode to {self.power_mode}...")
        result = self.priv.run(
            ["nvpmodel", "-m", str(self.power_mode), "--force"],
            capture_output=True,
        )
        if not result:
            print("Failed to set power mode.", file=sys.stderr)
            return
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        if output:
            print(output)
        if getattr(result, "returncode", 0) != 0:
            print("Failed to set power mode.", file=sys.stderr)
            return

        self.changes_made = True
        # Successful ``nvpmodel -m`` executions that trigger an immediate reboot
        # emit lines like ``Automatically rebooting to reflect the mode change``.
        # Checking for the substring "reboot" lets the script surface that
        # behaviour to the caller.
        if "reboot" in output.lower():
            self.power_mode_auto_reboot = True
        print(f"Power mode set to {self.power_mode}.")

    def ensure_jetson_clocks_service(self) -> None:
        """Provision and enable the jetson_clocks systemd service when missing or outdated."""
        if shutil.which("jetson_clocks") is None:
            print("jetson_clocks command not found; skipping systemd service configuration.")
            return
        if not self.priv.have_priv:
            self.note_root_required("Create and enable jetson_clocks systemd service")
            return

        service_path = "/etc/systemd/system/jetson_clocks.service"
        desired_service = """[Unit]
Description=Jetson performance clocks
After=nvpmodel.service

[Service]
Type=oneshot
ExecStart=/usr/bin/jetson_clocks
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""
        reloaded = False
        existing = self._read_file_with_priv(service_path)
        if existing is None or existing.strip() != desired_service.strip():
            print("Configuring jetson_clocks systemd service...")
            with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
                tmp.write(desired_service)
                tmp_path = tmp.name
            try:
                install_result = self.priv.run(["install", "-m", "0644", tmp_path, service_path])
                if not install_result or getattr(install_result, "returncode", 0) != 0:
                    print(f"Failed to write {service_path}", file=sys.stderr)
                    return
            finally:
                try:
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    pass
            reloaded = True
            self.changes_made = True

        if reloaded:
            reload_proc = self.priv.run(["systemctl", "daemon-reload"])
            if reload_proc and getattr(reload_proc, "returncode", 0) == 0:
                print("Reloaded systemd units.")
            else:
                print("Failed to reload systemd daemon.", file=sys.stderr)

        enabled_proc = self.priv.run(["systemctl", "is-enabled", "jetson_clocks"], capture_output=True)
        if not enabled_proc or getattr(enabled_proc, "returncode", 0) != 0:
            print("Enabling jetson_clocks service...")
            enable_proc = self.priv.run(["systemctl", "enable", "jetson_clocks"])
            if enable_proc and getattr(enable_proc, "returncode", 0) == 0:
                self.changes_made = True
                print("jetson_clocks service enabled.")
            else:
                print("Failed to enable jetson_clocks service.", file=sys.stderr)
        else:
            print("jetson_clocks service already enabled.")

        start_proc = self.priv.run(["systemctl", "start", "jetson_clocks"])
        if start_proc and getattr(start_proc, "returncode", 0) == 0:
            print("jetson_clocks service started.")

    def ensure_jetson_clocks(self) -> None:
        """Activate jetson_clocks either via systemd or direct invocation to maximise clocks."""
        if shutil.which("jetson_clocks") is None:
            print("jetson_clocks command not found; skipping Jetson clocks configuration.")
            return
        if not self.priv.have_priv:
            self.note_root_required("Run jetson_clocks to maximize clocks")
            return

        show_proc = self.priv.run(
            ["jetson_clocks", "--show"], capture_output=True
        )
        if show_proc and getattr(show_proc, "returncode", 0) == 0:
            # ``jetson_clocks --show`` emits a multi-line hardware report, with a
            # trailing summary containing ``FreqOverride=<0|1>``.  When the clocks
            # are already locked to their maximum values the flag is ``FreqOverride=1``.
            # The setup workflow only inspects that flag to detect the existing
            # configuration and avoid redundant updates.
            show_output = (show_proc.stdout or "") + (show_proc.stderr or "")
            if "FreqOverride=1" in show_output:
                print("Jetson clocks already configured for maximum performance.")
                return

        print("Applying Jetson clocks configuration...")
        service_start = self.priv.run(["systemctl", "start", "jetson_clocks"])
        if service_start and getattr(service_start, "returncode", 0) == 0:
            self.changes_made = True
            print("Jetson clocks ensured via systemd service.")
            return

        direct = self.priv.run(["jetson_clocks"])
        if direct and getattr(direct, "returncode", 0) == 0:
            self.changes_made = True
            print("Jetson clocks ensured directly.")
        else:
            print("Failed to run jetson_clocks.", file=sys.stderr)

    def write_state_file(self) -> None:
        """Persist the completion timestamp, version, and power mode to skip repeated setup."""
        timestamp = datetime.datetime.now().isoformat(timespec="seconds")
        content = (
            f"setup_on = \"{timestamp}\"\n"
            f"version = \"{VERSION}\"\n"
            f"power_mode = \"{self.power_mode}\"\n"
        )
        self.state_file.write_text(content, encoding="utf-8")
        print()
        print(f"Recorded setup completion in {self.state_file.name}.")

    def run(self) -> int:
        """Execute each setup task and report any outstanding manual follow-up."""
        print("=== Jetson Setup Script ===")
        print(f"Target user: {self.target_user}")
        print(f"Desired power mode: {self.power_mode}")

        self.ensure_docker_default_runtime()
        self.ensure_docker_group_membership()
        self.ensure_jetson_clocks_service()
        self.ensure_power_mode()
        self.ensure_jetson_clocks()

        if self.root_missing_actions:
            print()
            print("The following actions require root privileges to complete:")
            for action in self.root_missing_actions:
                print(f"  - {action}")
            print("Please re-run this script with sudo or execute the commands above manually.")

        if not self.docker_restarted and self.needs_restart:
            print()
            print("Docker service needs to be restarted manually to apply changes.")

        if self.power_mode_change_requested:
            print()
            print(
                "Power mode change requested; the system will reboot automatically if required to finalize the setting."
            )
            if self.power_mode_auto_reboot:
                print(
                    "nvpmodel reported that the system is rebooting immediately. Allow the device to restart before continuing."
                )

        if not self.changes_made:
            print()
            print("No changes were necessary.")

        if not self.root_missing_actions:
            self.write_state_file()
        else:
            print()
            print(
                f"Skipping creation of {self.state_file.name} because some actions require root privileges."
            )

        return 0


def main() -> int:
    """Entry point for CLI execution."""
    args = parse_args()
    setup = JetsonSetup(args)
    return setup.run()


if __name__ == "__main__":
    sys.exit(main())
