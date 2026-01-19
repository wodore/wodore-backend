from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.cache import cache_control
from ninja import Query, Router
from ninja.decorators import decorate_view
from ninja.errors import HttpError

from server.apps.translations import LanguageParam, override, with_language_param
from server.apps.categories.models import Category

from .models import WeatherCode
from .schemas import IncludeModeEnum, SymbolStyleEnum, DayTimeEnum

router = Router()

DEFAULT_ORG_SLUG = "weather-icons"
# CACHE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds
CACHE_MAX_AGE = 60  # 60 secs for dev


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
    code: WeatherCode,
    request: HttpRequest,
    include_symbols: IncludeModeEnum,
    include_category: IncludeModeEnum,
    include_organization: IncludeModeEnum,
) -> dict:
    """Build weather code dictionary with configurable detail levels."""
    data = {
        "code": code.code,
        "slug": code.slug,
        "priority": code.priority,
        "description_day": code.description_day_i18n,
        "description_night": code.description_night_i18n,
    }

    # Add symbols based on include mode
    if include_symbols != IncludeModeEnum.no:
        if include_symbols == IncludeModeEnum.slug:
            data["symbol_day"] = code.symbol_day.slug if code.symbol_day else None
            data["symbol_night"] = code.symbol_night.slug if code.symbol_night else None
        else:  # all
            data["symbol_day"] = resolve_symbol_url(
                request, code.symbol_day, include_symbols
            )
            data["symbol_night"] = resolve_symbol_url(
                request, code.symbol_night, include_symbols
            )

    # Add category based on include mode
    if include_category != IncludeModeEnum.no and code.category:
        if include_category == IncludeModeEnum.slug:
            data["category"] = code.category.slug
            # Add parent category if exists
            if code.category.parent:
                data["category"] = f"{code.category.parent.slug}.{code.category.slug}"
        else:  # all
            category_data = {
                "slug": code.category.slug,
                "name": code.category.name_i18n,
            }
            # Add parent slug if exists
            if code.category.parent:
                category_data["parent"] = code.category.parent.slug
                category_data["slug"] = (
                    f"{code.category.parent.slug}.{code.category.slug}"
                )

            # Add symbol URLs
            if code.category.symbol_detailed:
                category_data["symbol_detailed"] = request.build_absolute_uri(
                    code.category.symbol_detailed.svg_file.url
                )
            if code.category.symbol_simple:
                category_data["symbol_simple"] = request.build_absolute_uri(
                    code.category.symbol_simple.svg_file.url
                )
            if code.category.symbol_mono:
                category_data["symbol_mono"] = request.build_absolute_uri(
                    code.category.symbol_mono.svg_file.url
                )

            data["category"] = category_data

    # Add organization based on include mode
    if include_organization != IncludeModeEnum.no:
        if include_organization == IncludeModeEnum.slug:
            data["organization"] = code.source_organization.slug
        else:  # all
            data["organization"] = {
                "slug": code.source_organization.slug,
                "name": code.source_organization.name_i18n,
                "fullname": code.source_organization.fullname_i18n,
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
    org: str = Query(
        DEFAULT_ORG_SLUG,
        description="Organization slug (default: weather-icons)",
    ),
    category: str | None = Query(
        None,
        description="Filter by category slug (supports dot notation like 'accommodation.hut')",
    ),
    include_symbols: IncludeModeEnum = Query(
        IncludeModeEnum.slug,
        description="Include symbols: 'no' excludes, 'slug' returns slugs only, 'all' returns full URLs",
    ),
    include_category: IncludeModeEnum = Query(
        IncludeModeEnum.no,
        description="Include category: 'no' excludes, 'slug' returns slug, 'all' returns full details with symbols",
    ),
    include_organization: IncludeModeEnum = Query(
        IncludeModeEnum.slug,
        description="Include organization: 'no' excludes, 'slug' returns slug, 'all' returns full details",
    ),
) -> dict[int, dict]:
    """
    Get all weather codes as a dictionary with WMO code as key.

    When multiple codes exist for the same WMO code, returns the one with highest priority.
    """
    with override(lang):
        # Get queryset filtered by organization
        qs = WeatherCode.objects.filter(source_organization__slug=org)

        # Filter by category if provided
        if category:
            # Support dot notation - find by slug
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

        # Optimize with select_related based on include parameters
        select_related_fields = ["source_organization"]
        if include_symbols != IncludeModeEnum.no:
            select_related_fields.extend(["symbol_day", "symbol_night"])
        if include_category != IncludeModeEnum.no:
            select_related_fields.append("category")
            if include_category == IncludeModeEnum.all:
                # Also fetch parent and category symbols
                select_related_fields.extend(
                    [
                        "category__parent",
                        "category__symbol_detailed",
                        "category__symbol_simple",
                        "category__symbol_mono",
                    ]
                )

        qs = qs.select_related(*select_related_fields)

        # Order by priority descending (highest first) and get distinct codes
        # Using distinct() to ensure only one entry per WMO code
        codes = qs.order_by("code", "-priority").distinct("code")

        # Build dictionary with WMO code as key
        result = {}
        for code in codes:
            result[code.code] = build_weather_code_dict(
                code=code,
                request=request,
                include_symbols=include_symbols,
                include_category=include_category,
                include_organization=include_organization,
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
    org: str = Query(
        DEFAULT_ORG_SLUG,
        description="Organization slug (default: weather-icons)",
    ),
    include_symbols: IncludeModeEnum = Query(
        IncludeModeEnum.slug,
        description="Include symbols: 'no' excludes, 'slug' returns slugs only, 'all' returns full URLs",
    ),
    include_category: IncludeModeEnum = Query(
        IncludeModeEnum.no,
        description="Include category: 'no' excludes, 'slug' returns slug, 'all' returns full details with symbols",
    ),
    include_organization: IncludeModeEnum = Query(
        IncludeModeEnum.slug,
        description="Include organization: 'no' excludes, 'slug' returns slug, 'all' returns full details",
    ),
) -> dict:
    """Get a specific weather code by WMO code."""
    with override(lang):
        # Get queryset filtered by organization and code
        qs = WeatherCode.objects.filter(
            source_organization__slug=org,
            code=code,
        )

        # Optimize with select_related based on include parameters
        select_related_fields = ["source_organization"]
        if include_symbols != IncludeModeEnum.no:
            select_related_fields.extend(["symbol_day", "symbol_night"])
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

        qs = qs.select_related(*select_related_fields)

        # Get highest priority code
        weather_code = qs.order_by("-priority").first()

        if weather_code is None:
            raise HttpError(
                404, f"Weather code {code} not found for organization '{org}'"
            )

        return build_weather_code_dict(
            code=weather_code,
            request=request,
            include_symbols=include_symbols,
            include_category=include_category,
            include_organization=include_organization,
        )


