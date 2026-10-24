# from django.db import models
from computedfields.models import ComputedFieldsModel, computed
from jinja2 import Environment

from modeltrans.manager import MultilingualManager

from django.conf import settings
from django.contrib.gis.db import models
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from server.apps.contacts.models import Contact
from server.apps.images.models import Image
from server.apps.organizations.models import Organization
from server.core.models import TimeStampedModel


class HutContactAssociation(TimeStampedModel):
    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name="details", db_index=True
    )
    hut = models.ForeignKey("Hut", on_delete=models.CASCADE, db_index=True)
    order = models.PositiveSmallIntegerField(blank=True, null=True)

    def __str__(self) -> str:
        return f"{self.hut} <> {self.contact}"

    class Meta:
        verbose_name = _("Contact and Hut Association")
        ordering = ("contact__function__priority", "order", "hut__name")
        app_label = "huts"
        constraints = (
            models.UniqueConstraint(
                name="%(app_label)s_%(class)s_unique_relationships",
                fields=["contact", "hut"],
            ),
        )


class HutImageAssociation(TimeStampedModel):
    # Display-order bands inside the API contract's 0–100 (the image endpoints
    # validate properties.score against that): curated uploads/imports live in
    # 90–99 (deliberate content outranks pins), pinned external images are
    # clamped to 0–89 by pin_place_images (their provider score).
    UPLOAD_DEFAULT_SCORE = 90
    #: Highest score a pinned external image association may carry.
    PROVIDER_SCORE_MAX = 89
    #: Hard display-order ceiling (imports stack upward from UPLOAD_DEFAULT_SCORE
    #: and stop here — >10 imports share the top slot, ordering falls back to id).
    SCORE_MAX = 99

    @classmethod
    def import_score(cls, previous: int | None) -> int:
        """Score for the next import photo: stacks upward from
        ``UPLOAD_DEFAULT_SCORE`` (newest import first) and stops at
        ``SCORE_MAX`` — the image endpoints validate scores against 0–100,
        so an uncapped ``+= 1`` loop would re-mint >100 scores (and 500s)
        on large or repeated imports."""
        if previous is None:
            return cls.UPLOAD_DEFAULT_SCORE
        return min(max(previous, cls.UPLOAD_DEFAULT_SCORE - 1) + 1, cls.SCORE_MAX)

    image = models.ForeignKey(
        Image, on_delete=models.CASCADE, db_index=True, related_name="details"
    )
    hut = models.ForeignKey(
        "Hut", on_delete=models.CASCADE, db_index=True, related_name="huts"
    )
    score = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        help_text=_(
            "Display score — higher is shown first; curated uploads live in 90–99, "
            "pinned external images in 0–89."
        ),
    )

    def __str__(self) -> str:
        return f"{self.hut} <> {self.image}"

    class Meta:
        verbose_name = _("Image and Hut Association")
        ordering = ("hut__name", "-score", "id")
        app_label = "huts"
        constraints = (
            models.UniqueConstraint(
                name="%(app_label)s_%(class)s_unique_relationships",
                fields=["image", "hut"],
            ),
        )


class HutOrganizationAssociation(TimeStampedModel, ComputedFieldsModel):
    # objects = BaseMutlilingualManager()

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="source", db_index=True
    )
    hut = models.ForeignKey(
        "Hut", on_delete=models.CASCADE, db_index=True, related_name="orgs_source"
    )
    props = models.JSONField(
        help_text=_("Organization dependend properties."), blank=True, default=dict
    )
    source_id = models.CharField(
        max_length=40, blank=True, null=True, default="", help_text="Source id"
    )
    # link -> see below (computed)

    class Meta:
        verbose_name = _("Hut and Organization Association")
        constraints = (
            models.UniqueConstraint(
                name="%(app_label)s_%(class)s_unique_relationships",
                fields=["organization", "hut"],
            ),
        )

    objects = MultilingualManager()

    def __str__(self) -> str:
        return f"{self.hut} <> {self.organization}"

    # TODO: does not work for different languages, needs one field for each ...
    @computed(
        models.CharField(
            max_length=200,
            blank=True,
            null=True,
            default="",
            help_text=_("Link to object by this organisation"),
        ),
        depends=[
            ("self", ["props", "source_id"]),
            ("organization", ["link_hut_pattern", "config", "slug"]),
        ],
    )
    def link(self):
        lang = get_language() or settings.LANGUAGE_CODE  # TODO lang replace by query
        link_pattern = self.organization.link_hut_pattern
        _tmpl = Environment().from_string(link_pattern)
        return _tmpl.render(
            lang=lang,
            slug=self.organization.slug,
            id=self.source_id,
            props=self.props,
            config=self.organization.config,
        )

    @property
    def link_i18n(self):
        return self.link
        # lang = get_language() or settings.LANGUAGE_CODE  # TODO lang replace by query
        # if self.link is not None:
        #    return self.link.replace("#LANG#", lang)
        # return ""
