from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import GinIndex, GistIndex
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from modeltrans.fields import TranslationField
from django_countries.fields import CountryField

from server.apps.categories.models import Category
from server.apps.images.models import Image
from server.apps.organizations.models import Organization
from server.core.models import TimeStampedModel

if TYPE_CHECKING:
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

    def save(self, *args, **kwargs):
        """Auto-generate slug from name if not provided."""
        if not self.slug and self.name_i18n:
            self.slug = self.generate_unique_slug(self.name_i18n, exclude_id=self.id)

        super().save(*args, **kwargs)

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
