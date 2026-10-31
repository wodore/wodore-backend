from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING, Any, NamedTuple, override

from django_countries.fields import CountryField
from modeltrans.fields import TranslationField

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.contrib.postgres.indexes import GinIndex, GistIndex
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from server.apps.categories.models import Category
from server.apps.images.models import Image
from server.apps.organizations.models import Organization
from server.apps.translations import activate
from server.apps.translations.detect import detect_main_language
from server.core.models import TimeStampedModel
from server.core.utils import UpdateCreateStatus

from ..converters import RESERVED_URL_SEGMENTS, SLUG_GRAMMAR_RE
from ..kinds import (
    DOMAIN_ADMIN,
    DOMAIN_AMENITY,
    DOMAIN_NONE,
    anchor_category,
    contract_for_group,
    kind_root_category,
    place_domain,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from server.apps.geometries.schemas import (
        DedupOptions,
        GeoPlaceBaseInput,
        PlaceTypeInput,
        SourceInput,
    )

    from ._associations import GeoPlaceSourceAssociation
    from ._relation import GeoPlaceRelation


# Substrings of database errors that are worth retrying (locks, deadlocks).
RETRYABLE_DB_MESSAGES = (
    "database is locked",
    "deadlock",
    "could not serialize",
    "database error",
)


class _ReviewStatusChoices(models.TextChoices):
    new = "new", _("New")
    review = "review", _("Review Needed")
    rework = "rework", _("needs rework")
    done = "done", _("Reviewed")


class PlaceTypeSpec(NamedTuple):
    """Resolved category plus its association attributes.

    The schema write path (``GeoPlace.update_or_create``) resolves
    ``place_type_identifiers`` — plain strings or ``PlaceTypeInput``
    entries — into these specs before creating/updating the
    ``GeoPlaceCategory`` rows (OpenSpec
    ``geoplace-capacity-and-types-via-categories``).
    """

    category: Category
    classifier: Category | None
    extra: dict[str, Any]


class GeoPlace(TimeStampedModel):
    """
    Canonical, curated geographic place.
    Can aggregate data from multiple sources (GeoNames, OSM, manual edits).
    """

    # TODO: add index which starts at 10000 or UIID?

    # Translation support
    i18n = TranslationField(
        fields=("name", "description"),
        fallback_language_field="main_language",
    )
    # Source language of this place's texts; all other languages are
    # translated from it (see `app update_translations`).
    main_language = models.CharField(
        max_length=10,
        choices=settings.LANGUAGES,
        default=settings.LANGUAGE_CODE,
        verbose_name=_("Main language"),
        help_text=_(
            "Language of the original texts; other languages are translated from it."
        ),
    )

    name = models.CharField(max_length=200, blank=True, verbose_name=_("Name"))
    name_i18n: str  # for typing

    # Identification
    slug = models.SlugField(
        max_length=15,
        unique=True,
        db_index=True,
        verbose_name=_("Slug"),
        help_text=_("Unique URL identifier (max 15 chars)"),
        blank=True,
    )

    # Classification
    categories = models.ManyToManyField(
        Category,
        through="GeoPlaceCategory",
        through_fields=("geo_place", "category"),
        related_name="geo_places",
        verbose_name=_("Categories"),
        help_text=_("Category associations for this place"),
    )

    # Location
    location = models.PointField(srid=4326, spatial_index=True)
    shape = models.PolygonField(
        srid=4326,
        null=True,
        blank=True,
        spatial_index=True,
        verbose_name=_("Shape"),
        help_text=_(
            "Optional polygon geometry for natural features or administrative areas"
        ),
    )
    elevation = models.IntegerField(null=True, blank=True)
    country_code = CountryField(db_index=True)

    importance = models.SmallIntegerField(
        default=25,
        db_index=True,
        verbose_name=_("Importance"),
        help_text=_("Higher values = more important (0-100 scale)"),
    )

    # Description (translated)
    description = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Description"),
        help_text=_("Long-form text description"),
    )
    description_i18n: str

    # LLM quality score (1-10) of the main-language description;
    # NULL = never assessed (see `app assess_descriptions`).
    description_quality = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        verbose_name=_("Description quality"),
        help_text=_(
            "LLM quality score of the description: 1 = low (thin/marketing "
            "text), 10 = excellent. Empty means not assessed yet."
        ),
    )
    description_quality_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Description quality assessed at"),
    )

    # Review workflow
    ReviewStatusChoices = _ReviewStatusChoices
    review_status = models.CharField(
        max_length=20,
        choices=ReviewStatusChoices.choices,
        default=ReviewStatusChoices.new,
        db_index=True,
        verbose_name=_("Review Status"),
        help_text=_("Editorial state - places shown only when 'new' or 'done'"),
    )
    review_comment = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Review Comment"),
        help_text=_("Internal reviewer note"),
    )

    # Kind slug (super-root identifier — map.amenity / map.admin /
    # map.natural — derived on write from the category tree)
    domain = models.CharField(
        max_length=100,
        default=DOMAIN_NONE,
        # indexed via Meta (geoplace_domain_idx); db_index would
        # create a duplicate auto index (the rename from detail_type
        # carried the old auto pair along — dropped in 0069,
        # geoplace-read-performance)
        verbose_name=_("Domain"),
        help_text=_(
            "Super-root tier of the place (derived) — amenity / admin / natural / none"
        ),
    )

    # Kind — the anchoring main category (first association by
    # (order, slug), derived on write alongside `domain`). Stored as
    # an indexed FK; the association table stays the source of truth
    # for classifiers/extras (geoplace-kind-fk D1).
    kind_id: int | None

    kind = models.ForeignKey(
        "categories.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="places_anchored",
        verbose_name=_("Kind"),
        help_text=_(
            "The anchoring main category (derived: first association "
            "by order, slug) — categories inline edits re-anchor on save"
        ),
    )

    # Protected fields (manual edits)
    protected_fields = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Protected Fields"),
        help_text=_("Field names that sources may not overwrite"),
    )

    # OSM tags (raw data from OpenStreetMap)
    osm_tags = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("OSM Tags"),
        help_text=_("Raw tags from OpenStreetMap (JSON)"),
    )

    # Extra data (category-specific overflow)
    extra = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Extra"),
        help_text=_("Category-specific overflow data (JSON)"),
    )

    # External links (shared across all place types)
    external_links = models.ManyToManyField(
        "external_links.ExternalLink",
        through="GeoPlaceExternalLink",
        related_name="geo_places",
        verbose_name=_("External Links"),
        help_text=_(
            "Associated external links (websites, social media, documents, etc.)"
        ),
    )

    # Status
    is_active = models.BooleanField(default=True, db_index=True)
    is_public = models.BooleanField(default=True, db_index=True)
    is_modified = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Modifed"),
        help_text=_("Any modification compared to the original source were done"),
    )

    # External source references (many-to-many through association)
    source_set = models.ManyToManyField(
        Organization,
        through="GeoPlaceSourceAssociation",
        verbose_name=_("Sources"),
        related_name="geo_places",
    )

    images_pinned_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Images pinned at"),
        help_text=_("Last pin sync from providers."),
    )
    image_set = models.ManyToManyField(
        Image,
        through="GeoPlaceImageAssociation",
        related_name="geo_places",
        verbose_name=_("Images"),
    )

    class Meta:
        verbose_name = _("Geo Place")
        verbose_name_plural = _("Geo Places")
        ordering = ("-importance", Lower("name_i18n"))
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(
                fields=["is_active", "is_public"], name="geoplaces_active_public_idx"
            ),
            # Composite index for active + public + importance (used in search/nearby)
            models.Index(
                fields=["is_active", "is_public", "importance"],
                name="geoplaces_act_pub_imp_idx",
            ),
            # Composite index for active + public + country (used in search)
            models.Index(
                fields=["is_active", "is_public", "country_code"],
                name="geoplaces_act_pub_cnt_idx",
            ),
            models.Index(fields=["-importance"]),
            models.Index(fields=["domain"], name="geoplace_domain_idx"),
            # GIN index for trigram similarity search (critical for search performance)
            GinIndex(
                fields=["name"],
                name="geoplaces_name_gin_idx",
                opclasses=["gin_trgm_ops"],
            ),
            # GIN index for i18n fields (supports multi-language search)
            GinIndex(fields=["i18n"]),
            # GIST index for spatial queries (critical for nearby search)
            GistIndex(fields=["location"], name="geoplaces_location_gist_idx"),
        ]
        constraints = (
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_country_valid",
                condition=models.Q(country_code__in=settings.COUNTRIES_ONLY),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_main_language_valid",
                condition=models.Q(main_language__in=settings.LANGUAGE_CODES),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_slug_grammar_valid",
                condition=models.Q(slug__regex=f"^{SLUG_GRAMMAR_RE}$"),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_review_status_valid",
                condition=models.Q(review_status__in=_ReviewStatusChoices.values),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_description_quality_valid",
                condition=models.Q(description_quality__isnull=True)
                | (
                    models.Q(description_quality__gte=1)
                    & models.Q(description_quality__lte=10)
                ),
            ),
        )

    def __str__(self) -> str:
        if not self.pk:
            return self.name_i18n

        # Display follows the stored kind FK (anchor rule —
        # classifier priority, then ``(order, slug)``); fall back to
        # the historical first-category read when no kind is stored.
        if self.kind_id is not None:
            category_slug = self.kind.slug if self.kind else "uncategorized"
        else:
            first_category = self.categories.order_by("order", "slug").first()
            category_slug = first_category.slug if first_category else "uncategorized"
        return f"{self.name_i18n} ({category_slug})"

    def clean_slug(self) -> None:
        """Enforce the URL slug grammar (openspec: place-detail-endpoint).

        Slugs must match the path converter grammar — lowercase slug
        characters with at least one ``-`` or ``_`` — so an item route
        can never shadow (or be shadowed by) a fixed collection
        segment (``search``, ``nearby``, ``overlays``). The database
        check constraint mirrors this for write paths that skip
        ``full_clean()`` (``save()`` does not run ``clean()``).
        """
        if not self.slug:
            return  # save() mints one at creation
        if self.slug in RESERVED_URL_SEGMENTS:
            msg = (
                f"'{self.slug}' is a reserved URL segment and cannot be "
                f"used as a slug. Reserved: "
                f"{', '.join(sorted(RESERVED_URL_SEGMENTS))}."
            )
            raise ValidationError({"slug": msg})
        if re.fullmatch(SLUG_GRAMMAR_RE, self.slug) is None:
            msg = (
                "Slug must be lowercase letters, digits, hyphens or "
                "underscores and contain at least one '-' or '_' (it is "
                "used as a URL path segment that must stay distinct from "
                "fixed routes like 'search')."
            )
            raise ValidationError({"slug": msg})

    @override
    def clean(self) -> None:
        super().clean()
        self.clean_slug()

    @override
    def save(
        self,
        *args: Any,
        track_modifications: bool = True,
        fallback_slug: str | None = None,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> None:
        """Auto-generate slug from name if not provided and track manual modifications.

        Args:
            track_modifications: If True, track field changes and mark as modified.
                                Set to False during imports to avoid marking as manually edited.
            fallback_slug: Optional fallback slug string (used during imports to avoid DB queries).
                          If None and name is empty, will query categories (for admin edits).
            max_retries: Maximum retry attempts for database lock errors (default 3).

        Raises:
            IntegrityError: If max retries exceeded and operation still fails.
        """
        # Auto-generate slug from name if not provided
        # Always use English for slug generation (for international consistency)
        minted_slug = False
        name_for_slug = ""
        category_slug = fallback_slug
        if not self.slug:
            # Temporarily activate English to get English name for slug
            activate("en")

            # Determine the name to use for slug generation
            # First try name_i18n (which returns English name after activate("en"))
            # If empty (e.g., during first save before i18n fields are populated), fall back to self.name
            name_for_slug = (
                self.name_i18n if self.name_i18n else (self.name if self.name else "")
            )

            # Use fallback_slug if provided (import path - no DB query)
            # Otherwise query categories for fallback (admin edit path)
            category_slug = fallback_slug
            if (
                not name_for_slug
                and category_slug is None
                and self.pk  # Only query if object has been saved (has an ID)
                and hasattr(self, "categories")
            ):
                # Only query DB if we're in admin, name is empty, no fallback was provided,
                # and the object has already been saved
                if self.categories.exists():
                    first_category = self.categories.first()
                    if first_category:
                        category_slug = first_category.slug

            self.slug = self.generate_unique_slug(
                name_for_slug, category_slug=category_slug
            )
            minted_slug = True

        # Track modifications if this is a manual edit (not an import)
        if track_modifications and self.pk:
            self._track_field_modifications()

        # Retry logic for database locks — and for the rare unique
        # collision on a freshly minted slug (re-mint a new random
        # suffix and retry; the savepoint keeps the surrounding
        # transaction usable).
        import time

        last_exception = None
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    super().save(*args, **kwargs)
                return  # Success, exit retry loop
            except IntegrityError as e:
                last_exception = e
                if minted_slug and attempt < max_retries - 1:
                    self.slug = self.generate_unique_slug(
                        name_for_slug, category_slug=category_slug
                    )
                    continue
                raise
            except Exception as e:
                last_exception = e
                error_str = str(e).lower()
                is_retryable = any(
                    message in error_str for message in RETRYABLE_DB_MESSAGES
                )
                attempts_left = attempt < max_retries - 1
                if is_retryable:
                    if attempts_left:
                        # Retry with exponential backoff
                        wait_time = 0.1 * (2**attempt)  # 100ms, 200ms, 400ms
                        time.sleep(wait_time)
                        continue
                # Not retryable or max retries exceeded
                raise

        # If we get here, all retries failed
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("retry loop exited without an exception")

    def _track_field_modifications(self):
        """Track which fields were manually modified and add them to protected_fields.

        This is called during save() when track_modifications=True (manual edits).
        During imports, track_modifications=False so fields remain unprotected.
        """
        if not self.pk:
            return  # New instance, nothing to track

        # Get original instance from database
        try:
            original = self.__class__.objects.get(pk=self.pk)
        except self.__class__.DoesNotExist:
            return

        if original.is_modified and not self.is_modified:
            # it was removed on purpose, reset proteted fields
            self.protected_fields = list()
            return

        # Fields to check for modifications
        simple_fields = [
            "elevation",
            "country_code",
            "importance",
            "location",
            "shape",
            "osm_tags",
            "extra",
            "is_active",
            "is_public",
        ]
        translation_fields = ["name", "description"]

        # Helper function to normalize values for comparison
        def normalize_value(value: Any) -> Any:
            """Treat None and empty string as equivalent."""
            if value is None or value == "":
                return ""
            return value

        # Track simple field changes
        modified_fields = []
        for field in simple_fields:
            if field in translation_fields:
                continue
            original_value = normalize_value(getattr(original, field, None))
            current_value = normalize_value(getattr(self, field, None))
            if original_value != current_value:
                modified_fields.append(field)

        # Track translation field changes
        # Strategy:
        # - Always use suffixes (name_de, name_en, etc.) - even for default language
        # - Only protect the specific translation fields that were edited
        # - Exception: if base field 'name' (no suffix) changed, protect ALL translations

        # Check if base 'name' field (without suffix) was edited
        for tfield in translation_fields:
            # Check individual language translations (with suffixes)
            for lang_code in settings.LANGUAGE_CODES:
                if lang_code == settings.LANGUAGE_CODE:
                    name_field = tfield
                else:
                    name_field = f"{tfield}_{lang_code}"
                original_value = normalize_value(getattr(original, name_field, None))
                current_value = normalize_value(getattr(self, name_field, None))
                if original_value != current_value:
                    modified_fields.append(
                        f"{tfield}_{lang_code}"
                    )  # Only protect this specific language

        # If any fields were modified, mark as modified and update protected_fields
        if modified_fields:
            self.is_modified = True
            # Add to protected_fields (avoid duplicates). Structured
            # entries (role-scoped party protection dicts) are
            # unhashable — carry them through untouched instead of
            # feeding them to set() (advisor review finding 2).
            entries = list(self.protected_fields or [])
            protected_strings = {e for e in entries if isinstance(e, str)}
            protected_strings.update(modified_fields)
            structured = [e for e in entries if not isinstance(e, str)]
            self.protected_fields = structured + sorted(protected_strings)

            # Auto-transition review_status from "new" to "done"
            # If it was new and we're making manual changes, we're happy with it
            if self.review_status == "new":
                self.review_status = "done"

    def protected_party_roles(self) -> set[str]:
        """Role identifiers with role-scoped party protection.

        Reads ``{"parties": ["role.brand", ...]}`` entries from
        ``protected_fields`` (manual admin edits record the roles they
        touched, OpenSpec ``party-slug-minting``). The legacy flat
        ``"parties"`` string means *all* roles protected and is
        handled by the update-path gates before this resolver runs.
        """
        roles: set[str] = set()
        for entry in self.protected_fields or []:
            if isinstance(entry, dict) and isinstance(entry.get("parties"), list):
                roles.update(str(role) for role in entry["parties"])
        return roles

    #: Amenity-type words that carry no identity in a place name -
    #: filtered from the minted base slug (geoplace-specific vocabulary
    #: for the generic ``mint_short_slug`` helper).
    SLUG_IGNORE_WORDS = [
        "hotel",
        "restaurant",
        "gasthaus",
        "gasthof",
        "berghaus",
        "berggasthaus",
        "hostel",
        "cafeteria",
        "campground",
    ]

    @classmethod
    def generate_unique_slug(
        cls,
        name: str,
        category_slug: str | None = None,
        max_length: int = 15,
    ) -> str:
        """
        Generate unique slug without DB check.

        Format: {base_slug}-{uuid}
        - base_slug: 4-11 chars, no hyphens
        - uuid: 4-8 chars based on base length (shorter base = longer UUID)
        - Final slug: max 15 chars (enforced by slug[:15])

        Args:
            name: The place name to generate slug from
            category_slug: Optional category slug for fallback when name is empty
            max_length: Maximum length for the slug (default 15)

        Returns:
            Unique slug string (max 15 chars)

        Examples:
            "Liechtensteinisches Landesspital" → "liechtenst-dne4"
            "Gemeindepolizei Schellenberg" → "gemeindepo-wz9j"
            "Adolf Bike Shop" → "adolfbike-uabf"
            "Lio" → "lio-3k8m9x4"
            "" (category: "drinkwater") → "drinkwater-ito4"
            "" (no category) → "place-vn191wad"
        """
        from server.core.utils import mint_short_slug

        return mint_short_slug(
            name,
            fallback=category_slug or "place",
            ignore_words=cls.SLUG_IGNORE_WORDS,
            max_length=max_length,
        )

    @classmethod
    def create_with_source(
        cls,
        source: Organization | int | str,
        source_id: str | None = None,
        **kwargs: Any,
    ) -> GeoPlace:
        """
        Create a new GeoPlace and associate it with a source.

        Args:
            source: Organization instance, ID, or slug
            source_id: External ID used by the source (e.g., GeoNames ID)
            **kwargs: Fields for GeoPlace creation (name, location, etc.)

        Returns:
            Created GeoPlace instance with source association

        Example:
            place = GeoPlace.create_with_source(
                source="geonames",
                source_id="2658434",
                name="Matterhorn",
                location=Point(7.6588, 45.9763),
                elevation=4478,
                country_code="CH",
                importance=95,
            )
            place.categories.add(peak_category)
        """
        from ._associations import GeoPlaceSourceAssociation

        # Resolve source to Organization instance
        if isinstance(source, str):
            source_obj = Organization.objects.get(slug=source)
        elif isinstance(source, int):
            source_obj = Organization.objects.get(pk=source)
        else:
            source_obj = source

        # Create the place
        place = cls.objects.create(**kwargs)

        # Create source association
        GeoPlaceSourceAssociation.objects.create(
            geo_place=place,
            organization=source_obj,
            source_id=source_id or "",
        )

        return place

    @classmethod
    def from_schema(
        cls,
        schema: GeoPlaceBaseInput,
        from_source: SourceInput | None = None,
        dedup_options: DedupOptions | None = None,
    ) -> tuple[GeoPlace, UpdateCreateStatus]:
        """
        Helper method that routes to update_or_create based on schema type.

        This is an alias for update_or_create() to provide a more intuitive API.

        Args:
            schema: Input schema (GeoPlaceBaseInput or subclass)
            from_source: Source information (organization, source_id, policies)
            dedup_options: Deduplication options

        Returns:
            Tuple of (GeoPlace instance, UpdateCreateStatus)
        """
        return cls.update_or_create(
            schema=schema,
            from_source=from_source,
            dedup_options=dedup_options,
        )

    @classmethod
    def update_or_create(
        cls,
        schema: GeoPlaceBaseInput,
        from_source: SourceInput | None = None,
        dedup_options: DedupOptions | None = None,
    ) -> tuple[GeoPlace, UpdateCreateStatus]:
        """
        Create or update a GeoPlace using a schema.

        This method handles:
        - Deduplication based on location proximity
        - Multi-language field handling (name, description)
        - Detail model creation/update (AmenityDetail, AdminDetail, etc.)
        - Source association with update/delete policies
        - Protected fields that won't be overwritten

        Args:
            schema: Input schema (GeoPlaceBaseInput or subclass)
            from_source: Source information with organization slug, source_id, and policies
            dedup_options: Deduplication options (distances, checks)

        Returns:
            Tuple of (GeoPlace instance, UpdateCreateStatus)

        Example:
            schema = GeoPlaceAmenityInput(
                name=TranslationSchema(de="Bäckerei", en="Bakery"),
                location=LocationSchema(lon=7.7343, lat=46.0234),
                country_code="CH",
                place_type_identifiers=["shop.bakery"],
                operating_status=OperatingStatus.OPEN,
                parties=[PartyInput(slug="volg", role="role.brand")],
            )

            place, status = GeoPlace.update_or_create(
                schema=schema,
                from_source=SourceInput(
                    slug="osm",
                    source_id="node/123456",
                    extra={"osm_type": "node", "osm_id": "123456"},
                ),
                dedup_options=DedupOptions(distance_same=20, distance_any=4),
            )
        """
        # Import here to avoid circular import during model loading
        from server.apps.geometries.schemas import DedupOptions

        # Set default dedup options
        if dedup_options is None:
            dedup_options = DedupOptions()

        # Convert location to Point
        location = Point(schema.location.lon, schema.location.lat, srid=4326)

        # Resolve categories (validate identifiers once) — plain
        # strings and PlaceTypeInput entries alike; the latter carry
        # association classifier/extra (validated by the same helper
        # GeoPlaceCategory.clean() uses).
        place_types = cls._resolve_place_types(schema.place_type_identifiers)
        categories = [spec.category for spec in place_types]

        # Resolve source organization
        source_obj = None
        if from_source is not None:
            source_obj = cls._get_organization_by_slug(from_source.slug)

        # Check for existing place (deduplication)
        existing_place = None
        if dedup_options.enabled:
            existing_place = cls._find_existing_place_by_schema(
                schema, location, source_obj, from_source, dedup_options, categories
            )

        if existing_place:
            # UPDATE PATH
            return cls._update_from_schema(
                existing_place,
                schema,
                place_types,
                source_obj,
                from_source,
            )
        else:
            # CREATE PATH
            return cls._create_from_schema(
                schema,
                place_types,
                location,
                source_obj,
                from_source,
            )

    @classmethod
    def _find_existing_place_by_schema(
        cls,
        schema: GeoPlaceBaseInput,
        location: Point,
        source_obj: Organization | None,
        from_source: SourceInput | None,
        dedup_options: DedupOptions,
        categories: list[Category],
    ) -> GeoPlace | None:
        """Find existing place using deduplication logic."""
        import math

        from django.contrib.gis.db.models.functions import Distance
        from django.contrib.gis.geos import Polygon

        from ._associations import GeoPlaceSourceAssociation

        # 1. Check source ID first (if enabled and source provided)
        if dedup_options.check_source_id and from_source and source_obj:
            try:
                assoc = GeoPlaceSourceAssociation.objects.select_related(
                    "geo_place"
                ).get(organization=source_obj, source_id=from_source.source_id)
                return assoc.geo_place
            except GeoPlaceSourceAssociation.DoesNotExist:
                pass

        # Helper function to convert meters to degrees at given latitude
        def meters_to_degrees(
            latitude: float, target_meters: float
        ) -> tuple[float, float]:
            """Convert meters to latitude/longitude delta at given latitude."""
            # Meters per degree at this latitude
            # More accurate formulas accounting for Earth's ellipsoid shape
            lat_rad = math.radians(latitude)
            meters_per_deg_lat = (
                111132.954
                - 559.822 * math.cos(2 * lat_rad)
                + 1.175 * math.cos(4 * lat_rad)
            )
            meters_per_deg_lon = (
                111412.84 * math.cos(lat_rad)
                - 93.5 * math.cos(3 * lat_rad)
                + 0.118 * math.cos(5 * lat_rad)
            )

            # Convert target meters to degrees
            delta_lat = target_meters / meters_per_deg_lat
            delta_lon = target_meters / meters_per_deg_lon

            return delta_lat, delta_lon

        # 2. Check by location + category + brand using BBox (much faster than distance)
        if dedup_options.distance_same > 0:
            # Build BBox for fast spatial filtering
            delta_lat, delta_lon = meters_to_degrees(
                location.y,  # latitude
                dedup_options.distance_same,
            )

            bbox = Polygon.from_bbox(
                (
                    location.x - delta_lon,
                    location.y - delta_lat,
                    location.x + delta_lon,
                    location.y + delta_lat,
                )
            )

            filters = {
                "is_active": True,
                "location__contained": bbox,  # BBox filter: 10x faster than distance
            }

            # Add category filter if enabled
            category_filter = Q()
            if dedup_options.check_category:
                parent_slugs = {cat.parent.slug for cat in categories if cat.parent}
                root_slugs = {cat.slug for cat in categories if not cat.parent}

                category_filter = Q()
                if parent_slugs:
                    category_filter |= Q(categories__parent__slug__in=parent_slugs)
                if root_slugs:
                    category_filter |= Q(
                        categories__slug__in=root_slugs,
                        categories__parent__isnull=True,
                    )

            nearby = cls.objects.filter(**filters)
            if dedup_options.check_category and category_filter.children:
                nearby = nearby.filter(category_filter)

            nearby = nearby.annotate(distance=Distance("location", location)).distinct()

            # Filter by brand party if enabled and provided
            if dedup_options.check_brand and schema.parties:
                brand_entries = [p for p in schema.parties if p.role == "role.brand"]
                if brand_entries:
                    # Slug entries reference the party by its slug;
                    # name-only entries (OSM import) by the
                    # ``extra.osm_name`` import identity — containment,
                    # served by the party GIN index. A plain
                    # ``slug__in`` over name-only entries used to filter
                    # on ``[None]`` and never match (advisor-adjacent
                    # regression of party-slug-minting).
                    from server.apps.parties.models import Party

                    brand_q = Q()
                    for entry in brand_entries:
                        if entry.slug:
                            brand_q |= Q(
                                party_associations__party__slug=entry.slug,
                                party_associations__role__identifier="role.brand",
                            )
                        else:
                            brand_q |= Q(
                                party_associations__party__extra__contains={
                                    "osm_name": Party.normalize_key(entry.name or "")
                                },
                                party_associations__role__identifier="role.brand",
                            )
                    nearby = nearby.filter(brand_q)
                else:
                    # Brand check on but no brand entry - only match places
                    # without a brand party association
                    nearby = nearby.exclude(
                        party_associations__role__identifier="role.brand"
                    )
            elif dedup_options.check_brand:
                # No brand specified - only match places without a brand party
                nearby = nearby.exclude(
                    party_associations__role__identifier="role.brand"
                )

            # CRITICAL FIX: Use first() instead of list() to avoid memory leak
            # list() creates temporary list objects that aren't garbage collected
            first_match = nearby.order_by("distance").first()
            if first_match:
                return first_match

        return None

    @staticmethod
    @lru_cache(maxsize=32)
    def _get_organization_by_slug(slug: str) -> Organization:
        return Organization.objects.get(slug=slug)

    @staticmethod
    @lru_cache(maxsize=4096)  # global identifier space (group.child pairs)
    def _resolve_category_from_identifier(identifier: str) -> Category:
        """Resolve Category from identifier with fallbacks for legacy trees."""
        parts = identifier.split(".")
        if parts and parts[0] == "root":
            parts = parts[1:]

        if not parts:
            raise Category.DoesNotExist("Empty category identifier")

        if len(parts) == 1:
            slug = parts[0]
            try:
                return Category.objects.get(slug=slug, parent=None)
            except Category.DoesNotExist:
                return Category.objects.get(identifier=identifier)

        parent_slug, child_slug = parts[0], parts[1]
        # Stored-identifier column first — depth-agnostic and indexed
        # (contract groups gained parents under super-roots in the
        # map tree, so root-level parent lookups miss).
        try:
            return Category.objects.get(identifier=f"{parent_slug}.{child_slug}")
        except (Category.DoesNotExist, Category.MultipleObjectsReturned):
            pass
        try:
            parent = Category.objects.get(slug=parent_slug, parent=None)
            return Category.objects.get(slug=child_slug, parent=parent)
        except Category.DoesNotExist:
            category = Category.objects.filter(
                slug=child_slug, parent__slug=parent_slug
            ).first()
            if category:
                return category
            raise Category.DoesNotExist(
                f"Unknown category identifier: {identifier}"
            ) from None

    @classmethod
    def _resolve_place_types(
        cls, identifiers: list[str | PlaceTypeInput]
    ) -> list[PlaceTypeSpec]:
        """Resolve place-type entries into category + association attrs.

        Plain identifiers resolve to bare specs (no classifier, empty
        extra); ``PlaceTypeInput`` entries resolve their ``classifier``
        and normalized ``extra`` through the shared
        ``GeoPlaceCategory.validate_attributes`` — the same checks
        ``clean()`` enforces (Django never calls ``clean()`` here).
        """
        from ._associations import GeoPlaceCategory

        specs: list[PlaceTypeSpec] = []
        seen: set[tuple[int, int | None]] = set()
        for entry in identifiers:
            if isinstance(entry, str):
                category = cls._resolve_category_from_identifier(entry)
                spec = PlaceTypeSpec(category, None, {})
            else:
                category = cls._resolve_category_from_identifier(entry.identifier)
                classifier = (
                    cls._resolve_category_from_identifier(entry.classifier)
                    if entry.classifier
                    else None
                )
                extra = GeoPlaceCategory.normalize_extra(entry.extra)
                GeoPlaceCategory.validate_attributes(category, classifier, extra)
                spec = PlaceTypeSpec(category, classifier, extra)
            # Dedupe per (category, mode) — the two-association
            # operating-mode model legitimately pairs one category
            # with mode.standard AND mode.reduced (e.g. open and
            # closed type both unknown).
            key = (category.pk, spec.classifier.pk if spec.classifier else None)
            if key in seen:
                continue
            specs.append(spec)
            seen.add(key)
        return specs

    @classmethod
    def _resolve_categories_from_identifiers(
        cls, identifiers: list[str | PlaceTypeInput]
    ) -> list[Category]:
        # Accepts plain identifiers and PlaceTypeInput entries (the
        # latter contribute only their category — association
        # attributes go through _resolve_place_types).
        plain = [
            entry if isinstance(entry, str) else entry.identifier
            for entry in identifiers
        ]
        if not plain:
            raise Category.DoesNotExist("No category identifiers provided")

        categories: list[Category] = []
        seen_ids: set[int] = set()
        for identifier in plain:
            category = cls._resolve_category_from_identifier(identifier)
            if category.id in seen_ids:
                continue
            categories.append(category)
            seen_ids.add(category.id)
        return categories

    @classmethod
    def _write_operations(
        cls, place: GeoPlace, operations: Any, place_types: list[PlaceTypeSpec]
    ) -> bool:
        """Upsert GeoPlaceOperation rows per (place, mode) (task 2.3).

        Gated by the kind contract (task 2.2): the place's contract
        group must enable operations — a group without a contract (or
        with ``has_operations`` off) rejects the write.

        The mode identifier must resolve to a ``mode.*`` child;
        same-mode re-writes refresh capacity/hours (the per-mode
        capacity invariant holds by construction — one row per mode).
        """
        from ._operation import GeoPlaceOperation

        contract = contract_for_group(
            # specs (not bare categories): the duck-typed helpers keep
            # the classifier priority tier — anchor semantics, not just
            # display order, ride this resolution
            kind_root_category(place_types)
        )
        if contract is None or not contract.has_operations:
            raise ValidationError(
                {
                    "operations": _(
                        "Places under this kind's group carry no operations contract."
                    )
                }
            )

        changed_any = False
        for entry in operations:
            mode = cls._resolve_category_from_identifier(entry.mode)
            if mode.parent is None or mode.parent.slug != "mode":
                msg = f"Invalid operation mode identifier: {entry.mode}"
                raise ValueError(msg)
            defaults = {
                "capacity": entry.capacity,
                "opening_hours": entry.opening_hours or {},
            }
            existing = GeoPlaceOperation.objects.filter(
                geo_place=place, mode=mode
            ).first()
            if existing is None:
                GeoPlaceOperation.objects.create(geo_place=place, mode=mode, **defaults)
                changed_any = True
            elif (
                existing.capacity != defaults["capacity"]
                or existing.opening_hours != defaults["opening_hours"]
            ):
                GeoPlaceOperation.objects.filter(pk=existing.pk).update(**defaults)
                changed_any = True
        return changed_any

    @classmethod
    def _write_seasonality(
        cls, place: GeoPlace, seasonality: Any, place_types: list[PlaceTypeSpec]
    ) -> bool:
        """Upsert the place's GeoPlaceSeasonality row (task 2.3).

        Gated by the kind contract (task 2.2): the place's contract
        group must enable seasonality.

        Absent months stay untouched (unknown = NULL preserved);
        shares are range-checked by the accessor and the DB.
        """
        from ._seasonality import GeoPlaceSeasonality, Month

        contract = contract_for_group(
            # specs carry classifiers — same anchor rule as everywhere
            kind_root_category(place_types)
        )
        if contract is None or not contract.has_seasonality:
            raise ValidationError(
                {
                    "seasonality": _(
                        "Places under this kind's group carry no seasonality contract."
                    )
                }
            )
        if seasonality is None:
            return False
        row, _created = GeoPlaceSeasonality.objects.get_or_create(geo_place=place)
        for key, share in dict(seasonality.months).items():
            month = key if isinstance(key, Month) else Month(int(key))
            row.months[month] = share
        row.save()
        return True

    @classmethod
    def _create_from_schema(
        cls,
        schema: GeoPlaceBaseInput,
        place_types: list[PlaceTypeSpec],
        location: Point,
        source_obj: Organization | None,
        from_source: SourceInput | None,
    ) -> tuple[GeoPlace, UpdateCreateStatus]:
        """Create a new GeoPlace from schema."""
        from django.contrib.gis.geos import GEOSGeometry

        from server.core import UpdateCreateStatus

        from ._admin_detail import AdminDetail
        from ._amenity_detail import AmenityDetail
        from ._associations import GeoPlaceCategory, GeoPlaceSourceAssociation

        # Prepare name translations
        name_dict = schema.get_name_dict()
        description_dict = schema.get_description_dict()

        # domain + kind derived on write from the category tree
        # (geoplace-kind-fk D4 — one derivation step, two stored
        # facts). The input schema declares neither. Specs (not bare
        # categories): the anchor rule is classifier-aware —
        # mode.standard outranks (order, slug); stripping the
        # classifier regressed mixed mode writes to the order-only
        # rule (accommodation.unknown at order 0 anchored).
        anchor = anchor_category(place_types)
        derived_domain = place_domain(place_types)

        # Build place data
        place_data = {
            "name": name_dict.get(settings.LANGUAGE_CODE, ""),
            "main_language": detect_main_language(name_dict) or settings.LANGUAGE_CODE,
            "location": location,
            "country_code": schema.country_code,
            "domain": derived_domain,
            "kind": anchor,
            "elevation": schema.elevation,
            "importance": schema.importance,
            "review_status": schema.review_status.value,
            "osm_tags": schema.osm_tags,
            "extra": schema.extra,
            "is_active": schema.is_active,
            "is_public": schema.is_public,
            # is_modified and protected_fields are managed automatically
        }

        # Add slug if provided
        if schema.slug:
            place_data["slug"] = schema.slug

        # Add shape if provided
        if schema.shape:
            if isinstance(schema.shape, str):
                place_data["shape"] = GEOSGeometry(schema.shape, srid=4326)
            else:
                place_data["shape"] = schema.shape

        # Add name translations for non-default languages
        for lang_code, name_value in name_dict.items():
            if lang_code != settings.LANGUAGE_CODE:
                place_data[f"name_{lang_code}"] = name_value

        # Add description (default language)
        if settings.LANGUAGE_CODE in description_dict:
            place_data["description"] = description_dict[settings.LANGUAGE_CODE]

        # Add description translations for non-default languages
        for lang_code, desc_value in description_dict.items():
            if lang_code != settings.LANGUAGE_CODE and desc_value:
                place_data[f"description_{lang_code}"] = desc_value

        # Create the place (track_modifications=False for imports)
        # Slug is auto-generated in save() with UUID-based uniqueness (no DB check needed)
        # Pass first category slug as fallback for empty names
        fallback_slug = place_types[0].category.slug if place_types else None
        place = cls(**place_data)
        place.save(track_modifications=False, fallback_slug=fallback_slug)

        if place_types:
            GeoPlaceCategory.objects.bulk_create(
                [
                    GeoPlaceCategory(
                        geo_place=place,
                        category=spec.category,
                        classifier=spec.classifier,
                        extra=spec.extra,
                    )
                    for spec in place_types
                ],
                ignore_conflicts=True,
            )

        # Typed operating facts + seasonality (task 2.3)
        if schema.operations:
            cls._write_operations(place, schema.operations, place_types)
        if schema.seasonality is not None:
            cls._write_seasonality(place, schema.seasonality, place_types)

        # Create detail model based on type (flattened structure)
        if derived_domain == DOMAIN_AMENITY and schema.operating_status:
            amenity_kwargs = {
                "geo_place": place,
                "operating_status": schema.operating_status.value,
                "opening_months": schema.opening_months,
                "opening_hours": schema.opening_hours,
                # phones retired (external-link-uris): numbers live as
                # uri.phone external links on the place
            }
            # Party associations are place-level (replaces the former
            # brand FK on the detail row)
            if schema.parties:
                AmenityDetail._write_party_associations(place, schema.parties)

            AmenityDetail.objects.create(**amenity_kwargs)

        elif derived_domain == DOMAIN_ADMIN and schema.admin_level:
            AdminDetail.objects.create(
                geo_place=place,
                admin_level=schema.admin_level,
                population=schema.population,
                postal_code=schema.postal_code,
            )

        # Create source association if provided
        if source_obj and from_source:
            GeoPlaceSourceAssociation.objects.create(
                geo_place=place,
                organization=source_obj,
                source_id=from_source.source_id,
                import_date=from_source.import_date,
                modified_date=from_source.modified_date,
                confidence=from_source.confidence,
                update_policy=from_source.update_policy.value,
                delete_policy=from_source.delete_policy.value,
                priority=from_source.priority,
                extra=from_source.extra,
            )

        return place, UpdateCreateStatus.created

    @classmethod
    def _update_from_schema(
        cls,
        place: GeoPlace,
        schema: GeoPlaceBaseInput,
        place_types: list[PlaceTypeSpec],
        source_obj: Organization | None,
        from_source: SourceInput | None,
    ) -> tuple[GeoPlace, UpdateCreateStatus]:
        """Update an existing GeoPlace from schema."""
        from datetime import datetime

        from django.contrib.gis.geos import GEOSGeometry

        from server.core import UpdateCreateStatus

        from ._admin_detail import AdminDetail
        from ._amenity_detail import AmenityDetail
        from ._associations import (
            GeoPlaceCategory,
            GeoPlaceSourceAssociation,
            UpdatePolicy,
        )

        # Get or create source association
        association = None
        if source_obj and from_source:
            association, _ = GeoPlaceSourceAssociation.objects.get_or_create(
                geo_place=place,
                organization=source_obj,
                defaults={
                    "source_id": from_source.source_id,
                    "import_date": from_source.import_date or datetime.now(),
                    "modified_date": from_source.modified_date,
                    "confidence": from_source.confidence,
                    "update_policy": from_source.update_policy.value,
                    "delete_policy": from_source.delete_policy.value,
                    "priority": from_source.priority,
                    "extra": from_source.extra,
                },
            )

            # Update modified_date
            if from_source.modified_date:
                association.modified_date = from_source.modified_date
                association.save(update_fields=["modified_date"])

        # Check update policy
        if association and association.update_policy == UpdatePolicy.PROTECTED:
            # Don't update protected records
            return place, UpdateCreateStatus.no_change

        # Determine which fields can be updated. String entries only —
        # structured role-scoped party protection ({"parties": [...]} —
        # dicts, unhashable) is resolved per role inside
        # _write_party_associations instead (advisor review finding 1).
        protected = {
            entry for entry in (place.protected_fields or []) if isinstance(entry, str)
        }

        # Check if we should respect protected fields
        respect_protected = False
        if association:
            if association.update_policy == UpdatePolicy.MERGE:
                respect_protected = True
            elif association.update_policy == UpdatePolicy.AUTO_PROTECT:
                # Check if place has been manually modified
                if place.is_modified:
                    respect_protected = True

        if respect_protected:
            # Policy-level enforcement deferred (pre-existing TODO): the
            # per-field ``protected`` checks below already honor protected
            # fields uniformly; MERGE vs AUTO_PROTECT currently behave the
            # same here.
            pass

        # Track if anything was updated
        place_updated = False
        categories_updated = False
        update_fields = []
        i18n_dirty = False

        # Update categories: create missing associations AND refresh
        # classifier/extra on existing rows — the wodore backfill's
        # core guarantee (additive-only used to leave existing
        # associations untouched, silently dropping closed types and
        # capacities). Stale associations (category no longer claimed
        # by this source) are not removed — reconciliation is a
        # documented follow-up.
        if "categories" not in protected and place_types:
            from ._category_extra_schema import resolve_extra_schema

            # Keyed per (category, mode) — the two-association model
            # legitimately holds one category under both modes.
            existing = {
                (assoc.category_id, assoc.classifier_id): assoc
                for assoc in GeoPlaceCategory.objects.filter(geo_place=place)
            }
            for spec in place_types:
                key = (
                    spec.category.pk,
                    spec.classifier.pk if spec.classifier is not None else None,
                )
                assoc = existing.get(key)
                if assoc is None:
                    GeoPlaceCategory.objects.create(
                        geo_place=place,
                        category=spec.category,
                        classifier=spec.classifier,
                        extra=spec.extra,
                    )
                    categories_updated = True
                    continue
                # Schema-defined keys are source truth (replaced or
                # dropped); keys outside the schema are preserved —
                # imports never write those. Without a schema the
                # merge is additive only.
                schema_row = resolve_extra_schema(spec.category)
                schema_keys = (
                    set((schema_row.schema or {}).get("properties") or {})
                    if schema_row is not None
                    else set()
                )
                if schema_keys:
                    merged_extra = {
                        key_: value
                        for key_, value in assoc.extra.items()
                        if key_ not in schema_keys
                    }
                    merged_extra.update(spec.extra)
                else:
                    merged_extra = {**assoc.extra, **spec.extra}
                if assoc.extra != merged_extra:
                    assoc.extra = merged_extra
                    assoc.save(update_fields=["extra", "modified"])
                    categories_updated = True

        # domain + kind derived on write from the category tree
        # (geoplace-kind-fk D4). Specs carry the association
        # classifiers — the anchor rule needs them (mode.standard
        # outranks the order-only fallback category).
        anchor = anchor_category(place_types)
        derived_domain = place_domain(place_types)
        if "domain" not in protected and place.domain != derived_domain:
            place.domain = derived_domain
            update_fields.append("domain")
            place_updated = True
        if "kind" not in protected and place.kind_id != (anchor.pk if anchor else None):
            place.kind = anchor
            update_fields.append("kind")
            place_updated = True

        # Typed operating facts + seasonality (task 2.3) — own
        # protection keys (admin edits mark them like categories).
        ops_changed = False
        seasonality_changed = False
        if "operations" not in protected and schema.operations:
            ops_changed = cls._write_operations(place, schema.operations, place_types)
        if "seasonality" not in protected and schema.seasonality is not None:
            seasonality_changed = cls._write_seasonality(
                place, schema.seasonality, place_types
            )
        operations_updated = ops_changed or seasonality_changed

        # Update name translations
        if "name" not in protected:
            name_dict = schema.get_name_dict()
            detected_language = detect_main_language(name_dict)
            if detected_language and place.main_language != detected_language:
                place.main_language = detected_language
                update_fields.append("main_language")
                place_updated = True
            for lang_code, name_value in name_dict.items():
                if lang_code == settings.LANGUAGE_CODE:
                    if place.name != name_value:
                        place.name = name_value
                        update_fields.append("name")
                        place_updated = True
                else:
                    field_name = f"name_{lang_code}"
                    current_value = getattr(place, field_name, None)
                    if current_value != name_value:
                        setattr(place, field_name, name_value)
                        i18n_dirty = True
                        place_updated = True

        # Update description translations
        if "description" not in protected:
            description_dict = schema.get_description_dict()
            for lang_code, desc_value in description_dict.items():
                if lang_code == settings.LANGUAGE_CODE:
                    if place.description != desc_value:
                        place.description = desc_value
                        update_fields.append("description")
                        place_updated = True
                else:
                    field_name = f"description_{lang_code}"
                    current_value = getattr(place, field_name, None)
                    if current_value != desc_value:
                        setattr(place, field_name, desc_value)
                        i18n_dirty = True
                        place_updated = True

        # Update other fields
        field_mapping = {
            "elevation": schema.elevation,
            "country_code": schema.country_code,
            "importance": schema.importance,
            "is_active": schema.is_active,
            "is_public": schema.is_public,
        }

        for field, value in field_mapping.items():
            if field not in protected and getattr(place, field) != value:
                setattr(place, field, value)
                update_fields.append(field)
                place_updated = True

        # Update shape if provided
        if "shape" not in protected and schema.shape:
            new_shape = schema.shape
            if isinstance(new_shape, str):
                new_shape = GEOSGeometry(new_shape, srid=4326)
            if place.shape != new_shape:
                place.shape = new_shape
                update_fields.append("shape")
                place_updated = True

        # Update OSM tags (merge strategy)
        if "osm_tags" not in protected and schema.osm_tags:
            if place.osm_tags != schema.osm_tags:
                place.osm_tags = {**place.osm_tags, **schema.osm_tags}
                update_fields.append("osm_tags")
                place_updated = True

        # Update extra data (merge strategy) — validated against the
        # kind-root schema first (task 2.6, same fail-open guardrails)
        if "extra" not in protected and schema.extra:
            from ._category_extra_schema import validate_place_extra

            validate_place_extra(place_types, schema.extra)
            if place.extra != schema.extra:
                place.extra = {**place.extra, **schema.extra}
                update_fields.append("extra")
                place_updated = True

        # Save place if updated (track_modifications=False for imports)
        if place_updated:
            if i18n_dirty and "i18n" not in update_fields:
                update_fields.append("i18n")
            place.save(update_fields=update_fields, track_modifications=False)

        # Update or create detail model (flattened structure)
        detail_updated = False
        if derived_domain == DOMAIN_AMENITY and schema.operating_status:
            # Build amenity detail data from flattened schema
            try:
                amenity_detail = place.amenity_detail  # type: ignore  # dynamic attr: plugin-less inference gap
                is_new = False
            except AmenityDetail.DoesNotExist:
                amenity_detail = AmenityDetail(geo_place=place)
                is_new = True

            update_fields = []
            if (
                "operating_status" not in protected
                and amenity_detail.operating_status != schema.operating_status.value
            ):
                amenity_detail.operating_status = schema.operating_status.value
                update_fields.append("operating_status")
                detail_updated = True

            if "opening_hours" not in protected and schema.opening_hours:
                if amenity_detail.opening_hours != schema.opening_hours:
                    amenity_detail.opening_hours = schema.opening_hours
                    update_fields.append("opening_hours")
                    detail_updated = True

            # phones retired (external-link-uris): uri.phone links at the
            # place level — no detail-row write path

            if "parties" not in protected and schema.parties:
                if AmenityDetail._write_party_associations(
                    place, schema.parties, respect_protection=True
                ):
                    detail_updated = True

            if is_new:
                amenity_detail.save()
            elif update_fields:
                amenity_detail.save(update_fields=update_fields)

        elif derived_domain == DOMAIN_ADMIN and schema.admin_level:
            admin_detail, created = AdminDetail.objects.update_or_create(
                geo_place=place,
                defaults={
                    "admin_level": schema.admin_level,
                    "population": schema.population,
                    "postal_code": schema.postal_code,
                },
            )
            if not created:
                detail_updated = True

        # Return appropriate status
        if place_updated or categories_updated or detail_updated or operations_updated:
            return place, UpdateCreateStatus.updated
        return place, UpdateCreateStatus.no_change

    def add_relation(
        self,
        to_place: GeoPlace,
        relation_slug: str = "part_of",
        **kwargs: Any,
    ) -> GeoPlaceRelation:
        """Idempotently add a semantic edge to another place (task 3.3).

        Curated by default (confidence 1.0); pass ``confidence < 1.0``
        for generated edges — re-runs replace them, curated edges win
        (same triple, higher confidence preserved).
        """
        from ._relation import GeoPlaceRelation

        relation_category = Category.objects.get(
            slug=relation_slug, parent__slug="relations"
        )
        # Curated edges win: only update confidence if the new value
        # is HIGHER (generated 0.8 never overwrites curated 1.0).
        new_confidence = kwargs.pop("confidence", 1.0)
        edge, created = GeoPlaceRelation.objects.get_or_create(
            from_place=self,
            to_place=to_place,
            relation=relation_category,
            defaults={"confidence": new_confidence, **(kwargs or {})},
        )
        if not created and new_confidence > edge.confidence:
            edge.confidence = new_confidence
            edge.save(update_fields=["confidence"])
        return edge

    def get_related_places(
        self,
        relation_slug: str | None = None,
        direction: str = "outgoing",
    ) -> QuerySet[GeoPlace]:
        """Places related by a given edge type (direction-aware)."""

        qs = GeoPlace.objects.all()  # type: ignore[no-any-return]  # QuerySet typing drift
        if direction == "outgoing":
            filter_kwargs: dict[str, Any] = {
                "outgoing_relations__from_place": self,
            }
            if relation_slug:
                filter_kwargs["outgoing_relations__relation__slug"] = relation_slug
            return qs.filter(**filter_kwargs).distinct()
        filter_kwargs = {"incoming_relations__to_place": self}
        if relation_slug:
            filter_kwargs["incoming_relations__relation__slug"] = relation_slug
        return qs.filter(**filter_kwargs).distinct()

    def add_source(
        self,
        source: Organization | int | str,
        source_id: str | None = None,
        **kwargs: Any,
    ) -> GeoPlaceSourceAssociation:
        """
        Add or update a source association for this GeoPlace.

        Args:
            source: Organization instance, ID, or slug
            source_id: External ID used by the source
            **kwargs: Additional fields for the association (confidence, source_props, etc.)

        Returns:
            Created or updated GeoPlaceSourceAssociation instance

        Example:
            place.add_source("geonames", source_id="2658434", confidence=1.0)
        """
        from ._associations import GeoPlaceSourceAssociation

        # Resolve source to Organization instance
        if isinstance(source, str):
            source_obj = Organization.objects.get(slug=source)
        elif isinstance(source, int):
            source_obj = Organization.objects.get(pk=source)
        else:
            source_obj = source

        # Create or update association
        association, _ = GeoPlaceSourceAssociation.objects.update_or_create(
            geo_place=self,
            organization=source_obj,
            defaults={
                "source_id": source_id or "",
                **kwargs,
            },
        )

        return association
