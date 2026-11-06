"""
Management command to sync Martin tile server assets to a target directory.

This command copies config and sprite SVG files needed by Martin from the database
to a target directory (typically a Kubernetes PVC mount in production).

Usage:
    # Sync default sprite collections (transport, accommodation, spot)
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

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import yaml
from django_admin_runner import register_command

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from server.apps.symbols.svg import sanitize_svg

if TYPE_CHECKING:
    from server.apps.categories.models import Category

#: `${NAME}` / `${NAME:-default}` tokens in passthrough source headers —
#: resolved through the env registry (DB value wins, process-env
#: fallback) at sync time so a key stored in the EnvVar admin reaches
#: Martin without any container-env plumbing. Unresolvable tokens stay
#: verbatim: Martin expands them from its own process env as fallback
#: (``:-`` defaults empty), so an unset registry row degrades to an
#: unauthenticated upstream instead of a broken config.
_HEADER_ENV_TOKEN_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::-[^}]*)?\}")

#: Slug of the map namespace root (geometries migration 0067 seeded the
#: display tree as ``map → super-root (amenity/admin/natural) → contract
#: group → kind``). Sprite collections follow the served styles, not
#: the full tree: ONE collection per contract group
#: (``parent__parent__slug="map"`` — ``accommodation``, ``transport``, …,
#: ``CategoryQuerySet.contract_groups``), named by its slug. Vocabulary
#: roots (``spot``, ``mode``, ``relations``, ``role``, ``uri``, ``emoji`` …)
#: own NO collection (owner decision: nothing outside the map tree is
#: served as map sprites), nor do the ``map`` root and the super-roots
#: themselves (structural domain anchors, no style-referenced icons).
#: Icon names inside a collection are the tree path below ``map`` —
#: ``<domain>.<group>`` for the group's own icon (its identifier),
#: ``<domain>.<group>.<kind>`` for kinds.
_MAP_ROOT_SLUG = "map"


def resolve_passthrough_headers(config: dict[str, Any]) -> list[str]:
    """Substitute `${NAME}` tokens in ``passthrough.sources.*.headers``.

    Scoped to header values on purpose: every other `${…}` in the config
    (``${DATABASE_URL}``, ``${MARTIN_SYNC_MOUNT:-…}``) keeps Martin's own
    env expansion — the env registry is an allowlist for API keys, not a
    general substitution engine. Returns the names actually resolved
    (for logging); never logs values.
    """
    from server.apps.envvars.registry import resolve
    from server.apps.envvars.registry import rows as registry_rows

    resolved_names: list[str] = []
    sources = (config.get("passthrough") or {}).get("sources") or {}
    if not isinstance(sources, dict):
        return resolved_names
    try:
        snapshot = registry_rows()
    except Exception:
        # Degraded registry (SimpleTestCase tests, early boot, cache/DB
        # failure — same rationale as registry.resolve_setting): no
        # substitution, tokens stay verbatim for Martin's own env
        # expansion. Never let a registry hiccup break config generation.
        return resolved_names
    for source in sources.values():
        if not isinstance(source, dict):
            continue  # shorthand URL (string/list) — no headers
        headers = source.get("headers")
        if not isinstance(headers, dict):
            continue
        for name, value in headers.items():
            if not isinstance(value, str) or "${" not in value:
                continue
            for match in _HEADER_ENV_TOKEN_RE.finditer(value):
                resolved = resolve(match.group(1), snapshot)
                if not resolved:
                    continue  # unregistered/blank: leave for Martin's env expansion
                value = value.replace(match.group(0), resolved)
                resolved_names.append(match.group(1))
            headers[name] = value
    return resolved_names


@register_command(group="Huts")
class Command(BaseCommand):
    help = "Sync Martin tile server assets to target directory (e.g., Kubernetes PVC)"

    @override
    def add_arguments(self, parser: CommandParser) -> None:
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
            help="Comma-separated list of sprite collection slugs to include "
            "(contract groups like accommodation,transport). If not "
            "specified, all collections are included.",
        )
        parser.add_argument(
            "--category-variants",
            type=str,
            default="",
            help="Comma-separated list of category variants to sync (e.g., color,primitive,mono). "
            "Default: all available variants",
        )
        parser.add_argument(
            "--merge",
            type=str,
            default="",
            help="Path to YAML file to merge with martin.yaml config. "
            "Useful for environment-specific overrides (e.g., martin_test.yaml for debug settings). "
            "The merge file's settings will override the base config.",
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

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        from server.apps.categories.models import Category
        from server.apps.symbols.models import Symbol

        target_path = Path(options["target"])
        dry_run = options.get("dry_run", False)
        validate = options.get("validate", False)
        include_slugs = options.get("include", "").strip()
        variants_param = options.get("category_variants", "").strip()
        merge_file_path = options.get("merge", "").strip()

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
        stats: dict[str, Any] = {
            "files_copied": 0,
            "files_updated": 0,
            "files_created": 0,
            "bytes_copied": 0,
            "files_skipped": 0,
            "categories_processed": 0,
            "categories_skipped": 0,
            "errors": 0,
            "config_changed": False,
            "files_deleted": 0,
        }

        # 0. Cleanup old sprite files before syncing
        self._cleanup_old_sprites(
            target_path, dry_run, stats, include_list, variants, Category
        )

        # 1. Copy sprites from database (do this first to get sprite_dirs list)
        self._sync_sprites(
            target_path, dry_run, stats, include_list, variants, Category
        )

        # 1b. Copy static sprites (basemap sprites like wd-maps: peak,
        # station markers, rings — referenced root-relative by the
        # backend-served basemap styles, so Martin must serve them too).
        self._sync_static_sprites(target_path, dry_run, stats)

        # 2. Copy font files (TTF for Martin glyph serving)
        # (Styles are no longer synced: the backend serves them from the
        # basemaps registry at /v1/map/styles/<slug>.json — MapLibre styles
        # live in the database now, Martin serves tiles/sprites/fonts only.)
        self._sync_fonts(target_path, dry_run, stats)

        # 3. Generate and copy martin.yaml config with sprite paths
        self._sync_config(target_path, dry_run, stats, merge_file_path)

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

    def _cleanup_old_sprites(
        self,
        target_path: Path,
        dry_run: bool,
        stats: dict[str, Any],
        include_list: list[str] | None,
        variants: list[str],
        Category: type[Category],
    ) -> None:
        """
        Remove old sprite files that are no longer in the database.

        This handles cases where sprite files outlive their categories:
        restructured collections (e.g. the map super-root restructure,
        when contract-group sprites must move out of a collapsed
        ``map/`` directory), renamed identifiers or deleted
        categories/symbols.

        Only removes files in the sprite directories, never touches config or styles.
        """
        self.stdout.write("\n[0/3] Cleaning up old sprite files...")

        # Target: <target>/sprites/
        target_base_dir = target_path / "sprites"

        if not target_base_dir.exists():
            self.stdout.write(
                "  ⚠ Sprites directory does not exist yet, skipping cleanup"
            )
            return

        # Get sprite collections (same filtering as sync) — the walk
        # that defines the expected file set below.
        collections = self._sprite_collections(Category, include_list)

        if not collections:
            self.stdout.write("  ⚠ No sprite collections found, skipping cleanup")
            return

        # Build set of expected file paths (what should exist after sync)
        expected_files = set()

        for collection, children in collections:
            # Collection's own icon (<domain>.<group>) + kind icons
            # (<domain>.<group>.<kind>) — same naming as the sync.
            members: list[tuple[Category, str]] = [
                (collection, f"{collection.identifier}.svg")
            ]
            members += [
                (child, f"{collection.identifier}.{child.slug}.svg")
                for child in children
            ]

            for category, filename in members:
                for variant in variants:
                    symbol_field = f"symbol_{variant}"
                    symbol = getattr(category, symbol_field, None)
                    if symbol and symbol.svg_file:
                        expected_files.add(Path(collection.slug) / variant / filename)

        # Find and remove old files
        files_deleted_count = 0
        for root_category_dir in target_base_dir.iterdir():
            if not root_category_dir.is_dir():
                continue

            for variant_dir in root_category_dir.iterdir():
                if not variant_dir.is_dir():
                    continue

                for sprite_file in variant_dir.iterdir():
                    if not sprite_file.is_file() or not sprite_file.suffix == ".svg":
                        continue

                    # Build relative path for comparison
                    rel_path = sprite_file.relative_to(target_base_dir)

                    # Check if this file should exist
                    if rel_path not in expected_files:
                        if dry_run:
                            self.stdout.write(f"  Would delete: {rel_path}")
                            files_deleted_count += 1
                        else:
                            try:
                                sprite_file.unlink()
                                self.stdout.write(f"  ✓ Deleted old file: {rel_path}")
                                files_deleted_count += 1
                            except Exception as e:
                                self.stderr.write(
                                    self.style.ERROR(
                                        f"  ✗ Failed to delete {rel_path}: {e}"
                                    )
                                )
                                stats["errors"] += 1

        stats["files_deleted"] = files_deleted_count

        if files_deleted_count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Deleted {files_deleted_count} old sprite file(s)"
                )
            )
        else:
            self.stdout.write("  ✓ No old files to remove")

    def _sync_static_sprites(
        self, target_path: Path, dry_run: bool, stats: dict[str, Any]
    ) -> None:
        """Copy static sprite SVG files (basemap sprites like wd-maps).

        ``tile_server/sprites/<name>/`` directories are sprite collections
        authored in the repo (peak/station/ring markers referenced by the
        backend-served basemap styles). They are copied verbatim into the
        martin_sync target and registered in ``sprite_dirs`` so the
        generated martin.yaml serves them (``/sprite/<name>``).

        Their flat layout (SVGs directly in the collection dir, no variant
        subdirectories) keeps them outside ``_cleanup_old_sprites``, which
        only prunes files inside variant dirs.
        """
        self.stdout.write("\n[1b] Syncing static sprites...")

        source_dir = Path(settings.BASE_DIR) / "tile_server" / "sprites"

        if not source_dir.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠ Static sprites directory not found: {source_dir}"
                )
            )
            return

        # Ensure sprite_dirs is initialized in stats
        if "sprite_dirs" not in stats:
            stats["sprite_dirs"] = list[str]()

        for sprite_category_dir in sorted(source_dir.iterdir()):
            if not sprite_category_dir.is_dir():
                continue

            category_name = sprite_category_dir.name
            target_dir = target_path / "sprites" / category_name

            # Register in sprite_dirs for martin.yaml config
            if category_name not in stats["sprite_dirs"]:
                stats["sprite_dirs"].append(category_name)

            svg_files = list(sprite_category_dir.glob("*.svg"))
            self.stdout.write(f"  {category_name}: {len(svg_files)} SVG(s)")

            for svg_file in sorted(svg_files):
                target_file = target_dir / svg_file.name
                self._copy_file(
                    svg_file,
                    target_file,
                    target_dir,
                    dry_run,
                    stats,
                    label=f"static-sprite: {category_name}/{svg_file.stem}",
                )

    def _sync_fonts(
        self, target_path: Path, dry_run: bool, stats: dict[str, Any]
    ) -> None:
        """Copy TTF font files for Martin glyph serving."""
        self.stdout.write("\n[2b] Syncing font files...")

        source_dir = Path(settings.BASE_DIR) / "tile_server" / "fonts"

        if not source_dir.exists():
            self.stdout.write(
                self.style.WARNING(f"  ⚠ Fonts directory not found: {source_dir}")
            )
            return

        target_dir = target_path / "fonts"
        font_files = list(source_dir.glob("*.ttf")) + list(source_dir.glob("*.otf"))

        if not font_files:
            self.stdout.write(
                self.style.WARNING(f"  ⚠ No font files found in {source_dir}")
            )
            return

        self.stdout.write(f"  Found {len(font_files)} font file(s)")

        for font_file in sorted(font_files):
            target_file = target_dir / font_file.name
            self._copy_file(
                font_file,
                target_file,
                target_dir,
                dry_run,
                stats,
                label=f"font: {font_file.stem}",
            )

    def _sync_config(
        self,
        target_path: Path,
        dry_run: bool,
        stats: dict[str, Any],
        merge_file_path: str = "",
    ) -> None:
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

        # Merge additional YAML file if specified
        if merge_file_path:
            merge_file = Path(merge_file_path)
            if not merge_file.exists():
                self.stderr.write(
                    self.style.WARNING(f"  ⚠ Merge file not found: {merge_file}")
                )
            else:
                try:
                    with open(merge_file, "r") as f:
                        merge_config = yaml.safe_load(f)

                    if merge_config:
                        # Deep merge the configs
                        def deep_merge(
                            base: dict[str, Any], override: dict[str, Any]
                        ) -> dict[str, Any]:
                            """Recursively merge override dict into base dict."""
                            result = base.copy()
                            for key, value in override.items():
                                if (
                                    key in result
                                    and isinstance(result[key], dict)
                                    and isinstance(value, dict)
                                ):
                                    result[key] = deep_merge(result[key], value)
                                else:
                                    result[key] = value
                            return result

                        config = deep_merge(config, merge_config)
                        self.stdout.write(
                            self.style.SUCCESS(f"  ✓ Merged config from: {merge_file}")
                        )
                except Exception as e:
                    self.stderr.write(
                        self.style.ERROR(
                            f"  ✗ Failed to merge config from {merge_file}: {e}"
                        )
                    )
                    stats["errors"] += 1

        # Resolve `${NAME}` tokens in passthrough source headers through
        # the env registry (DB value wins, process-env fallback) — an API
        # key stored in the EnvVar admin reaches the GENERATED (gitignored)
        # config without container-env plumbing; Martin's own env expansion
        # stays the fallback for unresolvable tokens.
        resolved_env = resolve_passthrough_headers(config)
        if resolved_env:
            names = ", ".join(sorted(set(resolved_env)))
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Resolved passthrough header env tokens: {names}"
                )
            )

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

        self.stdout.write("  No styles path configured (styles served by the API)")

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

    def _sprite_collections(
        self,
        category_model: type[Category],
        include_list: list[str] | None,
    ) -> list[tuple[Category, list[Category]]]:
        """Resolve sprite collections (contract groups) with their children.

        Exactly the shape the served styles address
        (``/sprite/accommodation,availability``, ``/sprite/transport`` —
        basemaps ``seed_lib``): every contract group under a super-root
        (``parent__parent__slug="map"``) with its direct children (the
        kinds). Vocabulary roots (``spot``, ``mode``, ``relations``, …)
        own no collection — nothing outside the map tree is served as
        map sprites. Icon names are derived from the live tree path
        (see :meth:`_sync_sprites`) so a group moving between domains
        renames its icons without a martin_sync change.
        """
        queryset = category_model.objects.filter(is_active=True)

        collections: list[Category] = list(
            queryset.filter(parent__parent__slug=_MAP_ROOT_SLUG).select_related(
                "parent", "symbol_color", "symbol_primitive", "symbol_mono"
            )
        )

        if include_list is not None:
            collections = [cat for cat in collections if cat.slug in include_list]

        return [
            (
                category,
                list(
                    queryset.filter(parent=category).select_related(
                        "symbol_color", "symbol_primitive", "symbol_mono"
                    )
                ),
            )
            for category in collections
        ]

    def _sync_sprites(
        self,
        target_path: Path,
        dry_run: bool,
        stats: dict[str, Any],
        include_list: list[str] | None,
        variants: list[str],
        Category: type[Category],
    ) -> None:
        """Copy sprite SVG files from database (Category -> Symbol -> svg_file).

        One sprite collection per :meth:`_sprite_collections` entry:
        ``sprites/<group_slug>/<variant>/<icon>.svg``. Icon names are
        the category's tree path below ``map``, derived from the live
        tree at sync time:

        * the group's own icon — its identifier ``<domain>.<group>``
          (e.g. ``transport.transport``);
        * kinds — ``<domain>.<group>.<kind>`` (e.g.
          ``transport.transport.rail``;
          ``amenity.accommodation.hut``). Kinds' 2-segment identifiers
          (``transport.rail``) gain the domain prefix so a
          future group move between super-roots renames consistently.
        """
        self.stdout.write("\n[1/3] Syncing sprites from database...")

        collections = self._sprite_collections(Category, include_list)

        if not collections:
            self.stdout.write(
                self.style.WARNING("  ⚠ No sprite collections found to sync")
            )
            return

        self.stdout.write(f"  Found {len(collections)} sprite collections")

        # Target: <target>/sprites/
        target_base_dir = target_path / "sprites"

        # Track sprite directories for config generation
        sprite_dirs = []

        # Process each collection
        for collection, children in collections:
            self.stdout.write(f"\n  Processing sprite collection: {collection.slug}")

            # Track files copied for this collection
            files_before = stats["files_copied"]

            # The collection's own icon — its identifier (<domain>.<group>)
            self._sync_category_sprites(
                collection,
                target_base_dir,
                variants,
                dry_run,
                stats,
                collection_slug=collection.slug,
                filename=f"{collection.identifier}.svg",
            )

            for child in children:
                self._sync_category_sprites(
                    child,
                    target_base_dir,
                    variants,
                    dry_run,
                    stats,
                    collection_slug=collection.slug,
                    filename=f"{collection.identifier}.{child.slug}.svg",
                )

            # Only track this sprite directory if we actually copied files
            files_after = stats["files_copied"]
            files_copied_for_collection = files_after - files_before
            if files_copied_for_collection > 0:
                sprite_dirs.append(collection.slug)
                self.stdout.write(
                    f"    ✓ Added {collection.slug} to sprite config "
                    f"({files_copied_for_collection} files)"
                )
            else:
                self.stdout.write(
                    f"    ⚠ No sprites found for {collection.slug}, "
                    "skipping from config"
                )

        # Store sprite directories for config generation
        stats["sprite_dirs"] = sprite_dirs

    def _sync_category_sprites(
        self,
        category: Category,
        target_base_dir: Path,
        variants: list[str],
        dry_run: bool,
        stats: dict[str, Any],
        collection_slug: str,
        filename: str,
    ) -> None:
        """
        Sync all style variants for a single category.

        Structure (names come from the caller — the tree-path naming
        documented in ``_sync_sprites``):
        - Group's own icon: {collection_slug}/{variant}/{domain}.{group}.svg
        - Kind: {collection_slug}/{variant}/{domain}.{group}.{kind}.svg

        Args:
            category: Category instance to sync
            target_base_dir: Base sprites directory (e.g., ./martin_sync/sprites/)
            variants: List of style variants to sync
            collection_slug: Sprite collection directory name
            filename: Sprite file name within the variant directory
        """
        stats["categories_processed"] += 1

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

            # Build target path: {collection_slug}/{variant}/{filename}
            target_dir = target_base_dir / collection_slug / variant
            target_file = target_dir / filename

            # Copy file
            self._copy_file(
                source_file,
                target_file,
                target_dir,
                dry_run,
                stats,
                label=f"{category.slug} ({variant})",
                sanitize=True,
            )
            copied_any = True

        if not copied_any:
            stats["categories_skipped"] += 1

    def _copy_file(
        self,
        source_file: Path,
        target_file: Path,
        target_dir: Path,
        dry_run: bool,
        stats: dict[str, Any],
        label: str | None = None,
        sanitize: bool = False,
    ) -> None:
        """Copy a single file from source to target.

        ``sanitize`` runs SVG bytes through
        :func:`server.apps.symbols.svg.sanitize_svg` before comparing /
        writing — sprite SVGs must parse under Martin's strict XML parser
        (the staging ``NoRootNode`` incident: ``ns0:`` prefixes, missing
        root ``xmlns``). Every other file kind copies verbatim.
        """
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
            # SVG sprite bytes go through the sanitizer (None = verbatim copy)
            content = sanitize_svg(source_file.read_bytes()) if sanitize else None

            # Check if file changed by comparing content
            if existed:
                import filecmp

                # Copy to temp location for comparison
                temp_target = target_file.parent / f".tmp_{target_file.name}"
                if content is None:
                    shutil.copy2(source_file, temp_target)
                else:
                    temp_target.write_bytes(content)
                file_changed = not filecmp.cmp(temp_target, target_file, shallow=False)
                if file_changed:
                    shutil.move(temp_target, target_file)
                else:
                    temp_target.unlink()
            else:
                if content is None:
                    shutil.copy2(source_file, target_file)
                else:
                    target_file.write_bytes(content)

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

    def _write_marker_file(self, target_path: Path, stats: dict[str, Any]) -> None:
        """Write a marker file with timestamp - only updated if changes were made."""
        from datetime import datetime, timezone

        marker_file = target_path / ".martin_sync_last_changed"
        changes_made = (
            stats["files_created"] > 0
            or stats["files_updated"] > 0
            or stats["config_changed"]
        )

        def _write_marker(text: str) -> None:
            """Best-effort marker write — an unwritable target must not
            fail an otherwise successful sync."""
            try:
                with open(marker_file, "w") as f:
                    f.write(text)
            except OSError as e:
                self.stderr.write(
                    self.style.WARNING(
                        f"  ⚠ Failed to write marker file {marker_file}: {e}"
                    )
                )

        if changes_made:
            # Write timestamp - changes detected
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            _write_marker(f"Last modified: {timestamp}\n")
            self.stdout.write(f"\n✓ Updated marker file: {marker_file}")
        else:
            # Don't update marker file - no changes
            if marker_file.exists():
                self.stdout.write("\n✓ Marker file unchanged (no changes detected)")
            else:
                # First run with no changes - create marker anyway
                timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                _write_marker(f"Last modified: {timestamp}\n")
                self.stdout.write(f"\n✓ Created marker file: {marker_file}")

    def _validate_files(self, target_path: Path, stats: dict[str, Any]) -> None:
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

    def _print_summary(self, stats: dict[str, Any], dry_run: bool) -> None:
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
            if stats["files_deleted"] > 0:
                self.stdout.write(f"  Files deleted:        {stats['files_deleted']}")
        else:
            self.stdout.write(f"  Files to process:     {stats['files_copied']}")
            if stats["files_deleted"] > 0:
                self.stdout.write(f"  Files to delete:      {stats['files_deleted']}")

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
            or stats["files_deleted"] > 0
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
                        "  Verify: curl http://martin-service:3000/catalog\n\n"
                        "  Asset versions: an immediate martin_asset_watch\n"
                        "  observation was enqueued — it publishes the new\n"
                        "  sprite/font hashes once Martin serves the new\n"
                        "  bytes (after the restart); the recurring q2\n"
                        "  schedule is the backstop."
                    )
                )
                # Content-gated publication: enqueue an observation now;
                # it only publishes when Martin's served bytes actually
                # changed (i.e. after the restart above).
                try:
                    from django_q.tasks import async_task

                    async_task("server.apps.basemaps.tile_assets.run_martin_watcher")
                except Exception as exc:  # enqueue is best-effort
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ⚠ Could not enqueue martin_asset_watch: {exc}"
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
