"""Import icon packs from pluggable upstream sources.

openspec: icon-library — one idempotent command per source:

    icon_import --source fluent --ref <pin>   # Fluent Emoji (MIT)
    icon_import --source noto  --ref <pin>    # Noto Emoji (Apache-2.0)

Sources plug in via ``server.apps.symbols.icon_sources`` (adding one is
a new plugin module + registry entry — no schema, API, or command
change). The generic pipeline for every source:

- SVGs become pack-prefixed ``Symbol`` rows (styles per source),
  mirroring the meteo importers' asset naming.
- ``Icon`` rows keep the clean upstream slug (so the same slug can
  exist across packs) with the OPTIONAL unicode hexcode (joined
  against emojibase by emoji sources; identity stays the slug).
- Emoji sources attach localized keywords (emojibase-data,
  de/en/fr/it) and the CLDR taxonomy (``emoji`` root → groups →
  subgroups as localized ``Category`` rows).
- Re-running at the same ref creates no duplicates; pinned refs and
  licenses are recorded (``SymbolCollection.extra``, ``Symbol.license``).
"""

import json
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from django_admin_runner import register_command

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from server.apps.categories.models import Category
from server.apps.licenses.models import License
from server.apps.organizations.models import Organization
from server.apps.symbols.icon_data import (
    DEFAULT_LOCALES,
    EMOJIBASE_VERSION,
    fold_keyword,
    normalize_hexcode,
)
from server.apps.symbols.icon_sources import SOURCES, IconSource
from server.apps.symbols.icon_sources.base import slugify
from server.apps.symbols.models import Icon, IconKeyword, Symbol, SymbolCollection

EMOJIBASE_URL = "https://cdn.jsdelivr.net/npm/emojibase-data@{version}/{path}"


def _read_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


