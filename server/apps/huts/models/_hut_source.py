import typing as t

from deepdiff import DeepDiff

from model_utils.models import TimeStampedModel

from django.contrib.gis.db import models
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from server.apps import organizations

from server.apps.organizations.models import Organization
from server.core import UpdateCreateStatus
from server.core.managers import BaseManager


if t.TYPE_CHECKING:
    from ._hut import Hut


class _ReviewStatusChoices(models.TextChoices):
    # waiting = 'waiting'
    new = "new", _("new")
    review = "review", _("review")
    done = "done", _("done")
    old = "old", _("old")
    failed = "failed", _("failed")
    reject = "reject", _("reject")


class HutSource(TimeStampedModel):
    """
    Source data for huts, e.g from SAC.
    """

    ReviewStatusChoices = _ReviewStatusChoices

    objects: BaseManager = BaseManager()

    source_id = models.CharField(
        blank=False, max_length=100, verbose_name=_("Source ID"), help_text=_("Original ID from source object.")
    )
    version = models.PositiveSmallIntegerField(default=0, verbose_name=_("Version"))
    name = models.CharField(blank=False, max_length=100, verbose_name=_("Name"), help_text=_("Name of the object"))
    organization = models.ForeignKey(Organization, on_delete=models.RESTRICT)
    location = models.PointField(blank=True, default=None, verbose_name=_("Location"))
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name=_("Active"),
        help_text=_("If set to inactive no more updates are done from this source"),
    )
    is_current = models.BooleanField(default=True, db_index=True, verbose_name=_("Current Entry"))
    review_status = models.TextField(
        max_length=12,
        choices=ReviewStatusChoices.choices,
        default=ReviewStatusChoices.new,
        verbose_name=_("Review status"),
    )
    review_comment = models.TextField(blank=True, default="", max_length=10000, verbose_name=_("Review comment"))
    source_data = models.JSONField(
        verbose_name=_("Source data as JSON"), help_text=_("Data from the source model."), blank=True, default=dict
    )
    source_properties = models.JSONField(
        verbose_name=_("Source properties as JSON"),
        help_text=_("Additional properties from the source model."),
        blank=True,
        default=dict,
    )
    previous_object = models.ForeignKey["HutSource"](
        "self",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name=_("Previous Entry"),
        help_text=_("Id to the previous object."),
    )
    hut = models.ForeignKey["Hut"](
        "Hut", null=True, blank=True, related_name="hut_sources", on_delete=models.SET_NULL, verbose_name=_("Hut")
    )

    class Meta:
        verbose_name = "Hut Source"
        verbose_name_plural = "Hut Sources"
        ordering = (Lower("name"), "organization__order")
        constraints = (
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_review_status_valid",
                check=models.Q(review_status__in=_ReviewStatusChoices.values),
            ),
        )

    def __str__(self) -> str:
        return f"{self.name} v{self.version} ({self.organization.name_i18n})"

    @classmethod
    def add(
        cls, hut_source: "HutSource", new_review_status: "HutSource.ReviewStatusChoices" = ReviewStatusChoices.new
    ) -> tuple["HutSource", UpdateCreateStatus]:
        # check if already in DB
        status: UpdateCreateStatus = UpdateCreateStatus.ignored
        try:
            other_hut_src = cls.objects.get(
                source_id=hut_source.source_id, organization=hut_source.organization, is_current=True
            )
            if other_hut_src.is_active is False:  # ignore if not active
                return hut_source, UpdateCreateStatus.ignored
            diff = DeepDiff(
                other_hut_src.source_data,
                hut_source.source_data,
                ignore_type_in_groups=[DeepDiff.numbers, (list, tuple)],
            )
            if diff:  # something changed, add a new entry:
                diff_comment = (
                    diff.pretty()
                    .replace("root[", "")
                    .replace("']['", ".")
                    .replace("']", "'")
                    .replace("'[", "[")
                    .replace("]['", "].")
                    .replace("] ", "]' ")
                )
                if other_hut_src.review_status == cls.ReviewStatusChoices.review and other_hut_src.review_comment:
                    diff_comment += (
                        f"\n\n~~~\nComments from version {other_hut_src.version}:\n\n{other_hut_src.review_comment}"
                    )
                if len(diff_comment) >= 5000:
                    diff_comment = "alot changed, have a look ..."
                hut_source.review_comment = diff_comment
                hut_source.review_status = cls.ReviewStatusChoices.review
                if other_hut_src is not None:
                    hut_source.previous_object = other_hut_src
                hut_source.version = other_hut_src.version + 1
                other_hut_src.review_status = HutSource.ReviewStatusChoices.old
                other_hut_src.is_current = False
                # check hut and chagne status
                hut_db: None | Hut = None
                if other_hut_src.hut is not None:
                    hut_db = other_hut_src.hut
                    if hut_db is not None and hut_db.review_status == hut_db.ReviewStatusChoices.done:
                        hut_db.review_status = hut_db.ReviewStatusChoices.review
                    if hut_db is not None:
                        hut_db.add_review_comment(title=f"New source '{hut_source.organization.slug}' updates")
                        # change hut reference from old to new
                        # hut_db.sources.remove(other_hut_src)
                        other_hut_src.hut = None
                        hut_source.hut = hut_db
                with transaction.atomic():
                    hut_source.save()
                    other_hut_src.save()
                    if hut_db is not None:
                        hut_db.save()
                status = UpdateCreateStatus.updated
            else:
                hut_source = other_hut_src
                status = UpdateCreateStatus.no_change
        except ObjectDoesNotExist:
            hut_source.review_status = new_review_status
            hut_source.save()
            status = UpdateCreateStatus.created
        return hut_source, status
