import json
import time
from pathlib import Path

import httpx
from django.conf import settings
from django.core.files.base import ContentFile
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
    help = "Import MeteoSwiss weather icons and codes from JSON mapping"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--skip-download",
            action="store_true",
            help="Skip downloading icons (use existing files)",
        )
        parser.add_argument(
            "--skip-codes",
            action="store_true",
            help="Skip importing weather codes (only download icons)",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        skip_download = options.get("skip_download", False)
        skip_codes = options.get("skip_codes", False)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        # Base paths
        base_path = Path(__file__).resolve().parent.parent.parent / "assets"
        meteoswiss_path = base_path / "meteoswiss"
        icons_path = meteoswiss_path / "symbols" / "filled"
        mapping_json_path = meteoswiss_path / "wmo4677mapping.json"
        descriptions_json_path = base_path / "wmo_descriptions.json"

        if not mapping_json_path.exists():
            self.stderr.write(
                self.style.ERROR(f"WMO mapping file not found: {mapping_json_path}")
            )
            return

        if not descriptions_json_path.exists():
            self.stderr.write(
                self.style.ERROR(
                    f"WMO descriptions file not found: {descriptions_json_path}"
                )
            )
            return

        # Create icons directory
        if not dry_run and not icons_path.exists():
            icons_path.mkdir(parents=True, exist_ok=True)

        # Statistics
        stats = {
            "icons_downloaded": 0,
            "icons_skipped": 0,
            "icons_failed": 0,
            "symbols_created": 0,
            "symbols_skipped": 0,
            "weather_codes_created": 0,
            "weather_codes_updated": 0,
            "collection_created": False,
            "code_symbols_created": 0,
            "code_symbols_updated": 0,
        }

        # Read WMO mapping JSON and descriptions
        with open(mapping_json_path, "r", encoding="utf-8") as f:
            wmo_mappings = json.load(f)

        with open(descriptions_json_path, "r", encoding="utf-8") as f:
            wmo_descriptions = json.load(f)

        # Download icons
        if not skip_download:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("Downloading MeteoSwiss icons...")
            self.stdout.write("=" * 60)
            self._download_icons(wmo_mappings, icons_path, dry_run, stats)

        # Import symbols and codes
        if not skip_codes:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("Importing MeteoSwiss weather data...")
            self.stdout.write("=" * 60)
            self._import_data(
                wmo_mappings, wmo_descriptions, icons_path, dry_run, stats
            )

        # Print summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Summary:")
        self.stdout.write(f"  Icons downloaded:         {stats['icons_downloaded']}")
        self.stdout.write(f"  Icons skipped:            {stats['icons_skipped']}")
        self.stdout.write(f"  Icons failed:             {stats['icons_failed']}")
        self.stdout.write(f"  Symbols created:          {stats['symbols_created']}")
        self.stdout.write(f"  Symbols skipped:          {stats['symbols_skipped']}")
        self.stdout.write(
            f"  Weather codes created:    {stats['weather_codes_created']}"
        )
        self.stdout.write(
            f"  Weather codes updated:    {stats['weather_codes_updated']}"
        )
        self.stdout.write(
            f"  Collection created:       {'Yes' if stats['collection_created'] else 'No'}"
        )
        self.stdout.write(
            f"  Code symbols created:     {stats['code_symbols_created']}"
        )
        self.stdout.write(
            f"  Code symbols updated:     {stats['code_symbols_updated']}"
        )
        self.stdout.write("=" * 60)

    def _download_icons(self, wmo_mappings, icons_path, dry_run, stats):
        """Download icons from MeteoSwiss"""
        base_url = "https://www.meteoswiss.admin.ch/static/resources/weather-symbols"

        for icon_id in wmo_mappings.keys():
            icon_file = icons_path / f"{icon_id}.svg"

            # Skip if already exists
            if icon_file.exists():
                stats["icons_skipped"] += 1
                self.stdout.write(f"  ⊘ Skipped icon {icon_id}: already exists")
                continue

            if dry_run:
                stats["icons_downloaded"] += 1
                self.stdout.write(f"  → Would download icon {icon_id}")
                continue

            # Download icon
            url = f"{base_url}/{icon_id}.svg"
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(url)
                    response.raise_for_status()

                    # Save to file
                    with open(icon_file, "wb") as f:
                        f.write(response.content)

                    stats["icons_downloaded"] += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"  ✓ Downloaded icon {icon_id}")
                    )

                    # Rate limiting - be nice to MeteoSwiss servers
                    time.sleep(0.5)

            except Exception as e:
                stats["icons_failed"] += 1
                self.stderr.write(
                    self.style.ERROR(f"  ✗ Failed to download icon {icon_id}: {e}")
                )

    def _import_data(self, wmo_mappings, wmo_descriptions, icons_path, dry_run, stats):
        """Import symbols and weather codes"""
        # Get language configuration from settings
        main_language = settings.LANGUAGE_CODE
        all_languages = [lang[0] for lang in settings.LANGUAGES]
        other_languages = [lang for lang in all_languages if lang != main_language]

        other_langs_str = ", ".join(other_languages)
        self.stdout.write(
            f"Using main language: {main_language}, other languages: {other_langs_str}"
        )

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

        # Get or create symbol collection
        collection = self._get_or_create_collection(organization, dry_run, stats)
        if collection is None and not dry_run:
            self.stderr.write(self.style.ERROR("Failed to get/create collection"))
            return

        # Get or create meteo parent category
        meteo_parent = self._get_or_create_meteo_categories(dry_run)

        # Load WMO category mapping
        base_path = Path(__file__).resolve().parent.parent.parent / "assets"
        category_mapping_file = base_path / "wmo_category_mapping.json"
        category_mapping = {}
        if category_mapping_file.exists():
            with open(category_mapping_file, "r") as f:
                category_mapping = json.load(f)

        # Group icons by WMO code and day/night
        wmo_code_mappings = {}  # wmo_code -> {"day": [(icon_id, priority)], "night": [...]}

        for icon_id, mapping in wmo_mappings.items():
            wmo_codes = mapping.get("wmo_codes", [mapping.get("wmo_code")])
            if not isinstance(wmo_codes, list):
                wmo_codes = [wmo_codes]

            priority = mapping["priority"]
            is_day = mapping.get("is_day", True)

            for wmo_code in wmo_codes:
                if wmo_code not in wmo_code_mappings:
                    wmo_code_mappings[wmo_code] = {"day": [], "night": []}

                period = "day" if is_day else "night"
                wmo_code_mappings[wmo_code][period].append((icon_id, priority))

        # Process each WMO code
        for wmo_code in sorted(wmo_code_mappings.keys()):
            periods = wmo_code_mappings[wmo_code]

            # Get category for this WMO code
            category = None
            if str(wmo_code) in category_mapping and meteo_parent:
                category_slug = category_mapping[str(wmo_code)]
                category = Category.objects.filter(
                    parent=meteo_parent, slug=category_slug
                ).first()

            # Get descriptions from wmo_descriptions.json
            wmo_desc = wmo_descriptions.get(str(wmo_code), {})
            descriptions_day = {}
            descriptions_night = {}

            for lang in all_languages:
                descriptions_day[lang] = wmo_desc.get(lang, "")
                descriptions_night[lang] = wmo_desc.get(f"{lang}_night", "")

            # Get best (highest priority) icons for day and night
            day_icons = sorted(periods.get("day", []), key=lambda x: x[1], reverse=True)
            night_icons = sorted(
                periods.get("night", []), key=lambda x: x[1], reverse=True
            )

            best_day_icon_id = day_icons[0][0] if day_icons else None
            best_night_icon_id = night_icons[0][0] if night_icons else None

            # Create or update WeatherCode (universal, no symbols)
            weather_code_obj = self._create_or_update_weathercode(
                wmo_code,
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
                    self.style.ERROR(f"Failed to create WeatherCode {wmo_code}")
                )
                continue

            # Create symbols for best day and night icons
            symbol_day = None
            symbol_night = None

            if best_day_icon_id:
                symbol_day = self._create_or_get_symbol(
                    best_day_icon_id, icons_path, license, organization, dry_run, stats
                )

            if best_night_icon_id:
                symbol_night = self._create_or_get_symbol(
                    best_night_icon_id,
                    icons_path,
                    license,
                    organization,
                    dry_run,
                    stats,
                )

            # Create or update WeatherCodeSymbol (links code to symbols in this collection)
            self._create_or_update_code_symbol(
                weather_code_obj,
                collection,
                symbol_day,
                symbol_night,
                wmo_code,
                dry_run,
                stats,
            )

        # Verify all forecast codes are covered
        if not dry_run:
            self._verify_coverage(collection, stats)

    def _create_or_update_weathercode(
        self,
        wmo_code,
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
            stats["weather_codes_created"] += 1
            msg = (
                f"  → Would create WMO {wmo_code}: {main_desc_day} / {main_desc_night}"
            )
            self.stdout.write(msg)
            return None

        # Check if exists
        existing = WeatherCode.objects.filter(code=wmo_code).first()

        if existing:
            # Update
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
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ Updated WeatherCode WMO {wmo_code}")
                )
            else:
                self.stdout.write(f"  ⊘ Skipped WeatherCode WMO {wmo_code}: no changes")

            return existing
        else:
            # Create
            try:
                weather_code = WeatherCode(
                    code=wmo_code,
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
                msg = f"  ✓ Created WeatherCode WMO {wmo_code} (slug: {weather_code.slug})"
                self.stdout.write(self.style.SUCCESS(msg))
                return weather_code
            except Exception as e:
                msg = f"  ✗ Failed to create WeatherCode {wmo_code}: {e}"
                self.stderr.write(self.style.ERROR(msg))
                return None

    def _create_or_update_code_symbol(
        self,
        weather_code_obj,
        collection,
        symbol_day,
        symbol_night,
        wmo_code,
        dry_run,
        stats,
    ):
        """Create or update WeatherCodeSymbol linking code to symbols in collection"""
        if dry_run:
            stats["code_symbols_created"] += 1
            day_id = symbol_day if isinstance(symbol_day, str) else "?"
            night_id = symbol_night if isinstance(symbol_night, str) else "?"
            msg = f"  → Would link WMO {wmo_code} to day:{day_id}, night:{night_id}"
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
                msg = f"  ✓ Updated symbols for WMO {wmo_code}"
                self.stdout.write(self.style.SUCCESS(msg))
            else:
                self.stdout.write(f"  ⊘ Skipped symbols for WMO {wmo_code}: no changes")
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
                msg = f"  ✓ Linked WMO {wmo_code} to collection symbols"
                self.stdout.write(self.style.SUCCESS(msg))
            except Exception as e:
                msg = f"  ✗ Failed to link WMO {wmo_code}: {e}"
                self.stderr.write(self.style.ERROR(msg))

    def _create_or_get_symbol(
        self, icon_id, icons_path, license, organization, dry_run, stats
    ):
        """Create or get symbol for MeteoSwiss icon"""
        slug = f"meteoswiss-{icon_id}"
        style = "filled"

        # Check if symbol exists
        if not dry_run:
            existing = Symbol.objects.filter(slug=slug, style=style).first()
            if existing:
                return existing

        icon_file = icons_path / f"{icon_id}.svg"

        if not dry_run:
            if not icon_file.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠ Icon file not found for {icon_id}: {icon_file}"
                    )
                )
                return None

            try:
                symbol = Symbol(
                    slug=slug,
                    style=style,
                    search_text=f"meteoswiss {icon_id}",
                    license=license,
                    is_active=True,
                    review_status="approved",
                    source_url="https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/weather-symbols.html",
                    source_org=organization,
                    author="MeteoSwiss",
                    author_url="https://www.meteoswiss.admin.ch/",
                )

                with open(icon_file, "rb") as f:
                    content = f.read()
                    symbol.svg_file.save(
                        f"{icon_id}.svg", ContentFile(content), save=True
                    )

                stats["symbols_created"] += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created symbol {slug}"))
                return symbol
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f"  ✗ Failed to create symbol {slug}: {e}")
                )
                return None
        else:
            stats["symbols_created"] += 1
            self.stdout.write(f"  → Would create symbol {slug}")
            return icon_id  # Return icon_id for dry-run display

    def _get_or_create_collection(self, organization, dry_run, stats):
        """Get or create WeatherCodeSymbolCollection"""
        slug = "meteoswiss-filled"

        if dry_run:
            self.stdout.write(f"Would create collection '{slug}'")
            stats["collection_created"] = True
            return None

        existing = WeatherCodeSymbolCollection.objects.filter(slug=slug).first()
        if existing:
            self.stdout.write(f"Using existing collection '{slug}'")
            return existing

        try:
            collection = WeatherCodeSymbolCollection.objects.create(
                slug=slug, source_org=organization
            )
            stats["collection_created"] = True
            self.stdout.write(self.style.SUCCESS(f"Created collection '{slug}'"))
            return collection
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f"Failed to create collection '{slug}': {e}")
            )
            return None

    def _verify_coverage(self, collection, stats):
        """Verify all forecast codes (0-3, 45-99) are covered in the collection"""
        forecast_codes = set(range(0, 4)) | set(range(45, 100))

        covered = WeatherCodeSymbol.objects.filter(
            collection=collection, weather_code__code__in=forecast_codes
        ).values_list("weather_code__code", flat=True)

        covered_set = set(covered)
        missing = forecast_codes - covered_set

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Coverage Verification:")
        self.stdout.write(f"  Forecast codes covered: {len(covered_set)}/59")

        if missing:
            self.stderr.write(
                self.style.ERROR(f"  ✗ Missing WMO codes: {sorted(missing)}")
            )
            raise Exception(
                f"Incomplete coverage! Missing {len(missing)} forecast codes: {sorted(missing)}"
            )
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ All forecast codes covered!"))

    def _get_or_create_license(self, dry_run):
        """Get or create license for MeteoSwiss data"""
        license = License.objects.filter(slug="open-data-meteoswiss").first()
        if not license and not dry_run:
            license = License.objects.create(
                slug="open-data-meteoswiss",
                name="MeteoSwiss Open Data",
                link="https://www.meteoswiss.admin.ch/services-and-publications/service/open-government-data.html",
                attribution_required=True,
                no_commercial=False,
                is_active=True,
            )
            self.stdout.write(
                self.style.SUCCESS("Created MeteoSwiss Open Data license")
            )
        elif not license and dry_run:
            self.stdout.write("Would create MeteoSwiss Open Data license")
        return license

    def _get_or_create_organization(self, dry_run):
        """Get or create MeteoSwiss organization"""
        org = Organization.objects.filter(slug="meteoswiss").first()
        if not org and not dry_run:
            org = Organization.objects.create(
                slug="meteoswiss",
                name="MeteoSwiss",
                fullname="Federal Office of Meteorology and Climatology MeteoSwiss",
                description="Swiss national weather service",
                url="https://www.meteoschweiz.admin.ch",
                is_active=True,
                is_public=True,
            )
            self.stdout.write(self.style.SUCCESS("Created MeteoSwiss organization"))
        elif not org and dry_run:
            self.stdout.write("Would create MeteoSwiss organization")
        return org

    def _get_or_create_meteo_categories(self, dry_run):
        """Get or create weather categories under meteo parent"""
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
