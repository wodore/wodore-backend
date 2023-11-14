from django.shortcuts import get_object_or_404
from ninja import Field, Query, Router
from typing import List, Optional

from pydantic import parse_obj_as, BaseModel
from .models import Organization
from ninja.orm import create_schema
from ninja.errors import HttpError

from ninja import ModelSchema, Schema

from ..utils.api import fields_query
from ..djjmt.utils import override
from ..djjmt.fields import TranslationSchema


router = Router()

class OrganizationSchema(ModelSchema):
    class Config:
        model = Organization
        model_fields = Organization.get_fields_all()

class OrganizationSchemaOut(ModelSchema):
    #slug: Optional[str] = None
    name: str | TranslationSchema = None
    description: str | TranslationSchema = None
    #fullname: str | TranslationSchema = None
    #attribution: str | TranslationSchema = None
    #order: int = None

    class Config:
        model = Organization
        model_fields = Organization.get_fields_all()
        model_fields_optional = Organization.get_fields_all()

class OrganizationSchemaIn(ModelSchema):
    class Config:
        model = Organization
        model_fields = Organization.get_fields_in()

# TODO: use this to add TranslationSchema
#def make_optional(schema_cls):
#    for field in schema_cls.__fields__.values():
#        if field.required:
#            field.required = False
#            field.default = None
#make_optional(PersonSchema) 


@router.get('/', response=List[OrganizationSchemaOut], exclude_unset=True)
def list_organizations(request, lang: str | None = None,
            fields:fields_query(Organization) = Query(...)):
    with override(lang):
        objs = parse_obj_as(List[fields.get_schema()], list(Organization.objects.all()))
    return objs

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

@router.get('/{slug}', response=OrganizationSchemaOut, exclude_unset=True)
def organization_details(request, slug: str, lang: str | None = None,
            fields:fields_query(Organization) = Query(...)):
    with override(lang):
        obj =  parse_obj_as(fields.get_schema(), get_object_or_404(Organization, slug=slug))
    return obj

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