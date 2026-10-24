"""Through-model connecting Parties to ExternalLinks.

Mirrors ``GeoPlaceExternalLink``: one link entity can serve a place and a
party; ordering is per association.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel


class PartyLink(TimeStampedModel):
    party = models.ForeignKey(
        "Party",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="link_associations",
        verbose_name=_("Party"),
    )
    external_link = models.ForeignKey(
        "external_links.ExternalLink",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="party_associations",
        verbose_name=_("External Link"),
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        verbose_name=_("Order"),
        help_text=_("Display order for this link"),
    )

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        verbose_name = _("Party Link")
        verbose_name_plural = _("Party Links")
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["party", "order"]),
            models.Index(fields=["external_link"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["party", "external_link"],
                name="%(app_label)s_%(class)s_unique_party_link",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.party}: {self.external_link.label_i18n}"
