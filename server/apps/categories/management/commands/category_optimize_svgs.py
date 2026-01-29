import subprocess
from pathlib import Path
from argparse import ArgumentTypeError

from django.core.management.base import BaseCommand


def int_or_str_size(value):
    """Parse size argument - can be integer (for square) or 'WxH' format."""
    if isinstance(value, int):
        return value, value

    # Try to parse as "WxH" format
    if "x" in value.lower():
        try:
            width, height = value.lower().split("x")
            return int(width), int(height)
        except (ValueError, AttributeError):
            raise ArgumentTypeError(
                f"Invalid size format: {value}. Use '48' for 48x48 or '48x64' for custom."
            )

    # Try to parse as single integer
    try:
        size = int(value)
        return size, size
    except ValueError:
        raise ArgumentTypeError(
            f"Invalid size: {value}. Use an integer or 'WxH' format (e.g., '48' or '48x64')."
        )


class Command(BaseCommand):
    help = "Optimize and resize SVG assets from assets_src to assets using svgo"

    def add_arguments(self, parser):
        parser.add_argument(
            "assets_src",
            nargs="?",
            type=str,
            default="server/apps/categories/assets_src",
            help='Path to source assets directory (relative to cwd). Default: "server/apps/categories/assets_src"',
        )
        parser.add_argument(
            "-s",
            "--size",
            type=int_or_str_size,
            default="48",
            help='Target size (default: 48 for 48x48). Can be single int or "WxH" format (e.g., "48x64")',
        )
        parser.add_argument(
            "-o",
            "--output",
            type=str,
            default="server/apps/categories/assets",
            help='Path to output directory (relative to cwd). Default: "server/apps/categories/assets"',
        )
        parser.add_argument(
            "-c",
            "--config",
            type=str,
            default="server/apps/categories/svgo.config.js",
            help='Path to svgo config file (relative to cwd). Default: "server/apps/categories/svgo.config.js"',
        )

    def check_svgo_installed(self):
        """Check if svgo is available via npx."""
        try:
            result = subprocess.run(
                ["npx", "svgo", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def update_config_size(self, config_path, target_width, target_height):
        """Update the svgo config file with the target size."""
        with open(config_path, "r") as f:
            content = f.read()

        # Replace width and height values in the config
        content = content.replace("width: '48'", f"width: '{target_width}'")
        content = content.replace("height: '48'", f"height: '{target_height}'")

        with open(config_path, "w") as f:
            f.write(content)

    def optimize_directory(self, source_dir, output_dir, config_path):
        """Optimize all SVG files in a directory using svgo."""
        try:
            cmd = [
                "npx",
                "svgo",
                "-f",
                str(source_dir),
                "-o",
                str(output_dir),
                "--config",
                str(config_path),
                "--multipass",
                "-r",
                "--quiet",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minutes timeout for batch processing
            )

            if result.returncode != 0:
                self.stdout.write(self.style.ERROR(f"svgo error: {result.stderr}"))
                return False

            return True
        except subprocess.TimeoutExpired:
            self.stdout.write(self.style.ERROR("svgo timeout"))
            return False
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error running svgo: {e}"))
            return False

    def get_dir_stats(self, directory):
        """Get statistics about SVG files in directory."""
        svg_files = list(directory.rglob("*.svg"))
        total_size = sum(f.stat().st_size for f in svg_files)
        return len(svg_files), total_size

    def handle(self, *args, **options):
        """Execute the command."""
        # Check if svgo is installed
        if not self.check_svgo_installed():
            self.stdout.write(
                self.style.ERROR(
                    "svgo is not available. Please install Node.js and ensure 'npx svgo' works."
                )
            )
            self.stdout.write(self.style.WARNING("Try running: npx svgo --version"))
            return

        # Setup paths - relative to current working directory
        cwd = Path.cwd()
        assets_src_path = (cwd / options["assets_src"]).resolve()
        assets_output_path = (cwd / options["output"]).resolve()
        config_path = (cwd / options["config"]).resolve()

        target_width, target_height = options["size"]

        # Print header
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("SVG Optimization Command (svgo)"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(f"Working directory: {cwd}")
        self.stdout.write(f"Source directory: {assets_src_path}")
        self.stdout.write(f"Output directory: {assets_output_path}")
        self.stdout.write(f"Config file: {config_path}")
        self.stdout.write(f"Target size: {target_width}x{target_height}")
        self.stdout.write("")

        # Check if source directory exists
        if not assets_src_path.exists():
            self.stdout.write(
                self.style.ERROR(f"Source directory not found: {assets_src_path}")
            )
            return

        # Check if config file exists
        if not config_path.exists():
            self.stdout.write(self.style.ERROR(f"Config file not found: {config_path}"))
            return

        # Get source statistics
        source_count, source_size = self.get_dir_stats(assets_src_path)

        if source_count == 0:
            self.stdout.write(
                self.style.WARNING("No SVG files found in source directory!")
            )
            return

        self.stdout.write(f"Found {source_count} SVG files ({source_size} bytes)")
        self.stdout.write("")

        # Update config with target size
        self.update_config_size(config_path, target_width, target_height)
        self.stdout.write(f"Updated config with size {target_width}x{target_height}")

        # Create output directory
        assets_output_path.mkdir(parents=True, exist_ok=True)

        self.stdout.write("Optimizing...")
        self.stdout.write("")

        # Optimize directory
        if self.optimize_directory(assets_src_path, assets_output_path, config_path):
            # Get output statistics
            output_count, output_size = self.get_dir_stats(assets_output_path)
            reduction = (1 - output_size / source_size) * 100

            self.stdout.write(self.style.SUCCESS("=" * 60))
            self.stdout.write(self.style.SUCCESS("Processing complete!"))
            self.stdout.write("")
            self.stdout.write(f"Files: {source_count} → {output_count}")
            self.stdout.write(
                f"Size: {source_size} → {output_size} bytes ({reduction:.1f}% reduction)"
            )
            self.stdout.write("")
            self.stdout.write(f"Optimized files saved to: {assets_output_path}")
            self.stdout.write("")
        else:
            self.stdout.write(self.style.ERROR("Optimization failed!"))
