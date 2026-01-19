from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.cache import cache_control
from ninja import Query, Router
from ninja.decorators import decorate_view
from ninja.errors import HttpError

from server.apps.translations import LanguageParam, override, with_language_param
from server.apps.categories.models import Category

from .models import WeatherCode, WeatherCodeSymbol, WeatherCodeSymbolCollection
from .schemas import IncludeModeEnum, DayTimeEnum

router = Router()

DEFAULT_COLLECTION = "weather-icons-outlined-mono"
CACHE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds
# CACHE_MAX_AGE = 60  # 60 secs for dev


def resolve_symbol_url(
    request: HttpRequest, symbol, include_mode: IncludeModeEnum
) -> Any:
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
    request: HttpRequest,
    include_symbols: IncludeModeEnum,
    include_category: IncludeModeEnum,
    include_collection: IncludeModeEnum,
) -> dict:
    """Build weather code dictionary with configurable detail levels."""
    data = {
        "code": weather_code.code,
        "slug": weather_code.slug,
        "description_day": weather_code.description_day_i18n,
        "description_night": weather_code.description_night_i18n,
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


@router.get(
    "weather_codes",
    response=dict[int, dict],
    exclude_unset=True,
    operation_id="get_weather_codes",
)
@decorate_view(cache_control(max_age=CACHE_MAX_AGE))
@with_language_param("lang")
def get_weather_codes(
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    collection: str = Query(
        DEFAULT_COLLECTION,
        description="Symbol collection slug (default: weather-icons-outlined-mono)",
    ),
    category: str | None = Query(
        None,
        description="Filter by category slug (supports dot notation like 'meteo.rain')",
    ),
    include_symbols: IncludeModeEnum = Query(
        IncludeModeEnum.slug,
        description="Include symbols: 'no' excludes, 'slug' returns slugs only, 'all' returns full URLs",
    ),
    include_category: IncludeModeEnum = Query(
        IncludeModeEnum.no,
        description="Include category: 'no' excludes, 'slug' returns slug, 'all' returns full details with symbols",
    ),
    include_collection: IncludeModeEnum = Query(
        IncludeModeEnum.slug,
        description="Include collection: 'no' excludes, 'slug' returns slug, 'all' returns full details",
    ),
) -> dict[int, dict]:
    """
    Get all weather codes as a dictionary with WMO code as key.

    Returns weather codes with symbols from the specified collection.
    If a WMO code is missing from the collection, an error is raised.
    """
    with override(lang):
        # Verify collection exists
        collection_obj = WeatherCodeSymbolCollection.objects.filter(
            slug=collection
        ).first()
        if collection_obj is None:
            raise HttpError(404, f"Collection '{collection}' not found")

        # Get base weather codes
        qs = WeatherCode.objects.all()

        # Filter by category if provided
        if category:
            category_obj, paths = Category.objects.find_by_slug(
                category, is_active=True
            )
            if category_obj is None:
                if paths:
                    raise HttpError(
                        400,
                        f"Category slug '{category}' is not unique. Use one of: {', '.join(paths)}",
                    )
                else:
                    raise HttpError(404, f"Category '{category}' not found")
            qs = qs.filter(category=category_obj)

        # Optimize with select_related/prefetch_related
        select_related_fields = []
        if include_category != IncludeModeEnum.no:
            select_related_fields.append("category")
            if include_category == IncludeModeEnum.all:
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

        # Get weather codes
        weather_codes = qs.order_by("code")

        # Get symbols for this collection
        code_symbols = {}
        if (
            include_symbols != IncludeModeEnum.no
            or include_collection != IncludeModeEnum.no
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

        # Build result
        result = {}
        for weather_code in weather_codes:
            code_symbol = code_symbols.get(weather_code.code)

            # Note: If a forecast code (0-3, 45-99) is missing from the collection,
            # we still return the weather code data but without symbols.
            # This allows the API to work even if collection data is incomplete.

            result[weather_code.code] = build_weather_code_dict(
                weather_code=weather_code,
                code_symbol=code_symbol,
                request=request,
                include_symbols=include_symbols,
                include_category=include_category,
                include_collection=include_collection,
            )

        return result


@router.get(
    "weather_codes/{code}",
    response=dict,
    exclude_unset=True,
    operation_id="get_weather_code",
)
@decorate_view(cache_control(max_age=CACHE_MAX_AGE))
@with_language_param("lang")
def get_weather_code(
    request: HttpRequest,
    response: HttpResponse,
    code: int,
    lang: LanguageParam,
    collection: str = Query(
        DEFAULT_COLLECTION,
        description="Symbol collection slug (default: weather-icons-outlined-mono)",
    ),
    include_symbols: IncludeModeEnum = Query(
        IncludeModeEnum.slug,
        description="Include symbols: 'no' excludes, 'slug' returns slugs only, 'all' returns full URLs",
    ),
    include_category: IncludeModeEnum = Query(
        IncludeModeEnum.no,
        description="Include category: 'no' excludes, 'slug' returns slug, 'all' returns full details with symbols",
    ),
    include_collection: IncludeModeEnum = Query(
        IncludeModeEnum.slug,
        description="Include collection: 'no' excludes, 'slug' returns slug, 'all' returns full details",
    ),
) -> dict:
    """Get a specific weather code by WMO code."""
    with override(lang):
        # Verify collection exists
        collection_obj = WeatherCodeSymbolCollection.objects.filter(
            slug=collection
        ).first()
        if collection_obj is None:
            raise HttpError(404, f"Collection '{collection}' not found")

        # Get weather code
        weather_code = WeatherCode.objects.filter(code=code).first()
        if weather_code is None:
            raise HttpError(404, f"Weather code {code} not found")

        # Optimize with select_related
        if include_category != IncludeModeEnum.no:
            weather_code = (
                WeatherCode.objects.filter(code=code)
                .select_related(
                    "category",
                    "category__parent"
                    if include_category == IncludeModeEnum.all
                    else None,
                )
                .first()
            )

        # Get symbol for this collection
        code_symbol = None
        if (
            include_symbols != IncludeModeEnum.no
            or include_collection != IncludeModeEnum.no
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
                raise HttpError(
                    404,
                    f"Weather code {code} not found in collection '{collection}'",
                )

        return build_weather_code_dict(
            weather_code=weather_code,
            code_symbol=code_symbol,
            request=request,
            include_symbols=include_symbols,
            include_category=include_category,
            include_collection=include_collection,
        )


@router.get(
    "symbol/{collection}/{time}/{code}.svg",
    operation_id="get_weather_code_svg",
)
@decorate_view(cache_control(max_age=CACHE_MAX_AGE))
def get_weather_code_svg(
    request: HttpRequest,
    collection: str,
    time: DayTimeEnum,
    code: int,
) -> HttpResponseRedirect:
    """
    Redirect to the SVG icon for a weather code from a specific collection.

    Collection examples: weather-icons-outlined-mono, weather-icons-filled, meteoswiss-filled
    Time options: day, night

    If the collection doesn't have a symbol for the WMO code, returns 404.
    """

    # Get the collection
    collection_obj = WeatherCodeSymbolCollection.objects.filter(slug=collection).first()
    if collection_obj is None:
        raise HttpError(404, f"Collection '{collection}' not found")

    # Get the weather code
    weather_code = WeatherCode.objects.filter(code=code).first()
    if weather_code is None:
        raise HttpError(404, f"Weather code {code} not found")

    # Get the symbol for this code in this collection
    code_symbol = (
        WeatherCodeSymbol.objects.filter(
            collection=collection_obj, weather_code=weather_code
        )
        .select_related("symbol_day", "symbol_night")
        .first()
    )

    if code_symbol is None:
        raise HttpError(
            404, f"Weather code {code} not found in collection '{collection}'"
        )

    # Determine which symbol to use (day or night)
    symbol = (
        code_symbol.symbol_day if time == DayTimeEnum.day else code_symbol.symbol_night
    )

    if symbol is None:
        raise HttpError(
            404, f"No {time} symbol found for weather code {code} in '{collection}'"
        )

    if not symbol.svg_file:
        raise HttpError(404, f"SVG file not found for symbol {symbol.slug}")

    return HttpResponseRedirect(symbol.svg_file.url)
