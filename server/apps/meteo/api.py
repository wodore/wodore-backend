"""Meteo (weather code) endpoints on dmr (sparse fieldsets).

Response narrowing via ``fields[weather_codes]=...``, ``fields[symbols]=...``,
``fields[categories]=...``, ``fields[collections]=...`` (JSON:API sparse
fieldsets, harmonized with the other search endpoints). The old
``include_symbols/category/collection=no|slug|all`` tri-state params are
removed. Shape change: slug shorthand values are now objects.
"""

from http import HTTPStatus

import pydantic
from dmr import APIError, Path, Query, RedirectTo, modify
from dmr.routing import path
from pydantic import Field

from django.http import HttpRequest

from server.apps.api.controller import ApiController, cache_headers, raise_not_found
from server.apps.api.projection import field_selected
from server.apps.api.query import sparse_fields_query
from server.apps.categories.models import Category
from server.apps.translations import LanguageQuery

from .models import WeatherCode, WeatherCodeSymbol, WeatherCodeSymbolCollection
from .response import WeatherCodeValue
from .schemas import DayTimeEnum

DEFAULT_COLLECTION = "weather-icons-outlined-mono"
CACHE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds

# ---------------------------------------------------------------------------
# Shared types for sparse fieldsets documentation
# ---------------------------------------------------------------------------


class _SymbolDTOSchema(type("_SymbolDTOSchema", (), {})):
    """Documentation shape for symbol fields (slug + url)."""


class _CategoryDTOSchema(type("_CategoryDTOSchema", (), {})):
    """Documentation shape for category fields."""


class _CollectionDTOSchema(type("_CollectionDTOSchema", (), {})):
    """Documentation shape for collection fields."""


# Use lightweight pydantic models just for the fields documentation
from pydantic import BaseModel


class SymbolDTO(BaseModel):
    """Symbol fields available via fields[symbols]."""

    slug: str
    url: str | None = None


class CategoryDTO(BaseModel):
    """Category fields available via fields[categories]."""

    slug: str
    name: str | None = None
    parent: str | None = None
    symbol_detailed: str | None = None
    symbol_simple: str | None = None
    symbol_mono: str | None = None


class CollectionDTO(BaseModel):
    """Collection fields available via fields[collections]."""

    slug: str
    organization: str | None = None


MeteoFields = sparse_fields_query(
    weather_codes=BaseModel,  # top-level fields: code, slug, descriptions, symbols, category, collection
    symbols=SymbolDTO,
    categories=CategoryDTO,
    collections=CollectionDTO,
)

# Field map: TYPE name → field name(s) on the weather code dict
METEO_FIELD_MAP = {
    "symbols": None,  # maps to symbol_day + symbol_night (special)
    "categories": "category",
    "collections": "collection",
}


# ---------------------------------------------------------------------------
# Full-shape result builder
# ---------------------------------------------------------------------------


def _symbol_obj(request: HttpRequest, symbol) -> dict | None:
    """Build the full symbol object (slug + absolute URL)."""
    if symbol is None:
        return None
    url = None
    if symbol.svg_file:
        url = request.build_absolute_uri(symbol.svg_file.url)
    return {"slug": symbol.slug, "url": url}


def _category_obj(request: HttpRequest, category: Category) -> dict | None:
    """Build the full category object."""
    if category is None:
        return None
    data: dict = {
        "slug": category.slug,
        "name": category.name_i18n,  # noqa: WPS308  # modeltranslation
    }
    if category.parent:
        data["parent"] = category.parent.slug
        data["slug"] = f"{category.parent.slug}.{category.slug}"
    if category.symbol_detailed:
        data["symbol_detailed"] = request.build_absolute_uri(
            category.symbol_detailed.svg_file.url
        )
    if category.symbol_simple:
        data["symbol_simple"] = request.build_absolute_uri(
            category.symbol_simple.svg_file.url
        )
    if category.symbol_mono:
        data["symbol_mono"] = request.build_absolute_uri(
            category.symbol_mono.svg_file.url
        )
    return data


def _collection_obj(code_symbol: WeatherCodeSymbol) -> dict | None:
    """Build the full collection object."""
    if code_symbol is None:
        return None
    return {
        "slug": code_symbol.collection.slug,
        "organization": code_symbol.collection.source_org.slug,
    }


def build_weather_code_full(
    weather_code: WeatherCode,
    code_symbol: WeatherCodeSymbol | None,
    request: HttpRequest,
) -> dict:
    """Build the full weather code dict (all fields, objects not slugs)."""
    data: dict = {
        "code": weather_code.code,
        "slug": weather_code.slug,
        "description_day": weather_code.description_day_i18n,  # noqa: WPS308
        "description_night": weather_code.description_night_i18n,  # noqa: WPS308
    }
    if code_symbol is not None:
        data["symbol_day"] = _symbol_obj(request, code_symbol.symbol_day)
        data["symbol_night"] = _symbol_obj(request, code_symbol.symbol_night)
        data["collection"] = _collection_obj(code_symbol)
    if weather_code.category:
        data["category"] = _category_obj(request, weather_code.category)
    return data


