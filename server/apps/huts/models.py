# from django.db import models
import string
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
from server.core.managers import BaseMutlilingualManager

from jinja2 import Environment

from easydict import EasyDict


class ReviewStatusChoices(models.TextChoices):
    # waiting = 'waiting'
    new = "new", _("new")
    review = "review", _("review")
    done = "done", _("done")
    old = "old", _("old")
    reject = "reject", _("reject")


class HutSource(TimeStampedModel):
    """
    Source data for huts, e.g from SAC.
    """

    source_id = models.CharField(blank=False, max_length=100, help_text=_("Original id from source object."))
    version = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(blank=False, max_length=100, help_text=_("Name of the object object."))
    organization = models.ForeignKey(Organization, on_delete=models.RESTRICT)
    point = models.PointField(blank=True, default=None)
    is_active = models.BooleanField(default=True, db_index=True)
    is_current = models.BooleanField(default=True, db_index=True)
    review_status = models.TextField(
        max_length=12, choices=ReviewStatusChoices.choices, default=ReviewStatusChoices.new
    )
    review_comment = models.CharField(blank=True, default="", max_length=2000)
    source_data = models.JSONField(help_text=_("Data from the source model."), blank=True, default=dict)
    previous_object = models.ForeignKey(
        "self", blank=True, null=True, on_delete=models.RESTRICT, help_text=_("Id to the previous object.")
    )
    hut = models.ForeignKey("Hut", null=True, related_name="sources", on_delete=models.SET_NULL)

    class Meta(object):
        verbose_name = "Hut Source"
        verbose_name_plural = "Hut Sources"
        ordering = [Lower("name"), "organization__order"]

    def __str__(self) -> str:
        return f"{self.name} v{self.version} ({self.organization.name_i18n})"


class ContactFunction(models.Model):
    slug = models.SlugField(unique=True)
    name = TranslationJSONField(models.CharField(max_length=100), help_text="Function name")
    icon = models.CharField(blank=True, max_length=70, help_text=_("Icon"))

    def __str__(self) -> str:
        return self.slug


class Contact(TimeStampedModel):
    name = models.CharField(blank=True, default="", max_length=70, help_text=_("Name"))
    email = models.EmailField(blank=True, default="", max_length=70, help_text=_("E-Mail"))
    phone = models.CharField(blank=True, default="", max_length=30, help_text=_("Phone"))
    mobile = models.CharField(blank=True, default="", max_length=30, help_text=_("Mobile"))
    # function = models.CharField(blank=True, max_length=50, help_text=_("Function (e.g. hut warden)"))  # maybe as enum?
    function = models.ForeignKey(ContactFunction, on_delete=models.RESTRICT)
    url = models.URLField(blank=True, default="", max_length=200, help_text=_("URL"))
    address = models.CharField(blank=True, default="", max_length=200, help_text=_("Address"))
    note = models.TextField(blank=True, max_length=500, help_text=_("Note"))
    is_active = models.BooleanField(default=True, db_index=True)
    is_public = models.BooleanField(default=False, db_index=True)

    class Meta(object):
        verbose_name = _("Contact")
        verbose_name_plural = _("Contacts")
        # ordering = ["order"]

    def __str__(self) -> str:
        out = []
        if self.name:
            # out.append(self.name)
            try:
                out.append(self.name.get("de"))
            except AttributeError:
                out.append(self.name)
        if self.email:
            out.append(f"<{self.email}>")
        return " ".join(out)


class Owner(TimeStampedModel):
    name = TranslationJSONField(models.CharField(max_length=100), help_text="Owner name (e.g. SAC Bern)")
    url = models.URLField(blank=True, default="", max_length=200, help_text=_("URL"))
    note = models.TextField(blank=True, default="", max_length=500, help_text=_("Note"))

    def __str__(self) -> str:
        try:
            return self.name.get("de")
        except AttributeError:
            return self.name


