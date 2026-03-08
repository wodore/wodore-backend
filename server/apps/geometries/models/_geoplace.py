from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import GinIndex, GistIndex
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from modeltrans.fields import TranslationField
from django_countries.fields import CountryField
from django.contrib.gis.geos import Point

from server.apps.categories.models import Category
from server.apps.images.models import Image
from server.apps.organizations.models import Organization
from server.core.models import TimeStampedModel
from server.core.utils import UpdateCreateStatus

if TYPE_CHECKING:
    from server.apps.geometries.schemas import (
        DedupOptions,
        GeoPlaceBaseInput,
        SourceInput,
    )
    from ._associations import GeoPlaceSourceAssociation


class DetailType(models.TextChoices):
    """Detail model types for GeoPlace."""

    AMENITY = "amenity", _("Amenity")
    TRANSPORT = "transport", _("Transport")
    ADMIN = "admin", _("Admin")
    NATURAL = "natural", _("Natural")
    NONE = "none", _("None")


class GeoPlace(TimeStampedModel):
    """
    Canonical, curated geographic place.
    Can aggregate data from multiple sources (GeoNames, OSM, manual edits).
    """

    # TODO: add index which starts at 10000 or UIID?

    # Translation support
    i18n = TranslationField(fields=("name", "description"))

    name = models.CharField(max_length=200, verbose_name=_("Name"))
    name_i18n: str  # for typing

    # Identification
    slug = models.SlugField(
        max_length=200,
        unique=True,
        db_index=True,
        verbose_name=_("Slug"),
        help_text=_("Unique URL identifier"),
        null=True,  # Temporarily nullable for migration
        blank=True,
    )

    # Classification
    place_type = models.ForeignKey(
        Category,
        on_delete=models.RESTRICT,
        related_name="places",
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

    parent = models.ForeignKey(
        "self",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="children",
    )

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

    # Review workflow
    review_status = models.CharField(
        max_length=20,
        choices=[
            ("new", _("New")),
            ("review", _("Review Needed")),
            ("work", _("In Review")),
            ("done", _("Reviewed")),
        ],
        default="new",
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

    # Detail model type
    detail_type = models.CharField(
        max_length=20,
        choices=DetailType.choices,
        default=DetailType.NONE,
        db_index=True,
        verbose_name=_("Detail Type"),
        help_text=_("Which detail model is attached"),
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
            models.Index(fields=["detail_type"]),
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
                name="%(app_label)s_%(class)s_detail_type_valid",
                condition=models.Q(
                    detail_type__in=["amenity", "transport", "admin", "natural", "none"]
                ),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_review_status_valid",
                condition=models.Q(review_status__in=["new", "review", "work", "done"]),
            ),
        )

    def __str__(self) -> str:
        return f"{self.name_i18n} ({self.place_type.slug})"

    def save(self, *args, track_modifications=True, **kwargs):
        """Auto-generate slug from name if not provided and track manual modifications.

        Args:
            track_modifications: If True, track field changes and mark as modified.
                                Set to False during imports to avoid marking as manually edited.
        """
        # Auto-generate slug from name if not provided
        if not self.slug and self.name_i18n:
            self.slug = self.generate_unique_slug(self.name_i18n, exclude_id=self.id)

        # Track modifications if this is a manual edit (not an import)
        if track_modifications and self.pk:
            self._track_field_modifications()

        super().save(*args, **kwargs)

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

        if getattr(original, "is_modified") and not getattr(self, "is_modified"):
            # it was removed on purpose, reset proteted fields
            self.protected_fields = list()
            return

        # Fields to check for modifications
        simple_fields = [
            "elevation",
            "country_code",
            "place_type",
            "importance",
            "parent",
            "location",
            "shape",
            "osm_tags",
            "extra",
            "is_active",
            "is_public",
        ]
        translation_fields = ["name", "description"]

        # Helper function to normalize values for comparison
        def normalize_value(value):
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
            # Add to protected_fields (avoid duplicates)
            current_protected = set(self.protected_fields)
            current_protected.update(modified_fields)
            self.protected_fields = list(current_protected)

    @classmethod
    def generate_unique_slug(
        cls,
        name: str,
        max_length: int = 30,
        min_length: int = 3,
        uuid_length: int = 3,
        exclude_id: int | None = None,
    ) -> str:
        """
        Generate a unique slug using hut-style filtering with short UUID suffix.

        This approach:
        1. Filters out common/unhelpful words (similar to guess_slug_name for huts)
        2. Creates a base slug from the meaningful parts of the name
        3. Adds a short UUID suffix (3 chars, expanding to 4 if needed)
        4. Keeps slugs readable while ensuring uniqueness

        Args:
            name: The place name to generate slug from
            max_length: Maximum length for the slug (default 50)
            min_length: Minimum length for the slug (default 3)
            uuid_length: Starting length for UUID suffix (default 3)
            exclude_id: ID to exclude from uniqueness check (for updates)

        Returns:
            Unique slug string

        Examples:
            "Restaurant Berggasthaus Zermatt" → "berggasthaus-a3f"
            "Hotel Bellevue" → "bellevue-b2k"
            "Camping Alpenglühn" → "alpengluehn-c9p"
        """
        # Common words to filter out (amenity-specific)
        NOT_IN_SLUG = [
            # Amenity types
            "restaurant",
            "ristorante",
            "beizli",
            "gasthaus",
            "gasthof",
            "hotel",
            "hostel",
            "jugendherberg",
            "berghotel",
            "berggasthaus",
            "cafe",
            "cafeteria",
            "bar",
            "pub",
            "camping",
            "zelt",
            "campground",
            # Common filler words
            "alp",
            "alpe",
            "la",
            "le",
            "les",
            "del",
            "des",
            "sous",
            "sur",
            # Place types
            "berghaus",
            "berghuette",
            "waldhuette",
            "huette",
            "hütte",
            "cabane",
            "capanna",
            "rifugio",
            "refuge",
            "rif",
            # Articles/prepositions
            "am",
            "an",
            "im",
            "in",
            "zum",
            "zur",
            "bei",
            "ob",
            "unter",
            # Operators/organizations
            "sac",
            "cai",
            "dac",
            "cas",
        ]

        # Additional words to replace (remove if resulting word > 4 chars)
        REPLACE_IN_SLUG = [
            "restaurant",
            "hotel",
            "hostel",
            "camping",
            "berghaus",
            "berggasthaus",
            "gasthaus",
            "gasthof",
        ]

        import re
        from slugify import slugify as pyslugify

        # Replace umlauts
        for r in ("ä", "ae"), ("ü", "ue"), ("ö", "oe"), ("é", "e"):
            name = name.lower().replace(r[0], r[1])

        # Create base slug
        slug = pyslugify(name, word_boundary=True)
        slug = re.sub(r"[0-9]", "", slug)  # Remove numbers
        slug = slug.strip(" -")

        # Filter and clean
        slugs = slug.split("-")
        slugl = [s for s in slugs if (s not in NOT_IN_SLUG and len(s) >= 3)]

        # Try replacing common words
        for _replace in REPLACE_IN_SLUG:
            slugl = [
                v.replace(_replace, "") if len(v.replace(_replace, "")) > 4 else v
                for v in slugl
                if v.replace(_replace, "")
            ]

        # Fallback to original if too short
        if not slugl or len("-".join(slugl)) < min_length:
            slugl = pyslugify(name).split("-")

        base_slug = pyslugify(" ".join(slugl), word_boundary=True)

        # Truncate if needed, leave room for UUID suffix
        uuid_space = uuid_length + 1  # +1 for the hyphen
        max_base_length = max_length - uuid_space
        if len(base_slug) > max_base_length:
            base_slug = base_slug[:max_base_length]

        # Ensure minimum length
        if len(base_slug) < min_length:
            base_slug = (
                base_slug[:min_length] if len(base_slug) >= min_length else "place"
            )

        # Add short UUID suffix and ensure uniqueness
        return cls._add_unique_suffix(base_slug, uuid_length, exclude_id)

    @classmethod
    def _slug_exists(cls, slug: str, exclude_id: int | None = None) -> bool:
        """Check if a slug already exists in the database."""
        queryset = cls.objects.filter(slug=slug)
        if exclude_id is not None:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.exists()

    @classmethod
    def _add_unique_suffix(
        cls,
        base_slug: str,
        uuid_length: int = 3,
        exclude_id: int | None = None,
        max_attempts: int = 10,
    ) -> str:
        """
        Add a short UUID suffix to a base slug, expanding length if needed.

        Tries UUID suffixes of increasing length until a unique slug is found:
        1. Try 3-character UUID (62^3 = 238,328 combinations)
        2. Expand to 4 characters (62^4 = 14,776,336 combinations)
        3. Expand to 5 characters if still not unique (rare)

        Args:
            base_slug: The base slug to add suffix to
            uuid_length: Starting length for UUID suffix (default 3)
            exclude_id: ID to exclude from uniqueness check (for updates)
            max_attempts: Maximum attempts per UUID length (default 10)

        Returns:
            Unique slug with UUID suffix

        Examples:
            base_slug="bellevue" → "bellevue-a3f"
            If collision: → "bellevue-b2k"
            If all 3-char taken: → "bellevue-a3f9"
        """
        import secrets
        import string

        # Character set: lowercase letters + digits (no vowels to avoid words)
        charset = string.ascii_lowercase + string.digits

        for current_length in [uuid_length, uuid_length + 1, uuid_length + 2]:
            for _attempt in range(max_attempts):
                # Generate random suffix
                suffix = "".join(secrets.choice(charset) for _ in range(current_length))
                slug = f"{base_slug}-{suffix}"

                # Check uniqueness
                if not cls._slug_exists(slug, exclude_id):
                    return slug

        # Ultimate fallback: use timestamp
        import time

        return f"{base_slug}-{int(time.time())}"

    @classmethod
    def create_with_source(
        cls,
        source: Organization | int | str,
        source_id: str | None = None,
        **kwargs,
    ) -> "GeoPlace":
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
                place_type=peak_category,
                elevation=4478,
                country_code="CH",
                importance=95,
            )
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
        schema: "GeoPlaceBaseInput",
        from_source: "SourceInput | None" = None,
        dedup_options: "DedupOptions | None" = None,
    ) -> tuple["GeoPlace", "UpdateCreateStatus"]:
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
        schema: "GeoPlaceBaseInput",
        from_source: "SourceInput | None" = None,
        dedup_options: "DedupOptions | None" = None,
    ) -> tuple["GeoPlace", "UpdateCreateStatus"]:
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
                place_type_identifier="shop.bakery",
                operating_status=OperatingStatus.OPEN,
                brand=BrandInput(slug="volg"),
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

        # Resolve source organization
        source_obj = None
        if from_source is not None:
            source_obj = Organization.objects.get(slug=from_source.slug)

        # Check for existing place (deduplication)
        existing_place = None
        if dedup_options.enabled:
            existing_place = cls._find_existing_place_by_schema(
                schema, location, source_obj, from_source, dedup_options
            )

        if existing_place:
            # UPDATE PATH
            return cls._update_from_schema(
                existing_place,
                schema,
                source_obj,
                from_source,
            )
        else:
            # CREATE PATH
            return cls._create_from_schema(
                schema,
                location,
                source_obj,
                from_source,
            )

    @classmethod
    def _find_existing_place_by_schema(
        cls,
        schema: "GeoPlaceBaseInput",
        location: "Point",
        source_obj: Organization | None,
        from_source: "SourceInput | None",
        dedup_options: "DedupOptions",
    ) -> "GeoPlace | None":
        """Find existing place using deduplication logic."""
        from django.contrib.gis.db.models.functions import Distance

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

        # 2. Check by location + category + brand
        if dedup_options.distance_same > 0:
            filters = {
                "is_active": True,
                "location__distance_lte": (location, dedup_options.distance_same),
            }

            # Add category filter if enabled
            if dedup_options.check_category:
                category_parent = schema.place_type_identifier.split(".")[0]
                filters["place_type__slug__startswith"] = category_parent

            nearby = cls.objects.filter(**filters).annotate(
                distance=Distance("location", location)
            )

            # Filter by brand if enabled and provided
            if dedup_options.check_brand and schema.brand:
                from server.apps.categories.models import Category

                try:
                    brand_cat = Category.objects.get(slug=schema.brand.slug)
                    nearby = nearby.filter(amenity_detail__brand=brand_cat)
                except Category.DoesNotExist:
                    pass
            elif dedup_options.check_brand:
                # No brand specified - only match places without brand
                nearby = nearby.filter(amenity_detail__brand__isnull=True)

            nearby_list = list(nearby.order_by("distance")[:2])
            if len(nearby_list) == 1:
                return nearby_list[0]

        # 3. Check very close proximity (any place)
        if dedup_options.distance_any > 0:
            very_nearby = list(
                cls.objects.filter(
                    is_active=True,
                    location__distance_lte=(location, dedup_options.distance_any),
                )
                .annotate(distance=Distance("location", location))
                .order_by("distance")[:2]
            )
            if len(very_nearby) == 1:
                return very_nearby[0]

        return None

    @classmethod
    def _create_from_schema(
        cls,
        schema: "GeoPlaceBaseInput",
        location: "Point",
        source_obj: Organization | None,
        from_source: "SourceInput | None",
    ) -> tuple["GeoPlace", "UpdateCreateStatus"]:
        """Create a new GeoPlace from schema."""
        from django.contrib.gis.geos import GEOSGeometry

        from server.core import UpdateCreateStatus

        from ._admin_detail import AdminDetail
        from ._amenity_detail import AmenityDetail
        from ._associations import GeoPlaceSourceAssociation

        # Get category
        category = Category.objects.get(identifier=schema.place_type_identifier)

        # Prepare name translations
        name_dict = schema.get_name_dict()
        description_dict = schema.get_description_dict()

        # Build place data
        place_data = {
            "name": name_dict.get(settings.LANGUAGE_CODE, "Unnamed"),
            "location": location,
            "place_type": category,
            "country_code": schema.country_code,
            "detail_type": schema.detail_type,
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

        # Add parent if provided
        if schema.parent_id:
            place_data["parent_id"] = schema.parent_id

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
        place = cls(**place_data)
        place.save(track_modifications=False)

        # Create detail model based on type (flattened structure)
        from ..schemas import DetailType

        if schema.detail_type == DetailType.AMENITY and schema.operating_status:
            amenity_kwargs = {
                "geo_place": place,
                "operating_status": schema.operating_status.value,
                "opening_months": schema.opening_months,
                "opening_hours": schema.opening_hours,
                "phones": [
                    p.model_dump() if hasattr(p, "model_dump") else p
                    for p in schema.phones
                ],
            }
            # Add brand if provided
            if schema.brand:
                brand = Category.objects.get(slug=schema.brand.slug)
                amenity_kwargs["brand"] = brand

            AmenityDetail.objects.create(**amenity_kwargs)

        elif schema.detail_type == DetailType.ADMIN and schema.admin_level:
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
        place: "GeoPlace",
        schema: "GeoPlaceBaseInput",
        source_obj: Organization | None,
        from_source: "SourceInput | None",
    ) -> tuple["GeoPlace", "UpdateCreateStatus"]:
        """Update an existing GeoPlace from schema."""
        from datetime import datetime

        from django.contrib.gis.geos import GEOSGeometry

        from server.core import UpdateCreateStatus

        from ._admin_detail import AdminDetail
        from ._amenity_detail import AmenityDetail
        from ._associations import GeoPlaceSourceAssociation, UpdatePolicy

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

        # Determine which fields can be updated
        protected = set(place.protected_fields)

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
            pass  # TODO do something with it

        # Track if anything was updated
        updated = False
        update_fields = []

        # Get category
        category = Category.objects.get(identifier=schema.place_type_identifier)

        # Update place_type
        if "place_type" not in protected and place.place_type != category:
            place.place_type = category
            update_fields.append("place_type")
            updated = True

        # Update name translations
        if "name" not in protected:
            name_dict = schema.get_name_dict()
            for lang_code, name_value in name_dict.items():
                if lang_code == settings.LANGUAGE_CODE:
                    if place.name != name_value:
                        place.name = name_value
                        update_fields.append("name")
                        updated = True
                else:
                    field_name = f"name_{lang_code}"
                    current_value = getattr(place, field_name, None)
                    if current_value != name_value:
                        setattr(place, field_name, name_value)
                        update_fields.append(field_name)
                        updated = True

        # Update description translations
        if "description" not in protected:
            description_dict = schema.get_description_dict()
            for lang_code, desc_value in description_dict.items():
                if lang_code == settings.LANGUAGE_CODE:
                    if place.description != desc_value:
                        place.description = desc_value
                        update_fields.append("description")
                        updated = True
                else:
                    field_name = f"description_{lang_code}"
                    current_value = getattr(place, field_name, None)
                    if current_value != desc_value:
                        setattr(place, field_name, desc_value)
                        update_fields.append(field_name)
                        updated = True

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
                updated = True

        # Update shape if provided
        if "shape" not in protected and schema.shape:
            new_shape = schema.shape
            if isinstance(new_shape, str):
                new_shape = GEOSGeometry(new_shape, srid=4326)
            if place.shape != new_shape:
                place.shape = new_shape
                update_fields.append("shape")
                updated = True

        # Update OSM tags (merge strategy)
        if "osm_tags" not in protected and schema.osm_tags:
            if place.osm_tags != schema.osm_tags:
                place.osm_tags = {**place.osm_tags, **schema.osm_tags}
                update_fields.append("osm_tags")
                updated = True

        # Update extra data (merge strategy)
        if "extra" not in protected and schema.extra:
            if place.extra != schema.extra:
                place.extra = {**place.extra, **schema.extra}
                update_fields.append("extra")
                updated = True

        # Save place if updated (track_modifications=False for imports)
        if updated:
            place.save(update_fields=update_fields, track_modifications=False)

        # Update or create detail model (flattened structure)
        from ..schemas import DetailType

        detail_updated = False
        if schema.detail_type == DetailType.AMENITY and schema.operating_status:
            # Build amenity detail data from flattened schema
            try:
                amenity_detail = place.amenity_detail
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

            if "phones" not in protected and schema.phones:
                new_phones = [
                    p.model_dump() if hasattr(p, "model_dump") else p
                    for p in schema.phones
                ]
                if amenity_detail.phones != new_phones:
                    amenity_detail.phones = new_phones
                    update_fields.append("phones")
                    detail_updated = True

            if "brand" not in protected and schema.brand:
                brand = Category.objects.get(slug=schema.brand.slug)
                if amenity_detail.brand != brand:
                    amenity_detail.brand = brand
                    update_fields.append("brand")
                    detail_updated = True

            if is_new:
                amenity_detail.save()
            elif update_fields:
                amenity_detail.save(update_fields=update_fields)

        elif schema.detail_type == DetailType.ADMIN and schema.admin_level:
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
        if updated or detail_updated:
            return place, UpdateCreateStatus.updated
        return place, UpdateCreateStatus.no_change

    def add_source(
        self,
        source: Organization | int | str,
        source_id: str | None = None,
        **kwargs,
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

    @classmethod
    def create_amenity(
        cls,
        source: Organization | int | str,
        source_id: str | None = None,
        amenity_data: dict | None = None,
        **kwargs,
    ) -> "GeoPlace":
        """
        Create a new GeoPlace with AmenityDetail.

        Args:
            source: Organization instance, ID, or slug
            source_id: External ID used by the source
            amenity_data: Data for AmenityDetail model (operating_status, opening_hours, phones, etc.)
            **kwargs: Fields for GeoPlace creation (name, location, websites, etc.)

        Returns:
            Created GeoPlace instance with AmenityDetail and source association

        Example:
            place = GeoPlace.create_amenity(
                source="osm",
                source_id="n123456",
                name="Mountain Bakery",
                location=Point(8.1234, 46.7890),
                place_type=bakery_category,
                country_code="CH",
                websites=[{"url": "https://bakery.example.com", "label": "Official"}],
                amenity_data={
                    "operating_status": "open",
                    "opening_hours": {"mon": [["07:00", "12:00"]]},
                },
            )
        """
        from ._amenity_detail import AmenityDetail
        from ._associations import GeoPlaceSourceAssociation

        # Set detail_type
        kwargs["detail_type"] = DetailType.AMENITY

        # Resolve source to Organization instance
        if isinstance(source, str):
            source_obj = Organization.objects.get(slug=source)
        elif isinstance(source, int):
            source_obj = Organization.objects.get(pk=source)
        else:
            source_obj = source

        # Create the place
        place = cls.objects.create(**kwargs)

        # Create amenity detail
        if amenity_data:
            AmenityDetail.objects.create(
                geo_place=place,
                **amenity_data,
            )

        # Create source association
        GeoPlaceSourceAssociation.objects.create(
            geo_place=place,
            organization=source_obj,
            source_id=source_id or "",
        )

        return place

    @classmethod
    def create_transport(
        cls,
        source: Organization | int | str,
        source_id: str | None = None,
        **kwargs,
    ) -> "GeoPlace":
        """
        Create a new GeoPlace with TransportDetail.

        Note: TransportDetail model not yet implemented - this is a placeholder
        for future use as per WEP008.

        Args:
            source: Organization instance, ID, or slug
            source_id: External ID used by the source
            **kwargs: Fields for GeoPlace creation (name, location, etc.)

        Returns:
            Created GeoPlace instance with source association

        Example:
            place = GeoPlace.create_transport(
                source="osm",
                source_id="n789012",
                name="Zermatt Station",
                location=Point(7.7343, 46.0234),
                place_type=train_station_category,
                country_code="CH",
            )
        """
        from ._associations import GeoPlaceSourceAssociation

        # Set detail_type
        kwargs["detail_type"] = DetailType.TRANSPORT

        # Resolve source to Organization instance
        if isinstance(source, str):
            source_obj = Organization.objects.get(slug=source)
        elif isinstance(source, int):
            source_obj = Organization.objects.get(pk=source)
        else:
            source_obj = source

        # Create the place
        place = cls.objects.create(**kwargs)

        # TransportDetail will be created here in the future

        # Create source association
        GeoPlaceSourceAssociation.objects.create(
            geo_place=place,
            organization=source_obj,
            source_id=source_id or "",
        )

        return place

    @classmethod
    def create_admin(
        cls,
        source: Organization | int | str,
        source_id: str | None = None,
        admin_data: dict | None = None,
        **kwargs,
    ) -> "GeoPlace":
        """
        Create a new GeoPlace with AdminDetail.

        Args:
            source: Organization instance, ID, or slug
            source_id: External ID used by the source
            admin_data: Data for AdminDetail model (admin_level, population, etc.)
            **kwargs: Fields for GeoPlace creation (name, location, etc.)

        Returns:
            Created GeoPlace instance with AdminDetail and source association

        Example:
            place = GeoPlace.create_admin(
                source="geonames",
                source_id="2658434",
                name="Zermatt",
                location=Point(7.7343, 46.0234),
                place_type=village_category,
                country_code="CH",
                admin_data={
                    "admin_level": 10,
                    "population": 5700,
                    "postal_code": "3920",
                },
            )
        """
        from ._admin_detail import AdminDetail
        from ._associations import GeoPlaceSourceAssociation

        # Set detail_type
        kwargs["detail_type"] = DetailType.ADMIN

        # Resolve source to Organization instance
        if isinstance(source, str):
            source_obj = Organization.objects.get(slug=source)
        elif isinstance(source, int):
            source_obj = Organization.objects.get(pk=source)
        else:
            source_obj = source

        # Create the place
        place = cls.objects.create(**kwargs)

        # Create admin detail
        if admin_data:
            AdminDetail.objects.create(
                geo_place=place,
                **admin_data,
            )

        # Create source association
        GeoPlaceSourceAssociation.objects.create(
            geo_place=place,
            organization=source_obj,
            source_id=source_id or "",
        )

        return place

    @classmethod
    def create_natural(
        cls,
        source: Organization | int | str,
        source_id: str | None = None,
        **kwargs,
    ) -> "GeoPlace":
        """
        Create a new GeoPlace for natural features.

        Natural features (peaks, passes, lakes, glaciers) have detail_type=natural
        but no detail model - the category slug and existing GeoPlace fields
        (location, elevation, name, parent) are sufficient.

        Args:
            source: Organization instance, ID, or slug
            source_id: External ID used by the source
            **kwargs: Fields for GeoPlace creation (name, location, etc.)

        Returns:
            Created GeoPlace instance with source association

        Example:
            place = GeoPlace.create_natural(
                source="geonames",
                source_id="2658434",
                name="Matterhorn",
                location=Point(7.6588, 45.9763),
                place_type=peak_category,
                elevation=4478,
                country_code="CH",
                importance=95,
            )
        """
        from ._associations import GeoPlaceSourceAssociation

        # Set detail_type
        kwargs["detail_type"] = DetailType.NATURAL

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
