"""
Management command to sync Martin tile server assets to a target directory.

This command copies config and sprite SVG files needed by Martin from the database
to a target directory (typically a Kubernetes PVC mount in production).

Usage:
    # Sync default categories (transport, accommodation, spot)
    app martin_sync --target /mnt/martin-pvc

    # Sync all categories
    app martin_sync --target /mnt/martin-pvc --all

    # Sync specific categories
    app martin_sync --target /mnt/martin-pvc --include transport,accommodation

    # Sync specific styles only
    app martin_sync --target /mnt/martin-pvc --styles detailed,simple

    # Dry run to preview
    app martin_sync --target ./test_output --dry-run --all
"""

import shutil
import yaml
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Sync Martin tile server assets to target directory (e.g., Kubernetes PVC)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--target",
            type=str,
            default="./martin_sync",
            help="Target directory path. Default: ./martin_sync (for local development). "
            "Use /mnt/martin-pvc for production Kubernetes PVC.",
        )
        parser.add_argument(
            "--include",
            type=str,
            default="",
            help="Comma-separated list of parent/root category slugs to include. "
            "If not specified, all categories are included.",
        )
        parser.add_argument(
            "--category-variants",
            type=str,
            default="",
            help="Comma-separated list of category variants to sync (e.g., detailed,simple,mono). "
            "Default: all available variants",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be copied without making changes",
        )
        parser.add_argument(
            "--validate",
            action="store_true",
            help="Validate files after copying (verify they exist and are readable)",
        )

    def handle(self, *args, **options):
        from server.apps.categories.models import Category
        from server.apps.symbols.models import Symbol

        target_path = Path(options["target"])
        dry_run = options.get("dry_run", False)
        validate = options.get("validate", False)
        include_slugs = options.get("include", "").strip()
        variants_param = options.get("category_variants", "").strip()

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        # Parse category variants
        if variants_param:
            requested_variants = [
                s.strip() for s in variants_param.split(",") if s.strip()
            ]
            # Validate variants against Symbol.StyleChoices
            valid_variants = [choice[0] for choice in Symbol.StyleChoices.choices]
            invalid_variants = [
                s for s in requested_variants if s not in valid_variants
            ]
            if invalid_variants:
                raise CommandError(
                    f"Invalid variants: {', '.join(invalid_variants)}. "
                    f"Valid variants: {', '.join(valid_variants)}"
                )
            variants = requested_variants
        else:
            # Default: all available variants
            variants = [choice[0] for choice in Symbol.StyleChoices.choices]

        # Parse include slugs
        if include_slugs:
            include_list = [s.strip() for s in include_slugs.split(",") if s.strip()]
            self.stdout.write(f"Including: {', '.join(include_list)}")
        else:
            include_list = None  # None means all
            self.stdout.write("Including: ALL categories")

        self.stdout.write(f"Category variants: {', '.join(variants)}")

        # Validate target path
        if not dry_run:
            if not target_path.exists():
                try:
                    target_path.mkdir(parents=True, exist_ok=True)
                    self.stdout.write(
                        self.style.SUCCESS(f"Created target directory: {target_path}")
                    )
                except Exception as e:
                    raise CommandError(f"Failed to create target directory: {e}")
            elif not target_path.is_dir():
                raise CommandError(
                    f"Target path exists but is not a directory: {target_path}"
                )

        self.stdout.write(f"Target: {target_path}")
        self.stdout.write("=" * 60)

        # Statistics
        stats = {
            "files_copied": 0,
            "files_updated": 0,
            "files_created": 0,
            "bytes_copied": 0,
            "files_skipped": 0,
            "categories_processed": 0,
            "categories_skipped": 0,
            "errors": 0,
            "config_changed": False,
        }

        # 1. Copy sprites from database (do this first to get sprite_dirs list)
        self._sync_sprites(
            target_path, dry_run, stats, include_list, variants, Category
        )

        # 2. Copy style files
        self._sync_styles(target_path, dry_run, stats)

        # 3. Generate and copy martin.yaml config with sprite paths
        self._sync_config(target_path, dry_run, stats)

        # Validation
        if validate and not dry_run:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("Validating copied files...")
            self._validate_files(target_path, stats)

        # Write marker file indicating if changes were made
        if not dry_run:
            self._write_marker_file(target_path, stats)

        # Print summary
        self._print_summary(stats, dry_run)

    def _sync_styles(self, target_path, dry_run, stats):
        """Copy MapLibre style JSON files."""
        self.stdout.write("\n[2/3] Syncing style files...")

        # Source: tile_server/styles/ in Git repo
        source_dir = Path(settings.BASE_DIR) / "tile_server" / "styles"

        if not source_dir.exists():
            self.stdout.write(
                self.style.WARNING(f"  ⚠ Styles directory not found: {source_dir}")
            )
            return

        # Target: <target>/styles/
        target_dir = target_path / "styles"

        # Find all JSON style files
        style_files = list(source_dir.glob("*.json"))

        if not style_files:
            self.stdout.write(
                self.style.WARNING(f"  ⚠ No style files found in {source_dir}")
            )
            return

        self.stdout.write(f"  Found {len(style_files)} style file(s)")

        for style_file in sorted(style_files):
            target_file = target_dir / style_file.name
            self._copy_file(
                style_file,
                target_file,
                target_dir,
                dry_run,
                stats,
                label=f"style: {style_file.stem}",
            )

    def _sync_config(self, target_path, dry_run, stats):
        """Generate and copy martin.yaml config file with sprite paths."""
        self.stdout.write("\n[3/3] Generating config file...")

        # Source: tile_server/config/martin.yaml in Git repo
        # BASE_DIR is already the repo root (wodore-backend/)
        source_file = Path(settings.BASE_DIR) / "tile_server" / "config" / "martin.yaml"

        if not source_file.exists():
            self.stdout.write(
                self.style.WARNING(f"  ⚠ Config file not found: {source_file}")
            )
            stats["errors"] += 1
            return

        # Read source config as YAML
        try:
            with open(source_file, "r") as f:
                config = yaml.safe_load(f)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"  ✗ Failed to parse config YAML: {e}"))
            stats["errors"] += 1
            return

        # Generate sprite paths based on synced directories
        sprite_dirs = stats.get("sprite_dirs", [])
        if sprite_dirs:
            if "sprites" not in config:
                config["sprites"] = {}

            # Generate sprite paths (Martin will auto-discover sprite names from directories)
            sprite_paths = []
            for sprite_dir in sorted(sprite_dirs):
                sprite_paths.append(
                    f"${{MARTIN_SYNC_MOUNT:-/martin_sync}}/sprites/{sprite_dir}"
                )

            config["sprites"]["paths"] = sprite_paths

            self.stdout.write(f"  Generated {len(sprite_dirs)} sprite paths:")
            for sprite_dir in sorted(sprite_dirs):
                self.stdout.write(f"    - {sprite_dir}")
        else:
            # No sprites synced - remove paths field or set to empty list
            if "sprites" in config and "paths" in config["sprites"]:
                del config["sprites"]["paths"]
            self.stdout.write(
                "  No sprite directories synced, paths field removed from config"
            )

        # Target: <target>/config/martin.yaml
        target_dir = target_path / "config"
        target_file = target_dir / "martin.yaml"

        # Write generated config
        if not dry_run:
            try:
                target_dir.mkdir(parents=True, exist_ok=True)

                # Check if config changed by comparing content
                config_existed = target_file.exists()
                config_changed = True
                if config_existed:
                    with open(target_file, "r") as f:
                        old_config = yaml.safe_load(f)
                    config_changed = old_config != config

                with open(target_file, "w") as f:
                    yaml.dump(config, f, default_flow_style=False, sort_keys=False)

                if config_changed:
                    verb = "Updated" if config_existed else "Created"
                    self.stdout.write(
                        self.style.SUCCESS(f"  ✓ {verb} config file: {target_file}")
                    )
                    stats["config_changed"] = True
                    if config_existed:
                        stats["files_updated"] += 1
                    else:
                        stats["files_created"] += 1
                else:
                    self.stdout.write(f"  ✓ Config unchanged: {target_file}")

                stats["files_copied"] += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  ✗ Failed to write config: {e}"))
                stats["errors"] += 1
        else:
            self.stdout.write("  Would generate config file:")
            self.stdout.write(f"  → {target_file}")
            stats["files_copied"] += 1

    def _sync_sprites(
        self, target_path, dry_run, stats, include_list, variants, Category
    ):
        """Copy sprite SVG files from database (Category -> Symbol -> svg_file)."""
        self.stdout.write("\n[1/3] Syncing sprites from database...")

        # Get root categories (no parent)
        root_categories = Category.objects.filter(
            is_active=True, parent=None
        ).select_related("symbol_detailed", "symbol_simple", "symbol_mono")

        # Filter by include_list if specified
        if include_list is not None:
            root_categories = [
                cat for cat in root_categories if cat.slug in include_list
            ]

        if not root_categories:
            self.stdout.write(
                self.style.WARNING("  ⚠ No root categories found to sync")
            )
            return

        self.stdout.write(f"  Found {len(root_categories)} root categories")

        # Target: <target>/sprites/
        target_base_dir = target_path / "sprites"

        # Track sprite directories for config generation
        sprite_dirs = []

        # Process each root category
        for root_category in root_categories:
            self.stdout.write(f"\n  Processing root category: {root_category.slug}")

            # Track files copied for this category
            files_before = stats["files_copied"]

            # Sync the root category itself
            self._sync_category_sprites(
                root_category,
                target_base_dir,
                variants,
                dry_run,
                stats,
                parent_slug=root_category.slug,
            )

            # Get all children of this root category
            children = Category.objects.filter(
                is_active=True, parent=root_category
            ).select_related("symbol_detailed", "symbol_simple", "symbol_mono")

            if children.exists():
                self.stdout.write(f"    Found {children.count()} children")
                for child in children:
                    self._sync_category_sprites(
                        child,
                        target_base_dir,
                        variants,
                        dry_run,
                        stats,
                        parent_slug=root_category.slug,
                    )

            # Only track this sprite directory if we actually copied files
            files_after = stats["files_copied"]
            files_copied_for_category = files_after - files_before
            if files_copied_for_category > 0:
                sprite_dirs.append(root_category.slug)
                self.stdout.write(
                    f"    ✓ Added {root_category.slug} to sprite config ({files_copied_for_category} files)"
                )
            else:
                self.stdout.write(
                    f"    ⚠ No sprites found for {root_category.slug}, skipping from config"
                )

        # Store sprite directories for config generation
        stats["sprite_dirs"] = sprite_dirs

    def _sync_category_sprites(
        self, category, target_base_dir, variants, dry_run, stats, parent_slug
    ):
        """
        Sync all style variants for a single category.

        Structure:
        - Root category: {parent_slug}/{variant}/{parent_slug}.svg
        - Child category: {parent_slug}/{variant}/{child_slug}.svg

        Args:
            category: Category instance to sync
            target_base_dir: Base sprites directory (e.g., ./martin_sync/sprites/)
            styles: List of styles to sync
            parent_slug: Root category slug (used as sprite collection name)
        """
        stats["categories_processed"] += 1

        # Filename is always the category's own slug
        filename = f"{category.slug}.svg"

        # Track if we copied any files for this category
        copied_any = False

        # Process each variant
        for variant in variants:
            # Get symbol for this variant
            symbol_field = f"symbol_{variant}"
            symbol = getattr(category, symbol_field, None)

            if symbol is None:
                # No symbol for this variant - skip silently
                continue

            # Get SVG file path
            if not symbol.svg_file:
                self.stdout.write(
                    self.style.WARNING(
                        f"    ⚠ {category.slug}: {variant} symbol has no svg_file"
                    )
                )
                continue

            try:
                source_file = Path(symbol.svg_file.path)
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(
                        f"    ⚠ {category.slug}: {variant} svg_file path error: {e}"
                    )
                )
                continue

            if not source_file.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"    ⚠ {category.slug}: {variant} svg_file not found: {source_file}"
                    )
                )
                continue

            # Build target path: {parent_slug}/{variant}/{slug}.svg
            target_dir = target_base_dir / parent_slug / variant
            target_file = target_dir / filename

            # Copy file
            self._copy_file(
                source_file,
                target_file,
                target_dir,
                dry_run,
                stats,
                label=f"{category.slug} ({variant})",
            )
            copied_any = True

        if not copied_any:
            stats["categories_skipped"] += 1

    def _copy_file(
        self, source_file, target_file, target_dir, dry_run, stats, label=None
    ):
        """Copy a single file from source to target."""
        indent = "  "

        # Use label if provided, otherwise use filename
        display_name = label if label else source_file.name

        # Check if target exists - always overwrite to keep files in sync
        if target_file.exists():
            action = "Updating" if not dry_run else "Would update"
        else:
            action = "Copying" if not dry_run else "Would copy"

        # Get file size
        file_size = source_file.stat().st_size
        size_kb = file_size / 1024
        size_str = f"{size_kb:.1f} KB"

        if dry_run:
            self.stdout.write(f"{indent}{action} {display_name} ({size_str})")
            self.stdout.write(f"{indent}  → {target_file}")
            stats["files_copied"] += 1
            stats["bytes_copied"] += file_size
            return

        # Create target directory if needed
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(
                    f"{indent}✗ Failed to create directory {target_dir}: {e}"
                )
            )
            stats["errors"] += 1
            return

        # Copy file
        try:
            existed = target_file.exists()
            file_changed = True

            # Check if file changed by comparing content
            if existed:
                import filecmp

                # Copy to temp location for comparison
                temp_target = target_file.parent / f".tmp_{target_file.name}"
                shutil.copy2(source_file, temp_target)
                file_changed = not filecmp.cmp(temp_target, target_file, shallow=False)
                if file_changed:
                    shutil.move(temp_target, target_file)
                else:
                    temp_target.unlink()
            else:
                shutil.copy2(source_file, target_file)

            if file_changed:
                if existed:
                    verb = "✓ Updated"
                    stats["files_updated"] += 1
                else:
                    verb = "✓ Copied"
                    stats["files_created"] += 1
                self.stdout.write(
                    self.style.SUCCESS(f"{indent}{verb} {display_name} ({size_str})")
                )
            else:
                # File unchanged, don't show as success
                pass

            stats["files_copied"] += 1
            stats["bytes_copied"] += file_size
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f"{indent}✗ Failed to copy {display_name}: {e}")
            )
            stats["errors"] += 1

    def _write_marker_file(self, target_path, stats):
        """Write a marker file with timestamp - only updated if changes were made."""
        from datetime import datetime

        marker_file = target_path / ".martin_sync_last_changed"
        changes_made = (
            stats["files_created"] > 0
            or stats["files_updated"] > 0
            or stats["config_changed"]
        )

        if changes_made:
            # Write timestamp - changes detected
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            with open(marker_file, "w") as f:
                f.write(f"Last modified: {timestamp}\n")
            self.stdout.write(f"\n✓ Updated marker file: {marker_file}")
        else:
            # Don't update marker file - no changes
            if marker_file.exists():
                self.stdout.write("\n✓ Marker file unchanged (no changes detected)")
            else:
                # First run with no changes - create marker anyway
                timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                with open(marker_file, "w") as f:
                    f.write(f"Last modified: {timestamp}\n")
                self.stdout.write(f"\n✓ Created marker file: {marker_file}")

    def _validate_files(self, target_path, stats):
        """Validate that all files were copied successfully."""
        validation_errors = 0

        # Check config
        config_file = target_path / "config" / "martin.yaml"
        if not config_file.exists():
            self.stderr.write(
                self.style.ERROR(f"  ✗ Config file missing: {config_file}")
            )
            validation_errors += 1
        elif not config_file.is_file():
            self.stderr.write(
                self.style.ERROR(f"  ✗ Config path is not a file: {config_file}")
            )
            validation_errors += 1
        else:
            self.stdout.write(f"  ✓ Config file exists: {config_file}")

        # Check sprites directory
        sprites_dir = target_path / "sprites"
        if sprites_dir.exists():
            svg_files = list(sprites_dir.glob("**/*.svg"))
            if svg_files:
                self.stdout.write(
                    f"  ✓ Sprites directory exists with {len(svg_files)} SVG files"
                )
            else:
                self.stdout.write(
                    self.style.WARNING("  ⚠ Sprites directory exists but is empty")
                )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "  ⚠ Sprites directory not found (may be intentional)"
                )
            )

        if validation_errors > 0:
            stats["errors"] += validation_errors
            self.stderr.write(
                self.style.ERROR(f"\nValidation failed with {validation_errors} errors")
            )
        else:
            self.stdout.write(self.style.SUCCESS("\n✓ Validation successful"))

    def _print_summary(self, stats, dry_run):
        """Print summary statistics."""
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Summary:")

        if not dry_run:
            self.stdout.write(f"  Files created:        {stats['files_created']}")
            self.stdout.write(f"  Files updated:        {stats['files_updated']}")
            files_unchanged = (
                stats["files_copied"] - stats["files_created"] - stats["files_updated"]
            )
            self.stdout.write(f"  Files unchanged:      {files_unchanged}")
        else:
            self.stdout.write(f"  Files to process:     {stats['files_copied']}")

        if stats["bytes_copied"] > 0:
            total_mb = stats["bytes_copied"] / (1024 * 1024)
            total_size = (
                f"{total_mb:.2f} MB"
                if total_mb >= 1
                else f"{stats['bytes_copied'] / 1024:.1f} KB"
            )
            self.stdout.write(f"  Total size:           {total_size}")

        self.stdout.write(f"  Categories processed: {stats['categories_processed']}")

        if stats["categories_skipped"] > 0:
            self.stdout.write(
                f"  Categories skipped:   {stats['categories_skipped']} (no sprites)"
            )

        if stats["errors"] > 0:
            self.stdout.write(
                self.style.ERROR(f"  Errors:               {stats['errors']}")
            )

        self.stdout.write("=" * 60)

        # Determine if changes were made
        changes_made = (
            stats["files_created"] > 0
            or stats["files_updated"] > 0
            or stats["config_changed"]
        )

        if not dry_run and stats["errors"] == 0:
            if changes_made:
                self.stdout.write(
                    self.style.SUCCESS(
                        "\n✓ Sync completed with changes!\n\n"
                        "⚠️  RESTART REQUIRED: Martin needs to be restarted to load the updated assets.\n\n"
                        "Next steps:\n"
                        "  Local: docker-compose restart martin\n"
                        "  Kubernetes: kubectl rollout restart deployment martin\n"
                        "  Verify: curl http://martin-service:3000/catalog"
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        "\n✓ Sync completed - no changes detected.\n"
                        "All files are up to date. No restart needed."
                    )
                )
        elif stats["errors"] > 0:
            self.stderr.write(
                self.style.ERROR(
                    f"\n✗ Sync completed with {stats['errors']} errors. "
                    "Please check the output above for details."
                )
            )
