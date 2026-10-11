import uuid

from model_utils.fields import MonitorField
from modeltrans.fields import TranslationField

from django.contrib.auth import get_user_model
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from server.apps.categories.models import Category
from server.apps.licenses.models import License
from server.apps.organizations.models import Organization
from server.core.managers import BaseMutlilingualManager
from server.core.models import TimeStampedModel

User = get_user_model()


class _SymbolStyleChoices(models.TextChoices):
    detailed = "detailed", "detailed"
    simple = "simple", "simple"
    mono = "mono", "mono"
    outlined = "outlined", "outlined"
    filled = "filled", "filled"
    detailed_animated = "detailed-animated", "detailed-animated"
    simple_animated = "simple-animated", "simple-animated"
    mono_animated = "mono-animated", "mono-animated"
    outlined_animated = "outlined-animated", "outlined-animated"
    filled_animated = "filled-animated", "filled-animated"


class _ReviewStatusChoices(models.TextChoices):
    pending = "pending", _("Pending")
    approved = "approved", _("Approved")
    disabled = "disabled", _("Disabled")
    rejected = "rejected", _("Rejected")


class Symbol(TimeStampedModel):
    """SVG icon with style variants."""

    # i18n = TranslationField(fields=())  # No translatable fields currently
    objects = BaseMutlilingualManager()
    ReviewStatusChoices = _ReviewStatusChoices
    StyleChoices = _SymbolStyleChoices

    # Identification
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(
        max_length=100,
        db_index=True,
        help_text=_("Symbol identifier (e.g., 'water', 'mountain')"),
    )
    style = models.CharField(
        max_length=20,
        choices=_SymbolStyleChoices.choices,
        default=_SymbolStyleChoices.detailed,
        db_index=True,
        verbose_name=_("Style"),
        help_text=_("Symbol style variant"),
    )

    # File
    svg_file = models.FileField(
        upload_to="symbols/",
        verbose_name=_("SVG File"),
        help_text=_("SVG file for this symbol"),
    )

    # Search/discovery
    search_text = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Search Text"),
        help_text=_("Keywords for admin search (e.g., 'water, river, lake, blue')"),
    )

    # Status
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Active"),
        help_text=_("Only shown to admin if not active"),
    )
    review_status = models.CharField(
        max_length=12,
        choices=_ReviewStatusChoices.choices,
        default=_ReviewStatusChoices.approved,
        verbose_name=_("Review status"),
    )
    review_comment = models.TextField(
        verbose_name=_("Review Comment"), blank=True, default=""
    )

    # Attribution
    license = models.ForeignKey(
        License, on_delete=models.CASCADE, verbose_name=_("License")
    )
    author = models.CharField(
        max_length=255, default="", blank=True, null=True, verbose_name=_("Author")
    )
    author_url = models.URLField(
        blank=True, max_length=500, null=True, default="", verbose_name=_("Author URL")
    )

    # Source
    source_url = models.URLField(
        blank=True, max_length=500, null=True, default="", verbose_name=_("Source URL")
    )
    source_ident = models.CharField(
        max_length=512,
        default="",
        blank=True,
        null=True,
        verbose_name=_("Source Identification"),
    )
    source_org = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name=_("Source Organization"),
    )

    # User tracking - upload
    uploaded_by_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name=_("Uploaded By (User)"),
        related_name="symbol_uploaded_set",
    )
    uploaded_by_anonym = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        default="",
        verbose_name=_("Uploaded By (Anonym)"),
        help_text=_("E-mail or name of the anonymous uploader"),
    )
    uploaded_date = MonitorField(monitor="svg_file", verbose_name=_("Uploaded Date"))

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        verbose_name = _("Symbol")
        verbose_name_plural = _("Symbols")
        ordering = ("slug", "style")
        indexes = (
            models.Index(fields=["slug", "style"]),
            models.Index(fields=["is_active", "slug"]),
        )
        constraints = (
            models.UniqueConstraint(
                fields=["slug", "style"],
                name="symbols_symbol_slug_style_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(review_status__in=_ReviewStatusChoices.values),
                name="symbols_symbol_review_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(style__in=_SymbolStyleChoices.values),
                name="symbols_symbol_style_valid",
            ),
        )

    def __str__(self) -> str:
        return f"{self.slug} ({self.get_style_display()})"  # pyright: ignore[reportAttributeAccessIssue]  # choices auto-method

    @classmethod
    def get_fields_all(cls) -> list[str]:
        return [
            "id",
            "slug",
            "style",
            "svg_file",
            "search_text",
            "license",
            "author",
            "author_url",
            "source_url",
            "source_org",
            "is_active",
        ]

    @classmethod
    def get_fields_in(cls):
        return list(set(cls.get_fields_all()) - {"created", "modified", "id"})

    @classmethod
    def get_fields_update(cls):
        return list(set(cls.get_fields_all()) - {"created", "modified"})

    @classmethod
    def get_fields_out(cls):
        return cls.get_fields_all()

    @classmethod
    def get_fields_exclude(cls):
        return ["created", "modified"]


