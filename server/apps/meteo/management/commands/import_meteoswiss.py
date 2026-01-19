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
from server.apps.meteo.models import WeatherCode


class Command(BaseCommand):
    help = "Import MeteoSwiss weather icons and codes from CSV"

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
        icons_path = meteoswiss_path / "icons"
        mapping_json_path = meteoswiss_path / "wmo4677mapping.json"

        if not mapping_json_path.exists():
            self.stderr.write(
                self.style.ERROR(f"WMO mapping file not found: {mapping_json_path}")
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
            "codes_created": 0,
            "codes_updated": 0,
            "codes_skipped": 0,
        }

        # Read WMO mapping JSON
        with open(mapping_json_path, "r", encoding="utf-8") as f:
            wmo_mappings = json.load(f)

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
            self._import_data(wmo_mappings, icons_path, dry_run, stats)

        # Print summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Summary:")
        self.stdout.write(f"  Icons downloaded:    {stats['icons_downloaded']}")
        self.stdout.write(f"  Icons skipped:       {stats['icons_skipped']}")
        self.stdout.write(f"  Icons failed:        {stats['icons_failed']}")
        self.stdout.write(f"  Symbols created:     {stats['symbols_created']}")
        self.stdout.write(f"  Symbols skipped:     {stats['symbols_skipped']}")
        self.stdout.write(f"  Codes created:       {stats['codes_created']}")
        self.stdout.write(f"  Codes updated:       {stats['codes_updated']}")
        self.stdout.write(f"  Codes skipped:       {stats['codes_skipped']}")
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

    def _import_data(self, wmo_mappings, icons_path, dry_run, stats):
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

        # Get or create meteo parent category
        meteo_parent = self._get_or_create_meteo_categories(dry_run)

        # Load WMO category mapping
        base_path = Path(__file__).resolve().parent.parent.parent / "assets"
        category_mapping_file = base_path / "wmo_category_mapping.json"
        category_mapping = {}
        if category_mapping_file.exists():
            with open(category_mapping_file, "r") as f:
                category_mapping = json.load(f)

        # Process each icon from the JSON mapping
        for icon_id, mapping in wmo_mappings.items():
            # NEW: wmo_codes is now a list
            wmo_codes = mapping.get(
                "wmo_codes", [mapping.get("wmo_code")]
            )  # Backwards compat
            if not isinstance(wmo_codes, list):
                wmo_codes = [wmo_codes]

            priority = mapping["priority"]
            is_day = mapping.get("is_day", True)

            # Extract descriptions for all available languages
            descriptions = {}
            for lang in all_languages:
                key = f"description_{lang}"
                if key in mapping:
                    descriptions[lang] = mapping[key]
                else:
                    # Fallback to main language if translation missing
                    descriptions[lang] = mapping.get(f"description_{main_language}", "")

            # Create symbol once for this icon
            symbol = self._create_or_get_symbol(
                icon_id, icons_path, license, dry_run, stats
            )

            # Create weather code entry for EACH WMO code
            for wmo_code in wmo_codes:
                # Get category for this specific WMO code
                category = None
                if str(wmo_code) in category_mapping and meteo_parent:
                    category_slug = category_mapping[str(wmo_code)]
                    category = Category.objects.filter(
                        parent=meteo_parent, slug=category_slug
                    ).first()

                # Create weather code
                self._create_or_update_weathercode(
                    organization,
                    icon_id,
                    wmo_code,
                    priority,
                    descriptions,
                    main_language,
                    other_languages,
                    is_day,
                    category,
                    symbol,
                    dry_run,
                    stats,
                )

    def _create_or_get_symbol(self, icon_id, icons_path, license, dry_run, stats):
        """Create or get symbol for MeteoSwiss icon"""
        slug = f"meteoswiss-{icon_id}"
        style = "simple"

        # Check if symbol exists
        if not dry_run:
            existing = Symbol.objects.filter(slug=slug, style=style).first()
            if existing:
                stats["symbols_skipped"] += 1
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
            return None

    def _create_or_update_weathercode(
        self,
        organization,
        icon_id,
        wmo_code,
        priority,
        descriptions,
        main_language,
        other_languages,
        is_day,
        category,
        symbol,
        dry_run,
        stats,
    ):
        """Create or update weather code"""
        # Get main language description
        main_desc = descriptions.get(main_language, "")

        if dry_run:
            stats["codes_created"] += 1
            day_night = "day" if is_day else "night"
            msg = (
                f"  → Would create WMO {wmo_code} (MeteoSwiss {icon_id}, "
                f"priority {priority}, {day_night}): {main_desc}"
            )
            self.stdout.write(msg)
            return

        existing = WeatherCode.objects.filter(
            source_organization=organization, source_id=icon_id
        ).first()

        if existing:
            # Update
            updated = False
            if existing.code != wmo_code:
                existing.code = wmo_code
                updated = True
            if existing.priority != priority:
                existing.priority = priority
                updated = True
            if existing.category != category:
                existing.category = category
                updated = True

            # Update descriptions and symbols based on is_day flag
            # Main language goes into the main field, other languages into i18n
            if is_day:
                # Check if description needs update
                desc_changed = existing.description_day != main_desc
                for lang in other_languages:
                    field_name = f"description_day_{lang}"
                    if getattr(existing, field_name, None) != descriptions.get(
                        lang, ""
                    ):
                        desc_changed = True
                        break

                if desc_changed:
                    existing.description_day = main_desc  # Main language
                    # Update translations using i18n property (other languages)
                    i18n_data = existing.i18n or {}
                    for lang in other_languages:
                        i18n_data[f"description_day_{lang}"] = descriptions.get(
                            lang, ""
                        )
                    existing.i18n = i18n_data
                    updated = True

                if existing.symbol_day != symbol:
                    existing.symbol_day = symbol
                    updated = True
            else:
                # Check if description needs update
                desc_changed = existing.description_night != main_desc
                for lang in other_languages:
                    field_name = f"description_night_{lang}"
                    if getattr(existing, field_name, None) != descriptions.get(
                        lang, ""
                    ):
                        desc_changed = True
                        break

                if desc_changed:
                    existing.description_night = main_desc  # Main language
                    # Update translations using i18n property (other languages)
                    i18n_data = existing.i18n or {}
                    for lang in other_languages:
                        i18n_data[f"description_night_{lang}"] = descriptions.get(
                            lang, ""
                        )
                    existing.i18n = i18n_data
                    updated = True

                if existing.symbol_night != symbol:
                    existing.symbol_night = symbol
                    updated = True

            if updated:
                existing.save()
                stats["codes_updated"] += 1
                day_night = "day" if is_day else "night"
                msg = (
                    f"  ✓ Updated WMO {wmo_code} (MeteoSwiss {icon_id}, "
                    f"priority {priority}, {day_night})"
                )
                self.stdout.write(self.style.SUCCESS(msg))
            else:
                stats["codes_skipped"] += 1
                self.stdout.write(
                    f"  ⊘ Skipped WMO {wmo_code} (MeteoSwiss {icon_id}): no changes"
                )
        else:
            # Create - slug will be auto-generated
            try:
                # Set both day and night to same values initially
                # Will be updated by alternative entries
                # Main language goes into main field, other languages into i18n
                weather_code = WeatherCode(
                    source_organization=organization,
                    source_id=icon_id,
                    code=wmo_code,
                    priority=priority,
                    category=category,
                    description_day=main_desc,  # Main language
                    description_night=main_desc,  # Main language
                    symbol_day=symbol,
                    symbol_night=symbol,
                )
                # Set translations using i18n property (other languages)
                i18n_data = {}
                for lang in other_languages:
                    i18n_data[f"description_day_{lang}"] = descriptions.get(lang, "")
                    i18n_data[f"description_night_{lang}"] = descriptions.get(lang, "")
                weather_code.i18n = i18n_data

                # Save will auto-generate the slug
                weather_code.save()

                stats["codes_created"] += 1
                day_night = "day" if is_day else "night"
                msg = (
                    f"  ✓ Created WMO {wmo_code} (MeteoSwiss {icon_id}, "
                    f"slug: {weather_code.slug}, priority {priority}, "
                    f"{day_night}): {main_desc}"
                )
                self.stdout.write(self.style.SUCCESS(msg))
            except Exception as e:
                msg = f"  ✗ Failed to create WMO {wmo_code} (MeteoSwiss {icon_id}): {e}"
                self.stderr.write(self.style.ERROR(msg))

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