def project_meteo_fields(data: dict, parsed_query, request: HttpRequest) -> dict:
    """Apply fields[TYPE] projection to a weather code dict.

    Symbols are special: symbol_day/symbol_night are separate fields
    that share the same TYPE.
    """
    fields_map = parsed_query.fields or {}
    if not fields_map:
        return data

    result = dict(data)

    # Top-level selection
    top_spec = fields_map.get("weather_codes")
    if top_spec is not None and top_spec != "__all__":
        names = {n.strip() for n in top_spec.split(",") if n.strip()}
        result = {k: v for k, v in result.items() if k in names}

    # Nested types
    for type_name, spec in fields_map.items():
        if type_name == "weather_codes":
            continue

        if spec == "__all__":
            continue

        if isinstance(spec, str):
            selected = {n.strip() for n in spec.split(",") if n.strip()}

        if type_name == "symbols":
            # Narrow symbol_day and symbol_night (both share the TYPE)
            for field in ("symbol_day", "symbol_night"):
                if field in result and isinstance(result[field], dict):
                    result[field] = {
                        k: v for k, v in result[field].items() if k in selected
                    }
        elif type_name == "categories":
            if "category" in result and isinstance(result["category"], dict):
                result["category"] = {
                    k: v for k, v in result["category"].items() if k in selected
                }
        elif type_name == "collections":
            if "collection" in result and isinstance(result["collection"], dict):
                result["collection"] = {
                    k: v for k, v in result["collection"].items() if k in selected
                }

    return result


# ---------------------------------------------------------------------------
# Query models
# ---------------------------------------------------------------------------


class WeatherCodesQuery(LanguageQuery, MeteoFields):
    """Query parameters for the weather-codes list endpoint."""

    collection: str = Field(
        DEFAULT_COLLECTION,
        description="Symbol collection slug (default: weather-icons-outlined-mono)",
    )
    category: str | None = Field(
        None,
        description=(
            "Filter by category slug (supports dot notation like 'meteo.rain')"
        ),
    )


class WeatherCodeQuery(LanguageQuery, MeteoFields):
    """Query parameters for the single weather-code endpoint."""

    collection: str = Field(
        DEFAULT_COLLECTION,
        description="Symbol collection slug (default: weather-icons-outlined-mono)",
    )


class WeatherCodePath(pydantic.BaseModel):
    """WMO weather code path parameter."""

    code: int = Field(description="WMO weather code")


class WeatherSvgPath(pydantic.BaseModel):
    """Path parameters for the weather SVG redirect."""

    collection: str = Field(description="Symbol collection slug")
    time: DayTimeEnum = Field(description="Day or night variant")
    code: int = Field(description="WMO weather code")


# ---------------------------------------------------------------------------
# Controllers
# ---------------------------------------------------------------------------


