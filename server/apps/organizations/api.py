from django.shortcuts import get_object_or_404
from ninja import Field, Query, Router
from typing import List, Optional

from pydantic import parse_obj_as
from .models import Organization
from ninja.orm import create_schema
from ninja.errors import HttpError

from ninja import ModelSchema, Schema

from ..utils.locale import TranslationModel, Translations, set_current_locale
#from django.utils.translation import override, activate
from ..djjmt.utils import override

FIELDS = ["id", "slug", "is_active", "fullname",
           "description", "url", "attribution", "link_hut_pattern",
           "logo", "color_light", "color_dark", "config",
           "props_schema", "order"]


router = Router()
class OrganizationSchema(ModelSchema):
    class Config:
        model = Organization
        model_fields = FIELDS + ["created", "modified"] #"__all__"
        #model_exclude = ["i18n"]
        #model_exclude = ['i18n', 'name_i18n', 'name_de', 'name_en', 'name_it', 'name_fr', 'fullname_i18n', 'fullname_de', 'fullname_en', 'fullname_it', 'fullname_fr', 'attribution_i18n', 'attribution_de', 'attribution_en', 'attribution_it', 'attribution_fr', 'description_i18n', 'description_de', 'description_en', 'description_it', 'description_fr']
        orm_mode = True

class OrganizationSchemaOut(OrganizationSchema, TranslationModel):
    slug: Optional[str] = None
    name: str | dict = Field(None)
    fullname: str | dict = None
    order: int = None
    #i18n: dict = None
    #name2_t : Translations = Translations(locale="en")
    #_name2_t = Translations.get_validator('name2_t')
    #name2:str = Translations.TransField(field="name2_t")
    #name3: dict | str = ""

class OrganizationSchemaIn(ModelSchema):
    class Config:
        model = Organization
        #model_fields = "__all__"
        model_fields = FIELDS #"__all__"
        #model_exclude = ['i18n', "created", "modified", "id", "order", 'name_i18n', 'name_de', 'name_en', 'name_it', 'name_fr', 'fullname_i18n', 'fullname_de', 'fullname_en', 'fullname_it', 'fullname_fr', 'attribution_i18n', 'attribution_de', 'attribution_en', 'attribution_it', 'attribution_fr', 'description_i18n', 'description_de', 'description_en', 'description_it', 'description_fr']
        orm_mode = True



class Fields(Schema):
    include: str|None = Query(None,description="Comma separated list")
    exclude: str|None = Query("created,modified,id,order",description="Comma separated list, only used if 'include' is not set.")
    allowed_fields: List =  Field([], include_in_schema=False)

    def set_allowed_fields(self, fields):
        self.allowed_fields = [name for name, _ in fields.items()]

    def validate_fields(self, fields: List | None):
        if fields is not None and self.allowed_fields:
            for field in fields:
                if field not in self.allowed_fields:
                    raise HttpError(400, f"'{field}' is not a valid field name! Possible names: {self.allowed_fields}")

    def get_include(self) -> List[str]:
        if self.include is not None:
            self.include = [f.strip() for f in self.include.split(",") if f.strip()]
            self.validate_fields(self.include)
        else:
            self.include = FIELDS + ["created", "modified"]
            if self.exclude is None:
                self.exclude = "created,modified,id,order"
            if self.exclude:
                self.include = list(set(self.include) - set(self.exclude))
        return self.include

    def get_exclude(self) -> List[str]:
        return None
        #if self.exclude is None:
        #    self.exclude = "created,modified,id,order"
        #if self.exclude is not None:
        #    self.exclude = [f.strip() for f in self.exclude.split(",") if f.strip()]
        #    self.validate_fields(self.exclude)
        #return self.exclude if not self.include else None


@router.get('/', response=List[OrganizationSchemaOut], exclude_unset=True)
def list_organizations(request, fields:Fields = Query(...), lang: str = "de"):
    with override(lang):
        fields.set_allowed_fields(OrganizationSchemaOut.__fields__)
        Schema = create_schema(Organization, fields=fields.get_include(), exclude=fields.get_exclude())
        out = parse_obj_as(List[Schema], list(Organization.objects.all()))
    return out

@router.post("/", response=OrganizationSchemaOut)
def create_employee(request, payload: OrganizationSchemaIn):
    order = Organization.objects.last().order
    pay_dict = payload.dict()
    pay_dict["order"] = order + 1
    try:
        org = Organization.objects.create(**pay_dict)
    except:
        raise HttpError(400, "Invalid data request, maybe not unique slug?")
    return org

@router.get('/{slug}', response=OrganizationSchemaOut)#, exclude_unset=True)
def organization_details(request, slug: str, fields:Fields = Query(...), lang: str | None = None):
    fields.set_allowed_fields(OrganizationSchemaOut.__fields__)
    #Schema = create_schema(Organization, fields=fields.get_include(), exclude=fields.get_exclude())
    Schema = create_schema(Organization)
    with override(lang):
        obj =  parse_obj_as(Schema, get_object_or_404(Organization, slug=slug))
        #set_current_locale(lang)
        obj2 = OrganizationSchemaOut.from_orm(obj)
    return obj2
    #obj.name2 = obj.name2
    #obj_d = dict(obj)
    #obj_d["name2"] = obj.name2
    #return obj_d
    #with override(lang):

    #    return obj.fullname
    #return get_object_or_404(Organization, slug=slug)
    #return Organization.objects.get(slug=slug)

@router.put("/{slug}", response=OrganizationSchemaOut)
def update_organization(request, slug: str, payload: OrganizationSchemaIn):
    org = get_object_or_404(Organization, slug=slug)
    for attr, value in payload.dict().items():
        setattr(org, attr, value)
    org.save()
    return org

@router.delete("/{slug}")
def delete_organization(request, slug: str):
    org = get_object_or_404(Organization, slug=slug)
    org.delete()
    return {"success": True}