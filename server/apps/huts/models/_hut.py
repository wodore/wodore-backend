from easydict import EasyDict
from jinja2 import Environment

from django_countries.fields import CountryField
from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import GinIndex
from django.db.models import F, Value
from django.db.models.functions import Concat
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from server.apps.contacts.models import Contact
from server.apps.organizations.models import Organization

# from server.apps.owners.models import Owner
from ..managers import HutManager
from ._associations import HutContactAssociation, HutOrganizationAssociation
from ._hut_type import HutType


class _ReviewStatusChoices(models.TextChoices):
    new = "new", _("new")
    review = "review", _("review")
    done = "done", _("done")
    reject = "reject", _("reject")


class Hut(TimeStampedModel):
    ReviewStatusChoices = _ReviewStatusChoices
    # manager
    objects: HutManager = HutManager()
    # translations
    i18n = TranslationField(fields=("name", "description", "note"))

    slug = models.SlugField(unique=True, verbose_name=_("Slug"), db_index=True)
    review_status = models.TextField(
        max_length=12,
        choices=ReviewStatusChoices.choices,
        default=ReviewStatusChoices.review,
        verbose_name=_("Review status"),
    )
    review_comment = models.CharField(blank=True, default="", max_length=2000, verbose_name=_("Review comment"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Active"))
    name = models.CharField(max_length=100, verbose_name=_("Name"))
    description = models.TextField(max_length=2000, verbose_name="Description")
    owner = models.ForeignKey(
        "owners.Owner",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="huts",
        verbose_name=_("Hut owner."),
        help_text=_("For example 'SAC Bern' ..."),
    )
    contacts = models.ManyToManyField(
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
    photo = models.CharField(blank=True, default="", max_length=200, verbose_name=_("Hut photo"))
    country = CountryField()
    point = models.PointField(blank=False, verbose_name="Location")
    elevation = models.DecimalField(null=True, blank=True, max_digits=5, decimal_places=1, verbose_name=_("Elevation"))
    capacity = models.PositiveSmallIntegerField(blank=True, null=True, verbose_name=_("Capacity"))
    capacity_shelter = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        verbose_name=_("Shelter Capacity"),
        help_text=_("Only if an additional shelter is available, e.g. during winter."),
    )

    type = models.ForeignKey(
        HutType, related_name="huts", on_delete=models.RESTRICT, verbose_name=_("Hut type"), db_index=True
    )
    # organizations = models.ManyToManyField(Organization, related_name="huts", db_table="hut_organization_association")
    organizations = models.ManyToManyField(
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
        ordering = ("name_i18n",)
        indexes = (GinIndex(fields=["i18n"]),)
        constraints = (
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_country_valid", check=models.Q(country__in=settings.COUNTRIES_ONLY)
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

    def organizations_query(self, organization: str | Organization | None = None, annotate=True):
        if isinstance(organization, Organization):
            organization = organization.slug
        org_q = self.organizations
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
