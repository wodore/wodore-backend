import typing as t
from sysconfig import is_python_build

from easydict import EasyDict
from hut_services import BaseService, HutSchema, HutSourceSchema
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
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from server.apps.contacts.models import Contact, ContactFunction
from server.apps.organizations.models import Organization
from server.apps.owners.models import Owner

from ..managers import HutManager
from ._associations import HutContactAssociation, HutOrganizationAssociation
from ._hut_source import HutSource
from ._hut_type import HutType


class _ReviewStatusChoices(models.TextChoices):
    new = "new", _("new")
    review = "review", _("review")
    done = "done", _("done")
    research = "research", _("research")
    reject = "reject", _("reject")


class Hut(TimeStampedModel):
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
    name = models.CharField(max_length=100, verbose_name=_("Name"))
    name_i18n: str  # for typing
    description = models.TextField(max_length=10000, verbose_name="Description")
    description_i18n: str  # for typing

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

    photo = models.CharField(blank=True, default="", max_length=200, verbose_name=_("Hut photo"))
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
    # organizations = models.ManyToManyField(Organization, related_name="huts", db_table="hut_organization_association")
    org_set = models.ManyToManyField(
        Organization,
        through=HutOrganizationAssociation,
        verbose_name=_("Organizations"),
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

    def save(self, *args, **kwargs):
        self.slug = self._create_slug_name(self.name_i18n)
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
        orgs = hut_source.organization.slug
        service: BaseService = settings.SERVICES.get(orgs)
        if service is None:
            err_msg = f"No service for organization '{orgs}' found."
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
        _hut_source: HutSource | None = None,
        _review_status: "Hut.ReviewStatusChoices | None" = None,
    ) -> "Hut":
        if _review_status is not None:
            review_status = _review_status
        else:
            review_status = Hut.ReviewStatusChoices.review if review else Hut.ReviewStatusChoices.done

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
                i18n_fields[f"{out_field}_{code}"] = value
        hut_db = Hut(
            location=dbPoint(hut_schema.location.lon_lat),
            elevation=hut_schema.location.ele,
            capacity=hut_schema.capacity.opened,
            url=hut_schema.url,
            is_active=hut_schema.is_active,
            is_public=hut_schema.is_public,
            country=hut_schema.country,
            type=HutType.values[str(hut_schema.hut_type.value)],
            review_status=review_status,
            **i18n_fields,
        )
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
                # new_org = HutOrganizationAssociation(
                #    hut=hut_db,
                #    organization=_hut_source.organization,
                #    props=_hut_source.source_properties,
                #    source_id=_hut_source.source_id,
                # )
                # new_org.save()
                # _hut_source.hut = hut_db
                # _hut_source.save()
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
        _review_status: "Hut.ReviewStatusChoices | None" = None,
    ) -> "Hut":
        hut_schema = cls._convert_source(hut_source)
        return cls.update_from_schema(
            hut_db=hut_db, hut_schema=hut_schema, review=review, _hut_source=hut_source, _review_status=_review_status
        )

    @classmethod
    def update_from_schema(
        cls,
        hut_db: "Hut",
        hut_schema: HutSchema,
        review: bool = True,
        _hut_source: HutSource | None = None,
        _review_status: "Hut.ReviewStatusChoices | None" = None,
    ) -> "Hut":
        if _review_status is not None:
            review_status = _review_status
        else:
            review_status = Hut.ReviewStatusChoices.review if review else None
        updates = hut_schema.model_dump(
            by_alias=True,
            exclude_unset=True,
            exclude_none=True,
            include={"name", "note", "description", "location", "capacity", "url", "country"},
        )
        ### Translations -> Better solution?
        i18n_fields = {}
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
        if "capacity" in updates and hut_schema.capacity.opened is None:
            del updates["capacity"]
        if "capacity" in updates:
            updates["capacity"] = hut_schema.capacity.opened
        if review_status is not None:
            updates["review_status"] = review_status
        with transaction.atomic():
            for f, v in updates.items():
                setattr(hut_db, f, v)
            hut_db.save()
            # why does it not work with update
            # cls.objects.filter(slug=hut_db.slug).update(**updates)
            # check for new organization
            if _hut_source is not None and _hut_source.organization not in hut_db.org_set.all():
                hut_db.add_organization(_hut_source)
        # hut_db = Hut(
        #    location=dbPoint(hut_schema.location.lon_lat),
        #    elevation=hut_schema.location.ele,
        #    capacity=hut_schema.capacity.opened,
        #    url=hut_schema.url,
        #    is_active=hut_schema.is_active,
        #    is_public=hut_schema.is_public,
        #    country=hut_schema.country,
        #    type=HutType.values[str(hut_schema.hut_type.value)],
        #    review_status=review_status,
        #    **i18n_fields,
        # )
        hut_db.refresh_from_db()
        return hut_db

    @classmethod
    def update_or_create(
        cls,
        hut_schema: HutSchema | None = None,
        hut_source: HutSource | None = None,
        review: bool | None = None,
        _review_status_update: "Hut.ReviewStatusChoices | None" = None,
        _review_status_create: "Hut.ReviewStatusChoices | None" = None,
    ) -> tuple["Hut", bool]:
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
                return (
                    cls.update_from_source(
                        hut_db=hut_db, hut_source=hut_source, review=bool(review), _review_status=_review_status_update
                    ),
                    False,
                )
            if hut_schema is not None:
                return (
                    cls.update_from_schema(
                        hut_db=hut_db,
                        hut_schema=hut_schema,
                        _hut_source=hut_source,
                        review=bool(review),
                        _review_status=_review_status_update,
                    ),
                    False,
                )

        if hut_schema is None and hut_source is not None:
            return (
                cls.create_from_source(
                    hut_source=hut_source, review=bool(review), _review_status=_review_status_create
                ),
                True,
            )
        if hut_schema is not None:
            return (
                cls.create_from_schema(
                    hut_schema=hut_schema,
                    _hut_source=hut_source,
                    review=bool(review),
                    _review_status=_review_status_create,
                ),
                True,
            )
        err_msg = "Either 'hut_schema' or 'hut_source' is required."
        raise UserWarning(err_msg)

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

    def _create_slug_name(self, hut_name: str, max_length: int = 25, min_length: int = 5) -> str:
        for r in ("ä", "ae"), ("ü", "ue"), ("ö", "oe"):
            hut_name = hut_name.lower().replace(r[0], r[1])
        slug = slugify(hut_name)
        if len(slug) > max_length:
            slug = slug[:max_length]
        slug = slug.strip(" -")
        slug_orig = slug
        slugs = slug.split("-")
        slugl = []
        for s in slugs:
            if (
                s
                not in [
                    "alp",
                    "alpe",
                    "alpage",
                    "alpina",
                    "huette",
                    "cabanne",
                    "cabane",
                    "capanna",
                    "chamana",
                    "chamanna",
                    "chamonna",
                    "chalet",
                    "casa",
                    "capanna",
                    "biwak",
                    "bivouac",
                    "bivacco",
                    "berghotel",
                    "chalets",
                    "camona",
                    "hotel",
                    "berghuette",
                    "berggasthaus",
                    "berghaus",
                    "cascina",
                    "gite",
                    "rifugio",
                    "refuge",
                    "citta",
                    "guide",
                ]
                and len(s) >= min_length
            ):
                slugl.append(s)
        slug = "-".join(slugl)
        if not slug:
            slug = slug_orig
        slug = slug.replace("sac", "").replace("cas", "").replace("caf", "")
        return slug.strip(" -")
