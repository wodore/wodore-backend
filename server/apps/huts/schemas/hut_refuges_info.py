from typing import Dict, Literal, Optional

import click
from geojson_pydantic import Feature, FeatureCollection, Point
from pydantic import BaseModel, Field, computed_field

from django.contrib.gis.geos import Point as dbPoint

from server.apps.djjmt.fields import TranslationSchema

# from sqlmodel import Field, SQLModel
# from pydantic_computed import Computed, computed
# from ..hut import Hut
# from ..utils.hut_fields import HutType
from ..logic.hut_type import guess_hut_type

# import phonenumbers
# from app.models.ref import HutRefLink
from .hut_base import HutBaseSource

# from app.models.utils.locale import Translations
# from ..utils.hut_fields import Contact, Monthly, MonthlyOptions, Open, Catering
# from core.db.mixins.timestamp_mixin import TimestampMixinSQLModel
# from typing_extensions import TypedDict
# from .point import Elevation, Latitude, Longitude, Point
from .point import Point as chPoint

REFUGES_HUT_TYPES = {7: "cabane-non-gardee", 10: "refuge-garde", 9: "gite-d-etape", 28: "batiment-en-montagne"}
WODORE_HUT_TYPES = {7: "unattended-hut", 10: "hut", 9: "hut", 28: "basic-hotel"}


class Coord(BaseModel):
    alt: float
    long: float
    lat: float
    precision: dict[str, str]


class ValeurNom(BaseModel):
    nom: str
    valeur: str | None


class ValeurID(BaseModel):
    id: int
    valeur: str | None


class NomID(BaseModel):
    id: int
    nom: str | None


class Type(ValeurID):
    icone: str


class Etat(ValeurID):
    id: Literal["ouverture", "fermeture", "cle_a_recuperer", "detruit"] | None


class Date(BaseModel):
    derniere_modif: str
    creation: str


class Article(BaseModel):
    demonstratif: str
    defini: str
    partitif: str


class SiteOfficiel(ValeurNom):
    url: str | None


class PlacesMatelas(ValeurNom):
    nb: int | None


class InfoComp(BaseModel):
    site_officiel: SiteOfficiel
    manque_un_mur: ValeurNom
    cheminee: ValeurNom
    poele: ValeurNom
    couvertures: ValeurNom
    places_matelas: PlacesMatelas
    latrines: ValeurNom
    bois: ValeurNom
    eau: ValeurNom


class Description(BaseModel):
    valeur: str


class RefugesInfoProperties(BaseModel):
    id: int
    lien: str  # link
    nom: str
    sym: str
    coord: Coord
    type: Type
    places: ValeurNom
    etat: Etat
    date: Date
    remarque: ValeurNom
    acces: ValeurNom
    proprio: ValeurNom
    createur: NomID
    article: Article
    info_comp: InfoComp
    description: Description


class RefugesInfoFeature(Feature):
    """RefugesInfo Feature Model with required properties and geometry."""

    geometry: Point
    properties: RefugesInfoProperties


class RefugesInfoFeatureCollection(FeatureCollection):
    generator: str
    copyright: str
    timestamp: str
    size: str
    features: list[RefugesInfoFeature]


class HutRefugesInfo0Source(HutBaseSource):
    """data from OSM database"""

    source_class: str = Field(default_factory=lambda: __class__.__name__)
    convert_class: str = Field(default_factory=lambda: __class__.__name__.replace("Source", "Convert"))

    id: int
    feature: RefugesInfoFeature

    def get_id(self) -> str:
        return str(self.id)

    def get_name(self) -> str:
        return self.feature.properties.nom

    def get_point(self) -> chPoint:
        return chPoint(lat=self.feature.properties.coord.lat, lon=self.feature.properties.coord.long)

    def get_db_point(self) -> dbPoint:
        return self.get_point().db

    # @classmethod
    # def get_printable_fields(cls, alias=False):
    #    properties = ["osm_type"] + [f"tags.{k}" for k in list(OSMTags.__fields__.keys())]
    #    return properties


class HutRefugesInfo0Convert(BaseModel):
    source: HutRefugesInfo0Source

    @property
    def _props(self) -> RefugesInfoProperties:
        return self.source.feature.properties

    @computed_field
    @property
    def name(self) -> dict[str, str]:
        return TranslationSchema(fr=self._props.nom, de=self._props.nom).model_dump()

    @computed_field
    @property
    def description(self) -> dict[str, str]:
        return TranslationSchema(fr=self._props.description.valeur or "").model_dump()

    @computed_field
    @property
    def note(self) -> dict[str, str]:
        _note_fr = self._props.remarque.valeur or ""
        _note_de = ""
        if self._props.etat == "cle_a_recuperer":
            _note_fr = f"Clés nécessaires \n\n{_note_fr}".strip()
            _note_de = "Schlüssel erforderlich"
        return TranslationSchema(fr=_note_fr, de=_note_de).model_dump()
        # return self.description

    @computed_field
    @property
    def point(self) -> chPoint:
        return self.source.get_point()

    @computed_field
    @property
    def url(self) -> str:
        return self._props.info_comp.site_officiel.url or ""

    @computed_field
    @property
    def elevation(self) -> float | None:
        return self._props.coord.alt

    @computed_field
    @property
    def capacity(self) -> Optional[int]:
        try:
            return int(self._props.places.valeur)  # type: ignore  # noqa: PGH003
        except TypeError:
            return None

    @computed_field
    @property
    def capacity_shelter(self) -> Optional[int]:
        return None

    @computed_field
    @property
    def type(self) -> str:
        """Returns type slug"""
        _type = WODORE_HUT_TYPES.get(self._props.type.id, "unknown")
        if _type == "unattended-hut":
            if self._props.info_comp.manque_un_mur.valeur or "0" != "0":
                _type = "basic-shelter"
            elif self.elevation or 0 > 2500:
                _type = "bivouac"
        return _type

    @computed_field
    @property
    def owner(self) -> str:
        return self._props.proprio.valeur or ""

    @computed_field
    @property
    def is_active(self) -> bool:
        return self._props.etat.id in ["ouverture", "cle_a_recuperer"] or self._props.etat.id is None

    @computed_field
    @property
    def props(self) -> dict[str, str]:
        slug = self._props.lien.split("/")[-2]
        return {"hut_type": REFUGES_HUT_TYPES.get(self._props.type.id, ""), "slug": slug}


