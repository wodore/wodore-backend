# Create your models here.

from model_utils.models import TimeStampedModel

from django.db import models
from django.utils.translation import gettext_lazy as _


class _FeedbackStatusChoices(models.TextChoices):
    new = "new", _("new")
    done = "done", _("done")
    work = "work", _("work")
    reject = "reject", _("reject")


class Feedback(TimeStampedModel):
    id: int

    FeedbackStatusChoices = _FeedbackStatusChoices

    email: str = models.CharField(max_length=100, blank=False, null=False)
    subject: str = models.CharField(max_length=200, blank=True, null=True, default="")
    message: str = models.TextField(max_length=10000, blank=True, null=True, default="")
    urls = models.JSONField(
        verbose_name=_("URLs"), help_text=_("Additional urls ['url1','url2',...]."), blank=True, default=list
    )
    feedback_status = models.CharField(
        max_length=12,
        choices=FeedbackStatusChoices.choices,
        default=FeedbackStatusChoices.new,
        verbose_name=_("Review status"),
    )
    feedback_comment = models.TextField(blank=True, default="", max_length=100000, verbose_name=_("Review comment"))

    def __str__(self) -> str:
        return self.email

    class Meta:
        verbose_name = _("Feedback")
        constraints = (
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_feedback_status_valid",
                check=models.Q(feedback_status__in=_FeedbackStatusChoices.values),
            ),
        )
