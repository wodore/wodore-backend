from typing import Any, Literal

from ninja import Query, Router
from ninja.decorators import decorate_view
from ninja.errors import HttpError

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.cache import cache_control

from server.apps.translations import LanguageParam, override, with_language_param

from .models import Category
from .schemas import (
    CategoryListItemSchema,
    CategoryMapSchema,
    CategoryTreeSchema,
    MediaUrlModeEnum,
    SymbolVariantEnum,
)

router = Router()
CACHE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds


def resolve_media_url(
    request: HttpRequest, symbol, mode: MediaUrlModeEnum
) -> str | None:
    """Resolve media URL based on mode."""
    if not symbol or mode == MediaUrlModeEnum.no:
        return None

    # Symbol is a ForeignKey to the Symbol model
    # Get the svg_file from the symbol
    if hasattr(symbol, "svg_file") and symbol.svg_file:
        if mode == MediaUrlModeEnum.relative:
            # Return relative path from media root
            return symbol.svg_file.url
        # absolute
        return request.build_absolute_uri(symbol.svg_file.url)

    return None


def build_category_dict(
    category: Category,
    request: HttpRequest,
    media_mode: MediaUrlModeEnum,
    base_level: int = 0,
) -> dict:
    """Build category dict with common fields."""
    data = {
        "slug": category.slug,
        "name": category.name_i18n,
        "description": category.description_i18n or "",
        "order": category.order,
        "level": category.get_level() - base_level,  # Relative to base
        "parent": category.parent.slug if category.parent else None,
        "identifier": category.get_identifier(),
        "color": category.color,
    }

    if media_mode != MediaUrlModeEnum.no:
        data["symbol_detailed"] = resolve_media_url(
            request, category.symbol_detailed, media_mode
        )
        data["symbol_simple"] = resolve_media_url(
            request, category.symbol_simple, media_mode
        )
        data["symbol_mono"] = resolve_media_url(
            request, category.symbol_mono, media_mode
        )

    return data


def get_descendants_tree(
    category: Category,
    request: HttpRequest,
    max_level: int | None,
    is_active: bool,
    media_mode: MediaUrlModeEnum,
    base_level: int,
) -> dict:
    """Recursively build tree with level limit."""
    current_level = category.get_level() - base_level

    # Check if we should include children
    if max_level is not None and current_level >= max_level:
        # At max level, don't include children
        result = build_category_dict(category, request, media_mode, base_level)
        result["children"] = category.has_children()
        return result

    # Get children
    children_qs = category.children.all()
    if is_active:
        children_qs = children_qs.filter(is_active=True)

    tree_children = [
        get_descendants_tree(
            child, request, max_level, is_active, media_mode, base_level
        )
        for child in children_qs.order_by("order", "slug")
    ]

    result = build_category_dict(category, request, media_mode, base_level)
    result["children"] = tree_children if tree_children else False
    return result


def get_descendants_flat(
    category: Category,
    request: HttpRequest,
    max_level: int | None,
    is_active: bool,
    media_mode: MediaUrlModeEnum,
    base_level: int,
    include_self: bool = False,
) -> list[dict]:
    """Get flat list of descendants."""
    result = []
    current_level = category.get_level() - base_level

    if include_self:
        data = build_category_dict(category, request, media_mode, base_level)
        # Add children boolean
        data["children"] = category.has_children()
        result.append(data)

    # Check level limit
    if max_level is not None and current_level >= max_level:
        return result

    # Get children
    children_qs = category.children.all()
    if is_active:
        children_qs = children_qs.filter(is_active=True)

    for child in children_qs.order_by("order", "slug"):
        result.extend(
            get_descendants_flat(
                child,
                request,
                max_level,
                is_active,
                media_mode,
                base_level,
                include_self=True,
            )
        )

    return result


def get_descendants_map(
    category: Category,
    request: HttpRequest,
    max_level: int | None,
    is_active: bool,
    media_mode: MediaUrlModeEnum,
    base_level: int,
) -> dict:
    """Recursively build map with slug keys."""
    current_level = category.get_level() - base_level

    # Check if we should include children
    if max_level is not None and current_level >= max_level:
        # At max level, don't include children
        result = build_category_dict(category, request, media_mode, base_level)
        result["children"] = {}
        result["children_count"] = 0
        return result

    # Get children
    children_qs = category.children.all()
    if is_active:
        children_qs = children_qs.filter(is_active=True)

    children_map = {}
    for child in children_qs.order_by("order", "slug"):
        children_map[child.slug] = get_descendants_map(
            child, request, max_level, is_active, media_mode, base_level
        )

    result = build_category_dict(category, request, media_mode, base_level)
    result["children"] = children_map
    result["children_count"] = len(children_map)
    return result


