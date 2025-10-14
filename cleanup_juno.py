#!/usr/bin/env python3
"""Cleanup script for Juno runtime.

Parses Docker Compose YAML files to discover and remove all related resources.
Resets the device to a state as if run.sh was never executed.
"""

import argparse
import subprocess
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Set, Any, Optional


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Clean up all Juno runtime Docker resources"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without actually removing it"
    )
    parser.add_argument(
        "--compose-base",
        default="docker-compose.yml",
        help="Path to base docker-compose.yml (default: docker-compose.yml)"
    )
    parser.add_argument(
        "--compose-runtime",
        default="docker-compose.runtime.yml",
        help="Path to runtime docker-compose.yml (default: docker-compose.runtime.yml)"
    )
    return parser.parse_args()


def log(message: str, prefix: str = "[cleanup]") -> None:
    """Print a log message."""
    print(f"{prefix} {message}")


def run_command(
    cmd: List[str],
    dry_run: bool = False,
    check: bool = False,
    capture_output: bool = False
) -> Optional[subprocess.CompletedProcess]:
    """Run a command, optionally in dry-run mode."""
    cmd_str = " ".join(cmd)
    if dry_run:
        log(f"[DRY-RUN] Would run: {cmd_str}", prefix="")
        return None

    try:
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            check=check
        )
        return result
    except subprocess.CalledProcessError as e:
        if not check:
            return e
        raise


