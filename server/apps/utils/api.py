from datetime import datetime
from os import environ
from typing import List

from ninja import Field, Query, Router, Schema
from ninja.errors import HttpError
from ninja.orm import create_schema

from server.settings.components.common import BUILD_TIMESTAMP, GIT_HASH


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
    hash: str = Field(..., description="Git commit hash", example="abc123e")
    version: str = Field(..., description="Sematic version", example="1.2.0")
    timestamp: datetime = Field(
        ...,
        description="Build timestamp",
    )
    environment: str = Field(
        ...,
        description="Current environment (development, production)",
        example="production",
    )


@router.get("/version", response=VersionSchema, tags=["utils"])
def get_version(request):
    """Get version information including git hash, package version, build timestamp, and environment."""
    return {
        "hash": GIT_HASH,
        "version": PACKAGE_VERSION,
        "timestamp": datetime.fromisoformat(BUILD_TIMESTAMP),
        "environment": DJANGO_ENV,
    }


# @abc
class FieldsSchema(Schema):
    include: str | None = Query(
        None, description="Comma separated list, allowed value:"
    )  # {', '.join(fields)}")
    exclude: str | None = Query(
        None, description="Comma separated list, only used if 'include' is not set."
    )
    # ",".join(exclude_default), description="Comma separated list, only used if 'include' is not set."
    # )
    allowed_fields: List = Field(None, include_in_schema=False)
    _model = None

    def set_allowed_fields(self, fields: List):
        self.allowed_fields = fields

    def validate_fields(self, fields: List | None):
        if fields is not None and self.allowed_fields:
            for field in fields:
                if field not in self.allowed_fields:
                    raise HttpError(
                        400,
                        f"'{field}' is not a valid field name! Possible names: {self.allowed_fields}",
                    )

    def get_include(self) -> List[str]:
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
        return create_schema(self._model, fields=self.get_include())


def fields_query(Model) -> FieldsSchema:  # fields:List, exclude_default=[]):
    fields = Model.get_fields_all()[:]
    exclude_default = Model.get_fields_exclude()[:]

    """Returns a query which can be used to include and exclude fields"""

    class Fields(FieldsSchema):
        include: str | None = Query(
            None,
            description=f"Comma separated list, allowed value: {', '.join(fields)}",
        )
        exclude: str | None = Query(
            ",".join(exclude_default),
            description="Comma separated list, only used if 'include' is not set.",
        )
        allowed_fields: List = Field(fields, include_in_schema=False)
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

    return Fields
