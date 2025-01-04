from ninja import Query, Router

# from ninja.errors import HttpError
# from django.db import IntegrityError
from django.http import HttpRequest
from django.shortcuts import get_object_or_404

from server.apps.api.query import FieldsParam
from server.apps.translations import LanguageParam, override, with_language_param

from .models import License
from .schema import LicenseOptional

router = Router()


@router.get(
    "/", response=list[LicenseOptional], exclude_unset=True, operation_id="get_licenses"
)
@with_language_param("lang")
def get_licenses(
    request: HttpRequest,
    lang: LanguageParam,
    fields: Query[FieldsParam[LicenseOptional]],
    is_public: bool | None = None,
) -> list[LicenseOptional]:
    """Get a list of all licenses used for the huts."""
    fields.update_default(include=["slug", "url", "logo", "name", "fullname"])
    orgs = License.objects.all().filter(is_active=True)
    if isinstance(is_public, bool):
        orgs = orgs.filter(is_public=is_public)
    with override(lang):
        return fields.validate(list(orgs))


@router.get(
    "/{slug}", response=LicenseOptional, exclude_unset=True, operation_id="get_license"
)
@with_language_param()
def get_license(
    request: HttpRequest,
    slug: str,
    lang: LanguageParam,
    fields: Query[FieldsParam[LicenseOptional]],
) -> LicenseOptional:
    fields.update_default("__all__")
    with override(lang):
        return fields.validate(get_object_or_404(License, slug=slug, is_active=True))


# @router.post("/", response=LicenseOptional)
# def create_organization(request, payload: OrganizationCreate):
#    last_elem = Organization.objects.values("order").last() or {}
#    order = last_elem.get("order", -1) + 1
#    pay_dict = payload.model_dump()
#    pay_dict["order"] = order
#    try:
#        org = Organization.objects.create(**pay_dict)
#    except IntegrityError as e:
#        raise HttpError(400, str(e))
#    return org
#
#

#
#
# @router.put("/{slug}", response=LicenseOptional)
# def update_organization(request, slug: str, payload: OrganizationUpdate):
#    org = get_object_or_404(Organization, slug=slug)
#    for attr, value in payload.model_dump(exclude_unset=True).items():
#        setattr(org, attr, value)
#    org.save()
#    return org
#
#
# @router.delete("/{slug}")
# def delete_organization(request, slug: str):
#    org = get_object_or_404(Organization, slug=slug)
#    org.delete()
#    return {"success": True}
#
