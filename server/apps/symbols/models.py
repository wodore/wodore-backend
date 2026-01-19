import uuid


from model_utils.fields import MonitorField
from server.core.models import TimeStampedModel

from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _

from server.apps.licenses.models import License
from server.apps.organizations.models import Organization
from server.core.managers import BaseMutlilingualManager

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

    class Meta:
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
                check=models.Q(review_status__in=_ReviewStatusChoices.values),
                name="symbols_symbol_review_status_valid",
            ),
            models.CheckConstraint(
                check=models.Q(style__in=_SymbolStyleChoices.values),
                name="symbols_symbol_style_valid",
            ),
        )

    def __str__(self) -> str:
        return f"{self.slug} ({self.get_style_display()})"

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

    class Meta:
        proxy = True
        verbose_name = _("Symbol Group")
        verbose_name_plural = _("Symbol Groups")