@router.get(
    "/tree/{path:parent_slug}",
    response=list[CategoryTreeSchema],
    exclude_unset=True,
    operation_id="get_category_tree",
)
@with_language_param("lang")
def get_category_tree(
    request: HttpRequest,
    lang: LanguageParam,
    parent_slug: str | Literal["root"],
    level: int | None = Query(
        None,
        description="Maximum depth level relative to request slug, for the last level children are set to a boolean",
    ),
    is_active: bool = Query(True, description="Only include active categories"),
    media_mode: MediaUrlModeEnum = Query(
        MediaUrlModeEnum.absolute,
        description="How to return media URLs: 'no' (exclude), 'relative' (relative paths), 'absolute' (full URLs)",
    ),
) -> Any:
    """
    Get category hierarchy as a tree structure.

    Supports dot or slash-notation slugs with max one parent (e.g., `map/transport`).
    The parent is optional but if slug is ambiguous, returns 400 error with available paths.
    Use `root` to return all root categories.
    Always excludes the root from results (returns children).
    """
    with override(lang):
        if parent_slug != "root":
            # Resolve slug (handles dot notation and ambiguity)
            category, paths = Category.objects.find_by_slug(parent_slug, is_active)

            if category is None:
                if paths:
                    # Ambiguous slug
                    raise HttpError(
                        400,
                        f"Slug '{parent_slug}' is not unique. Use one of: {', '.join(paths)}",
                    )
                else:
                    # Not found
                    raise HttpError(404, f"Category '{parent_slug}' not found") or False
            # Return only children of found category
            children_qs = category.children.all()
            if is_active:
                children_qs = children_qs.filter(is_active=True)

            # Base level is the found category's level
            base_level = category.get_level()

            return [
                get_descendants_tree(
                    child, request, level, is_active, media_mode, base_level + 1
                )
                for child in children_qs.order_by("order", "slug")
            ]
        else:
            # No slug - return all roots
            qs = Category.objects.prefetch_related("children")
            if is_active:
                qs = qs.active()

            roots = qs.roots().order_by("order", "slug")
            return [
                get_descendants_tree(root, request, level, is_active, media_mode, 0)
                for root in roots
            ]


@router.get(
    "/list/{path:parent_slug}",
    response=list[CategoryListItemSchema],
    exclude_unset=True,
    operation_id="get_category_list_all",
)
@with_language_param("lang")
def get_category_list(
    request: HttpRequest,
    lang: LanguageParam,
    parent_slug: str | Literal["root"],
    level: int | None = Query(
        None, description="Maximum depth level relative to request slug"
    ),
    is_active: bool = Query(True, description="Only include active categories"),
    media_mode: MediaUrlModeEnum = Query(
        MediaUrlModeEnum.absolute,
        description="How to return media URLs: 'no' (exclude), 'relative' (relative paths), 'absolute' (full URLs)",
    ),
) -> Any:
    """
    Get flat list of categories.

    Supports dot-notation slugs with max one parent (e.g., 'accommodation.hut').
    If slug is ambiguous, returns 400 error with available paths.
    If slug is omitted, returns all categories.
    Always excludes the root from results (returns children).
    """
    with override(lang):
        if parent_slug != "root":
            # Resolve slug
            category, paths = Category.objects.find_by_slug(parent_slug, is_active)

            if category is None:
                if paths:
                    raise HttpError(
                        400,
                        f"Slug '{parent_slug}' is not unique. Use one of: {', '.join(paths)}",
                    )
                else:
                    raise HttpError(404, f"Category '{parent_slug}' not found")

            # Get flat list of descendants (exclude root)
            base_level = category.get_level()
            return get_descendants_flat(
                category,
                request,
                level,
                is_active,
                media_mode,
                base_level,
                include_self=False,
            )
        else:
            # No slug - return all categories as flat list
            qs = Category.objects.all()
            if is_active:
                qs = qs.active()

            # Get all categories
            categories = qs.order_by("order", "slug")

            result = []
            for cat in categories:
                if level is None or cat.get_level() <= level:
                    data = build_category_dict(cat, request, media_mode, 0)
                    data["children"] = cat.has_children()
                    result.append(data)

            return result