class SymbolGroup(Symbol):
    """
    Proxy model for grouping symbols by slug in admin.

    This allows displaying all style variants of a symbol
    (filled, outlined, outlined-mono, animated variants, etc.)
    on a single line in the admin interface.
    """

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        proxy = True
        verbose_name = _("Symbol Group")
        verbose_name_plural = _("Symbol Groups")


class SymbolCollection(TimeStampedModel):
    """A pack of icons from one source (e.g. ``fluent-emoji``).

    Same concept as meteo's ``WeatherCodeSymbolCollection``: creating a
    pack is a data operation, not a code change. ``extra`` records the
    pinned upstream refs an import ran against (openspec: icon-library).
    """

    i18n = TranslationField(fields=())  # No translatable fields currently
    objects = BaseMutlilingualManager()

    slug = models.SlugField(
        max_length=100,
        unique=True,
        db_index=True,
        verbose_name=_("Slug"),
        help_text=_("Unique identifier for this icon pack"),
    )
    source_org = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="symbol_collections",
        verbose_name=_("Source Organization"),
        help_text=_("Organization providing this icon pack"),
    )
    extra = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Extra Metadata"),
        help_text=_(
            "Additional metadata as JSON. Import commands record their "
            "pinned upstream refs here."
        ),
    )

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        verbose_name = _("Symbol Collection")
        verbose_name_plural = _("Symbol Collections")
        ordering = ("slug",)

    def __str__(self) -> str:
        return self.slug


class Icon(TimeStampedModel):
    """One icon within a pack (openspec: icon-library).

    Identity is ``(pack, slug)``: the same upstream slug may exist in
    several packs, each with its own assets and keywords. The three
    symbol slots follow ``Category``'s naming exactly so
    ``resolve_symbol_urls()`` works unchanged. ``category`` references a
    non-root (subgroup) ``Category`` for taxonomy browsing; roots are
    rejected in ``clean()`` (a DB CHECK cannot span joins).
    """

    i18n = TranslationField(fields=("name",))
    objects = BaseMutlilingualManager()

    pack = models.ForeignKey(
        SymbolCollection,
        on_delete=models.PROTECT,
        related_name="icons",
        db_index=True,
        verbose_name=_("Pack"),
        help_text=_("Icon pack this icon belongs to"),
    )
    slug = models.SlugField(
        max_length=100,
        db_index=True,
        verbose_name=_("Slug"),
        help_text=_("Upstream icon identifier, unique within the pack"),
    )
    name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name=_("Name"),
        help_text=_("Display name (English source; translated via i18n)"),
    )
    name_i18n: str
    order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        verbose_name=_("Order"),
        help_text=_("Display order (lower values appear first)"),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Active"),
        help_text=_("Only shown to admin if not active"),
    )
    unicode = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_("Unicode"),
        help_text=_(
            "Unicode hexcode(s), variation selectors stripped "
            "(e.g. '26FA' or '1F468-200D-2764')"
        ),
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="icons",
        limit_choices_to=models.Q(parent__isnull=False),
        verbose_name=_("Category"),
        help_text=_("CLDR subgroup category (non-root)"),
    )

    symbol_detailed = models.ForeignKey(
        Symbol,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="icons_detailed",
        limit_choices_to={"style": "detailed"},
        verbose_name=_("Symbol (Detailed)"),
        help_text=_("Reference to detailed symbol from Symbols app"),
    )
    symbol_simple = models.ForeignKey(
        Symbol,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="icons_simple",
        limit_choices_to={"style": "simple"},
        verbose_name=_("Symbol (Simple)"),
        help_text=_("Reference to simple symbol from Symbols app"),
    )
    symbol_mono = models.ForeignKey(
        Symbol,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="icons_mono",
        limit_choices_to={"style": "mono"},
        verbose_name=_("Symbol (Mono)"),
        help_text=_("Reference to monochrome symbol from Symbols app"),
    )

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        verbose_name = _("Icon")
        verbose_name_plural = _("Icons")
        ordering = ("pack__slug", "order", "slug")
        indexes = (models.Index(fields=["pack", "order", "slug"]),)
        constraints = (
            models.UniqueConstraint(
                fields=["pack", "slug"],
                name="symbols_icon_pack_slug_unique",
            ),
        )

    def __str__(self) -> str:
        return f"{self.pack.slug}:{self.slug}"

    def clean(self):
        """Reject root categories (subgroups only, see design D4)."""
        super().clean()
        if self.category_id and self.category.parent_id is None:  # pyright: ignore[reportAttributeAccessIssue]  # FK attnames: django-stubs gap
            raise ValidationError(
                {"category": _("Icons may only reference non-root categories.")}
            )

    @classmethod
    def get_fields_all(cls) -> list[str]:
        return [
            "id",
            "pack",
            "slug",
            "name",
            "order",
            "is_active",
            "unicode",
            "category",
            "symbol_detailed",
            "symbol_simple",
            "symbol_mono",
        ]


