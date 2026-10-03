"""Symbol endpoints on dmr."""

from http import HTTPStatus

import pydantic
from dmr import Path, Query, RedirectTo, ResponseSpec, modify
from dmr.headers import HeaderSpec
from dmr.routing import path
from pydantic import Field

from server.apps.api.controller import ApiController, raise_not_found
from server.apps.api.query import dump_sparse, dump_sparse_list, sparse_fields_query
from server.apps.translations import activate
from server.apps.translations.schema import LanguageQuery

from .models import Symbol
from .schema import SymbolOptional

SymbolFields = sparse_fields_query(symbols=SymbolOptional)

CACHE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds


class SymbolQuery(LanguageQuery, SymbolFields):
    """Query parameters shared by the symbol list endpoints."""

    is_active: bool = Field(True, description="Filter by active status (default: True)")


class SymbolBySlugQuery(SymbolQuery):
    """List-by-slug additionally filters by style."""

    style: str | None = Field(
        None, description="Filter by style (detailed, simple, mono)"
    )


class SymbolIdPath(pydantic.BaseModel):
    """Symbol UUID path parameter."""

    id: str = Field(description="Symbol UUID")


class SymbolSlugPath(pydantic.BaseModel):
    """Symbol slug path parameter."""

    slug: str = Field(description="Symbol slug")


class SymbolStylePath(pydantic.BaseModel):
    """Symbol style + slug path parameters."""

    style_slug: str = Field(description="Symbol style (detailed, simple, mono)")
    slug: str = Field(description="Symbol slug")


class SymbolsController(ApiController):
    """All symbols, by default only active ones."""

    @modify(operation_id="get_symbols")
    def get(
        self,
        parsed_query: Query[SymbolQuery],
    ) -> list[dict]:
        """List symbols.

        By default only returns active symbols."""
        symbols = Symbol.objects.filter(is_active=parsed_query.is_active)
        symbols = symbols.select_related("license", "source_org", "uploaded_by_user")
        activate(parsed_query.lang)
        return dump_sparse_list(
            SymbolOptional,
            list(symbols),
            parsed_query,
            "symbols",
            default_include=["slug", "style", "svg_file", "is_active"],
        )


class SymbolByIdController(ApiController):
    """A single symbol by UUID."""

    @modify(operation_id="get_symbol_by_id")
    def get(
        self,
        parsed_path: Path[SymbolIdPath],
        parsed_query: Query[SymbolQuery],
    ) -> dict:
        """Get a single symbol by UUID."""
        symbol = Symbol.objects.filter(
            id=parsed_path.id, is_active=parsed_query.is_active
        ).first()
        if symbol is None:
            raise_not_found("Symbol not found.")
        activate(parsed_query.lang)
        return dump_sparse(
            SymbolOptional,
            symbol,
            parsed_query,
            "symbols",
            default_include="__all__",
        )


class SymbolsBySlugController(ApiController):
    """All style variants for a symbol slug."""

    @modify(operation_id="get_symbols_by_slug")
    def get(
        self,
        parsed_path: Path[SymbolSlugPath],
        parsed_query: Query[SymbolBySlugQuery],
    ) -> list[dict]:
        """Get all style variants for a symbol by slug.

        By default only returns active symbols.
        """
        symbols = Symbol.objects.filter(
            slug=parsed_path.slug, is_active=parsed_query.is_active
        )
        if parsed_query.style:
            symbols = symbols.filter(style=parsed_query.style)
        symbols = symbols.select_related("license", "source_org", "uploaded_by_user")
        activate(parsed_query.lang)
        return dump_sparse_list(
            SymbolOptional,
            list(symbols),
            parsed_query,
            "symbols",
            default_include=["slug", "style", "svg_file", "is_active"],
        )


_REDIRECT_SPEC = ResponseSpec(
    None,
    status_code=HTTPStatus.FOUND,
    headers={"Location": HeaderSpec()},
)

_CACHE_SPEC = ResponseSpec(
    None,
    status_code=HTTPStatus.FOUND,
    headers={
        "Location": HeaderSpec(),
        "Cache-Control": HeaderSpec(),
    },
)


class SymbolSvgController(ApiController):
    """Redirect to a symbol's SVG file by style and slug."""

    @modify(operation_id="get_symbol_svg", extra_responses=[_CACHE_SPEC])
    def get(self, parsed_path: Path[SymbolStylePath]) -> None:
        """Redirect to a symbol SVG.

        By style and slug. Style options: detailed, simple, mono
        Example: /v1/symbols/detailed/mountain.svg

        If the symbol doesn't exist or has no SVG file, returns 404.
        """
        symbol = Symbol.objects.filter(
            slug=parsed_path.slug,
            style=parsed_path.style_slug,
            is_active=True,
        ).first()
        if symbol is None:
            raise_not_found(
                f"Symbol '{parsed_path.slug}' with style "
                f"'{parsed_path.style_slug}' not found"
            )
        if not symbol.svg_file:
            raise_not_found(f"SVG file not found for symbol {symbol.slug}")
        raise RedirectTo(
            symbol.svg_file.url,
            status_code=HTTPStatus.FOUND,
            headers={"Cache-Control": f"max-age={CACHE_MAX_AGE}"},
        )


class SymbolByStyleController(ApiController):
    """A single symbol by style and slug."""

    @modify(operation_id="get_symbol_by_style_and_slug")
    def get(
        self,
        parsed_path: Path[SymbolStylePath],
        parsed_query: Query[SymbolQuery],
    ) -> dict:
        """Get a single symbol by style and slug.

        Returns the same schema as the by-id endpoint.
        """
        symbol = Symbol.objects.filter(
            slug=parsed_path.slug,
            style=parsed_path.style_slug,
            is_active=parsed_query.is_active,
        ).first()
        if symbol is None:
            raise_not_found("Symbol not found.")
        activate(parsed_query.lang)
        return dump_sparse(
            SymbolOptional,
            symbol,
            parsed_query,
            "symbols",
            default_include="__all__",
        )


paths = [
    path("", SymbolsController.as_view(), name="get_symbols"),
    path(
        "by-id/<str:id>",
        SymbolByIdController.as_view(),
        name="get_symbol_by_id",
    ),
    path(
        "slug/<str:slug>",
        SymbolsBySlugController.as_view(),
        name="get_symbols_by_slug",
    ),
    # <style>/<slug>.svg must register BEFORE <style>/<slug>
    path(
        "<str:style_slug>/<str:slug>.svg",
        SymbolSvgController.as_view(),
        name="get_symbol_svg",
    ),
    path(
        "<str:style_slug>/<str:slug>",
        SymbolByStyleController.as_view(),
        name="get_symbol_by_style_and_slug",
    ),
]
