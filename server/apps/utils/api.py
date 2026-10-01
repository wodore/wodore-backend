from datetime import datetime
from os import environ

from ninja import Field, Query, Router, Schema
from ninja.errors import HttpError
from ninja.orm import create_schema

from django.http import HttpRequest, HttpResponse

from server.apps.api.sitemap import (
    SITEMAP_INDEX_TTL,
    SITEMAP_TTL,
    sitemap_huts,
    sitemap_index,
    sitemap_static,
)
from server.settings.components.common import (
    BUILD_TIMESTAMP,
    get_git_long_hash,
    get_git_short_hash,
)


# Get package version
def _get_package_version() -> str:
    """Get package version from pyproject.toml or package metadata."""
    # First try reading directly from pyproject.toml (works in Docker)
    try:
        try:
            import tomllib
        except ImportError:
            # Python < 3.11
            import tomli as tomllib  # type: ignore

        from pathlib import Path

        pyproject_path = Path(__file__).parents[3] / "pyproject.toml"
        if pyproject_path.exists():
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
                version = data.get("project", {}).get("version")
                if version:
                    return version
    except Exception:
        pass

    # Fallback: try importlib.metadata (works if package is installed)
    try:
        from importlib.metadata import version as get_version

        return get_version("wodore-backend")
    except Exception:
        pass

    return "unknown"


PACKAGE_VERSION = _get_package_version()

# Get environment
DJANGO_ENV = environ.get("DJANGO_ENV", "development")

router = Router()


class VersionSchema(Schema):
    hash: str = Field(  # pyright: ignore[reportCallIssue]  # Django Ninja Annotated idiom
        ...,
        description="Git commit short hash",
        json_schema_extra={"example": "abc123e"},
    )
    hash_long: str = Field(  # pyright: ignore[reportCallIssue]  # Django Ninja Annotated idiom
        ...,
        description="Git commit full hash",
        json_schema_extra={"example": "abc123ef4567890abcdef1234567890abcdef12"},
    )
    version: str = Field(  # pyright: ignore[reportCallIssue]  # Django Ninja Annotated idiom
        ...,
        description="Sematic version",
        json_schema_extra={"example": "1.2.0"},
    )
    timestamp: datetime = Field(  # pyright: ignore[reportCallIssue]  # Django Ninja Annotated idiom
        ...,
        description="Build timestamp",
    )
    environment: str = Field(  # pyright: ignore[reportCallIssue]  # Django Ninja Annotated idiom
        ...,
        description="Current environment (development, production)",
        json_schema_extra={"example": "production"},
    )


@router.get("/version", response=VersionSchema, tags=["version"])
def get_version(request):
    """Get version information including git short hash, full hash, package version, build timestamp, and environment."""
    return {
        "hash": get_git_short_hash(),
        "hash_long": get_git_long_hash(),
        "version": PACKAGE_VERSION,
        "timestamp": datetime.fromisoformat(BUILD_TIMESTAMP),
        "environment": DJANGO_ENV,
    }


def _xml_response(document: str, ttl: int = SITEMAP_TTL) -> HttpResponse:
    response = HttpResponse(document, content_type="application/xml; charset=utf-8")
    response["Cache-Control"] = f"public, max-age={ttl}"
    return response


@router.get("/sitemap.xml", include_in_schema=False)
def get_sitemap_index(request: HttpRequest) -> HttpResponse:
    """Sitemap index for wodore.com (static pages + paginated hut sitemaps).

    The frontend nginx proxies ``wodore.com/sitemap.xml`` here; all listed
    URLs (and the child sitemaps) are absolute wodore.com URLs.
    """
    return _xml_response(sitemap_index(), SITEMAP_INDEX_TTL)


@router.get("/sitemap-static.xml", include_in_schema=False)
def get_sitemap_static(request: HttpRequest) -> HttpResponse:
    """Canonical frontend entry pages of wodore.com."""
    return _xml_response(sitemap_static(), SITEMAP_INDEX_TTL)


