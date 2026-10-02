"""Organization endpoints (GET list + detail) on dmr."""

import pydantic
from dmr import Path, Query, modify
from dmr.routing import path
from pydantic import Field

from server.apps.api.controller import ApiController, raise_not_found
from server.apps.api.query import FieldsQuery, dump_fields, dump_fields_list
from server.apps.translations import override
from server.apps.translations.schema import LanguageQuery

from .models import Organization
from .schema import OrganizationOptional


class OrganizationListQuery(LanguageQuery, FieldsQuery):
    """Query parameters for the organization list."""

    is_public: bool | None = None


class OrganizationDetailQuery(LanguageQuery, FieldsQuery):
    """Query parameters for the organization detail endpoint."""


class OrgSlugPath(pydantic.BaseModel):
    """Organization slug path parameter."""

    slug: str = Field(description="Organization slug")


class OrganizationsController(ApiController):
    """Organizations used for the huts."""

    @modify(operation_id="get_organizations")
    def get(
        self,
        parsed_query: Query[OrganizationListQuery],
    ) -> list[dict]:
        """Get a list of all organizations used for the huts."""
        orgs = Organization.objects.all().filter(is_active=True)
        if isinstance(parsed_query.is_public, bool):
            orgs = orgs.filter(is_public=parsed_query.is_public)
        with override(parsed_query.lang):
            return dump_fields_list(
                OrganizationOptional,
                list(orgs),
                parsed_query,
                default_include=["slug", "url", "logo", "name", "fullname"],
            )


class OrganizationDetailController(ApiController):
    """A single organization by slug."""

    @modify(operation_id="get_organization")
    def get(
        self,
        parsed_path: Path[OrgSlugPath],
        parsed_query: Query[OrganizationDetailQuery],
    ) -> dict:
        """Get a single organization by its slug."""
        org = Organization.objects.filter(slug=parsed_path.slug, is_active=True).first()
        if org is None:
            raise_not_found(f"Organization {parsed_path.slug!r} not found.")
        with override(parsed_query.lang):
            return dump_fields(
                OrganizationOptional, org, parsed_query, default_include="__all__"
            )


paths = [
    path("", OrganizationsController.as_view(), name="get_organizations"),
    path(
        "<str:slug>",
        OrganizationDetailController.as_view(),
        name="get_organization",
    ),
]
