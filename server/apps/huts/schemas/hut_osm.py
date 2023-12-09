from typing import Literal, Optional, List

# import phonenumbers
# from app.models.ref import HutRefLink

from .hut_base import HutBaseSource
import click
from rich import print as rprint
from djjmt.fields import TranslationSchema

# from app.models.utils.locale import Translations
# from ..utils.hut_fields import Contact, Monthly, MonthlyOptions, Open, Catering
# from core.db.mixins.timestamp_mixin import TimestampMixinSQLModel
# from typing_extensions import TypedDict
# from .point import Elevation, Latitude, Longitude, Point
from .point import Point
from pydantic import BaseModel, Field, computed_field

from django.contrib.gis.geos import Point as dbPoint

# from sqlmodel import Field, SQLModel
# from pydantic_computed import Computed, computed
# from ..hut import Hut
# from ..utils.hut_fields import HutType

from huts.models import HutType

from huts.logic.hut_type import guess_hut_type


class OSMTags(BaseModel):  #:, table=True):
    # __tablename__: str = "hut_osm"
    tourism: Literal["alpine_hut", "wilderness_hut"]
    wikidata: Optional[str] = None

    name: str
    operator: Optional[str] = None
    email: Optional[str] = None
    contact_email: Optional[str] = Field(None, alias="contact:field")
    phone: Optional[str] = None
    contact_phone: Optional[str] = Field(None, alias="contact:phone")
    website: Optional[str] = None
    contact_website: Optional[str] = Field(None, alias="contact:website")
    note: Optional[str] = None

    bed: Optional[str] = None
    beds: Optional[str] = None
    capacity: Optional[str] = None
    access: Optional[str] = None
    fireplace: Optional[str] = None
    wall: Optional[str] = None
    amenity: Optional[str] = None
    shelter_type: Optional[str] = None
    winter_room: Optional[str] = None
    reservation: Optional[str] = None

    # ele: Optional[Elevation]
    ele: Optional[float] = None


class HutOsm0Source(HutBaseSource):
    """data from OSM database"""

    source_class: str = Field(default_factory=lambda: __class__.__name__)
    convert_class: str = Field(default_factory=lambda: __class__.__name__.replace("Source", "Convert"))

    osm_type: Optional[Literal["node", "way", "area"]] = None
    id: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None
    # lat: Optional[Latitude]
    # lon: Optional[Longitude]
    # center_lat: Optional[Latitude]
    # center_lon: Optional[Longitude]
    tags: OSMTags

    def get_id(self) -> str:
        return str(self.id)

    def get_name(self) -> str:
        return self.tags.name

    def get_point(self) -> Point:
        if self.lat:
            return Point(lat=self.lat, lon=self.lon)
        elif self.center_lat:
            return Point(lat=self.center_lat, lon=self.center_lon)
        else:
            raise UserWarning(f"OSM coordinates are missing.")

    def get_db_point(self) -> dbPoint:
        return self.get_point().db

    # def get_hut(self, include_refs: bool = True) -> Hut:
    #    # _convert = HutOsm0Convert(**self.dict())
    #    _convert = HutOsm0Convert.from_orm(self)
    #    hut = Hut.from_orm(_convert)
    #    if include_refs:
    #        refs = [
    #            HutRefLink(slug="osm", id=self.get_id(), props={"object_type": self.osm_type}, source_data=self.dict())
    #        ]
    #        if self.tags.wikidata:
    #            refs.append(HutRefLink(slug="wikidata", id=self.tags.wikidata))
    #        hut.refs = refs
    #    return hut

    @classmethod
    def get_printable_fields(cls, alias=False):
        properties = ["osm_type"] + [f"tags.{k}" for k in list(OSMTags.__fields__.keys())]
        return properties


class HutOsm0Convert(BaseModel):
    source: HutOsm0Source

    @property
    def _tags(self) -> OSMTags:
        return self.source.tags

    @computed_field
    @property
    def name(self) -> dict[str, str]:
        return TranslationSchema(de=self._tags.name[:69]).model_dump()

    @computed_field
    @property
    def description(self) -> dict[str, str]:
        return TranslationSchema(en=self._tags.note or "").model_dump()

    @computed_field
    @property
    def note(self) -> dict[str, str]:
        return self.description

    @computed_field
    @property
    def point(self) -> Point:
        lat = self.source.lat or self.source.center_lat
        lon = self.source.lon or self.source.center_lon
        if not (lat and lon):
            raise UserWarning(f"OSM coordinates are missing: {self._tags.name} (#{self.source.id})")
        return Point(lat=lat, lon=lon)

    @computed_field
    @property
    def url(self) -> str:
        url = ""
        if self._tags.website:
            url = self._tags.website
        elif self._tags.contact_website:
            url = self._tags.contact_website
        if len(url) > 200:
            url = ""
        return url

    @computed_field
    @property
    def elevation(self) -> float | None:
        if self._tags.ele:
            return self._tags.ele
        else:
            return None

    @computed_field
    @property
    def capacity(self) -> Optional[int]:
        tags = self._tags
        cap = None
        if tags.capacity:
            cap = tags.capacity
        elif tags.beds:
            cap = tags.beds
        elif tags.bed:
            cap = tags.bed
        try:
            if not cap is None:
                cap = int(cap)
        except ValueError:
            cap = None
        return cap

    @computed_field
    @property
    def capacity_shelter(self) -> Optional[int]:
        if self._tags.winter_room:
            try:
                return int(self._tags.winter_room)  # capacity in tag
            except ValueError:
                pass
        if self._tags.tourism == "wilderness_hut":
            return self.capacity
        return None

    @computed_field
    @property
    def type(self) -> str:
        """Returns type slug"""
        _orgs = ""
        if self._tags.operator:
            _orgs = "sac" if "sac" in self._tags.operator else ""
        return guess_hut_type(
            name=self.name.get("de", ""),
            capacity=self.capacity,
            capacity_shelter=self.capacity_shelter,
            elevation=self.elevation,
            organization=_orgs,
            osm_tag=self._tags.tourism,
        )

    @computed_field
    @property
    def is_active(self) -> bool:
        if self._tags.access:
            return self._tags.access in ["yes", "public", "customers", "permissive"]
        return True


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