class WeatherCodesController(ApiController):
    """All weather codes, keyed by WMO code."""

    @modify(
        operation_id="get_weather_codes",
        headers=cache_headers(CACHE_MAX_AGE),
    )
    def get(
        self, parsed_query: Query[WeatherCodesQuery]
    ) -> dict[int, WeatherCodeValue]:
        """List weather codes.

        Dict keyed by WMO code, with symbols from the specified collection.
        """
        request = self.request
        query = parsed_query

        collection_obj = WeatherCodeSymbolCollection.objects.filter(
            slug=query.collection
        ).first()
        if collection_obj is None:
            raise_not_found(f"Collection '{query.collection}' not found")

        qs = WeatherCode.objects.all()

        if query.category:
            category_obj, paths = Category.objects.find_by_slug(
                query.category, is_active=True
            )
            if category_obj is None:
                if paths:
                    raise APIError(
                        {
                            "code": "validation_error",
                            "detail": f"Category slug '{query.category}' is not "
                            f"unique. Use one of: {', '.join(paths)}",
                        },
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                raise_not_found(f"Category '{query.category}' not found")
            qs = qs.filter(category=category_obj)

        select_related_fields = []
        if field_selected(query, "weather_codes", "category"):
            select_related_fields.append("category")
            if query.fields and "categories" in (query.fields or {}):
                select_related_fields.extend(
                    [
                        "category__parent",
                        "category__symbol_detailed",
                        "category__symbol_simple",
                        "category__symbol_mono",
                    ]
                )

        if select_related_fields:
            qs = qs.select_related(*select_related_fields)

        weather_codes = qs.order_by("code")

        code_symbols = {}
        if (
            field_selected(query, "weather_codes", "symbol_day")
            or field_selected(query, "weather_codes", "symbol_night")
            or field_selected(query, "weather_codes", "collection")
        ):
            symbol_qs = WeatherCodeSymbol.objects.filter(
                collection=collection_obj, weather_code__in=weather_codes
            ).select_related(
                "weather_code",
                "symbol_day",
                "symbol_night",
                "collection",
                "collection__source_org",
            )
            for cs in symbol_qs:
                code_symbols[cs.weather_code.code] = cs

        result = {}
        for weather_code in weather_codes:
            code_symbol = code_symbols.get(weather_code.code)
            full = build_weather_code_full(weather_code, code_symbol, request)
            result[weather_code.code] = project_meteo_fields(full, query, request)

        return result


class WeatherCodeController(ApiController):
    """A single weather code by WMO code."""

    @modify(
        operation_id="get_weather_code",
        headers=cache_headers(CACHE_MAX_AGE),
    )
    def get(
        self,
        parsed_path: Path[WeatherCodePath],
        parsed_query: Query[WeatherCodeQuery],
    ) -> dict:
        """Get a weather code.

        Dict for one WMO code, with symbols from the specified collection.
        """
        request = self.request
        query = parsed_query

        collection_obj = WeatherCodeSymbolCollection.objects.filter(
            slug=query.collection
        ).first()
        if collection_obj is None:
            raise_not_found(f"Collection '{query.collection}' not found")

        weather_code = WeatherCode.objects.filter(code=parsed_path.code).first()
        if weather_code is None:
            raise_not_found(f"Weather code {parsed_path.code} not found")

        if field_selected(query, "weather_codes", "category"):
            select = ["category"]
            if query.fields and "categories" in (query.fields or {}):
                select.extend(
                    [
                        "category__parent",
                        "category__symbol_detailed",
                        "category__symbol_simple",
                        "category__symbol_mono",
                    ]
                )
            weather_code = (
                WeatherCode.objects.filter(code=parsed_path.code)
                .select_related(*select)
                .first()
            )

        code_symbol = None
        if (
            field_selected(query, "weather_codes", "symbol_day")
            or field_selected(query, "weather_codes", "symbol_night")
            or field_selected(query, "weather_codes", "collection")
        ):
            code_symbol = (
                WeatherCodeSymbol.objects.filter(
                    collection=collection_obj, weather_code=weather_code
                )
                .select_related(
                    "symbol_day", "symbol_night", "collection", "collection__source_org"
                )
                .first()
            )
            if code_symbol is None:
                raise_not_found(
                    f"Weather code {parsed_path.code} not found in "
                    f"collection '{query.collection}'",
                )

        full = build_weather_code_full(weather_code, code_symbol, request)
        return project_meteo_fields(full, query, request)


class WeatherSvgController(ApiController):
    """Redirect to the SVG icon for a weather code."""

    @modify(
        operation_id="get_weather_code_svg",
        headers=cache_headers(CACHE_MAX_AGE),
    )
    def get(self, parsed_path: Path[WeatherSvgPath]) -> None:
        """Redirect to a weather code SVG.

        From a specific collection. If the collection doesn't have a symbol
        for the WMO code, returns 404.
        """
        path_params = parsed_path
        collection_obj = WeatherCodeSymbolCollection.objects.filter(
            slug=path_params.collection
        ).first()
        if collection_obj is None:
            raise_not_found(f"Collection '{path_params.collection}' not found")

        weather_code = WeatherCode.objects.filter(code=path_params.code).first()
        if weather_code is None:
            raise_not_found(f"Weather code {path_params.code} not found")

        code_symbol = (
            WeatherCodeSymbol.objects.filter(
                collection=collection_obj, weather_code=weather_code
            )
            .select_related("symbol_day", "symbol_night")
            .first()
        )

        if code_symbol is None:
            raise_not_found(
                f"Weather code {path_params.code} not found in "
                f"collection '{path_params.collection}'",
            )

        symbol = (
            code_symbol.symbol_day
            if path_params.time == DayTimeEnum.day
            else code_symbol.symbol_night
        )

        if symbol is None:
            raise_not_found(
                f"No {path_params.time} symbol found for weather code "
                f"{path_params.code} in {path_params.collection!r}",
            )

        if not symbol.svg_file:
            raise_not_found(f"SVG file not found for symbol {symbol.slug}")

        raise RedirectTo(
            symbol.svg_file.url,
            status_code=HTTPStatus.FOUND,
        )


paths = [
    path("weather_codes", WeatherCodesController.as_view(), name="get_weather_codes"),
    path(
        "weather_codes/<int:code>",
        WeatherCodeController.as_view(),
        name="get_weather_code",
    ),
    path(
        "symbol/<str:collection>/<str:time>/<int:code>.svg",
        WeatherSvgController.as_view(),
        name="get_weather_code_svg",
    ),
]
