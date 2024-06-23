import uuid

from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField

from django.contrib.auth import get_user_model
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils.translation import gettext_lazy as _

# from imagefocus import ImageFocusField
from server.apps.licenses.models import License
from server.apps.meta_image_field.fields import MetaImageField
from server.apps.organizations.models import Organization
from server.core.managers import BaseMutlilingualManager

# from .forms import CustomImageField
User = get_user_model()


class _ReviewStatusChoices(models.TextChoices):
    pending = "pending", _("pending")
    approved = "approved", _("approved")
    disabled = "disabled", _("disabled")
    rejected = "rejected", _("rejected")


class ImageTag(TimeStampedModel):
    i18n = TranslationField(fields=("name",))
    objects = BaseMutlilingualManager()

    slug = models.SlugField(max_length=50, unique=True, verbose_name=_("Slug"), blank=False)
    name = models.TextField(max_length=50, verbose_name=_("Name"), blank=False)

    class Meta:
        verbose_name = _("Image Tag")
        ordering = ("slug",)
        indexes = (GinIndex(fields=["i18n"]),)

    def __str__(self) -> str:
        return str(self.slug)


class Image(TimeStampedModel):
    i18n = TranslationField(fields=("caption",))
    objects = BaseMutlilingualManager()
    ReviewStatusChoices = _ReviewStatusChoices

    # TODO: TAGS!!

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    image = MetaImageField(upload_to="images/", meta_field="image_meta", blank=False)
    image_meta = models.JSONField(blank=True, null=True, verbose_name=_("Image Metadata"))
    # image = models.ImageField(upload_to="images/", blank=False)
    # image = ImageUrlField(upload_to="images/", blank=False)
    # focal = ImageFocusField(image_field="image", blank=True, null=True)
    license = models.ForeignKey(License, on_delete=models.CASCADE)
    author = models.CharField(max_length=255, default="", blank=True, null=True, verbose_name=_("Author"))
    caption = models.TextField(max_length=400, verbose_name=_("Caption"), blank=False)
    tags = models.ManyToManyField(ImageTag, related_name="images", verbose_name=_("Tags"))

    granted_date = models.DateField(blank=True, null=True, verbose_name=_("Granted Date"))
    granted_by = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        default="",
        verbose_name=_("Granted By"),
        help_text=_("E-mail or name of the granted persion"),
    )
    uploaded_by_anonym = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        default="",
        verbose_name=_("Uploaded By (Anonym)"),
        help_text=_("E-mail or name of the anonymous uploader"),
    )
    uploaded_by_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, blank=True, null=True, verbose_name=_("Uploaded By (User)")
    )
    source_url = models.URLField(blank=True, max_length=500, null=True, default="", verbose_name=_("Source URL"))
    author_url = models.URLField(blank=True, max_length=500, null=True, default="", verbose_name=_("Author URL"))
    source_org = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, blank=True, null=True, verbose_name=_("Source Organization")
    )

    review_status = models.CharField(
        max_length=12,
        choices=ReviewStatusChoices.choices,
        default=ReviewStatusChoices.approved,
        verbose_name=_("Review status"),
    )

    class Meta:
        verbose_name = _("Image")
        ordering = ("created",)
        indexes = (GinIndex(fields=["i18n"]),)
        constraints = (
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_review_status_valid",
                check=models.Q(review_status__in=_ReviewStatusChoices.values),
            ),
        )

    def __str__(self) -> str:
        return str(self.caption_i18n)

    @classmethod
    def get_fields_all(cls) -> list[str]:
        return [
            "id",
            "image",
            "license",
            "caption",
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