def get_merged_compose_config(
    base_compose: Path,
    runtime_compose: Path,
    project_name: str
) -> Optional[Dict[str, Any]]:
    """Get merged compose configuration using docker compose config."""
    if not base_compose.exists() or not runtime_compose.exists():
        return None

    log(f"Getting merged config for project '{project_name}'...")
    cmd = [
        "docker", "compose",
        "-p", project_name,
        "-f", str(base_compose),
        "-f", str(runtime_compose),
        "config"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode != 0:
            log(f"Warning: Could not get merged config for project '{project_name}'", prefix="⚠️ ")
            return None

        # Parse the YAML output
        # Add custom constructors for Docker Compose YAML tags
        def reset_constructor(loader, node):
            """Handle !reset tag (sets value to None)."""
            return None

        def override_constructor(loader, node):
            """Handle !override tag (returns the node value)."""
            return loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_scalar(node)

        # Register custom constructors
        yaml.SafeLoader.add_constructor('!reset', reset_constructor)
        yaml.SafeLoader.add_constructor('!override', override_constructor)

        return yaml.safe_load(result.stdout)
    except Exception as e:
        log(f"Error getting merged config for project '{project_name}': {e}", prefix="❌")
        return None


def parse_compose_file(file_path: Path) -> Optional[Dict[str, Any]]:
    """Parse a Docker Compose YAML file."""
    if not file_path.exists():
        log(f"Warning: {file_path} not found, skipping", prefix="⚠️ ")
        return None

    # Add custom constructors for Docker Compose YAML tags
    def reset_constructor(loader, node):
        """Handle !reset tag (sets value to None)."""
        return None

    def override_constructor(loader, node):
        """Handle !override tag (returns the node value)."""
        return loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_scalar(node)

    # Register custom constructors
    yaml.SafeLoader.add_constructor('!reset', reset_constructor)
    yaml.SafeLoader.add_constructor('!override', override_constructor)

    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        log(f"Error parsing {file_path}: {e}", prefix="❌")
        return None


class ComposeResourceExtractor:
    """Extract Docker resources from compose configuration."""

    def __init__(self, base_config: Optional[Dict], runtime_config: Optional[Dict]):
        self.base_config = base_config or {}
        self.runtime_config = runtime_config or {}
        self.containers: Set[str] = set()
        self.images: Set[str] = set()
        self.volumes: Set[str] = set()
        self.networks: Set[str] = set()
        self.project_names = ["juno", "helios"]  # Check both project names

        # Track where resources came from for reporting
        self.containers_independent: Set[str] = set()
        self.containers_merged: Set[str] = set()
        self.images_independent: Set[str] = set()
        self.images_merged: Set[str] = set()
        self.volumes_independent: Set[str] = set()
        self.volumes_merged: Set[str] = set()
        self.networks_independent: Set[str] = set()
        self.networks_merged: Set[str] = set()

    def extract_all(self) -> None:
        """Extract all resources from both compose files independently."""
        for config in [self.base_config, self.runtime_config]:
            if config:
                self._extract_from_config(config, source="independent")

    def extract_from_merged(self, merged_config: Dict[str, Any]) -> None:
        """Extract resources from merged compose configuration."""
        self._extract_from_config(merged_config, source="merged")

    def _extract_from_config(self, config: Dict[str, Any], source: str = "independent") -> None:
        """Extract resources from a single compose configuration."""
        # Extract services
        services = config.get("services", {})
        for service_name, service_config in services.items():
            if not isinstance(service_config, dict):
                continue

            # Container names
            container_name = service_config.get("container_name")
            if container_name:
                self.containers.add(container_name)
                if source == "independent":
                    self.containers_independent.add(container_name)
                else:
                    self.containers_merged.add(container_name)

            # Image names
            image = service_config.get("image")
            if image:
                self.images.add(image)
                if source == "independent":
                    self.images_independent.add(image)
                else:
                    self.images_merged.add(image)

            # Build cache_from images
            build_config = service_config.get("build", {})
            if isinstance(build_config, dict):
                cache_from = build_config.get("cache_from", [])
                if isinstance(cache_from, list):
                    for img in cache_from:
                        if img:
                            self.images.add(img)
                            if source == "independent":
                                self.images_independent.add(img)
                            else:
                                self.images_merged.add(img)

        # Extract volumes
        volumes = config.get("volumes", {})
        if isinstance(volumes, dict):
            for volume_name in volumes.keys():
                self.volumes.add(volume_name)
                if source == "independent":
                    self.volumes_independent.add(volume_name)
                else:
                    self.volumes_merged.add(volume_name)

        # Extract networks
        networks = config.get("networks", {})
        if isinstance(networks, dict):
            for network_name in networks.keys():
                self.networks.add(network_name)
                if source == "independent":
                    self.networks_independent.add(network_name)
                else:
                    self.networks_merged.add(network_name)


class DockerCleaner:
    """Clean up Docker resources."""

    def __init__(self, extractor: ComposeResourceExtractor, dry_run: bool = False):
        self.extractor = extractor
        self.dry_run = dry_run

    def clean_containers(self) -> None:
        """Stop and remove containers."""
        if not self.extractor.containers:
            log("No containers to clean")
            return

        log(f"Cleaning {len(self.extractor.containers)} containers...")
        for container in self.extractor.containers:
            log(f"  Stopping container: {container}")
            run_command(["docker", "stop", container], dry_run=self.dry_run)

            log(f"  Removing container: {container}")
            run_command(["docker", "rm", container], dry_run=self.dry_run)

    def clean_images(self) -> None:
        """Remove images."""
        if not self.extractor.images:
            log("No images to clean")
            return

        log(f"Cleaning {len(self.extractor.images)} images...")
        for image in self.extractor.images:
            log(f"  Removing image: {image}")
            # Try to remove with all tags
            run_command(["docker", "rmi", "-f", image], dry_run=self.dry_run)

            # Also try to remove with wildcard pattern to catch all tags
            image_base = image.split(":")[0] if ":" in image else image
            log(f"  Removing all tags for: {image_base}")

            # Get all images matching the base
            if not self.dry_run:
                result = run_command(
                    ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}", image_base],
                    capture_output=True
                )
                if result and result.returncode == 0:
                    matching_images = result.stdout.strip().split("\n")
                    for img in matching_images:
                        if img and img != "<none>:<none>":
                            run_command(["docker", "rmi", "-f", img], dry_run=self.dry_run)

    def clean_volumes(self) -> None:
        """Remove volumes."""
        if not self.extractor.volumes:
            log("No volumes to clean")
            return

        log(f"Cleaning {len(self.extractor.volumes)} volumes...")
        for volume in self.extractor.volumes:
            # Try volume name as-is
            log(f"  Removing volume: {volume}")
            run_command(["docker", "volume", "rm", volume], dry_run=self.dry_run)

            # Try with project prefixes
            for project in self.extractor.project_names:
                prefixed_volume = f"{project}_{volume}"
                log(f"  Removing volume: {prefixed_volume}")
                run_command(["docker", "volume", "rm", prefixed_volume], dry_run=self.dry_run)

    def clean_networks(self) -> None:
        """Remove networks."""
        if not self.extractor.networks:
            log("No networks to clean")
            return

        log(f"Cleaning {len(self.extractor.networks)} networks...")
        for network in self.extractor.networks:
            # Try network name as-is
            log(f"  Removing network: {network}")
            run_command(["docker", "network", "rm", network], dry_run=self.dry_run)

            # Try with project prefixes
            for project in self.extractor.project_names:
                prefixed_network = f"{project}_{network}"
                log(f"  Removing network: {prefixed_network}")
                run_command(["docker", "network", "rm", prefixed_network], dry_run=self.dry_run)

    def clean_compose_projects(self, base_compose: Path, runtime_compose: Path) -> None:
        """Clean up using docker compose down."""
        log("Running docker compose down for each project...")

        for project in self.extractor.project_names:
            log(f"  Cleaning compose project: {project}")
            cmd = [
                "docker", "compose",
                "-p", project,
                "-f", str(base_compose),
                "-f", str(runtime_compose),
                "down", "-v", "--remove-orphans"
            ]
            run_command(cmd, dry_run=self.dry_run)


