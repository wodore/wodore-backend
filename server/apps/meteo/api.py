"""Meteo (weather code) endpoints on dmr."""

import pydantic
from dmr import Path, Query, RedirectTo, modify
from dmr.routing import path
from pydantic import Field

from server.apps.api.controller import ApiController, cache_headers, raise_not_found
from server.apps.api.error_codes import ErrorCode
from server.apps.categories.models import Category
from server.apps.translations import LanguageQuery, override

from .models import WeatherCode, WeatherCodeSymbol, WeatherCodeSymbolCollection
from .schemas import DayTimeEnum, IncludeModeEnum

DEFAULT_COLLECTION = "weather-icons-outlined-mono"
CACHE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds


def resolve_symbol_url(request, symbol, include_mode: IncludeModeEnum):
    """Resolve symbol URL based on include mode."""
    if symbol is None:
        return None

    if include_mode == IncludeModeEnum.no:
        return None

    if include_mode == IncludeModeEnum.slug:
        return symbol.slug

    # IncludeModeEnum.all - return full URL
    if symbol.svg_file:
        return request.build_absolute_uri(symbol.svg_file.url)

    return None


def build_weather_code_dict(
    weather_code: WeatherCode,
    code_symbol: WeatherCodeSymbol | None,
    request,
    include_symbols: IncludeModeEnum,
    include_category: IncludeModeEnum,
    include_collection: IncludeModeEnum,
) -> dict:
    """Build weather code dictionary with configurable detail levels."""
    data = {
        "code": weather_code.code,
        "slug": weather_code.slug,
        "description_day": weather_code.description_day_i18n,  # noqa: WPS308  # modeltranslation
        "description_night": weather_code.description_night_i18n,  # noqa: WPS308  # modeltranslation
    }

    # Add symbols based on include mode (from WeatherCodeSymbol)
    if include_symbols != IncludeModeEnum.no and code_symbol:
        if include_symbols == IncludeModeEnum.slug:
            data["symbol_day"] = (
                code_symbol.symbol_day.slug if code_symbol.symbol_day else None
            )
            data["symbol_night"] = (
                code_symbol.symbol_night.slug if code_symbol.symbol_night else None
            )
        else:  # all
            data["symbol_day"] = resolve_symbol_url(
                request, code_symbol.symbol_day, include_symbols
            )
            data["symbol_night"] = resolve_symbol_url(
                request, code_symbol.symbol_night, include_symbols
            )

    # Add category based on include mode
    if include_category != IncludeModeEnum.no and weather_code.category:
        if include_category == IncludeModeEnum.slug:
            data["category"] = weather_code.category.slug
            # Add parent category if exists
            if weather_code.category.parent:
                data["category"] = (
                    f"{weather_code.category.parent.slug}.{weather_code.category.slug}"
                )
        else:  # all
            category_data = {
                "slug": weather_code.category.slug,
                "name": weather_code.category.name_i18n,
            }
            # Add parent slug if exists
            if weather_code.category.parent:
                category_data["parent"] = weather_code.category.parent.slug
                category_data["slug"] = (
                    f"{weather_code.category.parent.slug}.{weather_code.category.slug}"
                )

            # Add symbol URLs
            if weather_code.category.symbol_detailed:
                category_data["symbol_detailed"] = request.build_absolute_uri(
                    weather_code.category.symbol_detailed.svg_file.url
                )
            if weather_code.category.symbol_simple:
                category_data["symbol_simple"] = request.build_absolute_uri(
                    weather_code.category.symbol_simple.svg_file.url
                )
            if weather_code.category.symbol_mono:
                category_data["symbol_mono"] = request.build_absolute_uri(
                    weather_code.category.symbol_mono.svg_file.url
                )

            data["category"] = category_data

    # Add collection based on include mode
    if include_collection != IncludeModeEnum.no and code_symbol:
        if include_collection == IncludeModeEnum.slug:
            data["collection"] = code_symbol.collection.slug
        else:  # all
            data["collection"] = {
                "slug": code_symbol.collection.slug,
                "organization": code_symbol.collection.source_org.slug,
            }

    return data


_INCLUDE_SYMBOLS_HELP = (
    "Include symbols: 'no' excludes, 'slug' returns slugs only, 'all' returns full URLs"
)
_INCLUDE_CATEGORY_HELP = (
    "Include category: 'no' excludes, 'slug' returns slug, "
    "'all' returns full details with symbols"
)
_INCLUDE_COLLECTION_HELP = (
    "Include collection: 'no' excludes, 'slug' returns slug, 'all' returns full details"
)


class WeatherCodesQuery(LanguageQuery):
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
    include_symbols: IncludeModeEnum = Field(  # type: ignore[assignment]
        IncludeModeEnum.slug,
        description=_INCLUDE_SYMBOLS_HELP,
    )
    include_category: IncludeModeEnum = Field(  # type: ignore[assignment]
        IncludeModeEnum.no,
        description=_INCLUDE_CATEGORY_HELP,
    )
    include_collection: IncludeModeEnum = Field(  # type: ignore[assignment]
        IncludeModeEnum.slug,
        description=_INCLUDE_COLLECTION_HELP,
    )


