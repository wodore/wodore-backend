import json
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from server.apps.licenses.models import License
from server.apps.symbols.models import Symbol
from server.apps.organizations.models import Organization
from server.apps.categories.models import Category
from server.apps.meteo.models import WeatherCode


class Command(BaseCommand):
    help = "Import weather icons and WMO codes from assets directory"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--skip-symbols",
            action="store_true",
            help="Skip importing symbols (only import WMO codes)",
        )
        parser.add_argument(
            "--skip-codes",
            action="store_true",
            help="Skip importing WMO codes (only import symbols)",
        )
        parser.add_argument(
            "--styles",
            type=str,
            default="detailed,simple,mono",
            help="Comma-separated list of styles to import (default: all styles)",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        skip_symbols = options.get("skip_symbols", False)
        skip_codes = options.get("skip_codes", False)
        styles = [s.strip() for s in options["styles"].split(",") if s.strip()]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        # Base path for assets
        base_path = Path(__file__).resolve().parent.parent.parent / "assets"

        if not base_path.exists():
            self.stderr.write(
                self.style.ERROR(f"Assets directory not found: {base_path}")
            )
            return

        # Statistics
        stats = {
            "symbols_created": 0,
            "symbols_skipped": 0,
            "codes_created": 0,
            "codes_updated": 0,
            "codes_skipped": 0,
        }

        # Import symbols
        if not skip_symbols:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("Importing weather icons...")
            self.stdout.write("=" * 60)
            self._import_symbols(base_path, styles, dry_run, stats)

        # Import WMO codes
        if not skip_codes:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("Importing WMO weather codes...")
            self.stdout.write("=" * 60)
            self._import_wmo_codes(base_path, dry_run, stats)

        # Print summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Summary:")
        self.stdout.write(f"  Symbols created:     {stats['symbols_created']}")
        self.stdout.write(f"  Symbols skipped:     {stats['symbols_skipped']}")
        self.stdout.write(f"  Codes created:       {stats['codes_created']}")
        self.stdout.write(f"  Codes updated:       {stats['codes_updated']}")
        self.stdout.write(f"  Codes skipped:       {stats['codes_skipped']}")
        self.stdout.write("=" * 60)

    def _import_symbols(self, base_path, styles, dry_run, stats):
        """Import weather icon symbols from assets/weather-icons/symbols/"""
        # Get or create license
        license = self._get_or_create_license(dry_run)
        if license is None and not dry_run:
            self.stderr.write(self.style.ERROR("Failed to get/create license"))
            return

        symbols_path = base_path / "weather-icons" / "symbols"
        if not symbols_path.exists():
            self.stderr.write(
                self.style.ERROR(f"Symbols directory not found: {symbols_path}")
            )
            return

        # Import symbols for each style
        for style in styles:
            style_path = symbols_path / style
            if not style_path.exists():
                self.stdout.write(
                    self.style.WARNING(f"Style directory not found: {style_path}")
                )
                continue

            self.stdout.write(f"\nProcessing {style} style...")

            # Get all SVG files in this style directory
            svg_files = sorted(style_path.glob("*.svg"))

            for svg_file in svg_files:
                # Generate slug: weather-icons-{filename-without-extension}
                icon_name = svg_file.stem
                slug = f"weather-icons-{icon_name}"

                # Check if symbol already exists
                existing = Symbol.objects.filter(slug=slug, style=style).first()
                if existing:
                    stats["symbols_skipped"] += 1
                    self.stdout.write(f"  ⊘ Skipped {slug} ({style}): already exists")
                    continue

                # Create symbol
                if not dry_run:
                    try:
                        symbol = Symbol(
                            slug=slug,
                            style=style,
                            search_text=icon_name.replace("-", " "),
                            license=license,
                            is_active=True,
                            review_status="approved",
                            source_url="https://github.com/basmilius/weather-icons",
                            author="Basmilius",
                            author_url="https://github.com/basmilius",
                        )
                        with open(svg_file, "rb") as f:
                            symbol.svg_file.save(svg_file.name, File(f), save=True)
                        stats["symbols_created"] += 1
                        self.stdout.write(
                            self.style.SUCCESS(f"  ✓ Created {slug} ({style})")
                        )
                    except Exception as e:
                        self.stderr.write(
                            self.style.ERROR(f"  ✗ Failed to create {slug}: {e}")
                        )
                else:
                    stats["symbols_created"] += 1
                    self.stdout.write(f"  → Would create {slug} ({style})")

    def _import_wmo_codes(self, base_path, dry_run, stats):
        """Import WMO weather codes from wmo4677mapping.json"""
        # Get or create organization
        organization = self._get_or_create_organization(dry_run)
        if organization is None and not dry_run:
            self.stderr.write(self.style.ERROR("Failed to get/create organization"))
            return

        # Load WMO mapping
        mapping_file = base_path / "weather-icons" / "wmo4677mapping.json"
        if not mapping_file.exists():
            self.stderr.write(
                self.style.ERROR(f"WMO mapping file not found: {mapping_file}")
            )
            return

        with open(mapping_file, "r") as f:
            wmo_data = json.load(f)

        # Load category mapping
        category_mapping_file = base_path / "wmo_category_mapping.json"
        category_mapping = {}
        if category_mapping_file.exists():
            with open(category_mapping_file, "r") as f:
                category_mapping = json.load(f)

        # Get or create meteo categories parent
        meteo_parent = self._get_or_create_meteo_categories(dry_run)

        # Process each weather code
        for entry in wmo_data:
            code = entry["weathercode"]
            day_desc = entry["day"]["description"]
            night_desc = entry["night"]["description"]
            day_icon = entry["day"]["icon"]
            night_icon = entry["night"]["icon"]

            # Get category
            category = None
            if str(code) in category_mapping and meteo_parent:
                category_slug = category_mapping[str(code)]
                category = Category.objects.filter(
                    parent=meteo_parent, slug=category_slug
                ).first()

            # Get symbols
            symbol_day = None
            symbol_night = None
            if not dry_run:
                # Look for detailed style first
                symbol_day = Symbol.objects.filter(
                    slug=f"weather-icons-{day_icon}", style="detailed"
                ).first()
                symbol_night = Symbol.objects.filter(
                    slug=f"weather-icons-{night_icon}", style="detailed"
                ).first()

            # Generate slug
            slug = f"wmo-{code}"

            # Check if code already exists
            existing = None
            if not dry_run:
                existing = WeatherCode.objects.filter(
                    source_organization=organization, code=code
                ).first()

            if existing:
                # Update existing
                updated = False
                if existing.description_day != day_desc:
                    existing.description_day = day_desc
                    updated = True
                if existing.description_night != night_desc:
                    existing.description_night = night_desc
                    updated = True
                if existing.category != category:
                    existing.category = category
                    updated = True
                if existing.symbol_day != symbol_day:
                    existing.symbol_day = symbol_day
                    updated = True
                if existing.symbol_night != symbol_night:
                    existing.symbol_night = symbol_night
                    updated = True

                if updated and not dry_run:
                    existing.save()
                    stats["codes_updated"] += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"  ✓ Updated WMO {code}: {day_desc}")
                    )
                else:
                    stats["codes_skipped"] += 1
                    if dry_run:
                        self.stdout.write(f"  → Would update WMO {code}: {day_desc}")
                    else:
                        self.stdout.write(f"  ⊘ Skipped WMO {code}: no changes")
            else:
                # Create new
                if not dry_run:
                    try:
                        WeatherCode.objects.create(
                            source_organization=organization,
                            source_id=str(code),
                            code=code,
                            slug=slug,
                            category=category,
                            description_day=day_desc,
                            description_night=night_desc,
                            symbol_day=symbol_day,
                            symbol_night=symbol_night,
                        )
                        stats["codes_created"] += 1
                        self.stdout.write(
                            self.style.SUCCESS(f"  ✓ Created WMO {code}: {day_desc}")
                        )
                    except Exception as e:
                        self.stderr.write(
                            self.style.ERROR(f"  ✗ Failed to create WMO {code}: {e}")
                        )
                else:
                    stats["codes_created"] += 1
                    self.stdout.write(f"  → Would create WMO {code}: {day_desc}")

    def _get_or_create_license(self, dry_run):
        """Get or create MIT license for weather icons"""
        license = License.objects.filter(slug="mit").first()
        if not license and not dry_run:
            license = License.objects.create(
                slug="mit",
                name="MIT License",
                url="https://opensource.org/licenses/MIT",
                link="https://opensource.org/licenses/MIT",
                attribution_required=False,
                no_commercial=False,
                is_active=True,
            )
            self.stdout.write(self.style.SUCCESS("Created MIT license"))
        elif not license and dry_run:
            self.stdout.write("Would create MIT license")
        return license

    def _get_or_create_organization(self, dry_run):
        """Get or create Open-Meteo organization"""
        org = Organization.objects.filter(slug="open-meteo").first()
        if not org and not dry_run:
            org = Organization.objects.create(
                slug="open-meteo",
                name="Open-Meteo",
                fullname="Open-Meteo Weather API",
                description="Open-source weather API",
                is_active=True,
                is_public=True,
            )
            self.stdout.write(self.style.SUCCESS("Created Open-Meteo organization"))
        elif not org and dry_run:
            self.stdout.write("Would create Open-Meteo organization")
        return org

    def _get_or_create_meteo_categories(self, dry_run):
        """Get or create weather categories under meteo parent"""
        # Get or create meteo parent category
        meteo_parent = Category.objects.filter(slug="meteo", parent=None).first()
        if not meteo_parent and not dry_run:
            meteo_parent = Category.objects.create(
                slug="meteo",
                name="Weather",
                description="Weather conditions",
                is_active=True,
            )
            self.stdout.write(self.style.SUCCESS("Created 'meteo' parent category"))
        elif not meteo_parent and dry_run:
            self.stdout.write("Would create 'meteo' parent category")
            return None

        # Define weather categories
        weather_categories = [
            ("clear", "Clear", "Clear sky conditions"),
            ("cloudy", "Cloudy", "Cloudy conditions"),
            ("fog", "Fog", "Fog and mist"),
            ("drizzle", "Drizzle", "Light rain"),
            ("rain", "Rain", "Rain"),
            ("snow", "Snow", "Snow"),
            ("shower", "Shower", "Rain showers"),
            ("thunderstorm", "Thunderstorm", "Thunderstorms"),
        ]

        for slug, name, description in weather_categories:
            existing = Category.objects.filter(parent=meteo_parent, slug=slug).first()
            if not existing and not dry_run:
                Category.objects.create(
                    parent=meteo_parent,
                    slug=slug,
                    name=name,
                    description=description,
                    is_active=True,
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Created 'meteo.{slug}' category")
                )
            elif not existing and dry_run:
                self.stdout.write(f"Would create 'meteo.{slug}' category")

        return meteo_parent