# class HutOsm0Convert(HutOsm0Source):
#    """Helper class to convert from OSM source to Hut class"""
#    slug: Optional[str]
#
#    name_t : Computed[Translations]
#    @computed('name_t')
#    def name_t(tags, **kwargs) -> Translations:
#        return Translations(de=tags.name[:69])
#
#    description_t : Computed[Translations]
#    @computed('description_t')
#    def description_t(tags, **kwargs) -> Translations:
#        return Translations(en=tags.note)
#
#    owner : Computed[str]
#    @computed('owner')
#    def _owner(tags, **kwargs) -> str:
#        owner = tags.operator
#        if owner:
#            if len(owner) > 100:
#                click.secho(f"warning: owner too long: '{owner}'", fg="red")
#            owner = owner[:100]
#        return owner
#
#    email : Computed[str]
#    @computed('email')
#    def _email(tags, **kwargs) -> str:
#        if tags.email:
#            return tags.email
#        elif tags.contact_email:
#            return tags.contact_email
#        return None
#
#    phones : Computed[List[Contact]]
#    @computed('phones')
#    def phones(tags) -> List[str]:
#        phone = None
#        if tags.phone:
#            phone = tags.phone
#        elif tags.contact_phone:
#            phone = tags.contact_phone
#        phones = []
#        if phone:
#            _matches = phonenumbers.PhoneNumberMatcher(phone, "CH")
#            if not _matches:
#                click.secho(f"warning: could not macht phone number: '{phone}'",fg="red")
#            for phone in _matches:
#                #if len(str(phone)) > 30: # probably not valid
#                    #click.secho(f"warning: phone number is too long: '{phone}'",fg="red")
#                phone_fmt = phonenumbers.format_number(phone.number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
#                phones.append(phone_fmt)
#        return phones
#
#
#
#    contacts : Computed[List[Contact]]
#    @computed('contacts')
#    def _contacts(email, phones, **kwargs) -> List[Contact]:
#        contacts = []
#        if email:
#            email = email.strip()
#        for phone in phones:
#            mobile = phonenumbers.number_type(phonenumbers.parse(phone)) \
#                            == phonenumbers.PhoneNumberType.MOBILE
#            contacts.append(Contact(phone=phone, email=email, mobile=mobile))
#            if email:
#                email = None
#        # TODO: do the same with emails as for phones
#        if email:
#            for email in email.split(";"):
#                contacts.append(Contact(email=email.strip()))
#        return contacts
#
#
#    url : Computed[str]
#    @computed('url')
#    def _url(tags, **kwargs) -> str:
#        if tags.website:
#            return tags.website[:200]
#        elif tags.contact_website:
#            return tags.contact_website[:200]
#        return None
#
#    comment : Computed[str]
#    @computed('comment')
#    def _comment(tags, **kwargs) -> Point:
#        return tags.note
#
#    wikidata : Computed[str]
#    @computed('wikidata')
#    def _wikidata(tags, **kwargs) -> str:
#        return tags.wikidata
#
#    point : Computed[Point]
#    @computed('point')
#    def _point(lat, lon, center_lat, center_lon, **kwargs) -> Point:
#        if lat:
#            return Point(lat=lat, lon=lon)
#        elif center_lat:
#            return Point(lat=center_lat, lon=center_lon)
#        else:
#            raise UserWarning(f"OSM coordinates are missing: {kwargs}")
#
#    elevation : Computed[Elevation]
#    @computed('elevation')
#    def _elevation(tags, **kwargs) -> Elevation:
#        if tags.ele:
#            return tags.ele
#        else:
#            return None
#
#    capacity : Computed[int]
#    @computed('capacity')
#    def _capacity(tags, **kwargs) -> Optional[int]:
#        cap = None
#        if tags.capacity:
#            cap = tags.capacity
#        elif tags.beds:
#            cap = tags.beds
#        elif tags.bed:
#            cap = tags.bed
#        try:
#            if not cap is None:
#                cap = int(cap)
#        except ValueError:
#            cap = None
#        return cap
#
#    capacity_shelter : Computed[int]
#    @computed('capacity_shelter')
#    def _capacity_shelter(tags, capacity, **kwargs) -> Optional[int]:
#        if tags.winter_room:
#            try:
#                return int(tags.winter_room) # capacity in tag
#            except ValueError:
#                pass
#        if tags.tourism == "wilderness_hut":
#            return capacity
#        return None
#
#    type_id :Computed[int]
#    @computed('type_id')
#    def type_id(name_t, capacity, capacity_shelter, elevation, tags, **kwargs) -> int:
#        _orgs = ""
#        if tags.operator:
#            _orgs = "sac" if "sac" in tags.operator else ""
#        return HutType.guess(name=name_t.de,capacity=capacity, capacity_shelter=capacity_shelter,
#                             elevation=elevation, organization=_orgs, osm_tag=tags.tourism)
#
#    is_active : Computed[bool]
#    @computed('is_active')
#    def _is_active(tags, **kwargs) -> str:
#        if tags.access:
#            return tags.access in ["yes", "public", "customers", "permissive"]
#        return True
#
#
