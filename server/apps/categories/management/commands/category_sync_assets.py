from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from server.apps.licenses.models import License
from server.apps.symbols.models import Symbol


class Command(BaseCommand):
    help = "Sync category symbols from optimized assets directory to database. Reads from assets/ and creates/updates Symbol records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ignore",
            action="append",
            dest="ignore",
            help="Ignore categories. Format: 'slug' or 'parent.slug'. Can be used multiple times.",
        )
        parser.add_argument(
            "--styles",
            type=str,
            default="detailed,simple,mono",
            help="Comma-separated list of styles to sync (default: all styles)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force update all symbols, even if slug already matches (re-uploads SVG files)",
        )
        parser.add_argument(
            "--symbol-prefix",
            type=str,
            default="auto",
            help="Symbol slug prefix: 'auto' (default), 'parent', or a custom prefix. "
            "Auto adds parent prefix for generic slugs (unknown, default, generic, etc).",
        )

    def handle(self, *args, **options):
        from server.apps.categories.models import Category

        ignore_patterns = options.get("ignore") or []
        styles = [s.strip() for s in options["styles"].split(",") if s.strip()]
        dry_run = options.get("dry_run", False)
        force = options.get("force", False)
        symbol_prefix = options.get("symbol_prefix", "auto")

        # Validate styles
        valid_styles = ["detailed", "simple", "mono"]
        invalid_styles = [s for s in styles if s not in valid_styles]
        if invalid_styles:
            self.stderr.write(
                self.style.ERROR(
                    f"Invalid styles: {', '.join(invalid_styles)}. "
                    f"Valid styles: {', '.join(valid_styles)}"
                )
            )
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        self.stdout.write(f"Syncing category symbols for styles: {', '.join(styles)}")

        # Get or create Flaticon Premium license
        license = License.objects.filter(slug="flaticon_premium").first()
        if not license:
            license = License(
                slug="flaticon_premium",
                name="Flaticon Premium",
                url="https://www.flaticon.com",
                link="https://www.flaticon.com/legal#nav-flaticon-agreement",
                attribution_required=False,
                no_commercial=False,
                is_active=True,
            )
            if not dry_run:
                license.save()
                self.stdout.write(
                    self.style.SUCCESS("Created Flaticon Premium license")
                )
            else:
                self.stdout.write("Would create Flaticon Premium license")

        # Base path for category asset files
        base_path = Path(__file__).resolve().parent.parent.parent / "assets"

        if not base_path.exists():
            self.stderr.write(
                self.style.ERROR(f"Assets directory not found: {base_path}")
            )
            return

        # Statistics
        stats = {
            "symbols_created": 0,
            "symbols_updated": 0,
            "categories_updated": 0,
            "categories_skipped": 0,
            "categories_ignored": 0,
        }

        # Get all categories
        categories = Category.objects.select_related("parent").all()

        for category in categories:
            # Check if category should be ignored
            if self._should_ignore(category, ignore_patterns):
                stats["categories_ignored"] += 1
                continue

            category_updated = False

            for style in styles:
                # Get the symbol field name for this style
                symbol_field = f"symbol_{style}"

                # Get current symbol
                current_symbol = getattr(category, symbol_field)

                # Determine expected symbol slug
                expected_slug = self._get_expected_slug(category, symbol_prefix)

                # Check if we need to update
                needs_update = False
                if current_symbol is None:
                    needs_update = True
                    reason = "missing symbol"
                elif current_symbol.slug != expected_slug:
                    needs_update = True
                    reason = f"different slug (has '{current_symbol.slug}', expects '{expected_slug}')"
                elif force:
                    needs_update = True
                    reason = "force update"
                else:
                    reason = "already has correct symbol"

                if not needs_update:
                    stats["categories_skipped"] += 1
                    self.stdout.write(
                        f"  ⊘ Skipped {self._get_category_identifier(category)} "
                        f"({style}): {reason}"
                    )
                    continue

                # Find SVG file
                svg_path = self._find_symbol_file(category, style, base_path)

                if svg_path is None:
                    self.stdout.write(
                        f"  ⚠ No SVG file found for {self._get_category_identifier(category)} "
                        f"({style})"
                    )
                    stats["categories_skipped"] += 1
                    continue

                # Get or create symbol
                symbol, created = self._get_or_create_symbol(
                    svg_path, style, expected_slug, license, dry_run, force
                )

                if symbol is None:
                    # Symbol creation failed (should be logged in method)
                    stats["categories_skipped"] += 1
                    continue

                if created:
                    stats["symbols_created"] += 1
                elif force:
                    stats["symbols_updated"] += 1

                # Update category
                if not dry_run:
                    setattr(category, symbol_field, symbol)
                    category_updated = True

                action = "Would update" if dry_run else "Updated"
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {action} {self._get_category_identifier(category)} "
                        f"({style}): {reason}"
                    )
                )

            # Save category if it was updated
            if category_updated and not dry_run:
                category.save()
                stats["categories_updated"] += 1

        # Print summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Summary:")
        self.stdout.write(f"  Symbols created:     {stats['symbols_created']}")
        self.stdout.write(f"  Symbols updated:     {stats['symbols_updated']}")
        self.stdout.write(f"  Categories updated:  {stats['categories_updated']}")
        self.stdout.write(f"  Categories skipped:  {stats['categories_skipped']}")
        self.stdout.write(f"  Categories ignored:  {stats['categories_ignored']}")
        self.stdout.write("=" * 60)

    def _should_ignore(self, category, ignore_patterns):
        """Check if category should be ignored based on ignore patterns."""
        if not ignore_patterns:
            return False

        identifier = self._get_category_identifier(category)

        for pattern in ignore_patterns:
            # Exact match
            if identifier == pattern:
                return True
            # Parent-only match (ignore all children)
            if (
                "." not in pattern
                and category.parent
                and category.parent.slug == pattern
            ):
                return True

        return False

    def _get_category_identifier(self, category):
        """Get category identifier (parent.slug or slug for root categories)."""
        if category.parent:
            return f"{category.parent.slug}.{category.slug}"
        return category.slug

    def _get_expected_slug(self, category, symbol_prefix="auto"):
        """
        Get expected symbol slug for a category.

        Args:
            category: The category instance
            symbol_prefix: One of:
                - 'auto': Add parent prefix for generic slugs (unknown, default, generic, etc)
                - 'parent': Always add parent prefix
                - custom string: Use as custom prefix
                - None or '': No prefix
        """
        # Slugs that should always have parent prefix when using 'auto'
        generic_slugs = {
            "unknown",
            "default",
            "generic",
            "fallback",
            "other",
            "misc",
            "placeholder",
            "empty",
            "low",
            "medium",
            "high",
            "full",
        }

        category_slug = category.slug
        parent_slug = category.parent.slug if category.parent else None

        # Determine the prefix
        prefix = None
        if symbol_prefix == "auto":
            # Auto: add parent prefix for generic slugs or root categories
            if category_slug in generic_slugs or not category.parent:
                prefix = parent_slug
        elif symbol_prefix == "parent":
            # Always use parent prefix if parent exists
            prefix = parent_slug
        elif symbol_prefix:
            # Custom prefix
            prefix = symbol_prefix

        # Build the slug
        if prefix:
            return f"{prefix}_{category_slug}"
        return category_slug

    def _find_symbol_file(self, category, style, base_path):
        """
        Find the SVG file for a category and style.

        Priority:
        1. assets/{parent_slug}/{style}/{child_slug}.svg (for children)
        2. assets/{category_slug}/{style}/{category_slug}.svg (for parents)
        3. assets/generic/{style}/generic.svg (ultimate fallback)
        """
        if category.parent:
            parent_slug = category.parent.slug
            child_slug = category.slug

            # Try child-specific symbol
            specific_path = base_path / parent_slug / style / f"{child_slug}.svg"
            if specific_path.exists():
                return specific_path

            # Fallback to parent symbol
            parent_path = base_path / parent_slug / style / f"{parent_slug}.svg"
            if parent_path.exists():
                return parent_path
        else:
            # Parent category
            category_slug = category.slug
            category_path = base_path / category_slug / style / f"{category_slug}.svg"
            if category_path.exists():
                return category_path

        # Fallback to generic
        generic_path = base_path / "generic" / style / "generic.svg"
        if generic_path.exists():
            return generic_path

        return None

    def _get_or_create_symbol(
        self, svg_path, style, slug, license, dry_run, force=False
    ):
        """
        Get or create a Symbol for a given SVG file path.

        Returns:
            tuple: (symbol, created) where created is True if a new symbol was created
                   or False if an existing symbol was returned/updated
        """
        # Check for existing symbol
        existing = Symbol.objects.filter(slug=slug, style=style).first()

        if existing:
            if force and not dry_run:
                # Update existing symbol's SVG file
                try:
                    # Delete old file
                    existing.svg_file.delete(save=False)
                    # Save new file
                    with open(svg_path, "rb") as f:
                        existing.svg_file.save(svg_path.name, File(f), save=True)
                    self.stdout.write(f"    Updated symbol: {slug} ({style})")
                    return existing, False
                except Exception as e:
                    self.stderr.write(
                        self.style.ERROR(
                            f"    Failed to update symbol {slug} ({style}): {e}"
                        )
                    )
                    return None, False
            else:
                return existing, False

        # Create new symbol
        new_symbol = Symbol(
            slug=slug,
            style=style,
            search_text=slug,
            license=license,
            is_active=True,
            review_status="approved",
        )

        if not dry_run:
            try:
                # Save SVG file
                with open(svg_path, "rb") as f:
                    new_symbol.svg_file.save(svg_path.name, File(f), save=True)

                self.stdout.write(f"    Created symbol: {slug} ({style})")
                return new_symbol, True
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(
                        f"    Failed to create symbol {slug} ({style}): {e}"
                    )
                )
                return None, False
        else:
            self.stdout.write(f"    Would create symbol: {slug} ({style})")
            return new_symbol, True
