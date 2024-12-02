import io
from django.utils.timezone import make_aware
import logging
import mimetypes
import os
import time
import uuid

import requests
from colorfield.fields import ColorField
from hut_services import LicenseSchema, PhotoSchema, TranslationSchema
from PIL import Image as PILImage

from model_utils.fields import (
    MonitorField,
)
from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField

from django.contrib.auth import get_user_model
from django.contrib.postgres.indexes import GinIndex
from django.core.files.base import ContentFile
from django.db import IntegrityError, models
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

# from imagefocus import ImageFocusField
from server.apps.images.transfomer import ImagorImage
from server.apps.licenses.models import License
from server.apps.meta_image_field.fields import MetaImageField
from server.apps.meta_image_field.schema import MetaImageSchema
from server.apps.organizations.models import Organization
from server.apps.utils.fields import MonitorFields
from server.core.managers import BaseMutlilingualManager
import contextlib

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

    color = ColorField(verbose_name=_("Color"), help_text=_("color as hex number with #"), default="#4B8E43")

    class Meta:
        verbose_name = _("Image Tag")
        ordering = ("slug",)
        indexes = (GinIndex(fields=["i18n"]),)

    def __str__(self) -> str:
        return str(self.slug)


class Image(TimeStampedModel):
    # TODO:
    # add size field
    # add long caption or something ..
    i18n = TranslationField(fields=("caption",))
    objects = BaseMutlilingualManager()
    ReviewStatusChoices = _ReviewStatusChoices

    # TODO: TAGS!!

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    image = MetaImageField(upload_to="images/", meta_field="image_meta", blank=False)
    image_meta = models.JSONField(blank=True, null=True, verbose_name=_("Image Metadata"))
    is_active = models.BooleanField(
        default=True, db_index=True, verbose_name=_("Active"), help_text=_("Only shown to admin if not active")
    )
    license = models.ForeignKey(License, on_delete=models.CASCADE)
    author = models.CharField(max_length=255, default="", blank=True, null=True, verbose_name=_("Author"))
    author_url = models.URLField(blank=True, max_length=500, null=True, default="", verbose_name=_("Author URL"))
    caption = models.TextField(max_length=400, verbose_name=_("Caption"), blank=False)
    tags = models.ManyToManyField(ImageTag, related_name="images", verbose_name=_("Tags"), blank=True)
    review_comment = models.TextField(verbose_name=_("Review Comment"), blank=True, default="")

    capture_date = models.DateTimeField(verbose_name=_("Capture Date"), blank=True, null=True)
    granted_date = MonitorFields(monitors=["granted_by_anonym", "granted_by_user"], verbose_name=_("Granted Date"))
    granted_by_anonym = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        default="",
        verbose_name=_("Granted By (Anonym)"),
        help_text=_("E-mail or name of the granted person"),
    )
    granted_by_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name=_("Granted By (User)"),
        related_name="image_granted_set",
    )
    uploaded_date = MonitorField(monitor="image", verbose_name=_("Uploaded Date"))
    uploaded_by_anonym = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        default="",
        verbose_name=_("Uploaded By (Anonym)"),
        help_text=_("E-mail or name of the anonymous uploader"),
    )
    uploaded_by_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name=_("Uploaded By (User)"),
        related_name="image_uploaded_set",
    )
    source_url = models.URLField(blank=True, max_length=500, null=True, default="", verbose_name=_("Source URL"))
    source_url_raw = models.URLField(
        blank=True, max_length=500, null=True, default="", verbose_name=_("Source URL to raw image")
    )
    source_ident = models.CharField(
        max_length=512, default="", blank=True, null=True, verbose_name=_("Source Identification")
    )
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
        if len(str(self.caption_i18n)) > 40:
            return str(self.caption_i18n[:40]) + " ..."
        return str(self.caption_i18n)

    def get_image_tag(self, width: int = 100, height: int = 60, radius: int = 0):  # new
        try:
            focal = self.image_meta.get("focal") if self.image_meta else None
            if focal:
                focal_str = f"{focal.get('x1',0)}x{focal.get('y1',0)}:{focal.get('x2',1)}x{focal.get('y2',1)}"
                crop_start, crop_stop = focal_str.split(":")
            else:
                # focal_str = "0x0:1x1"
                focal_str = None
                crop_start = None
                crop_stop = None
            img = (
                ImagorImage(self.image)
                .transform(
                    size=f"{width}x{height}",
                    focal=focal_str,
                    crop_start=crop_start,
                    crop_stop=crop_stop,
                    round_corner=(radius),
                )
                .get_html()
            )
        except Exception as e:
            print(e)
            img = "Missing"
        return mark_safe(img)

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

    @classmethod
    def create_image_from_schema(
        cls,
        photo_schema: PhotoSchema,
        path: str = "",
        default_caption: str | TranslationSchema | None = None,
        tags: list[str] | None = None,
    ) -> "Image | None":
        # Check if the image already exists based on the source.ident field
        # TODO: check if it already exists
        # source org special cases
        source_org_slug = photo_schema.source.name if photo_schema.source else None
        source_ident = ""
        if source_org_slug:
            source_ident = (
                f"{source_org_slug}-{photo_schema.source.ident}"
                if photo_schema.source and photo_schema.source.ident
                else ""
            )
            if source_org_slug == "refuges.info":
                source_org_slug = "refuges"
        else:
            source_ident = photo_schema.source.ident if photo_schema.source and photo_schema.source.ident else ""

        if cls.objects.filter(source_ident=source_ident).exists():
            logging.info("Image already exists, skipping...")
            return cls.objects.get(source_ident=source_ident)

        headers = {"User-Agent": "Wodore Backend Bot/1.0 (https://www.wodore.com)"}
        # Download the image from the raw_url
        try:
            response = requests.get(photo_schema.raw_url, headers=headers, timeout=10)
            time.sleep(0.2)  # not too many request at once ...
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                if "-originale" in photo_schema.raw_url:
                    # fix wrong url for refuges.info images
                    photo_schema.raw_url = photo_schema.raw_url.replace("-originale", "-reduite")
                    return cls.create_image_from_schema(
                        photo_schema, path=path, default_caption=default_caption, tags=tags
                    )
                logging.warning(
                    "Image not found: %s", photo_schema.source.url if photo_schema.source else photo_schema.raw_url
                )
                return None
        except requests.exceptions.ReadTimeout:
            logging.warning("Read timeout: %s. Skipping this one.", photo_schema.raw_url)
            return None
        except requests.exceptions.ConnectionError:
            logging.warning("Connection refused: %s. Sleep for 2 min.", photo_schema.raw_url)
            time.sleep(2 * 60)
            # try again
            return cls.create_image_from_schema(photo_schema, path=path, default_caption=default_caption, tags=tags)
        except:
            raise  # Re-raise the exception if it's not a 404 error
        image_content = response.content
        mime_type = mimetypes.guess_type(photo_schema.raw_url)[0]

        if mime_type == "image/jpeg":
            extension = ".jpg"
        elif mime_type == "image/png":
            extension = ".png"
        elif mime_type is None:
            # could not get image type
            return None
        else:
            msg = f"Unsupported image type: {mime_type}"
            raise ValueError(msg)

        image_uuid = uuid.uuid4()
        image_file = ContentFile(image_content, name=os.path.join(path, f"{image_uuid}{extension}"))

        # Get the image dimensions using Pillow
        pil_image = PILImage.open(io.BytesIO(image_content))
        width, height = pil_image.size

        img_review_status = Image.ReviewStatusChoices.approved
        # Create a new Image instance
        license = LicenseSchema(slug="unkown", name="Unknown")
        for lic in photo_schema.licenses:
            license = photo_schema.licenses[0]
            if "cc" in lic.slug:
                break

        lic_slug = license.slug  # .replace(".", "p")
        review_comment = ""
        if not License.objects.filter(slug=lic_slug).exists():
            img_review_status = Image.ReviewStatusChoices.pending
            review_comment += f"- Added new license: '{lic_slug}'\n"

        # source org special cases
        if source_org_slug:
            source_org_slug = source_org_slug[:50]
            source_org = Organization.objects.get_or_create(
                slug=source_org_slug, defaults={"name_en": photo_schema.source.name[:100]}
            )[0]
            if not Organization.objects.filter(slug=source_org_slug).exists():
                img_review_status = Image.ReviewStatusChoices.pending
                review_comment += f"- Added new organization: '{source_org_slug}'\n"
        else:
            source_org = None

        # tags
        tags_set = []
        for tag in set((tags or []) + (photo_schema.tags or [])):
            tag_obj, created = ImageTag.objects.get_or_create(slug=tag, defaults={"name_en": tag})
            if created:
                img_review_status = Image.ReviewStatusChoices.pending
                review_comment += f"- Added new tag: '{tag}'\n"
            tags_set.append(tag_obj)

        image = cls(
            id=image_uuid,
            review_status=img_review_status,
            image=image_file,
            # license=License.objects.get_or_create(slug=license.slug)[0],
            license=License.objects.get_or_create(
                slug=lic_slug,
                defaults={"name_en": license.name, "fullname_en": license.name, "link_en": license.url},
            )[0],
            source_org=source_org,
            author=photo_schema.author.name if photo_schema.author else "",
            author_url=(
                photo_schema.author.url.replace("&action=edit", "").replace("&redlink=1", "")
                if photo_schema.author and photo_schema.author.url
                else ""
            ),
            source_url=photo_schema.source.url if photo_schema.source else "",
            source_url_raw=photo_schema.raw_url if photo_schema.raw_url else "",
            source_ident=source_ident,
            image_meta=MetaImageSchema(width=width, height=height).model_dump(exclude_none=True),
            capture_date=(
                None
                if photo_schema.capture_date is None
                else (
                    photo_schema.capture_date
                    if photo_schema.capture_date.tzinfo is not None
                    else make_aware(photo_schema.capture_date) if photo_schema.capture_date else None
                )
            ),
        )
        image.save()  # this is needed to add the tags
        image.tags.set(tags_set)

        # Add translations
        updated = False
        for lang, text in photo_schema.caption:
            field_name = f"caption_{lang}"
            if hasattr(image, field_name) and text:
                updated = True
                setattr(image, field_name, text.strip().strip('"'))
        if not updated:
            if not default_caption:
                default_caption = (
                    os.path.basename(photo_schema.raw_url)
                    .replace(".jpg", "")
                    .replace(".png", "")
                    .replace(".jpeg", "")
                    .replace(".JPG", "")
                    .replace(".PNG", "")
                    .replace(".JPEG", "")
                    if photo_schema.raw_url is not None
                    else ""
                )
                review_comment += f"- Missing caption, use '{default_caption}' from file path instead.\n"
                img_review_status = Image.ReviewStatusChoices.pending
            if source_org_slug == "refuges":
                image.caption_fr = default_caption.strip().strip('"')
            else:
                image.caption_de = default_caption.strip().strip('"')
        if photo_schema.comment:
            review_comment += f"\n---\nSource Comment:\n\n{photo_schema.comment}\n"
        review_comment += f"\n---\nSource Data:\n\n```json\n{photo_schema.model_dump_json(indent=2)}\n```"
        image.review_comment = review_comment
        image.review_status = img_review_status

        try:
            # image.save()
            logging.info("Image added successfully!")
            return image
        except IntegrityError as e:
            logging.error("Error adding image %s: %s", image.caption_de, e)
            return None
