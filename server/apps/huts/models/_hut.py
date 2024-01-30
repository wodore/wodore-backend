import datetime
import typing as t

from django_extensions.db.fields import AutoSlugField
from easydict import EasyDict
from hut_services import (
    AnswerEnum,
    BaseService,
    HutSchema,
    HutSourceSchema,
    HutTypeEnum,
    OpenMonthlySchema,
)
from hut_services.core.guess import guess_slug_name
from hut_services.core.schema import HutBookingsSchema as HutServiceBookingSchema
from hut_services.core.schema import OccupancyStatusEnum
from jinja2 import Environment

from django_countries.fields import CountryField
from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point as dbPoint
from django.contrib.gis.measure import D
from django.contrib.postgres.indexes import GinIndex
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Concat, Lower
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from server.apps.contacts.models import Contact, ContactFunction
from server.apps.organizations.models import Organization
from server.apps.owners.models import Owner
from server.core import UpdateCreateStatus

from ..managers import HutManager
from ..schemas_booking import HutBookingsSchema
from ._associations import HutContactAssociation, HutOrganizationAssociation
from ._hut_source import HutSource
from ._hut_type import HutType

SERVICES: dict[str, BaseService] = settings.SERVICES


class _ReviewStatusChoices(models.TextChoices):
    new = "new", _("new")
    review = "review", _("review")
    done = "done", _("done")
    work = "work", _("work")
    reject = "reject", _("reject")


def _monthly_open_default_value() -> dict[str, AnswerEnum]:
    return {f"month_{m:02}": AnswerEnum["unknown"] for m in range(1, 13)}


