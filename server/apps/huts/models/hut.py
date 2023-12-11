from django.conf import settings
from django.contrib.gis.db import models
from django.forms import ModelForm

from organizations.models import Organization
from computedfields.models import ComputedFieldsModel, computed

from model_utils.models import TimeStampedModel

from django.contrib.postgres.indexes import GinIndex
from django.utils.translation import gettext_lazy as _
from django.utils.translation import get_language
from django_countries.fields import CountryField

from djjmt.fields import TranslationJSONField
from modeltrans.fields import TranslationField
from modeltrans.manager import MultilingualManager

from django.db.models.functions import Lower
from unidecode import unidecode
from django.utils.text import slugify
from django.db.models import F, Value
from django.db.models.functions import Concat

from huts.managers import HutManager
from server.core.managers import BaseMutlilingualManager, BaseManager

from jinja2 import Environment

from easydict import EasyDict


class Hut(TimeStampedModel):
    class ReviewStatusChoices(models.TextChoices):
        review = "review", _("review")
        done = "done", _("done")
        reject = "reject", _("reject")

    # manager
    objects: HutManager = HutManager()
    # translations
    i18n = TranslationField(fields=("name", "description", "note"))

    slug = models.SlugField(unique=True)
    review_status = models.TextField(
        max_length=12, choices=ReviewStatusChoices.choices, default=ReviewStatusChoices.review
    )
    review_comment = models.CharField(blank=True, default="", max_length=2000)
    is_active = models.BooleanField(default=True, db_index=True)
    name = models.CharField(max_length=100, help_text="Hut name (e.g. SAC Bern)")
    description = models.TextField(max_length=2000, help_text="Hut description")
    owner = models.ForeignKey(
        Owner, null=True, blank=True, on_delete=models.RESTRICT, related_name="huts", help_text=_("Hut owner.")
    )
    contacts = models.ManyToManyField(Contact, through=HutContactAssociation, related_name="huts")
    url = models.URLField(blank=True, default="", max_length=200, help_text=_("URL"))
    note = models.TextField(
        blank=True, default="", max_length=2000, help_text=_("note")
    )  # TODO: maybe notes with mutlipe notes and category
    photo = models.CharField(blank=True, default="", max_length=200, help_text=_("Photo"))
    country = CountryField()
    point = models.PointField(blank=False)
    elevation = models.DecimalField(null=True, blank=True, max_digits=5, decimal_places=1)
    capacity = models.PositiveSmallIntegerField(blank=True, null=True)
    capacity_shelter = models.PositiveSmallIntegerField(blank=True, null=True)

    type = models.ForeignKey(HutType, related_name="huts", on_delete=models.RESTRICT)
    # organizations = models.ManyToManyField(Organization, related_name="huts", db_table="hut_organization_association")
    organizations = models.ManyToManyField(Organization, through=HutOrganizationAssociation)  # , related_name="huts")
    # photos: List[Photo] = Field(default_factory=list, sa_column=Column(PydanticType(List[Photo])))

    # infrastructure: dict = Field(
    #     default_factory=dict, sa_column=Column(JSON)
    # )  # TODO, better name. Maybe use infra and service separated, external table
    # access: Access = Field(default_factory=Access, sa_column=Access.get_sa_column())
    # monthly: Monthly = Field(default_factory=Monthly, sa_column=Monthly.get_sa_column())

    def __str__(self) -> str:
        try:
            return self.name.get("de")
        except AttributeError:
            return self.name

    # @classmethod
    # def drop(cls, number: int | None = None, offset: int | None = 0) -> int:
    #    offset = offset or 0
    #    db = cls.objects
    #    entries = db.count()
    #    if number is not None:
    #        number_with_offset = number + offset
    #        if number_with_offset > entries:
    #            number_with_offset = entries
    #        pks = db.all()[offset:number_with_offset].values_list("pk", flat=True)
    #    else:
    #        pks = db.all().values_list("pk", flat=True)
    #    return db.filter(pk__in=pks).delete()[0]

    def save(self, *args, **kwargs):
        self.slug = self._create_slug_name(self.name_i18n)
        super(Hut, self).save(*args, **kwargs)

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

    # need a function which returns a list with all orgs to be perfomant
    # custom manager?
    # @classmethod
    # def organizations_list_query(cls, huts: list[int]):
    #    org_q = HutOrganizationAssociation.objects
    #    org_q = org_q.filter(hut_in=huts)
    #    org_q = org_q.annotate(
    #        logo_url=Concat(Value(settings.MEDIA_URL), F("logo"), output_field=models.CharField()),
    #        props=F("details__props"),
    #        source_id=F("details__source_id"),
    #    )
    #    org_q = org_q.order_by("order")
    #    return org_q

    # @classmethod
    # def view_organizations(self, organization: str | Organization | None = None):
    #    orgs = []

    #    # # without annotation -- at the moment many queries
    #    # org_q = self.organizations.select_related("details")
    #    # org_q = org_q.prefetch_related(
    #    #     models.Prefetch("organizations", queryset=self.organizations.through.objects.all(), to_attr="details")
    #    # )
    #    # org_q = self.organizations_query(organization=organization, annotate=False)
    #    # for org in org_q:
    #    #     details = org.details.first()
    #    #     lang = get_language() or settings.LANGUAGE_CODE
    #    #     link_pattern = org.link_hut_pattern
    #    #     _tmpl = Environment().from_string(link_pattern)
    #    #     link = _tmpl.render(lang=lang, slug=self.slug, id=details.source_id, props=details.props, config=org.config)
    #    #     org_d = {}
    #    #     org_d["logo"] = org.logo.url
    #    #     org_d["config"] = org.config
    #    #     org_d["link_hut_pattern"] = org.link_hut_pattern
    #    #     org_d["name"] = org.name_i18n
    #    #     org_d["fullname"] = org.fullname_i18n
    #    #     org_d["url"] = org.url_i18n
    #    #     org_d["link"] = link

    #    #     orgs.append(EasyDict(**org_d))
    #    # return orgs

    #    ### with annotation -- at the moment many queries
    #    org_q = self.organizations_query(organization=organization)
    #    organizations = org_q.values(
    #        "name_i18n", "fullname_i18n", "config", "link_hut_pattern", "url_i18n", "logo_url", "props", "source_id"
    #    )

    #    for org in organizations:
    #        lang = get_language() or settings.LANGUAGE_CODE
    #        link_pattern = org.get("link_hut_pattern", "")
    #        _tmpl = Environment().from_string(link_pattern)
    #        org["link"] = _tmpl.render(lang=lang, slug=self.slug, id=org.get("source_id"), **org)
    #        # link = _tmpl.render(lang=lang, config=config, slug=self.slug, id=source_id, props=props)
    #        org["logo"] = org["logo_url"]
    #        org["name"] = org["name_i18n"]
    #        org["fullname"] = org["fullname_i18n"]
    #        org["url"] = org["url_i18n"]

    #        orgs.append(EasyDict(**org))
    #    return orgs

    def _create_slug_name(self, hut_name: str, max_length: int = 25, min_length: int = 5) -> str:
        # dict_for_table = {special_char: "" for special_char in string.punctuation}
        # dict_for_table["_"] = "-"
        # dict_for_table[" "] = "-"
        # dict_for_table["-"] = "-"
        # slug = hut_name.lower().translate(str.maketrans(dict_for_table))
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
            if not s in [
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
            ]:
                if len(s) >= min_length:
                    slugl.append(s)
        slug = "-".join(slugl)
        if not slug:
            slug = slug_orig
        slug = slug.replace("sac", "").replace("cas", "").replace("caf", "")
        slug = slug.strip(" -")
        return slug
        # slug = unidecode(slug)
        # return slug.encode("ascii", errors="ignore").decode()