class IconKeyword(TimeStampedModel):
    """Localized search keyword for an icon (openspec: icon-library).

    ``keyword`` keeps the original form for display, ``keyword_folded``
    is accent- and case-folded for matching. Sources: emojibase-data
    labels + tags per UI locale (design D5).
    """

    objects = BaseMutlilingualManager()

    icon = models.ForeignKey(
        Icon,
        on_delete=models.CASCADE,
        related_name="keywords",
        db_index=True,
        verbose_name=_("Icon"),
    )
    locale = models.CharField(
        max_length=8,
        db_index=True,
        verbose_name=_("Locale"),
        help_text=_("Language code of this keyword (de, en, fr, it)"),
    )
    keyword = models.CharField(
        max_length=200,
        verbose_name=_("Keyword"),
        help_text=_("Original keyword form (label or tag)"),
    )
    keyword_folded = models.CharField(
        max_length=200,
        verbose_name=_("Keyword (folded)"),
        help_text=_("Accent- and case-folded form used for matching"),
    )

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        verbose_name = _("Icon Keyword")
        verbose_name_plural = _("Icon Keywords")
        ordering = ("icon", "locale", "keyword_folded")
        indexes = (
            models.Index(fields=["locale", "keyword_folded"]),
            # Trigram GIN: serves the ranked search's leading-wildcard
            # ``keyword_folded__contains`` scans (mirrors hut/geoplace).
            GinIndex(
                fields=["keyword_folded"],
                name="iconkeyword_folded_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        )
        constraints = (
            models.UniqueConstraint(
                fields=["icon", "locale", "keyword_folded"],
                name="symbols_iconkeyword_icon_locale_folded_unique",
            ),
        )

    def __str__(self) -> str:
        return f"{self.locale}:{self.keyword}"


class IconCuratedList(TimeStampedModel):
    """A named, admin-curated icon shortlist (openspec: icon-library).

    Pickers request lists by slug (``GET /v1/icons?list=activities``):
    activities, overlays, basemaps markers — any context wanting a
    hand-picked set. Curation is pure admin data: the import never
    touches it, so re-imports cannot clobber manual curation.
    """

    i18n = TranslationField(fields=("name",))
    objects = BaseMutlilingualManager()

    slug = models.SlugField(
        max_length=100,
        unique=True,
        db_index=True,
        verbose_name=_("Slug"),
        help_text=_("List identifier requested by clients (e.g. 'activities')"),
    )
    name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name=_("Name"),
        help_text=_("Display name (English source; translated via i18n)"),
    )
    name_i18n: str
    icons = models.ManyToManyField(
        Icon,
        through="IconCuratedListEntry",
        related_name="curated_lists",
        blank=True,
        verbose_name=_("Icons"),
        help_text=_("Curated icons, managed in the admin"),
    )

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        verbose_name = _("Icon Curated List")
        verbose_name_plural = _("Icon Curated Lists")
        ordering = ("slug",)

    def __str__(self) -> str:
        return self.slug


class IconCuratedListEntry(TimeStampedModel):
    """Membership of one icon in one curated list.

    An explicit through model (not an auto M2M table) so membership
    changes carry timestamps — the icons-endpoint ETag keys on them.
    """

    objects = BaseMutlilingualManager()

    curated_list = models.ForeignKey(
        IconCuratedList,
        on_delete=models.CASCADE,
        related_name="entries",
        db_index=True,
        verbose_name=_("Curated list"),
    )
    icon = models.ForeignKey(
        Icon,
        on_delete=models.CASCADE,
        related_name="curated_list_entries",
        db_index=True,
        verbose_name=_("Icon"),
    )

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        verbose_name = _("Icon Curated List Entry")
        verbose_name_plural = _("Icon Curated List Entries")
        ordering = ("curated_list", "icon__order", "icon__slug")
        constraints = (
            models.UniqueConstraint(
                fields=["curated_list", "icon"],
                name="symbols_iconcuratedlistentry_list_icon_unique",
            ),
        )

    def __str__(self) -> str:
        return f"{self.curated_list_id}:{self.icon_id}"  # pyright: ignore[reportAttributeAccessIssue]  # FK attnames: django-stubs gap
