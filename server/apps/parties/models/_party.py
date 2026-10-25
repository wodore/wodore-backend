"""Party — the neutral entity behind a place (brand, owner, operator, ...).

OpenSpec change: ``geoplace-parties`` (ISO 19115-1 ``CI_Party`` +
``CI_RoleCode``): the entity is neutral, the *relation* to a place carries
the semantics via ``GeoPlaceParty`` role categories (``role.*``).
"""

from typing import Any, override

from modeltrans.fields import TranslationField

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from server.apps.external_links.models import ReviewStatus
from server.core.managers import BaseMutlilingualManager
from server.core.models import TimeStampedModel
from server.core.utils import mint_short_slug

from ._party_link import PartyLink


class Party(TimeStampedModel):
    """A party associated to geoplaces through role-classified associations.

    Localized like ``owners.Owner`` (modeltrans); links reuse ``ExternalLink``
    through ``PartyLink`` (i18n labels, link types, health checks). Symbols
    reuse the curated SVG pipeline — color and mono only: parties are not map
    features, so the map-styling primitive variant has no consumer here.
    """

    i18n = TranslationField(fields=("name", "note"))
    objects = BaseMutlilingualManager()

    slug = models.SlugField(
        unique=True,
        db_index=True,
        blank=True,
        max_length=15,
        verbose_name=_("Slug"),
        help_text=_("Short public identifier; minted from the name when left blank"),
    )
    dedup_key = models.SlugField(
        max_length=50,
        unique=True,
        db_index=True,
        blank=True,
        verbose_name=_("Dedup key"),
        help_text=_("Normalized name - the import identity (auto-derived when blank)"),
    )
    name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name=_("Name"),
        help_text=_("For example 'SAC Bern', 'Volg', 'Migros', ..."),
    )
    name_i18n: str
    note = models.TextField(
        blank=True,
        default="",
        max_length=2000,
        verbose_name=_("Note"),
        help_text=_("Public note about the party"),
    )
    note_i18n: str

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Active"),
        help_text=_("Inactive parties are hidden from pickers and the API"),
    )
    is_public = models.BooleanField(
        default=True,
        verbose_name=_("Public"),
        help_text=_("Public parties may appear in public API responses"),
    )
    review_status = models.CharField(
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.DONE,
        db_index=True,
        verbose_name=_("Review Status"),
        help_text=_("Editorial state - imported/minted parties start in 'review'"),
    )

    links = models.ManyToManyField(
        "external_links.ExternalLink",
        through=PartyLink,
        related_name="parties",
        blank=True,
        verbose_name=_("Links"),
    )

    # Symbol references (ForeignKeys to Symbol app): exactly the two variants
    # a detail UI needs — no primitive/map-styling variant (design decision 1).
    symbol_color = models.ForeignKey(
        "symbols.Symbol",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parties_color",
        verbose_name=_("Symbol (Color)"),
        help_text=_("Reference to color symbol from Symbols app"),
        limit_choices_to={"style": "color"},
    )
    symbol_mono = models.ForeignKey(
        "symbols.Symbol",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parties_mono",
        verbose_name=_("Symbol (Monochrome)"),
        help_text=_("Reference to monochrome symbol from Symbols app"),
        limit_choices_to={"style": "mono"},
    )

    class Meta:
        verbose_name = _("Party")
        verbose_name_plural = _("Parties")
        indexes = (GinIndex(fields=["i18n"]),)
        constraints = [
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_review_status_valid",
                condition=models.Q(review_status__in=["new", "review", "work", "done"]),
            ),
        ]
        ordering = (Lower("name_i18n"),)

    @staticmethod
    def normalize_key(value: str) -> str:
        """Normalize a name to the import dedup key.

        Verbatim the OSM import's former ``_normalize_party_slug``
        (itself kept identical to the pre-parties ``_normalize_brand_slug``
        so re-imports keep matching migrated rows).
        """
        return value.lower().replace(" ", "_")[:50]

    @override
    def save(self, *args: Any, **kwargs: Any) -> None:
        """Mint the short slug and derive the dedup key when blank.

        The slug is minted once at creation and never re-derived - the
        dedup key is the stable import identity (OpenSpec change
        ``party-slug-minting``).
        """
        if not self.slug:
            base = (
                self.name
                if self.name and len(self.name.strip()) >= 2
                else self.dedup_key or ""
            )
            self.slug = mint_short_slug(base, fallback="party")
        if not self.dedup_key:
            self.dedup_key = Party.normalize_key(self.name if self.name else self.slug)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name_i18n