class Hut(TimeStampedModel):
    UPDATE_SCHEMA_FIELDS = (
        "slug",
        "name",
        "note",
        "description",
        "description_attribution",
        "location",
        "url",
        "country_code",
        "capacity",
        "type",
        "photos",
        "photos_attribution",
        "hut_type",
        "is_public",
        "open_monthly",
    )
    ReviewStatusChoices = _ReviewStatusChoices
    # manager
    objects: HutManager = HutManager()
    # translations
    i18n = TranslationField(fields=("name", "description", "note"))

    slug = models.SlugField(unique=True, verbose_name=_("Slug"), db_index=True)
    review_status = models.CharField(
        max_length=12,
        choices=ReviewStatusChoices.choices,
        default=ReviewStatusChoices.review,
        verbose_name=_("Review status"),
    )
    review_comment = models.TextField(blank=True, default="", max_length=10000, verbose_name=_("Review comment"))
    is_active = models.BooleanField(
        default=True, db_index=True, verbose_name=_("Active"), help_text=_("Only shown to admin if not active")
    )
    is_public = models.BooleanField(
        default=False, db_index=True, verbose_name=_("Public"), help_text=_("Only shown to editors if not public")
    )
    is_modified = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Modifed"),
        help_text=_("Any modification compared to the original source were done"),
    )
    name = models.CharField(max_length=100, verbose_name=_("Name"))
    name_i18n: str  # for typing
    description = models.TextField(max_length=10000, verbose_name="Description")
    description_i18n: str  # for typing
    description_attribution = models.CharField(
        blank=True, default="", max_length=1000, verbose_name=_("Descripion attribution")
    )

    hut_owner = models.ForeignKey(
        "owners.Owner",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="huts",
        verbose_name=_("Hut owner."),
        help_text=_("For example 'SAC Bern' ..."),
    )
    contact_set = models.ManyToManyField(
        Contact, through=HutContactAssociation, related_name="huts", verbose_name=_("Contacts")
    )
    url = models.URLField(blank=True, default="", max_length=200, verbose_name=_("URL"))
    note = models.TextField(
        blank=True,
        default="",
        max_length=2000,
        verbose_name=_("Note"),
        help_text=_("Public note, might be some important information"),
    )  # TODO: maybe notes with mutlipe notes and category
    note_i18n: str  # for typing

    photos = models.CharField(blank=True, default="", max_length=1000, verbose_name=_("Hut photo"))
    photos_attribution = models.CharField(
        blank=True, default="", max_length=1000, verbose_name=_("Hut photo attribution")
    )
    country_field = CountryField()
    location = models.PointField(blank=False, verbose_name="Location")
    elevation = models.DecimalField(null=True, blank=True, max_digits=5, decimal_places=1, verbose_name=_("Elevation"))
    capacity_open = models.PositiveSmallIntegerField(blank=True, null=True, verbose_name=_("Capacity if open"))
    capacity_closed = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        verbose_name=_("Capacity if closed"),
        help_text=_("Only if an additional shelter is available, e.g. during winter."),
    )
    open_monthly = models.JSONField(
        default=_monthly_open_default_value,
        verbose_name=_("Hut Open"),
        help_text=_(
            'Possible values: "yes", "maybe", "no" or "unknown". "url" is a link to information when it is open or closed.'
        ),
    )

    hut_type_open = models.ForeignKey(
        HutType,
        related_name="hut_open_set",
        on_delete=models.RESTRICT,
        verbose_name=_("Hut type if open"),
        db_index=True,
    )
    hut_type_closed = models.ForeignKey(
        HutType,
        null=True,
        blank=True,
        related_name="hut_closed_set",
        on_delete=models.RESTRICT,
        verbose_name=_("Hut type if closed"),
        db_index=True,
    )
    booking_ref = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        related_name="hut_booking_set",
        on_delete=models.SET_NULL,
        verbose_name=_("Booking Rerefence"),
        db_index=True,
    )
    # organizations = models.ManyToManyField(Organization, related_name="huts", db_table="hut_organization_association")
    org_set = models.ManyToManyField(
        Organization,
        through=HutOrganizationAssociation,
        verbose_name=_("Sources"),
        help_text=_(
            "This is used to link a hut to different organizations/portals, for example 'SAC', 'Open Stree Map', 'Gipfelbuch', ..."
        ),
    )  # , related_name="huts")
    # photos: List[Photo] = Field(default_factory=list, sa_column=Column(PydanticType(List[Photo])))

    # infrastructure: dict = Field(
    #     default_factory=dict, sa_column=Column(JSON)
    # )  # TODO, better name. Maybe use infra and service separated, external table
    # access: Access = Field(default_factory=Access, sa_column=Access.get_sa_column())
    # monthly: Monthly = Field(default_factory=Monthly, sa_column=Monthly.get_sa_column())

    class Meta:
        verbose_name = _("Hut")
        ordering = (Lower("name_i18n"),)
        indexes = (GinIndex(fields=["i18n"]),)
        constraints = (
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_country_valid", check=models.Q(country_field__in=settings.COUNTRIES_ONLY)
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_review_status_valid",
                check=models.Q(review_status__in=_ReviewStatusChoices.values),
            ),
        )

    def __str__(self) -> str:
        return self.name_i18n

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)

        # save original values, when model is loaded from database,
        # in a separate attribute on the model
        values = dict(zip(field_names, values))
        instance._orig_slug = values.get("slug")  # type: ignore  # noqa: PGH003
        instance._orig_review_status = values.get("review_status")  # type: ignore  # noqa: PGH003
        return instance

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.create_unique_slug_name(self.name_i18n)
        # if updated
        if not self._state.adding and self.slug != self._orig_slug:  # updates # type: ignore  # noqa: PGH003
            self.slug = self.create_unique_slug_name(self.slug)
        to_save = []
        if (
            not self._state.adding
            and self.review_status != self._orig_review_status
            and self._orig_review_status != self.ReviewStatusChoices.reject.value
            and self.review_status == self.ReviewStatusChoices.done.value
        ):
            for hs in self.hut_sources.all():
                if hs.review_status not in [
                    hs.ReviewStatusChoices.failed,
                    hs.ReviewStatusChoices.reject,
                    hs.ReviewStatusChoices.old,
                ]:
                    hs.review_status = hs.ReviewStatusChoices.done
                    to_save.append(hs)

        with transaction.atomic():
            for s in to_save:
                # TODO: save does not work!!
                s.save()
            super().save(*args, **kwargs)

    def next(self) -> int | None:
        """Returns next hut"""
        order_by = Lower("name")
        first_hut = Hut.objects.all().order_by(order_by).first()
        first_id = first_hut.id if first_hut else None
        next_id_dict = (
            Hut.objects.annotate(lowername=order_by)
            .filter(lowername__gt=self.name.lower())
            .order_by("lowername")
            .values("id")
            .first()
        )
        return next_id_dict.get("id") if next_id_dict else first_id

    def prev(self) -> int | None:
        order_by = Lower("name")
        last_hut = Hut.objects.all().order_by(order_by).last()
        last_id = last_hut.id if last_hut else None
        prev_id_dict = (
            Hut.objects.annotate(lowername=order_by)
            .filter(lowername__lt=self.name.lower())
            .order_by("lowername")
            .values("id")
            .last()
        )
        return prev_id_dict.get("id") if prev_id_dict else last_id

    @classmethod
    def _convert_source(cls, hut_source: HutSource) -> HutSchema:
        org = hut_source.organization.slug
        service: BaseService | None = SERVICES.get(org)
        if service is None:
            err_msg = f"No service for organization '{org}' found."
            raise NotImplementedError(err_msg)
        return service.convert(hut_source)

    def add_organization(self, hut_source, add_to_source=True):
        new_org = HutOrganizationAssociation(
            hut=self,
            organization=hut_source.organization,
            props=hut_source.source_properties,
            source_id=hut_source.source_id,
        )
        new_org.save()
        if add_to_source:
            hut_source.hut = self
            hut_source.save()

    @classmethod
    def create_from_source(
        cls, hut_source: HutSource, review: bool = True, _review_status: "Hut.ReviewStatusChoices | None" = None
    ) -> "Hut":
        hut = cls._convert_source(hut_source)
        return cls.create_from_schema(
            hut_schema=hut, review=review, _hut_source=hut_source, _review_status=_review_status
        )

    @classmethod
    def create_from_schema(
        cls,
        hut_schema: HutSchema,
        review: bool = True,
        is_modified: bool = False,
        _hut_source: HutSource | None = None,
        _review_status: "Hut.ReviewStatusChoices | None" = None,
    ) -> "Hut":
        if _review_status is not None:
            review_status = _review_status
        else:
            review_status = Hut.ReviewStatusChoices.new if review else Hut.ReviewStatusChoices.done

        ## Translations -> Better solution?
        i18n_fields = {}
        for field in ["name", "description", "notes"]:
            model = getattr(hut_schema, field)
            if not model:
                continue
            if field == "notes":
                model = model[0]
            for code, value in model.model_dump(by_alias=True).items():
                out_field = "note" if field == "notes" else field
                if value:
                    i18n_fields[f"{out_field}_{code}"] = value
        type_closed = (
            HutType.values[str(hut_schema.hut_type.if_closed.value)] if hut_schema.hut_type.if_closed else None
        )

        hut_db = Hut(
            description_attribution=hut_schema.description_attribution,
            location=dbPoint(hut_schema.location.lon_lat),
            elevation=hut_schema.location.ele,
            capacity_open=hut_schema.capacity.if_open,
            capacity_closed=hut_schema.capacity.if_closed,
            url=hut_schema.url,
            is_active=hut_schema.is_active,
            is_public=hut_schema.is_public,
            country_field=hut_schema.country_code or "CH",
            photos=hut_schema.photos[0].thumb or hut_schema.photos[0].url if hut_schema.photos else "",
            photos_attribution=hut_schema.photos[0].attribution if hut_schema.photos else "",
            hut_type_open=HutType.values[str(hut_schema.hut_type.if_open.value)],
            hut_type_closed=type_closed,
            review_status=review_status,
            is_modified=is_modified,
            open_monthly=hut_schema.open_monthly.model_dump(),
            **i18n_fields,
        )
        if hut_db.hut_type_open.slug == "hut" and hut_db.capacity_closed or 0 > 0 and not type_closed:
            if (hut_db.elevation or 0) < 3000:
                hut_db.hut_type_closed = HutType.values["selfhut"]
            else:
                hut_db.hut_type_closed = HutType.values["bicouac"]
        ## Owner stuff -> add to Owner
        src_hut_owner = hut_schema.owner
        owner = None
        if src_hut_owner:
            # try:
            i18n_fields = {}
            defaults = src_hut_owner.model_dump(by_alias=True)
            for field in ["note"]:
                model = getattr(src_hut_owner, field)
                if not model:
                    continue
                for code, value in model.model_dump(by_alias=True).items():
                    i18n_fields[f"{field}_{code}"] = value
                if field in defaults:
                    del defaults["note"]
            if "contacts" in defaults:
                del defaults["contacts"]
            if "slug" in defaults:
                del defaults["slug"]
            defaults.update(i18n_fields)
            owner, _created = Owner.objects.get_or_create(slug=src_hut_owner.slug, defaults=defaults)
            hut_db.hut_owner = owner

        # Contact Stuff
        # TODO check if numbers or email already exist -> update
        src_hut_contacts = hut_schema.contacts
        contacts: list[Contact] = []
        for c in src_hut_contacts:
            name = c.function.replace("_", " ").replace("-", " ") if c.function else None
            priority = 100 if c.function == "private_contact" else 10
            function = (
                ContactFunction.objects.get_or_create(defaults={"name": name, "priority": priority}, slug=c.function)[0]
                if c.function
                else None
            )
            contact = Contact(
                name=c.name,
                email=c.email,
                phone=c.phone,
                mobile=c.mobile,
                function=function,
                url=c.url,
                address=c.address,
                is_active=c.is_active,
                is_public=c.is_public,
            )
            contacts.append(contact)
            # Contact is saved later in a atomic transaction

        # write to DB as one transaction
        with transaction.atomic():
            hut_db.save()
            hut_db.refresh_from_db()
            if _hut_source is not None:
                hut_db.add_organization(_hut_source)
            if contacts:
                for i, c in enumerate(contacts):
                    c.save()
                    c.refresh_from_db()
                    a = HutContactAssociation(contact=c, hut=hut_db, order=i)
                    a.save()
        return hut_db

    @classmethod
    def update_from_source(
        cls,
        hut_db: "Hut",
        hut_source: HutSource,
        review: bool = True,
        force_overwrite: bool = False,  # overwrite exisitng entries
        force_overwrite_include: t.Sequence[str] = [],  # set a list which field which should be overwritten
        force_overwrite_exclude: t.Sequence[str] = [],  # ... exclude when overwritten
        force_none: bool = False,  # force t oset value to none (overwrite is needed)
        _review_status: "Hut.ReviewStatusChoices | None" = None,
    ) -> tuple["Hut", UpdateCreateStatus]:
        hut_schema = cls._convert_source(hut_source)
        return cls.update_from_schema(
            hut_db=hut_db,
            hut_schema=hut_schema,
            review=review,
            force_overwrite=force_overwrite,
            force_overwrite_include=force_overwrite_include,
            force_overwrite_exclude=force_overwrite_exclude,
            force_none=force_none,
            _hut_source=hut_source,
            _review_status=_review_status,
        )

    @classmethod
    def update_from_schema(
        cls,
        hut_db: "Hut",
        hut_schema: HutSchema,
        review: bool = True,
        force_overwrite: bool = False,  # overwrite exisitng entries
        force_overwrite_include: t.Sequence[str] = [],  # set a list which field which should be overwritten
        force_overwrite_exclude: t.Sequence[str] = [],  # ... exclude when overwritten
        force_none: bool = False,  # force t oset value to none (overwrite is needed)
        set_modified: bool = False,
        _hut_source: HutSource | None = None,
        _review_status: "Hut.ReviewStatusChoices | None" = None,
    ) -> tuple["Hut", UpdateCreateStatus]:
        if _review_status is not None:
            review_status = _review_status
        else:
            review_status = Hut.ReviewStatusChoices.review if review else None
        updates = hut_schema.model_dump(
            by_alias=False,
            # exclude_unset=True,
            # exclude_none=True,
            include=set(cls.UPDATE_SCHEMA_FIELDS),
        )
        ### Translations -> Better solution?
        i18n_fields = {}
        if "description" in updates:
            updates["description_attribution"] = hut_schema.description_attribution
        for field in ["name", "description", "notes"]:
            model = updates.get(field)
            if not model:
                continue
            del updates[field]
            if field == "notes":
                model = model[0]
            for code, value in model.items():
                out_field = "note" if field == "notes" else field
                i18n_fields[f"{out_field}_{code}"] = value
        updates.update(i18n_fields)
        if "location" in updates and hut_schema.location.ele is not None:
            updates["elevation"] = hut_schema.location.ele
        if "location" in updates:
            updates["location"] = dbPoint(hut_schema.location.lon_lat)
        # if "capacity_open" in updates and hut_schema.capacity.if_open is None:
        #    del updates["capacity_open"]
        # if "capacity_closed" in updates and hut_schema.capacity.if_closed is None:
        #    del updates["capacity_closed"]
        if "country_code" in updates:
            updates["country_field"] = updates["country_code"] or "CH"
            del updates["country_code"]
        if "capacity" in updates:
            del updates["capacity"]
            updates["capacity_open"] = hut_schema.capacity.if_open
            updates["capacity_closed"] = hut_schema.capacity.if_closed
        if "photos" in updates:
            updates["photos"] = hut_schema.photos[0].thumb or hut_schema.photos[0].url if hut_schema.photos else ""
            updates["photos_attribution"] = hut_schema.photos[0].attribution if hut_schema.photos else ""
        if "hut_type" in updates:
            del updates["hut_type"]
            updates["hut_type_open"] = HutType.values[str(hut_schema.hut_type.if_open.value)]
            updates["hut_type_closed"] = (
                HutType.values[str(hut_schema.hut_type.if_closed.value)] if hut_schema.hut_type.if_closed else None
            )
        if set_modified:
            updates["is_modified"] = True
        updated = UpdateCreateStatus.no_change

        changes = ""
        with transaction.atomic():
            for f, v in updates.items():
                # 1. Only update if no entry or forced
                # 2. Force to set None as well
                if (
                    (
                        not hasattr(hut_db, f)  # Value is still empty
                        or (  # -> check for overwrite force ...
                            # only overwrite without any fields specified -> overwrite all
                            (force_overwrite and not force_overwrite_exclude and not force_overwrite_include)
                            or (  # some fields (include or exclude) is defined (exclusive or)
                                (force_overwrite and f in force_overwrite_include and not force_overwrite_exclude)
                                or (
                                    force_overwrite and f not in force_overwrite_exclude and not force_overwrite_include
                                )
                            )
                        )
                    )
                    and (v or force_none)  # only write 'None' if foced to
                    and getattr(hut_db, f) != v  # only update if value is not the same
                ):
                    old_value = getattr(hut_db, f)
                    # special comparision for dbPoint -> valus are always different because it is a class
                    if isinstance(v, dbPoint) and v.tuple == old_value.tuple:  # type: ingore[attr-defined]
                        continue
                    setattr(hut_db, f, v)
                    sp = "'" if len(str(old_value)) < 100 and len(str(v)) < 100 else "\n---\n"
                    changes += f"* Changed '{f}' from {sp}{old_value}{sp} to {sp}{v}{sp}\n"
                    updated = UpdateCreateStatus.updated
            # Update review field
            if updated == UpdateCreateStatus.updated and hut_db.review_status not in [
                Hut.ReviewStatusChoices.reject,
                Hut.ReviewStatusChoices.new,
            ]:
                status = review_status if review_status != Hut.ReviewStatusChoices.work else None
                hut_db.add_review_comment(title="Field changes", text=changes, status=status)
            hut_db.save()
            # check for new organization
            if _hut_source is not None and _hut_source.organization not in hut_db.org_set.all():
                hut_db.add_organization(_hut_source)
        hut_db.refresh_from_db()
        return hut_db, updated

    @classmethod
    def update_or_create(
        cls,
        hut_schema: HutSchema | None = None,
        hut_source: HutSource | None = None,
        review: bool | None = None,
        force_overwrite: bool = False,  # overwrite exisitng entries
        force_overwrite_include: t.Sequence[str] = [],  # set a list which field which should be overwritten
        force_overwrite_exclude: t.Sequence[str] = [],  # ... exclude when overwritten
        force_none: bool = False,  # force t oset value to none (overwrite is needed)
        _review_status_update: "Hut.ReviewStatusChoices | None" = None,
        _review_status_create: "Hut.ReviewStatusChoices | None" = None,
    ) -> tuple["Hut", UpdateCreateStatus]:
        """Create or update either from a `HutSchema` or `HutSource` model.

        Args:
            hut_schema: Hut schema object, can be used together with `hut_source`.
            hut_source: Hut source model (from db), either `hut_source` or `hut_schema` is required.
            review: Set status to `review`. Per default it is set to `True` if an object is created and `review` is either `True` or `None`.
                    If object is updated the status is not changed if set to `False` or `None`.
            _review_status_update: Force `review` status to this value if updated, `review` is ignored.
            _review_status_create: Force `review` status to this value if created, `review` is ignored.

        Returns:
            Created or updated `Hut` model and a bool if it was created or only updated (`created`)."""

        # Check if it already exist
        location: dbPoint | None = None
        if hut_schema is not None and hut_schema.location:
            location = dbPoint(hut_schema.location.lon_lat)
        elif hut_source is not None and hut_source.location:
            location = hut_source.location  # (hut_source.location.x, hut_source.location.y)
        hut_db = None
        if location is not None:
            hut_db = (
                cls.objects.filter(location__distance_lt=(location, D(m=30)))
                .annotate(distance=Distance("location", location))
                .order_by("distance")
                .first()
            )
        if hut_db is not None:
            # do update
            if hut_schema is None and hut_source is not None:
                return cls.update_from_source(
                    hut_db=hut_db,
                    hut_source=hut_source,
                    review=bool(review),
                    force_overwrite=force_overwrite,
                    force_overwrite_include=force_overwrite_include,
                    force_overwrite_exclude=force_overwrite_exclude,
                    force_none=force_none,
                    _review_status=_review_status_update,
                )
            if hut_schema is not None:
                return cls.update_from_schema(
                    hut_db=hut_db,
                    hut_schema=hut_schema,
                    _hut_source=hut_source,
                    force_overwrite=force_overwrite,
                    force_overwrite_include=force_overwrite_include,
                    force_overwrite_exclude=force_overwrite_exclude,
                    force_none=force_none,
                    review=bool(review),
                    _review_status=_review_status_update,
                )

        if hut_schema is None and hut_source is not None:
            return (
                cls.create_from_source(
                    hut_source=hut_source, review=bool(review), _review_status=_review_status_create
                ),
                UpdateCreateStatus.created,
            )
        if hut_schema is not None:
            return (
                cls.create_from_schema(
                    hut_schema=hut_schema,
                    _hut_source=hut_source,
                    review=bool(review),
                    _review_status=_review_status_create,
                ),
                UpdateCreateStatus.created,
            )
        err_msg = "Either 'hut_schema' or 'hut_source' is required."
        raise UserWarning(err_msg)

    def add_review_comment(
        self,
        title: str | None = None,
        text: str = "",
        status: ReviewStatusChoices | None = None,
        append: bool = True,
    ) -> str:
        """Adds a review comment, if title included a date is added automatically."""
        title_date = (
            f"\n\n~~~ {datetime.datetime.today().strftime('%Y-%m-%d %H:%M')}\n{title}\n\n" if title is not None else ""
        )
        comment = self.review_comment
        if append:
            comment += f"{title_date}{text}"
        else:
            comment = f"{title_date}{text}\n\n{comment}"
        self.review_comment = comment.strip()
        if status is not None:
            self.review_status = status
        return comment

    # def bookings(
    #    self,
    #    date: datetime.datetime | datetime.date | t.Literal["now"] | None = None,
    #    days: int | None = None,
    # ) -> "HutBookingsSchema | None":
    #    source_id = self.orgs_source.source_id
    #    source = self.org_set.get(source_id=source_id).slug
    #    b = self.get_bookings(date=date, days=days, source_ids=[source_id], source=source)
    #    return b[0] if b else None

    @classmethod
    def get_bookings(
        cls,
        date: datetime.datetime | datetime.date | t.Literal["now"] | None = None,
        days: int | None = None,
        source_ids: list[int] | None = None,
        source: str | None = None,
        hut_ids: list[int] | None = None,
        hut_slugs: list[str] | None = None,
        lang: str = "de",
    ) -> list["HutBookingsSchema"]:
        # def get_bookings() -> dict[int, HutBookingsSchema]:
        bookings: dict[int, HutServiceBookingSchema] = {}
        huts = []
        obj = cls.objects
        if hut_ids is not None:
            obj = obj.filter(pk__in=hut_ids)
        if hut_slugs is not None:
            obj = obj.filter(slug__in=hut_slugs)
        for src_name, service in SERVICES.items():
            if service.support_booking and (src_name == source or source is None):
                bookings.update(service.get_bookings(date=date, days=days, source_ids=source_ids, lang=lang))
                huts += (
                    obj.filter(orgs_source__source_id__in=bookings.keys())
                    .prefetch_related("hut_type_open", "hut_type_closed")
                    .annotate(
                        source_id=F("orgs_source__source_id"),
                        source=F("org_set__slug"),
                        hut_type_open_slug=F("hut_type_open__slug"),
                        hut_type_closed_slug=F("hut_type_closed__slug"),
                    )
                    .values(
                        "id", "slug", "source_id", "location", "hut_type_open_slug", "hut_type_closed_slug", "source"
                    )
                )

        for h in huts:
            booking = bookings.get(int(h.get("source_id", -1)))
            if booking is not None:
                for b in booking.bookings:
                    b.hut_type = (
                        HutTypeEnum.unknown.value
                        if b.places.occupancy_status == OccupancyStatusEnum.unknown
                        else (
                            h["hut_type_closed_slug"]
                            if b.unattended and h["hut_type_closed_slug"] is not None
                            else h["hut_type_open_slug"]
                        )
                    )
                h.update(booking)
        return [HutBookingsSchema(**h) for h in huts]

    def organizations_query(self, organization: str | Organization | None = None, annotate=True):
        if isinstance(organization, Organization):
            organization = organization.slug
        org_q = self.org_set
        if isinstance(organization, str):
            org_q = org_q.filter(slug=organization)
        else:
            org_q = org_q.all()
        if annotate:
            org_q = org_q.annotate(
                logo_url=Concat(Value(settings.MEDIA_URL), F("logo"), output_field=models.CharField()),
                props=F("details__props"),
                source_id=F("details__source_id"),
            )
        org_q = org_q.order_by("order")
        return org_q

    # TODO: improve
    #  - create pydantic schema
    #  - maybe not needed ad use source?? (but probably prefered to separate it)
    #  - filter by organization slug or model
    def view_organizations(self, organization: str | Organization | None = None):
        orgs = []

        # # without annotation -- at the moment many queries
        # org_q = self.organizations.select_related("details")
        # org_q = org_q.prefetch_related(
        #     models.Prefetch("organizations", queryset=self.organizations.through.objects.all(), to_attr="details")
        # )
        # org_q = self.organizations_query(organization=organization, annotate=False)
        # for org in org_q:
        #     details = org.details.first()
        #     lang = get_language() or settings.LANGUAGE_CODE
        #     link_pattern = org.link_hut_pattern
        #     _tmpl = Environment().from_string(link_pattern)
        #     link = _tmpl.render(lang=lang, slug=self.slug, id=details.source_id, props=details.props, config=org.config)
        #     org_d = {}
        #     org_d["logo"] = org.logo.url
        #     org_d["config"] = org.config
        #     org_d["link_hut_pattern"] = org.link_hut_pattern
        #     org_d["name"] = org.name_i18n
        #     org_d["fullname"] = org.fullname_i18n
        #     org_d["url"] = org.url_i18n
        #     org_d["link"] = link

        #     orgs.append(EasyDict(**org_d))
        # return orgs

        ### with annotation -- at the moment many queries
        org_q = self.organizations_query(organization=organization)
        organizations = org_q.values(
            "name_i18n", "fullname_i18n", "config", "link_hut_pattern", "url_i18n", "logo_url", "props", "source_id"
        )

        for org in organizations:
            lang = get_language() or settings.LANGUAGE_CODE
            link_pattern = org.get("link_hut_pattern", "")
            _tmpl = Environment().from_string(link_pattern)
            org["link"] = _tmpl.render(lang=lang, slug=self.slug, id=org.get("source_id"), **org)
            # link = _tmpl.render(lang=lang, config=config, slug=self.slug, id=source_id, props=props)
            org["logo"] = org["logo_url"]
            org["name"] = org["name_i18n"]
            org["fullname"] = org["fullname_i18n"]
            org["url"] = org["url_i18n"]

            orgs.append(EasyDict(**org))
        return orgs

    def create_unique_slug_name(
        self, hut_name: str, max_length: int = 25, min_length: int = 5, attempts: int = 10
    ) -> str:
        orig_slug = guess_slug_name(hut_name=hut_name, max_length=max_length, min_length=min_length)
        slug = orig_slug
        cnt = 1
        while Hut.objects.filter(slug=slug).count() and cnt < attempts:  # slug exists
            slug = f"{orig_slug}{cnt}"
            cnt += 1
        return slug
