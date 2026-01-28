from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from server.apps.licenses.models import License
from server.apps.symbols.models import Symbol


class Command(BaseCommand):
    help = "Import availability categories from assets/availability directory"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing categories and symbols",
        )

    def handle(self, *args, **options):
        from server.apps.categories.models import Category

        dry_run = options.get("dry_run", False)
        force = options.get("force", False)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

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

        # Get or create parent "availability" category
        availability_parent = Category.objects.filter(
            slug="availability", parent__isnull=True
        ).first()

        if availability_parent and not force:
            self.stdout.write(
                self.style.WARNING(
                    "Parent 'availability' category already exists. Use --force to recreate."
                )
            )
            return
        elif availability_parent and force:
            self.stdout.write("Recreating 'availability' category and children...")

        # Availability category names and their order
        availability_types = [
            {"slug": "unknown", "name": "Unknown", "order": 0},
            {"slug": "empty", "name": "Empty", "order": 1},
            {"slug": "low", "name": "Low", "order": 2},
            {"slug": "medium", "name": "Medium", "order": 3},
            {"slug": "high", "name": "High", "order": 4},
            {"slug": "full", "name": "Full", "order": 5},
        ]

        # Base path for availability assets
        base_path = (
            Path(__file__).resolve().parent.parent.parent / "assets" / "availability"
        )

        if not base_path.exists():
            self.stderr.write(
                self.style.ERROR(f"Assets directory not found: {base_path}")
            )
            return

        # Statistics
        stats = {
            "categories_created": 0,
            "symbols_created": 0,
            "categories_updated": 0,
        }

        # Create parent category
        if not availability_parent:
            availability_parent = Category(
                slug="availability",
                name="Availability",
                description="Availability status categories",
                order=0,
                parent=None,
            )
            if not dry_run:
                availability_parent.save()
                stats["categories_created"] += 1
                self.stdout.write(
                    self.style.SUCCESS("Created parent category: availability")
                )
            else:
                self.stdout.write("Would create parent category: availability")
        else:
            # Delete existing child categories if force
            if force and not dry_run:
                Category.objects.filter(parent=availability_parent).delete()
                self.stdout.write("Deleted existing child categories")

        # Create child categories and symbols
        for avail_type in availability_types:
            slug = avail_type["slug"]
            name = avail_type["name"]
            order = avail_type["order"]

            # Check if category already exists
            category = Category.objects.filter(
                slug=slug, parent=availability_parent
            ).first()

            if category and not force:
                self.stdout.write(
                    f"  ⊘ Skipped {slug}: already exists (use --force to recreate)"
                )
                continue

            # Create or update category
            if not category:
                category = Category(
                    slug=slug,
                    name=name,
                    order=order,
                    parent=availability_parent,
                )
                action = "Would create" if dry_run else "Created"
                stats["categories_created"] += 1
            else:
                action = "Would update" if dry_run else "Updated"
                stats["categories_updated"] += 1

            # Create symbols for each style
            for style in ["detailed", "simple", "mono"]:
                svg_path = base_path / style / f"{slug}.svg"

                if not svg_path.exists():
                    self.stdout.write(f"  ⚠ No SVG file found for {slug} ({style})")
                    continue

                # Get or create symbol
                symbol = self._get_or_create_symbol(
                    svg_path, style, slug, license, dry_run
                )

                if symbol:
                    symbol_field = f"symbol_{style}"
                    setattr(category, symbol_field, symbol)
                else:
                    self.stdout.write(
                        f"  ⚠ Failed to create symbol for {slug} ({style})"
                    )

            # Save category
            if not dry_run:
                category.save()

            self.stdout.write(
                self.style.SUCCESS(f"  {action} category: availability.{slug}")
            )

        # Print summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Summary:")
        self.stdout.write(f"  Categories created: {stats['categories_created']}")
        self.stdout.write(f"  Categories updated: {stats['categories_updated']}")
        self.stdout.write(f"  Symbols created:     {stats['symbols_created']}")
        self.stdout.write("=" * 60)

    def _get_or_create_symbol(self, svg_path, style, slug, license, dry_run):
        """Get or create a Symbol for a given SVG file path."""
        # Check for existing symbol
        existing = Symbol.objects.filter(slug=slug, style=style).first()
        if existing:
            return existing

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
                return new_symbol
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(
                        f"    Failed to create symbol {slug} ({style}): {e}"
                    )
                )
                return None
        else:
            self.stdout.write(f"    Would create symbol: {slug} ({style})")
            return new_symbol