class WeatherCodeQuery(LanguageQuery):
    """Query parameters for the single weather-code endpoint."""

    collection: str = Field(
        DEFAULT_COLLECTION,
        description="Symbol collection slug (default: weather-icons-outlined-mono)",
    )
    include_symbols: IncludeModeEnum = Field(  # type: ignore[assignment]
        IncludeModeEnum.slug,
        description=_INCLUDE_SYMBOLS_HELP,
    )
    include_category: IncludeModeEnum = Field(  # type: ignore[assignment]
        IncludeModeEnum.no,
        description=_INCLUDE_CATEGORY_HELP,
    )
    include_collection: IncludeModeEnum = Field(  # type: ignore[assignment]
        IncludeModeEnum.slug,
        description=_INCLUDE_COLLECTION_HELP,
    )


class WeatherCodePath(pydantic.BaseModel):
    """WMO weather code path parameter."""

    code: int = Field(description="WMO weather code")


class WeatherCodesController(ApiController):
    """All weather codes, keyed by WMO code."""

    @modify(
        operation_id="get_weather_codes",
        headers=cache_headers(CACHE_MAX_AGE),
    )
    def get(self, parsed_query: Query[WeatherCodesQuery]) -> dict[int, dict]:
        """List weather codes.

        Dict keyed by WMO code. Returns weather codes with symbols from the specified collection.
        If a WMO code is missing from the collection, an error is raised.
        """
        request = self.request
        query = parsed_query
        with override(query.lang):
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
                        from http import HTTPStatus

                        from dmr import APIError

                        raise APIError(
                            {
                                "code": ErrorCode.validation_error,
                                "detail": f"Category slug '{query.category}' is not "
                                f"unique. Use one of: {', '.join(paths)}",
                            },
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    raise_not_found(f"Category '{query.category}' not found")
                qs = qs.filter(category=category_obj)

            select_related_fields = []
            if query.include_category != IncludeModeEnum.no:
                select_related_fields.append("category")
                if query.include_category == IncludeModeEnum.all:
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
                query.include_symbols != IncludeModeEnum.no
                or query.include_collection != IncludeModeEnum.no
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

                # Note: If a forecast code (0-3, 45-99) is missing from the
                # collection, we still return the weather code data but
                # without symbols (incomplete collections stay usable).

                result[weather_code.code] = build_weather_code_dict(
                    weather_code=weather_code,
                    code_symbol=code_symbol,
                    request=request,
                    include_symbols=query.include_symbols,
                    include_category=query.include_category,
                    include_collection=query.include_collection,
                )

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
        """Get a specific weather code by WMO code."""
        request = self.request
        query = parsed_query
        with override(query.lang):
            collection_obj = WeatherCodeSymbolCollection.objects.filter(
                slug=query.collection
            ).first()
            if collection_obj is None:
                raise_not_found(f"Collection '{query.collection}' not found")

            weather_code = WeatherCode.objects.filter(code=parsed_path.code).first()
            if weather_code is None:
                raise_not_found(f"Weather code {parsed_path.code} not found")

            # Optimize with select_related
            if query.include_category != IncludeModeEnum.no:
                weather_code = (
                    WeatherCode.objects.filter(code=parsed_path.code)
                    .select_related(
                        "category",
                        "category__parent"
                        if query.include_category == IncludeModeEnum.all
                        else None,
                    )
                    .first()
                )

            # Get symbol for this collection
            code_symbol = None
            if (
                query.include_symbols != IncludeModeEnum.no
                or query.include_collection != IncludeModeEnum.no
            ):
                code_symbol = (
                    WeatherCodeSymbol.objects.filter(
                        collection=collection_obj, weather_code=weather_code
                    )
                    .select_related(
                        "symbol_day",
                        "symbol_night",
                        "collection",
                        "collection__source_org",
                    )
                    .first()
                )

                if code_symbol is None:
                    raise_not_found(
                        f"Weather code {parsed_path.code} not found in "
                        f"collection '{query.collection}'",
                    )

            return build_weather_code_dict(
                weather_code=weather_code,
                code_symbol=code_symbol,
                request=request,
                include_symbols=query.include_symbols,
                include_category=query.include_category,
                include_collection=query.include_collection,
            )


class WeatherSvgPath(pydantic.BaseModel):
    """Path parameters for the weather SVG redirect."""

    collection: str = Field(description="Symbol collection slug")
    time: DayTimeEnum = Field(description="Day or night variant")
    code: int = Field(description="WMO weather code")


class WeatherSvgController(ApiController):
    """Redirect to the SVG icon for a weather code."""

    @modify(
        operation_id="get_weather_code_svg",
        headers=cache_headers(CACHE_MAX_AGE),
    )
    def get(self, parsed_path: Path[WeatherSvgPath]) -> None:
        """Redirect to a weather code SVG.

        From a specific collection. Collection examples: weather-icons-outlined-mono, weather-icons-filled, meteoswiss-filled
        Time options: day, night

        If the collection doesn't have a symbol for the WMO code, returns 404.
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

        from http import HTTPStatus

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
