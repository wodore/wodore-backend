import json
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from server.apps.licenses.models import License
from server.apps.symbols.models import Symbol
from server.apps.organizations.models import Organization
from server.apps.categories.models import Category
from server.apps.meteo.models import (
    WeatherCode,
    WeatherCodeSymbolCollection,
    WeatherCodeSymbol,
)


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
            default="filled,outlined,outlined-mono,filled-animated,outlined-animated",
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
            "weather_codes_created": 0,
            "weather_codes_updated": 0,
            "collections_created": 0,
            "code_symbols_created": 0,
            "code_symbols_updated": 0,
        }

        # Import symbols
        if not skip_symbols:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("Importing weather icons...")
            self.stdout.write("=" * 60)
            self._import_symbols(base_path, styles, dry_run, stats)

        # Import WMO codes (separate process for each style collection)
        if not skip_codes:
            for style in styles:
                self.stdout.write("\n" + "=" * 60)
                self.stdout.write(f"Importing WMO weather codes for {style} style...")
                self.stdout.write("=" * 60)
                self._import_wmo_codes(base_path, style, dry_run, stats)

        # Print summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Summary:")
        self.stdout.write(f"  Symbols created:          {stats['symbols_created']}")
        self.stdout.write(f"  Symbols skipped:          {stats['symbols_skipped']}")
        self.stdout.write(
            f"  Weather codes created:    {stats['weather_codes_created']}"
        )
        self.stdout.write(
            f"  Weather codes updated:    {stats['weather_codes_updated']}"
        )
        self.stdout.write(f"  Collections created:      {stats['collections_created']}")
        self.stdout.write(
            f"  Code symbols created:     {stats['code_symbols_created']}"
        )
        self.stdout.write(
            f"  Code symbols updated:     {stats['code_symbols_updated']}"
        )
        self.stdout.write("=" * 60)

    def _import_symbols(self, base_path, styles, dry_run, stats):
        """Import weather icon symbols from assets/weather-icons/symbols/"""
        # Get or create license
        license = self._get_or_create_license(dry_run)
        if license is None and not dry_run:
            self.stderr.write(self.style.ERROR("Failed to get/create license"))
            return

        # Get or create organization
        organization = self._get_or_create_organization(dry_run)
        if organization is None and not dry_run:
            self.stderr.write(self.style.ERROR("Failed to get/create organization"))
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
                            source_org=organization,
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

    def _import_wmo_codes(self, base_path, style, dry_run, stats):
        """Import WMO weather codes for a specific style collection"""
        # Get language configuration from settings
        main_language = settings.LANGUAGE_CODE
        all_languages = [lang[0] for lang in settings.LANGUAGES]
        other_languages = [lang for lang in all_languages if lang != main_language]

        other_langs_str = ", ".join(other_languages)
        self.stdout.write(
            f"Using main language: {main_language}, other languages: {other_langs_str}"
        )

        # Get or create organization
        organization = self._get_or_create_organization(dry_run)
        if organization is None and not dry_run:
            self.stderr.write(self.style.ERROR("Failed to get/create organization"))
            return

        # Get or create collection for this style
        collection = self._get_or_create_collection(organization, style, dry_run, stats)
        if collection is None and not dry_run:
            self.stderr.write(self.style.ERROR("Failed to get/create collection"))
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

        # Load WMO descriptions with translations
        descriptions_file = base_path / "wmo_descriptions.json"
        wmo_descriptions = {}
        if descriptions_file.exists():
            with open(descriptions_file, "r") as f:
                wmo_descriptions = json.load(f)
        else:
            msg = (
                f"WMO descriptions file not found: {descriptions_file}. "
                "Translations will not be available."
            )
            self.stdout.write(self.style.WARNING(msg))

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
            day_icon = entry["day"]["icon"]
            night_icon = entry["night"]["icon"]

            # Get descriptions from wmo_descriptions.json if available
            code_str = str(code)
            descriptions_day = {}
            descriptions_night = {}

            if code_str in wmo_descriptions:
                for lang in all_languages:
                    descriptions_day[lang] = wmo_descriptions[code_str].get(lang, "")
                    descriptions_night[lang] = wmo_descriptions[code_str].get(
                        f"{lang}_night", ""
                    )
            else:
                # Fallback to English from mapping file
                day_desc = entry["day"]["description"]
                night_desc = entry["night"]["description"]
                for lang in all_languages:
                    descriptions_day[lang] = day_desc
                    descriptions_night[lang] = night_desc

            # Get category
            category = None
            if str(code) in category_mapping and meteo_parent:
                category_slug = category_mapping[str(code)]
                category = Category.objects.filter(
                    parent=meteo_parent, slug=category_slug
                ).first()

            # Create or update universal WeatherCode (without symbols)
            weather_code_obj = self._create_or_update_weathercode(
                code,
                descriptions_day,
                descriptions_night,
                main_language,
                other_languages,
                category,
                dry_run,
                stats,
            )

            if weather_code_obj is None and not dry_run:
                self.stderr.write(
                    self.style.ERROR(f"Failed to create WeatherCode {code}")
                )
                continue

            # Get symbols for this style
            symbol_day = None
            symbol_night = None
            if not dry_run:
                symbol_day = Symbol.objects.filter(
                    slug=f"weather-icons-{day_icon}", style=style
                ).first()
                symbol_night = Symbol.objects.filter(
                    slug=f"weather-icons-{night_icon}", style=style
                ).first()

                if not symbol_day:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ⚠ Day symbol not found: weather-icons-{day_icon} ({style})"
                        )
                    )
                if not symbol_night:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ⚠ Night symbol not found: weather-icons-{night_icon} ({style})"
                        )
                    )

            # Create or update WeatherCodeSymbol (links code to symbols in this collection)
            self._create_or_update_code_symbol(
                weather_code_obj,
                collection,
                symbol_day,
                symbol_night,
                code,
                day_icon,
                night_icon,
                dry_run,
                stats,
            )

        # Verify all forecast codes are covered
        if not dry_run:
            self._verify_coverage(collection, style, stats)

    def _create_or_update_weathercode(
        self,
        code,
        descriptions_day,
        descriptions_night,
        main_language,
        other_languages,
        category,
        dry_run,
        stats,
    ):
        """Create or update universal WeatherCode"""
        main_desc_day = descriptions_day.get(main_language, "")
        main_desc_night = descriptions_night.get(main_language, "")

        if dry_run:
            self.stdout.write(
                f"  → Would ensure WMO {code} exists: {main_desc_day} / {main_desc_night}"
            )
            return None

        # Check if exists
        existing = WeatherCode.objects.filter(code=code).first()

        if existing:
            # Update if needed
            updated = False

            if existing.category != category:
                existing.category = category
                updated = True

            if existing.description_day != main_desc_day:
                existing.description_day = main_desc_day
                updated = True

            if existing.description_night != main_desc_night:
                existing.description_night = main_desc_night
                updated = True

            # Update translations
            i18n_data = existing.i18n or {}
            for lang in other_languages:
                day_key = f"description_day_{lang}"
                night_key = f"description_night_{lang}"

                new_day = descriptions_day.get(lang, "")
                new_night = descriptions_night.get(lang, "")

                if i18n_data.get(day_key) != new_day:
                    i18n_data[day_key] = new_day
                    updated = True

                if i18n_data.get(night_key) != new_night:
                    i18n_data[night_key] = new_night
                    updated = True

            if updated:
                existing.i18n = i18n_data
                existing.save()
                stats["weather_codes_updated"] += 1

            return existing
        else:
            # Create
            try:
                weather_code = WeatherCode(
                    code=code,
                    category=category,
                    description_day=main_desc_day,
                    description_night=main_desc_night,
                )

                # Set translations
                i18n_data = {}
                for lang in other_languages:
                    i18n_data[f"description_day_{lang}"] = descriptions_day.get(
                        lang, ""
                    )
                    i18n_data[f"description_night_{lang}"] = descriptions_night.get(
                        lang, ""
                    )
                weather_code.i18n = i18n_data

                weather_code.save()
                stats["weather_codes_created"] += 1
                msg = f"  ✓ Created WeatherCode WMO {code} (slug: {weather_code.slug})"
                self.stdout.write(self.style.SUCCESS(msg))
                return weather_code
            except Exception as e:
                msg = f"  ✗ Failed to create WeatherCode {code}: {e}"
                self.stderr.write(self.style.ERROR(msg))
                return None

    def _create_or_update_code_symbol(
        self,
        weather_code_obj,
        collection,
        symbol_day,
        symbol_night,
        code,
        day_icon,
        night_icon,
        dry_run,
        stats,
    ):
        """Create or update WeatherCodeSymbol linking code to symbols in collection"""
        if dry_run:
            msg = f"  → Would link WMO {code} to day:{day_icon}, night:{night_icon}"
            self.stdout.write(msg)
            return

        # Check if exists
        existing = WeatherCodeSymbol.objects.filter(
            weather_code=weather_code_obj, collection=collection
        ).first()

        if existing:
            # Update
            updated = False

            if existing.symbol_day != symbol_day:
                existing.symbol_day = symbol_day
                updated = True

            if existing.symbol_night != symbol_night:
                existing.symbol_night = symbol_night
                updated = True

            if updated:
                existing.save()
                stats["code_symbols_updated"] += 1
                msg = f"  ✓ Updated symbols for WMO {code}"
                self.stdout.write(self.style.SUCCESS(msg))
        else:
            # Create
            try:
                code_symbol = WeatherCodeSymbol(
                    weather_code=weather_code_obj,
                    collection=collection,
                    symbol_day=symbol_day,
                    symbol_night=symbol_night,
                )
                code_symbol.save()
                stats["code_symbols_created"] += 1
                msg = f"  ✓ Linked WMO {code} to collection symbols"
                self.stdout.write(self.style.SUCCESS(msg))
            except Exception as e:
                msg = f"  ✗ Failed to link WMO {code}: {e}"
                self.stderr.write(self.style.ERROR(msg))

    def _get_or_create_collection(self, organization, style, dry_run, stats):
        """Get or create WeatherCodeSymbolCollection for this style"""
        slug = f"weather-icons-{style}"

        if dry_run:
            self.stdout.write(f"Would ensure collection '{slug}' exists")
            return None

        existing = WeatherCodeSymbolCollection.objects.filter(slug=slug).first()
        if existing:
            self.stdout.write(f"Using existing collection '{slug}'")
            return existing

        try:
            collection = WeatherCodeSymbolCollection.objects.create(
                slug=slug, source_org=organization
            )
            stats["collections_created"] += 1
            self.stdout.write(self.style.SUCCESS(f"Created collection '{slug}'"))
            return collection
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f"Failed to create collection '{slug}': {e}")
            )
            return None

    def _verify_coverage(self, collection, style, stats):
        """Verify all forecast codes (0-3, 45-99) are covered in the collection"""
        forecast_codes = set(range(0, 4)) | set(range(45, 100))

        covered = WeatherCodeSymbol.objects.filter(
            collection=collection, weather_code__code__in=forecast_codes
        ).values_list("weather_code__code", flat=True)

        covered_set = set(covered)
        missing = forecast_codes - covered_set

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"Coverage Verification ({style}):")
        self.stdout.write(f"  Forecast codes covered: {len(covered_set)}/59")

        if missing:
            self.stderr.write(
                self.style.ERROR(f"  ✗ Missing WMO codes: {sorted(missing)}")
            )
            raise Exception(
                f"Incomplete coverage for {style}! Missing {len(missing)} forecast codes: {sorted(missing)}"
            )
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ All forecast codes covered!"))

    def _get_or_create_license(self, dry_run):
        """Get or create MIT license for weather icons"""
        license = License.objects.filter(slug="mit").first()
        if not license and not dry_run:
            license = License.objects.create(
                slug="mit",
                name="MIT License",
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
        """Get or create Weather Icons organization"""
        org = Organization.objects.filter(slug="weather-icons").first()
        if not org and not dry_run:
            org = Organization.objects.create(
                slug="weather-icons",
                name="Weather Icons",
                fullname="Weather Icons by Basmilius",
                description="Weather icon set by Basmilius",
                url="https://meteocons.com",
                is_active=True,
                is_public=True,
            )
            self.stdout.write(self.style.SUCCESS("Created Weather Icons organization"))
        elif not org and dry_run:
            self.stdout.write("Would create Weather Icons organization")
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
            ("observational", "Observational", "Observational weather phenomena"),
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