@register_command(group="Symbols")
class Command(BaseCommand):
    help = (
        "Import an icon pack from an upstream source at a pinned ref "
        "into the icon library (openspec: icon-library)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            choices=sorted(SOURCES),
            help=f"Upstream source: {', '.join(sorted(SOURCES))}",
        )
        parser.add_argument(
            "--ref",
            required=True,
            help="Pinned upstream ref (tag, branch or SHA) of the source",
        )
        parser.add_argument(
            "--locales",
            default=",".join(DEFAULT_LOCALES),
            help="Comma-separated keyword locales (default: de,en,fr,it)",
        )
        parser.add_argument(
            "--emojibase-version",
            default=EMOJIBASE_VERSION,
            help=f"emojibase-data version for keyword sources "
            f"(default: {EMOJIBASE_VERSION})",
        )
        parser.add_argument(
            "--data-dir",
            default=None,
            help=(
                "Use pre-downloaded data from this directory instead of "
                "downloading (layout: <source>/..., emojibase/)"
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without writing",
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.source: IconSource = SOURCES[options["source"]]
        spec = self.source.spec
        self.ref = options["ref"]
        self.locales = [
            loc.strip().lower() for loc in options["locales"].split(",") if loc.strip()
        ]
        self.emojibase_version = options["emojibase_version"]
        self.stats = {
            "symbols_created": 0,
            "symbols_reused": 0,
            "icons_created": 0,
            "icons_updated": 0,
            "keywords_created": 0,
            "keywords_deleted": 0,
            "categories_created": 0,
        }
        self.unmatched: list[str] = []

        base_dir = (
            Path(options["data_dir"]) if options["data_dir"] else self._download()
        )
        source_dir = self.source.source_dir(base_dir)
        if not source_dir.is_dir():
            raise CommandError(f"Source data not found: {source_dir}")
        emojibase_dir = base_dir / "emojibase"

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes"))

        self.entries: dict[str, dict] = {}
        if spec.needs_emojibase:
            self.entries = self._load_emojibase(emojibase_dir)
            self.stdout.write(
                f"emojibase: {len(self.entries)} emoji entries, "
                f"locales: {', '.join(self.locales)}"
            )

        with transaction.atomic():
            self.license = self._get_or_create_license(spec.license)
            self.pack = self._get_or_create_pack(spec)

            self.subgroups: dict[int, Category] = {}
            if spec.needs_emojibase:
                self.subgroups = self._get_or_create_taxonomy(emojibase_dir)

            self._import_candidates(source_dir)

        self._report()

    # ------------------------------------------------------------------
    # Download / extraction
    # ------------------------------------------------------------------

    def _download(self) -> Path:
        """Download and extract the source (and keyword data)."""
        spec = self.source.spec
        cache = (
            Path(tempfile.gettempdir())
            / f"wodore-icon-{spec.key}-{self.ref.replace('/', '-')}"
            f"-emojibase-{self.emojibase_version}"
        )
        cache.mkdir(parents=True, exist_ok=True)

        self._fetch(spec.repo_url.format(ref=self.ref), cache / f"{spec.key}.tar.gz")
        self._extract(
            cache / f"{spec.key}.tar.gz", cache / spec.key, spec.extract_marker
        )
        if spec.needs_emojibase:
            self._fetch_emojibase(cache / "emojibase")
        return cache

    def _fetch(self, url: str, dest: Path) -> None:
        if dest.exists() and dest.stat().st_size > 0:
            self.stdout.write(f"cached: {dest.name}")
            return
        self.stdout.write(f"downloading: {url}")
        request = urllib.request.Request(
            url, headers={"User-Agent": "wodore-backend icon_import"}
        )
        with urllib.request.urlopen(request) as response, dest.open("wb") as handle:
            shutil.copyfileobj(response, handle)

    def _extract(self, archive: Path, dest: Path, marker: str) -> None:
        """Extract a repo tarball, flattened so ``dest/<marker>`` exists.

        GitHub archives carry a single top-level directory
        (``<repo>-<ref>/``); its children are moved up one level.
        """
        if dest.is_dir() and any(dest.iterdir()):
            return
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tar:
            # filter="data" rejects absolute paths/.. traversal — safe.
            tar.extractall(dest, filter="data")
        top = [p for p in dest.iterdir() if p.is_dir()]
        if len(top) == 1 and (top[0] / marker).exists():
            for child in top[0].iterdir():
                shutil.move(str(child), str(dest / child.name))
            top[0].rmdir()

    def _fetch_emojibase(self, dest: Path) -> None:
        """Fetch pinned emojibase-data JSON files (small, per-locale)."""
        (dest / "meta").mkdir(parents=True, exist_ok=True)
        self._fetch(
            EMOJIBASE_URL.format(
                version=self.emojibase_version, path="meta/groups.json"
            ),
            dest / "meta" / "groups.json",
        )
        for locale in self.locales:
            (dest / locale).mkdir(parents=True, exist_ok=True)
            for name in ("data.json", "messages.json"):
                self._fetch(
                    EMOJIBASE_URL.format(
                        version=self.emojibase_version, path=f"{locale}/{name}"
                    ),
                    dest / locale / name,
                )

    # ------------------------------------------------------------------
    # emojibase parsing
    # ------------------------------------------------------------------

    def _load_emojibase(self, emojibase_dir: Path) -> dict[str, dict]:
        """Parse emojibase-data into hexcode-joined entries.

        Returns ``{normalized_hexcode: {...}}`` where each entry carries
        the English slug/name (falling back to the first available
        locale), group/subgroup indices, order and per-locale keywords
        (label + tags). First entry wins on duplicate normalized
        hexcodes (e.g. ``2764`` vs ``2764-FE0F``).
        """
        ordered = [loc for loc in ("en", *self.locales) if loc in self.locales]
        # True components (ZWJ, regional indicators, ...) live in the
        # `component` group — NOT `type: 0`, which is presentation
        # metadata (text-default) and marks ~200 real emoji.
        meta = _read_json(emojibase_dir / "meta" / "groups.json")
        component_idx = next(
            (int(idx) for idx, slug in meta["groups"].items() if slug == "component"),
            None,
        )
        entries: dict[str, dict] = {}
        for locale in ordered:
            data = _read_json(emojibase_dir / locale / "data.json")
            for item in data:
                hexcode = item.get("hexcode")
                if not hexcode:
                    continue
                group = item.get("group")
                if component_idx is not None and group == component_idx:
                    continue
                key = normalize_hexcode(hexcode)
                entry = entries.get(key)
                if entry is None:
                    entry = entries[key] = {
                        "slug": slugify(item["label"]),
                        "name": item["label"],
                        "group": item.get("group"),
                        "subgroup": item.get("subgroup"),
                        "order": item.get("order", 0),
                        "keywords": {},
                    }
                entry["keywords"][locale] = [
                    text
                    for text in (item["label"], *item.get("tags", []))
                    if text and text.strip()
                ]
        return entries

    # ------------------------------------------------------------------
    # Packs / orgs / licenses
    # ------------------------------------------------------------------

    def _get_or_create_license(self, lic: dict) -> License:
        license_obj = License.objects.filter(slug=lic["slug"]).first()
        if license_obj is not None or self.dry_run:
            return license_obj or License(slug=lic["slug"], name=lic["name"])
        license_obj, _ = License.objects.get_or_create(
            slug=lic["slug"],
            defaults={
                "name": lic["name"],
                "fullname": lic["fullname"],
                "url": lic["url"],
                "is_active": True,
            },
        )
        return license_obj

    def _get_or_create_pack(self, spec) -> SymbolCollection:
        organization = Organization.objects.filter(slug=spec.org_slug).first()
        if organization is None and not self.dry_run:
            organization = Organization.objects.create(
                slug=spec.org_slug, name=spec.org_name, is_public=True
            )
        pack = SymbolCollection.objects.filter(slug=spec.pack_slug).first()
        extra = {
            "ref": self.ref,
            "repo_url": spec.repo_url.format(ref=self.ref),
            "emojibase_version": self.emojibase_version
            if spec.needs_emojibase
            else None,
            "license": spec.license["slug"],
        }
        if pack is None:
            if self.dry_run:
                self.stdout.write(
                    f"pack {spec.pack_slug}: would create (ref {self.ref})"
                )
                return SymbolCollection(slug=spec.pack_slug, extra=extra)
            pack = SymbolCollection.objects.create(
                slug=spec.pack_slug,
                source_org=organization,
            )
            self.stdout.write(f"pack {spec.pack_slug}: created (ref {self.ref})")
        if pack.extra != extra:
            pack.extra = extra
            if not self.dry_run:
                pack.save(update_fields=["extra", "modified"])
        return pack

    # ------------------------------------------------------------------
    # Taxonomy (design D4)
    # ------------------------------------------------------------------

    def _get_or_create_taxonomy(self, emojibase_dir: Path) -> dict[int, Category]:
        """Get-or-create the CLDR ``emoji`` Category tree, localized.

        Mirrors the meteo importers' ``_get_or_create_meteo_categories``:
        ``emoji`` root → group categories → subgroup categories, names
        localized from emojibase ``messages.json`` via modeltrans.
        Returns subgroup-index → Category.
        """
        messages = {
            locale: _read_json(emojibase_dir / locale / "messages.json")
            for locale in self.locales
        }

        def localized(kind: str, key: str, english: str) -> tuple[str, dict]:
            """(default-language name, {name_<locale>: ...} i18n dict)."""
            i18n: dict[str, str] = {}
            name = english
            for locale in self.locales:
                rows = messages.get(locale, {}).get(kind, [])
                text = next((row["message"] for row in rows if row["key"] == key), None)
                if text is None:
                    continue
                if locale == "en":
                    name = text
                else:
                    i18n[f"name_{locale}"] = text
            return name, i18n

        root = self._get_or_create_category(
            slug="emoji", parent=None, order=0, name="Emoji", i18n={}
        )

        meta = _read_json(emojibase_dir / "meta" / "groups.json")
        group_slugs = meta["groups"]  # {"0": "smileys-emotion", ...}
        hierarchy = meta["hierarchy"]  # {"0": [subgroup indices]}
        subgroup_rows = messages.get("en", {}).get("subgroups", [])

        subgroups: dict[int, Category] = {}
        for group_idx_str, group_slug in group_slugs.items():
            group_idx = int(group_idx_str)
            group_name, group_i18n = localized("groups", group_slug, group_slug)
            group_cat = self._get_or_create_category(
                slug=group_slug,
                parent=root,
                order=group_idx,
                name=group_name,
                i18n=group_i18n,
            )
            for sub_idx in hierarchy.get(group_idx_str, []):
                row = next(
                    (r for r in subgroup_rows if r.get("order") == sub_idx), None
                )
                if row is None:
                    continue
                sub_name, sub_i18n = localized("subgroups", row["key"], row["key"])
                subgroups[sub_idx] = self._get_or_create_category(
                    slug=row["key"],
                    parent=group_cat,
                    order=sub_idx,
                    name=sub_name,
                    i18n=sub_i18n,
                )
        return subgroups

    def _get_or_create_category(
        self,
        slug: str,
        parent: Category | None,
        order: int,
        name: str,
        i18n: dict,
    ) -> Category:
        # A detached (dry-run) parent cannot take part in a lookup.
        if parent is not None and parent.pk is None:
            category = None
        else:
            category = Category.objects.filter(slug=slug, parent=parent).first()
        if category is None:
            if self.dry_run:
                self.stdout.write(f"  would create category {slug}")
                # Detached instance so the run can proceed without writes.
                return Category(slug=slug, parent=parent, order=order, name=name)
            category = Category.objects.create(
                slug=slug, parent=parent, order=order, name=name
            )
            self.stats["categories_created"] += 1
        updated = False
        if order and category.order != order:
            category.order = order
            updated = True
        if i18n:
            current = category.i18n or {}
            merged = {**current, **{k: v for k, v in i18n.items() if v}}
            if merged != current:
                category.i18n = merged
                updated = True
        if updated and not self.dry_run:
            # Category has no timestamps (plain model): no modified field.
            category.save(update_fields=["order", "i18n"])
        return category

    # ------------------------------------------------------------------
    # Generic import of one source's candidates
    # ------------------------------------------------------------------

    def _import_candidates(self, source_dir: Path) -> None:
        """Walk the source tree and upsert everything generically."""
        spec = self.source.spec
        self.stdout.write(
            f"importing {spec.key} -> pack {spec.pack_slug} from {source_dir} ..."
        )
        for candidate in self.source.iter_candidates(source_dir, self.entries):
            if candidate.entry is None:
                self.unmatched.append(f"{spec.key}:{candidate.slug}")
            icon = self._upsert_icon(
                pack=self.pack,
                slug=candidate.slug,
                entry=candidate.entry,
                unicode_hex=candidate.hexcode,
                fallback_name=candidate.fallback_name,
            )
            for style, svg_path in candidate.styles.items():
                symbol = self._upsert_symbol(
                    pack=self.pack,
                    slug=candidate.slug,
                    style=style,
                    svg_path=svg_path,
                    license_obj=self.license,
                    source_url=spec.web_url.format(ref=self.ref),
                )
                if icon is not None and symbol is not None:
                    self._assign_slot(icon, style, symbol)
        self.stdout.write(f"{spec.key} done")

    # ------------------------------------------------------------------
    # Row upserts
    # ------------------------------------------------------------------

    def _upsert_icon(
        self,
        pack: SymbolCollection,
        slug: str,
        entry: dict | None,
        unicode_hex: str | None,
        fallback_name: str,
    ) -> Icon | None:
        """Create/update one ``Icon`` row (idempotent).

        Curation is admin data (``IconCuratedList``) — the import
        never touches it, so re-imports cannot clobber it.
        """
        defaults = {
            "name": entry["name"] if entry else fallback_name,
            "order": min(entry["order"], 32767) if entry else 32000,
            "is_active": True,
            "unicode": unicode_hex or None,
            "category": (
                self.subgroups.get(entry["subgroup"])
                if entry and entry.get("subgroup") is not None
                else None
            ),
        }
        icon = None
        if not (self.dry_run and pack.pk is None):
            # A detached (dry-run) pack cannot take part in a lookup.
            icon = Icon.objects.filter(pack=pack, slug=slug).first()
        created = icon is None
        if self.dry_run:
            self.stats["icons_created" if created else "icons_updated"] += 1
            return None
        if icon is None:
            icon = Icon(pack=pack, slug=slug, **defaults)
        else:
            for field, value in defaults.items():
                setattr(icon, field, value)
        try:
            icon.clean()  # rejects root categories (design D4)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"icon {pack.slug}:{slug}: {exc}"))
            return None
        icon.save()
        self.stats["icons_created" if created else "icons_updated"] += 1
        if entry:
            self._sync_keywords(icon, entry)
        return icon

    def _assign_slot(self, icon: Icon, style: str, symbol: Symbol) -> None:
        field = f"symbol_{style}"
        if getattr(icon, field) == symbol:
            return
        setattr(icon, field, symbol)
        if not self.dry_run:
            icon.save(update_fields=[field, "modified"])

    def _upsert_symbol(
        self,
        pack: SymbolCollection,
        slug: str,
        style: str,
        svg_path: Path,
        license_obj: License,
        source_url: str,
    ) -> Symbol | None:
        """Create/reuse one pack-prefixed ``Symbol`` row (design D1).

        Existing files are kept when their size matches the incoming
        content — re-runs stay idempotent on disk and asset URLs stay
        stable; a genuinely changed upstream SVG is re-written in place.
        """
        symbol_slug = f"{pack.slug}-{slug}"
        name = f"{symbol_slug}_{style}.svg"
        storage_name = f"symbols/{name}"
        content = svg_path.read_bytes()
        symbol = Symbol.objects.filter(slug=symbol_slug, style=style).first()
        if symbol is not None:
            if self._storage_file_current(storage_name, content) or self.dry_run:
                self.stats["symbols_reused"] += 1
                return symbol
            symbol.svg_file.save(name, ContentFile(content), save=False)
            symbol.save()
            self.stats["symbols_reused"] += 1
            return symbol
        if self.dry_run:
            self.stats["symbols_created"] += 1
            return None
        symbol = Symbol(
            slug=symbol_slug,
            style=style,
            license=license_obj,
            source_org=pack.source_org,
            source_url=source_url,
            source_ident=f"icon_import {pack.slug}",
            review_status=Symbol.ReviewStatusChoices.approved,
            is_active=True,
        )
        symbol.svg_file.save(name, ContentFile(content), save=False)
        symbol.save()
        self.stats["symbols_created"] += 1
        return symbol

    @staticmethod
    def _storage_file_current(storage_name: str, content: bytes) -> bool:
        """True when the stored file exists with the expected size."""
        try:
            return default_storage.exists(storage_name) and default_storage.size(
                storage_name
            ) == len(content)
        except (FileNotFoundError, NotADirectoryError, OSError):
            return False

    def _sync_keywords(self, icon: Icon, entry: dict) -> None:
        """Sync ``IconKeyword`` rows for this icon from emojibase data."""
        wanted: dict[tuple[str, str], str] = {}
        for locale, keywords in entry["keywords"].items():
            if locale not in self.locales:
                continue
            for text in keywords:
                folded = fold_keyword(text)
                if folded:
                    wanted[(locale, folded)] = text
        existing = {
            (kw.locale, kw.keyword_folded): kw
            for kw in icon.keywords.all()  # pyright: ignore[reportAttributeAccessIssue]  # reverse FK: django-stubs gap
        }
        created = 0
        for (locale, folded), text in wanted.items():
            if (locale, folded) not in existing and not self.dry_run:
                IconKeyword.objects.create(
                    icon=icon, locale=locale, keyword=text, keyword_folded=folded
                )
            created += (locale, folded) not in existing
        stale = [kw for key, kw in existing.items() if key not in wanted]
        if stale and not self.dry_run:
            IconKeyword.objects.filter(pk__in=[kw.pk for kw in stale]).delete()
        self.stats["keywords_created"] += created
        self.stats["keywords_deleted"] += len(stale)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _report(self) -> None:
        self.stdout.write(self.style.SUCCESS("Summary:"))
        for key, value in self.stats.items():
            self.stdout.write(f"  {key}: {value}")
        if self.unmatched:
            preview = ", ".join(sorted(self.unmatched)[:20])
            more = " ..." if len(self.unmatched) > 20 else ""
            self.stdout.write(
                self.style.WARNING(
                    f"Icons without keyword-data match "
                    f"({len(self.unmatched)}): {preview}{more}"
                )
            )