def main() -> int:
    """Main entry point."""
    args = parse_args()

    log("=== Juno Runtime Cleanup ===")
    if args.dry_run:
        log("DRY-RUN MODE: No changes will be made", prefix="⚠️ ")

    # Resolve paths
    root_dir = Path(__file__).parent
    base_compose = root_dir / args.compose_base
    runtime_compose = root_dir / args.compose_runtime

    # Parse compose files
    log(f"Parsing {base_compose}...")
    base_config = parse_compose_file(base_compose)

    log(f"Parsing {runtime_compose}...")
    runtime_config = parse_compose_file(runtime_compose)

    if not base_config and not runtime_config:
        log("No compose files found to parse", prefix="❌")
        return 1

    # Extract resources from independent files
    log("\n=== Extracting from independent files ===")
    extractor = ComposeResourceExtractor(base_config, runtime_config)
    extractor.extract_all()

    # Extract resources from merged configs for each project
    log("\n=== Extracting from merged configs ===")
    for project_name in extractor.project_names:
        merged_config = get_merged_compose_config(base_compose, runtime_compose, project_name)
        if merged_config:
            extractor.extract_from_merged(merged_config)

    # Report findings
    log(f"\n=== Resource Summary ===")
    log(f"Total containers: {len(extractor.containers)} "
        f"(independent: {len(extractor.containers_independent)}, "
        f"merged: {len(extractor.containers_merged)})")
    log(f"Total images: {len(extractor.images)} "
        f"(independent: {len(extractor.images_independent)}, "
        f"merged: {len(extractor.images_merged)})")
    log(f"Total volumes: {len(extractor.volumes)} "
        f"(independent: {len(extractor.volumes_independent)}, "
        f"merged: {len(extractor.volumes_merged)})")
    log(f"Total networks: {len(extractor.networks)} "
        f"(independent: {len(extractor.networks_independent)}, "
        f"merged: {len(extractor.networks_merged)})")

    # Clean up
    cleaner = DockerCleaner(extractor, dry_run=args.dry_run)

    log("\n--- Cleaning Containers ---")
    cleaner.clean_containers()

    log("\n--- Cleaning Images ---")
    cleaner.clean_images()

    log("\n--- Cleaning Volumes ---")
    cleaner.clean_volumes()

    log("\n--- Cleaning Networks ---")
    cleaner.clean_networks()

    log("\n--- Cleaning Compose Projects ---")
    cleaner.clean_compose_projects(base_compose, runtime_compose)

    if not args.dry_run:
        log("\n✓ Cleanup complete!")
    else:
        log("\n✓ Dry-run complete! Run without --dry-run to actually clean up.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
