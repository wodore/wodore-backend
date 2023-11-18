from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from ninja import Query, Router
from typing import List, Dict

from .models import Organization
from .schema import OrganizationCreate, OrganizationOptional, OrganizationUpdate
from ninja.errors import HttpError

from ninja import ModelSchema

from ..utils.query import Fields as QueryFields
from ..djjmt.utils import override
from ..djjmt.fields import TranslationSchema

router = Router()


@router.get("/", response=List[OrganizationOptional], exclude_unset=True)
def list_organizations(request, lang: str | None = None, fields: Query[QueryFields[OrganizationOptional]] = None):
    with override(lang):
        objs = fields.validate(list(Organization.objects.all()))
    return objs


@router.post("/", response=OrganizationOptional)
def create_organization(request, payload: OrganizationCreate):
    last_elem = Organization.objects.values("order").last() or {}
    order = last_elem.get("order", -1) + 1
    pay_dict = payload.model_dump()
    pay_dict["order"] = order
    try:
        org = Organization.objects.create(**pay_dict)
    except IntegrityError as e:
        raise HttpError(400, str(e))
    return org


@router.get("/{slug}", response=OrganizationOptional, exclude_unset=True)
def organization_details(
    request, slug: str, lang: str | None = None, fields: Query[QueryFields[OrganizationOptional]] = None
):
    fields.update_default("__all__")
    with override(lang):
        obj = fields.validate(get_object_or_404(Organization, slug=slug))
    return obj


@router.put("/{slug}", response=OrganizationOptional)
def update_organization(request, slug: str, payload: OrganizationUpdate):
    org = get_object_or_404(Organization, slug=slug)
    for attr, value in payload.model_dump(exclude_unset=True).items():
        setattr(org, attr, value)
    org.save()
    return org


@router.delete("/{slug}")
def delete_organization(request, slug: str):
    org = get_object_or_404(Organization, slug=slug)
    org.delete()
    return {"success": True}