@router.get(
    "symbol/{style}/{time}/{code}.svg",
    operation_id="get_weather_code_svg",
)
@decorate_view(cache_control(max_age=CACHE_MAX_AGE))
def get_weather_code_svg(
    request: HttpRequest,
    style: SymbolStyleEnum,
    time: DayTimeEnum,
    code: int,
    org: str = Query(
        DEFAULT_ORG_SLUG,
        description="Organization slug (default: weather-icons)",
    ),
) -> HttpResponseRedirect:
    """
    Redirect to the SVG icon for a weather code.

    Style options: detailed, simple, mono
    Time options: day, night

    Fallback chain: requested style → simple → detailed → 404
    """

    # Get the weather code
    qs = WeatherCode.objects.filter(
        source_organization__slug=org,
        code=code,
    ).select_related("symbol_day", "symbol_night")

    weather_code = qs.order_by("-priority").first()

    if weather_code is None:
        raise HttpError(404, f"Weather code {code} not found for organization '{org}'")

    # Determine which symbol to use (day or night)
    symbol = (
        weather_code.symbol_day
        if time == DayTimeEnum.day
        else weather_code.symbol_night
    )

    if symbol is None:
        raise HttpError(404, f"No symbol found for weather code {code} ({time})")

    # Fallback chain: requested style → simple → detailed → 404
    fallback_styles = [style]
    if style != SymbolStyleEnum.simple:
        fallback_styles.append(SymbolStyleEnum.simple)
    if style != SymbolStyleEnum.detailed:
        fallback_styles.append(SymbolStyleEnum.detailed)

    # Try to find a symbol with one of the styles
    target_symbol = None
    for fallback_style in fallback_styles:
        # Look for symbol with the style
        target_symbol = (
            WeatherCode.objects.filter(
                source_organization__slug=org,
                code=code,
            )
            .select_related("symbol_day" if time == DayTimeEnum.day else "symbol_night")
            .order_by("-priority")
            .first()
        )

        if target_symbol:
            symbol_to_check = (
                target_symbol.symbol_day
                if time == DayTimeEnum.day
                else target_symbol.symbol_night
            )
            if symbol_to_check and symbol_to_check.style == fallback_style:
                # Found matching style
                return HttpResponseRedirect(symbol_to_check.svg_file.url)

    # If no style match found, use the original symbol
    if symbol.svg_file:
        return HttpResponseRedirect(symbol.svg_file.url)

    # No SVG file found
    raise HttpError(
        404,
        f"SVG icon not found for weather code {code} (style: {style}, time: {time})",
    )