@router.get("/sitemap-huts-{page}.xml", include_in_schema=False)
def get_sitemap_huts(request: HttpRequest, page: int) -> HttpResponse:
    """One page of public hut URLs (SITEMAP_PAGE_SIZE per file)."""
    if page < 0:
        raise HttpError(404, "Sitemap page numbers start at 0.")
    document = sitemap_huts(page)
    if document is None:
        raise HttpError(404, f"No huts for sitemap page {page}.")
    return _xml_response(document)


# @abc
class FieldsSchema(Schema):
    include: str | None = Query(  # pyright: ignore[reportCallIssue]  # Django Ninja Annotated idiom
        None, description="Comma separated list, allowed value:"
    )  # {', '.join(fields)}")
    exclude: str | None = Query(  # pyright: ignore[reportCallIssue]  # Django Ninja Annotated idiom
        None, description="Comma separated list, only used if 'include' is not set."
    )
    # ",".join(exclude_default), description="Comma separated list, only used if 'include' is not set."
    # )
    allowed_fields: list = Field(  # pyright: ignore[reportAssignmentType, reportCallIssue]  # ninja idiom (None default, Annotated marker)
        None, json_schema_extra={"include_in_schema": False}
    )
    _model = None

    def set_allowed_fields(self, fields: list):
        self.allowed_fields = fields

    def validate_fields(self, fields: list | None):
        if fields is not None and self.allowed_fields:
            for field in fields:
                if field not in self.allowed_fields:
                    raise HttpError(
                        400,
                        f"'{field}' is not a valid field name! Possible names: {self.allowed_fields}",
                    )

    def get_include(self) -> list[str]:
        if self.include is not None:
            _include = [f.strip() for f in self.include.split(",") if f.strip()]
            self.validate_fields(_include)
        else:
            _include = self._model.get_fields_all() if self._model else []
            if self.exclude is None:
                self.exclude = ",".join(
                    self._model.get_fields_exclude() if self._model else []
                )
            if self.exclude:
                _exclude = [f.strip() for f in self.exclude.split(",") if f.strip()]
                _include = list(set(_include) - set(_exclude))
        return _include

    def get_schema(self):
        return create_schema(
            self._model,  # pyright: ignore[reportArgumentType]  # dynamic _model
            fields=self.get_include(),
        )


def fields_query(Model) -> FieldsSchema:  # fields:List, exclude_default=[]):
    fields = Model.get_fields_all()[:]
    exclude_default = Model.get_fields_exclude()[:]

    """Returns a query which can be used to include and exclude fields"""

    class Fields(FieldsSchema):
        include: str | None = Query(  # pyright: ignore[reportCallIssue]  # Django Ninja Annotated idiom
            None,
            description=f"Comma separated list, allowed value: {', '.join(fields)}",
        )
        exclude: str | None = Query(  # pyright: ignore[reportCallIssue]  # Django Ninja Annotated idiom
            ",".join(exclude_default),
            description="Comma separated list, only used if 'include' is not set.",
        )
        allowed_fields: list = Field(  # pyright: ignore[reportCallIssue]  # Django Ninja Annotated idiom
            fields, json_schema_extra={"include_in_schema": False}
        )
        _model = Model

        # def set_allowed_fields(self, fields: List):
        #    self.allowed_fields = fields

        # def validate_fields(self, fields: List | None):
        #    if fields is not None and self.allowed_fields:
        #        for field in fields:
        #            if field not in self.allowed_fields:
        #                raise HttpError(
        #                    400, f"'{field}' is not a valid field name! Possible names: {self.allowed_fields}"
        #                )

        # def get_include(self) -> List[str]:
        #    if self.include is not None:
        #        _include = [f.strip() for f in self.include.split(",") if f.strip()]
        #        self.validate_fields(_include)
        #    else:
        #        _include = self._model.get_fields_all()
        #        if self.exclude is None:
        #            self.exclude = ",".join(self._model.get_fields_exclude())
        #        if self.exclude:
        #            _exclude = [f.strip() for f in self.exclude.split(",") if f.strip()]
        #            _include = list(set(_include) - set(_exclude))
        #    return _include

        # def get_schema(self):
        #    return create_schema(self._model, fields=self.get_include())

    return Fields  # pyright: ignore[reportReturnType]  # dynamic schema class
