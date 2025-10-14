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


def parse_size_string(size_str: str) -> float:
    """Convert Docker size string (e.g., '1.5GB', '500MB') to bytes."""
    if not size_str or size_str == "0B":
        return 0.0

    size_str = size_str.strip().upper()
    # Check longer units first to avoid matching 'B' when we want 'GB', etc.
    multipliers = [
        ('TB', 1024**4),
        ('GB', 1024**3),
        ('MB', 1024**2),
        ('KB', 1024),
        ('B', 1),
    ]

    for unit, multiplier in multipliers:
        if size_str.endswith(unit):
            try:
                return float(size_str[:-len(unit)]) * multiplier
            except ValueError:
                return 0.0
    return 0.0


def format_bytes(bytes_value: float) -> str:
    """Format bytes into human-readable string."""
    if bytes_value == 0:
        return "0B"

    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    value = float(bytes_value)

    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    return f"{value:.2f}{units[unit_index]}"


class DockerReporter:
    """Generate reports on Docker resources."""

    def __init__(self, patterns: List[str] = None):
        self.patterns = patterns or ["juno", "helios"]

    def get_leftover_containers(self) -> List[Dict[str, str]]:
        """Get remaining containers matching patterns."""
        containers = []
        result = run_command(
            ["docker", "ps", "-a", "--format", "{{.ID}}|{{.Names}}|{{.Size}}|{{.Status}}"],
            capture_output=True
        )

        if result and result.returncode == 0 and result.stdout:
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 4:
                    container_id, name, size, status = parts[0], parts[1], parts[2], parts[3]
                    if any(pattern in name.lower() for pattern in self.patterns):
                        containers.append({
                            "id": container_id,
                            "name": name,
                            "size": size,
                            "status": status
                        })

        return containers

    def get_leftover_images(self) -> List[Dict[str, str]]:
        """Get remaining images matching patterns."""
        images = []
        result = run_command(
            ["docker", "images", "--format", "{{.ID}}|{{.Repository}}:{{.Tag}}|{{.Size}}"],
            capture_output=True
        )

        if result and result.returncode == 0 and result.stdout:
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 3:
                    image_id, name, size = parts[0], parts[1], parts[2]
                    if any(pattern in name.lower() for pattern in self.patterns):
                        images.append({
                            "id": image_id,
                            "name": name,
                            "size": size
                        })

        return images

    def get_leftover_volumes(self) -> List[Dict[str, str]]:
        """Get remaining volumes matching patterns."""
        volumes = []
        result = run_command(
            ["docker", "volume", "ls", "--format", "{{.Name}}|{{.Size}}"],
            capture_output=True
        )

        if result and result.returncode == 0 and result.stdout:
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 1:
                    name = parts[0]
                    size = parts[1] if len(parts) >= 2 else "N/A"
                    if any(pattern in name.lower() for pattern in self.patterns):
                        volumes.append({
                            "name": name,
                            "size": size
                        })

        return volumes

    def get_leftover_networks(self) -> List[Dict[str, str]]:
        """Get remaining networks matching patterns."""
        networks = []
        result = run_command(
            ["docker", "network", "ls", "--format", "{{.ID}}|{{.Name}}|{{.Driver}}"],
            capture_output=True
        )

        if result and result.returncode == 0 and result.stdout:
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 3:
                    network_id, name, driver = parts[0], parts[1], parts[2]
                    if any(pattern in name.lower() for pattern in self.patterns):
                        networks.append({
                            "id": network_id,
                            "name": name,
                            "driver": driver
                        })

        return networks

    def calculate_total_size(self, items: List[Dict[str, str]], size_key: str = "size") -> float:
        """Calculate total size in bytes from a list of items."""
        total = 0.0
        for item in items:
            size_str = item.get(size_key, "0B")
            # Handle container size format "123MB (virtual 456MB)"
            if "(" in size_str:
                size_str = size_str.split("(")[0].strip()
            total += parse_size_string(size_str)
        return total

    def print_report(self) -> None:
        """Print a comprehensive report of leftover resources."""
        log("\n" + "="*70)
        log("=== POST-CLEANUP REPORT ===")
        log("="*70)

        # Get leftover resources
        containers = self.get_leftover_containers()
        images = self.get_leftover_images()
        volumes = self.get_leftover_volumes()
        networks = self.get_leftover_networks()

        # Containers
        log(f"\n📦 Leftover Containers: {len(containers)}")
        if containers:
            total_size = self.calculate_total_size(containers)
            log(f"   Total size: {format_bytes(total_size)}")
            for container in containers:
                log(f"   - {container['name']} ({container['status']}) - {container['size']}")
        else:
            log("   ✓ No leftover containers found")

        # Images
        log(f"\n🖼️  Leftover Images: {len(images)}")
        if images:
            total_size = self.calculate_total_size(images)
            log(f"   Total size: {format_bytes(total_size)}")
            for image in images:
                log(f"   - {image['name']} - {image['size']}")
        else:
            log("   ✓ No leftover images found")

        # Volumes
        log(f"\n💾 Leftover Volumes: {len(volumes)}")
        if volumes:
            total_size = self.calculate_total_size(volumes)
            if total_size > 0:
                log(f"   Total size: {format_bytes(total_size)}")
            else:
                log("   Total size: Unable to determine (volume sizes not available)")
            for volume in volumes:
                log(f"   - {volume['name']} - {volume['size']}")
        else:
            log("   ✓ No leftover volumes found")

        # Networks
        log(f"\n🌐 Leftover Networks: {len(networks)}")
        if networks:
            for network in networks:
                log(f"   - {network['name']} ({network['driver']})")
        else:
            log("   ✓ No leftover networks found")

        # Overall summary
        log("\n" + "="*70)
        total_items = len(containers) + len(images) + len(volumes) + len(networks)
        if total_items == 0:
            log("✅ Cleanup successful! No Juno/Helios resources remain.")
        else:
            log(f"⚠️  {total_items} item(s) still present. You may need to:")
            log("   - Stop running containers manually")
            log("   - Force remove images: docker rmi -f <image>")
            log("   - Remove volumes: docker volume rm <volume>")
        log("="*70 + "\n")


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
                        if img:
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

    def clean_leftover_images_by_pattern(self) -> None:
        """Remove any remaining images matching juno/helios patterns."""
        log("Searching for leftover images matching patterns...")

        # Get all images matching the patterns
        result = run_command(
            ["docker", "images", "--format", "{{.ID}}|{{.Repository}}:{{.Tag}}"],
            capture_output=True
        )

        if not result or result.returncode != 0 or not result.stdout:
            log("  No images found or error occurred")
            return

        leftover_images = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                image_id, image_name = parts[0], parts[1]
                # Check if image matches any pattern
                if any(pattern in image_name.lower() for pattern in ["juno", "helios"]):
                    leftover_images.append((image_id, image_name))

        if not leftover_images:
            log("  No leftover images found")
            return

        log(f"  Found {len(leftover_images)} leftover image(s)")
        for image_id, image_name in leftover_images:
            log(f"  Removing leftover image: {image_name} ({image_id})")
            run_command(["docker", "rmi", "-f", image_id], dry_run=self.dry_run)

    def clean_dangling_images(self) -> None:
        """Remove dangling images with user confirmation."""
        log("Checking for dangling images...")

        if self.dry_run:
            log("[DRY-RUN] Would prompt: Remove ALL dangling images (including non-Juno)? [y/N]", prefix="")
            log("[DRY-RUN] Would run: docker image prune -f (if confirmed)", prefix="")
            return

        # Prompt user for confirmation
        try:
            response = input("\n⚠️  Remove ALL dangling images (including non-Juno)? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            log("\n  Skipped dangling image cleanup")
            return

        if response in ['y', 'yes']:
            log("  Removing dangling images...")
            result = run_command(["docker", "image", "prune", "-f"], capture_output=True)
            if result and result.returncode == 0:
                log(f"  {result.stdout.strip()}")
        else:
            log("  Skipped dangling image cleanup")

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

    log("\n--- Bringing Down Services ---")
    log("Stopping all running services gracefully...")
    for project_name in extractor.project_names:
        log(f"  Stopping compose project: {project_name}")
        cmd = [
            "docker", "compose",
            "-p", project_name,
            "-f", str(base_compose),
            "-f", str(runtime_compose),
            "down"
        ]
        run_command(cmd, dry_run=args.dry_run)

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

    log("\n--- Cleaning Leftover Images ---")
    cleaner.clean_leftover_images_by_pattern()

    log("\n--- Dangling Images ---")
    cleaner.clean_dangling_images()

    if not args.dry_run:
        log("\n✓ Cleanup complete!")

        # Generate post-cleanup report
        reporter = DockerReporter(patterns=["juno", "helios"])
        reporter.print_report()
    else:
        log("\n✓ Dry-run complete! Run without --dry-run to actually clean up.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