@router.get(
    "/map/{path:parent_slug}",
    response=dict[str, CategoryMapSchema],
    exclude_unset=True,
    operation_id="get_category_map_all",
)
@with_language_param("lang")
def get_category_map(
    request: HttpRequest,
    lang: LanguageParam,
    parent_slug: str | Literal["root"],
    level: int | None = Query(
        None, description="Maximum depth level relative to request slug"
    ),
    is_active: bool = Query(True, description="Only include active categories"),
    media_mode: MediaUrlModeEnum = Query(
        MediaUrlModeEnum.absolute,
        description="How to return media URLs: 'no' (exclude), 'relative' (relative paths), 'absolute' (full URLs)",
    ),
) -> Any:
    """
    Get category hierarchy as a nested dictionary mapping.

    Keys are category slugs, values contain category data with nested 'children' dict.

    Supports dot-notation slugs with max one parent (e.g., 'accommodation.hut').
    If slug is ambiguous, returns 400 error with available paths.
    If slug is omitted, returns all root categories as a map.
    Always excludes the root from results (returns children).
    """
    with override(lang):
        if parent_slug != "root":
            # Resolve slug
            category, paths = Category.objects.find_by_slug(parent_slug, is_active)

            if category is None:
                if paths:
                    raise HttpError(
                        400,
                        f"Slug '{parent_slug}' is not unique. Use one of: {', '.join(paths)}",
                    )
                else:
                    raise HttpError(404, f"Category '{parent_slug}' not found")

            # Return only children as map (exclude root)
            children_qs = category.children.all()
            if is_active:
                children_qs = children_qs.filter(is_active=True)

            base_level = category.get_level()
            result = {}
            for child in children_qs.order_by("order", "slug"):
                result[child.slug] = get_descendants_map(
                    child, request, level, is_active, media_mode, base_level + 1
                )
            return result
        else:
            # No slug - return all roots as map
            qs = Category.objects.prefetch_related("children")
            if is_active:
                qs = qs.active()

            roots = qs.roots().order_by("order", "slug")
            result = {}
            for root in roots:
                result[root.slug] = get_descendants_map(
                    root, request, level, is_active, media_mode, 0
                )
            return result


def _get_category_symbol_redirect(
    variant: SymbolVariantEnum,
    slug: str,
) -> HttpResponseRedirect:
    """Helper function to get category symbol redirect."""
    # Resolve slug (handles dot notation and ambiguity)
    category, paths = Category.objects.find_by_slug(slug, is_active=True)

    if category is None:
        if paths:
            # Ambiguous slug
            raise HttpError(
                400,
                f"Slug '{slug}' is not unique. Use one of: {', '.join(paths)}",
            )
        else:
            # Not found
            raise HttpError(404, f"Category '{slug}' not found")

    # Get the symbol based on variant
    if variant == SymbolVariantEnum.detailed:
        symbol = category.symbol_detailed
    elif variant == SymbolVariantEnum.simple:
        symbol = category.symbol_simple
    else:  # mono
        symbol = category.symbol_mono

    if symbol is None:
        raise HttpError(404, f"No {variant} symbol found for category '{slug}'")

    if not symbol.svg_file:
        raise HttpError(404, f"SVG file not found for symbol {symbol.slug}")

    return HttpResponseRedirect(symbol.svg_file.url)


@router.get(
    "symbol/{variant}/{parent}/{slug}.svg",
    operation_id="get_category_symbol_svg_with_parent",
)
@decorate_view(cache_control(max_age=CACHE_MAX_AGE))
def get_category_symbol_svg_with_parent(
    request: HttpRequest,
    response: HttpResponse,
    variant: SymbolVariantEnum,
    parent: str,
    slug: str,
) -> HttpResponseRedirect:
    """
    Redirect to the SVG icon for a category with explicit parent.

    Variant options: detailed, simple, mono
    Example: /v1/categories/symbol/detailed/map/transport.svg

    If the category doesn't have a symbol for the variant, returns 404.
    """
    full_slug = f"{parent}.{slug}"
    return _get_category_symbol_redirect(variant, full_slug)


@router.get(
    "symbol/{variant}/{slug}.svg",
    operation_id="get_category_symbol_svg",
)
@decorate_view(cache_control(max_age=CACHE_MAX_AGE))
def get_category_symbol_svg(
    request: HttpRequest,
    response: HttpResponse,
    variant: SymbolVariantEnum,
    slug: str,
) -> HttpResponseRedirect:
    """
    Redirect to the SVG icon for a category.

    Variant options: detailed, simple, mono
    Slug can be a simple slug (e.g., 'transport') or root category

    If the category doesn't have a symbol for the variant, returns 404.
    """
    return _get_category_symbol_redirect(variant, slug)