class HutContactAssociation(TimeStampedModel):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="details")
    hut = models.ForeignKey("Hut", on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField(blank=True, null=True)

    def __str__(self) -> str:
        return f"{self.hut} <> {self.contact}"

    class Meta(object):
        verbose_name = _("Contacts to Hut")
        unique_together = [["contact", "hut"]]


class HutOrganizationAssociation(TimeStampedModel, ComputedFieldsModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="source")
    hut = models.ForeignKey("Hut", on_delete=models.CASCADE)
    props = models.JSONField(help_text=_("Organization dependend properties."), blank=True, default=dict)
    source_id = models.CharField(max_length=40, blank=True, null=True, default="", help_text="Source id")

    # TODO: does not work for different languages, needs one field for each ...
    @computed(
        models.CharField(
            max_length=200, blank=True, null=True, default="", help_text=_("Link to object by this organisation")
        ),
        depends=[("self", ["props", "source_id"]), ("organization", ["link_hut_pattern", "config", "slug"])],
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

    objects = MultilingualManager()

    def __str__(self) -> str:
        return f"{self.hut} <> {self.organization}"

    class Meta(object):
        verbose_name = _("Organizations to Hut")
        unique_together = [["organization", "hut"]]


class HutType(models.Model):
    i18n = TranslationField(fields=("name", "description"))
    objects = BaseMutlilingualManager()

    slug = models.SlugField(unique=True)
    # name = TranslationJSONField(models.CharField(max_length=100), help_text="Hut type name")
    # description = TranslationJSONField(models.CharField(max_length=400), help_text="Hut type description")
    name = models.CharField(max_length=100, blank=True, null=True, default="", help_text="Hut type name")
    description = models.CharField(max_length=400, blank=True, null=True, default="", help_text="Hut type description")
    level = models.PositiveSmallIntegerField(default=0, help_text=_("Comfort level, higher is more comfort"))
    symbol = models.ImageField(
        max_length=300,
        upload_to="huts_type/icons",
        default="huts/types/symbols/detailed/unknown.png",
        help_text="Normal icon",
    )
    symbol_simple = models.ImageField(
        max_length=300,
        upload_to="huts_type/icons",
        default="huts/types/symbols/simple/unknown.png",
        help_text="Simple icon",
    )
    icon = models.ImageField(
        max_length=300,
        upload_to="huts_type/icons",
        default="huts/types/icons/unknown.png",
        help_text="Black icon",
    )

    def __str__(self) -> str:
        if self.name_i18n is not None:
            return self.name_i18n
        return "-"

    class Meta(object):
        verbose_name = _("Hut Type")
        verbose_name_plural = _("Hut Types")
        ordering = ["level", "slug"]
        indexes = [
            GinIndex(fields=["i18n"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name_i18n)
        super(HutType, self).save(*args, **kwargs)


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


# class HutRefProps(BaseModel):
#    id:         Optional[str]
#    link:       Optional[str]
#    name:       Optional[str]
#    fullname:   Optional[str]
#    logo:       Optional[str]
#    icon:       Optional[str]
#    color_light:  Optional[str]
#    color_dark:   Optional[str]
#    ref_url:    Optional[str]
#    props:      dict             = Field(default_factory=dict, description="additional properties")
#
#    def update(self, data: dict or "HutRefProps", force:bool=False) -> "HutRefProps":
#        if isinstance(data, HutRefProps):
#            data = data.dict()
#        for k,v in self.validate(data).dict().items():
#            if not getattr(self, k, None) or force:
#                try:
#                    setattr(self, k, v)
#                except AttributeError:
#                    pass # ignore value
#        return self
#
#    class Config:
#        orm_mode = True
#
## TODO --> needs to be in locale.py
# class Translator(GetterDict):
#
#    def get(self, key: str, default: Any) -> Any:
#
#        val = getattr(self._obj, key)
#        #rprint(f"Get key: {key}: {type(val)}")
#        if isinstance(val, Translations.TransField):
#            field = getattr(self._obj, key.field)
#            val = getattr(self._obj, field, Translations()).get()
#        #if isinstance(val, Translations) or key == "name":
#        if getattr(self._obj, f"{key}_t", None):
#            #rprint(f"Got translation: {key}")
#            #key_t = key.replace(key, "_t")
#            key_t = key + "_t"
#            val = getattr(self._obj, key_t).get()
#            #rprint(value)
#            #setattr(self, key, value )
#        return val
#
# class HutReadBase(BaseModel):
#    #@root_validator(pre=True)
#    #def translate_name(cls, values):
#    #    rprint("ROOT Validator:")
#    #    rprint(values)
#    #    for key, val in values.items():
#    #        if isinstance(val, Translations.TransField):
#    #            values[key] = values.get(values[key].field, None)
#    #        if isinstance(val, Translations):
#    #            key_t = key.replace(key, "_t")
#    #            if key_t not in values.keys():
#    #                values[key_t] = val
#    #    return values
#
#    name:       Optional[str]
#    slug:       Optional[str]
#    type_id:      HutType = 0 # what type: caping, alpine, biwak ..
#
#    class Config:
#        getter_dict = Translator
#
# class HutReadRefs(BaseModel):
#    refs:       dict[str, HutRefProps] = Field(default_factory=dict)
#    @validator('refs', pre=True)
#    def list_to_ref_dict(cls, refs):
#        if isinstance(refs, list):
#            ref_d = {}
#            for ref in refs:
#                if ref.is_active:
#                    ref_link = ref.ref_link
#                    link_props = HutRefProps.from_orm(ref)
#                    link_props.link = ref.url
#                    link_props.update(ref_link)
#                    ref_d[ref.slug] = link_props
#            return ref_d
#        return refs
#
# class HutReadPhotos(BaseModel):
#    photos:     Optional[List[PhotoRead]]
#    @validator('photos', pre=True)
#    def photos_to_read(cls, photos:List[Photo]) -> List[PhotoRead]:
#        out = []
#        for p in photos:
#            if isinstance(p, Photo):
#                out.append(p.to_read())
#            else:
#                out.append(p)
#        return out
#
# class HutGeoReadBasic(HutReadBase):
#    pass
#
#    class Config:
#        orm_mode = True
#
#
# class HutGeoRead(HutReadBase, HutReadRefs, HutReadPhotos):
#    url:        Optional[str]
#    owner:      Optional[str]
#    booking:    List[BookingOccupation] = []
#
#    elevation:  Optional[Elevation]
#    capacity:   Optional[NaturalInt]
#    capacity_shelter: Optional[NaturalInt]
#
#    class Config:
#        orm_mode = True
#
# class HutFeature(Feature):
#    properties: HutGeoRead
#
# class HutFeatureCollection(FeatureCollection):
#    features: List[HutFeature]
#
##class HutBase(SQLModel):
# class HutBase(BaseModel):
#
#    #name_t: Translations  = Field(Translations(), sa_column=Column(PydanticType(Translations)))
#    #_name_t               = Translations.get_validator('name_t')
#
#    slug:        Optional[str] = Field(unique=True, schema_extra={"example": "sac-bergen"}, max_length=40)
#
#    #description_t: Translations  = Field(Translations(), sa_column=Column(PydanticType(Translations)))
#    #_description_t               = Translations.get_validator('description_t')
#    owner:       Optional[str] = Field(None, max_length=100)
#    # adress stuff
#    contacts:     List[Contact] = Field(default_factory=list, max_items=8, sa_column=Column(PydanticType(List[Contact])))
#    url:         Optional[str] = Field(None, max_length=200)
#    comment:     Optional[str] = Field(None, max_length=2000)#, sa_column=Column(VARCHAR(1000)))
#
#    photos:        List[Photo] = Field(default_factory=list, sa_column=Column(PydanticType(List[Photo])))
#
#    country :              str = Field("CH", max_length=10)
#    point:               Point = Field(..., sa_column=Column(saPoint, nullable=False))
#    elevation:   Optional[Elevation] = Field(None, index=True)
#    # hut stuff
#    capacity:          Optional[NaturalInt] = Field(default=0, index=True)
#    capacity_shelter:  Optional[NaturalInt] = Field(default=0, index=True)
#
#    infrastructure:       dict = Field(default_factory=dict, sa_column=Column(JSON)) # TODO, better name. Maybe use infra and service separated, external table
#    access:             Access = Field(default_factory=Access, sa_column=Access.get_sa_column())
#
#
#    review_status: ReviewStatus = ReviewStatus.new
#    is_active:             bool = Field(default=True, index=True)
#
#    monthly:            Monthly = Field(default_factory=Monthly, sa_column=Monthly.get_sa_column())
#    type_id:      HutType =  Field(0, sa_column=Column(IntEnum(HutType)))
#
#    def get_geojson(self, model:HutGeoReadBasic=HutGeoRead) -> HutFeature:
#        point = self.point.geojson
#        props = model.from_orm(self)
#        if not props.name:
#            props.name = self.name_t._
#        return Feature(geometry=point, properties=props, id=self.id, type="Feature")
#
#
#    class Config:
#        orm_mode = True
#
# class HutBaseT(HutBase, TranslationModel):
#    """Hut base with translations"""
#
#    name_t: Translations  = Field(Translations(), sa_column=Column(PydanticType(Translations)))
#    _name_t               = Translations.get_validator('name_t')
#
#    description_t: Translations  = Field(Translations(), sa_column=Column(PydanticType(Translations)))
#    _description_t               = Translations.get_validator('description_t')
#
# class Hut(HutBaseT):
#    """Main hut model"""
#    #test_name: str             = Translations.Field(field="test_name_t")
#    name: Optional[str]   = Translations.TransField(field="name_t")
#    description: Optional[str]   = Translations.TransField(field="description_t")
#    refs: List[HutRefLinkBase] = []
#
#
# class HutDatabase(HutBaseT, TimestampMixinSQLModel, SQLModel, table=True):
#    """Hut model used for the database"""
#    __tablename__: str = "hut"
#    id: Optional[int] = Field(default=None, primary_key=True)
#    refs: List[HutRefLink] = Relationship(back_populates="hut_link")#, sa_relationship_kwargs={"lazy": "selectin"})
