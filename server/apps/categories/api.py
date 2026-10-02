"""Category endpoints on dmr (tree/list/map + symbol SVG redirects)."""

from http import HTTPStatus
from typing import Any

import pydantic
from dmr import APIError, Path, Query, RedirectTo, modify
from dmr.routing import external_path, path
from pydantic import Field

from django.http import HttpRequest, HttpResponse

from server.apps.api.controller import ApiController, cache_headers, raise_not_found
from server.apps.translations import LanguageQuery, override

from .models import Category
from .schemas import (
    CategoryListItemSchema,
    CategoryMapSchema,
    CategoryTreeSchema,
    MediaUrlModeEnum,
    SymbolVariantEnum,
)

CACHE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds


def resolve_media_url(
    request: HttpRequest, symbol, mode: MediaUrlModeEnum
) -> str | None:
    """Resolve media URL based on mode."""
    if not symbol or mode == MediaUrlModeEnum.no:
        return None

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
        "name": category.name_i18n,  # noqa: WPS308  # modeltranslation
        "description": category.description_i18n or "",  # noqa: WPS308
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

    if max_level is not None and current_level >= max_level:
        # At max level, don't include children
        result = build_category_dict(category, request, media_mode, base_level)
        result["children"] = category.has_children()
        return result

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
        data["children"] = category.has_children()
        result.append(data)

    if max_level is not None and current_level >= max_level:
        return result

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

    if max_level is not None and current_level >= max_level:
        result = build_category_dict(category, request, media_mode, base_level)
        result["children"] = {}
        result["children_count"] = 0
        return result

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


def _resolve_parent_or_raise(parent_slug: str, is_active: bool) -> Category:
    """Resolve a (possibly dot-notation) parent slug or raise 400/404."""
    category, paths = Category.objects.find_by_slug(parent_slug, is_active)

    if category is None:
        if paths:
            raise APIError(
                {
                    "code": "ambiguous_category",
                    "detail": f"Slug '{parent_slug}' is not unique. "
                    f"Use one of: {', '.join(paths)}",
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )
        raise_not_found(f"Category '{parent_slug}' not found")
    return category  # type: ignore[return-value]


class _CategoryQuery(LanguageQuery):
    """Shared query parameters of the category endpoints."""

    level: int | None = Field(
        None,
        description="Maximum depth level relative to request slug",
    )
    is_active: bool = Field(True, description="Only include active categories")
    media_mode: MediaUrlModeEnum = Field(  # type: ignore[assignment]
        MediaUrlModeEnum.absolute,
        description=(
            "How to return media URLs: 'no' (exclude), 'relative' "
            "(relative paths), 'absolute' (full URLs)"
        ),
    )


class _CategoryTreeQuery(_CategoryQuery):
    """Tree endpoint: children become booleans at the last level."""

    level: int | None = Field(
        None,
        description=(
            "Maximum depth level relative to request slug, for the last "
            "level children are set to a boolean"
        ),
    )


class _ParentSlugPath(pydantic.BaseModel):
    """Parent slug (path converter: dotted/slash notation or ``root``)."""

    parent_slug: str = Field(description="Parent slug, dotted path or 'root'")


class CategoryTreeController(ApiController):
    """Category hierarchy as a tree structure."""

    @modify(operation_id="get_category_tree")
    def get(
        self,
        parsed_path: Path[_ParentSlugPath],
        parsed_query: Query[_CategoryTreeQuery],
    ) -> list[CategoryTreeSchema]:
        """Get the category tree.

        Supports dot or slash-notation slugs with max one parent
        (e.g., `map/transport`). The parent is optional but if slug is
        ambiguous, returns 400 error with available paths. Use `root` to
        return all root categories. Always excludes the root from results
        (returns children).
        """
        request = self.request
        query = parsed_query
        with override(query.lang):
            if parsed_path.parent_slug != "root":
                category = _resolve_parent_or_raise(
                    parsed_path.parent_slug, query.is_active
                )
                children_qs = category.children.all()
                if query.is_active:
                    children_qs = children_qs.filter(is_active=True)

                base_level = category.get_level()

                return [
                    get_descendants_tree(
                        child,
                        request,
                        query.level,
                        query.is_active,
                        query.media_mode,
                        base_level + 1,
                    )
                    for child in children_qs.order_by("order", "slug")
                ]

            qs = Category.objects.select_related(
                "symbol_detailed",
                "symbol_simple",
                "symbol_mono",
            ).prefetch_related("children")
            if query.is_active:
                qs = qs.active()

            roots = qs.roots().order_by("order", "slug")
            return [
                get_descendants_tree(
                    root, request, query.level, query.is_active, query.media_mode, 0
                )
                for root in roots
            ]


class CategoryListController(ApiController):
    """Flat list of categories."""

    @modify(operation_id="get_category_list_all")
    def get(
        self,
        parsed_path: Path[_ParentSlugPath],
        parsed_query: Query[_CategoryQuery],
    ) -> list[CategoryListItemSchema]:
        """List categories.

        Returns a flat list. Supports dot-notation slugs with max one parent
        (e.g., 'accommodation.hut'). If slug is ambiguous, returns 400
        error with available paths. If slug is omitted, returns all
        categories. Always excludes the root from results (returns
        children).
        """
        request = self.request
        query = parsed_query
        with override(query.lang):
            if parsed_path.parent_slug != "root":
                category = _resolve_parent_or_raise(
                    parsed_path.parent_slug, query.is_active
                )
                base_level = category.get_level()
                return get_descendants_flat(
                    category,
                    request,
                    query.level,
                    query.is_active,
                    query.media_mode,
                    base_level,
                    include_self=False,
                )

            qs = Category.objects.all()
            if query.is_active:
                qs = qs.active()

            categories = qs.order_by("order", "slug")

            result = []
            for cat in categories:
                if query.level is None or cat.get_level() <= query.level:
                    data = build_category_dict(cat, request, query.media_mode, 0)
                    data["children"] = cat.has_children()
                    result.append(data)

            return result


class CategoryMapController(ApiController):
    """Category hierarchy as a nested dictionary mapping."""

    @modify(operation_id="get_category_map_all")
    def get(
        self,
        parsed_path: Path[_ParentSlugPath],
        parsed_query: Query[_CategoryQuery],
    ) -> dict[str, CategoryMapSchema]:
        """Get the category map.

        Nested dict keyed by slug; keys are category slugs, values contain category data with
        nested 'children' dict. Supports dot-notation slugs with max one
        parent (e.g., 'accommodation.hut'). If slug is ambiguous, returns
        400 error with available paths. Always excludes the root from
        results (returns children).
        """
        request = self.request
        query = parsed_query
        with override(query.lang):
            if parsed_path.parent_slug != "root":
                category = _resolve_parent_or_raise(
                    parsed_path.parent_slug, query.is_active
                )
                children_qs = category.children.all()
                if query.is_active:
                    children_qs = children_qs.filter(is_active=True)

                base_level = category.get_level()
                result = {}
                for child in children_qs.order_by("order", "slug"):
                    result[child.slug] = get_descendants_map(
                        child,
                        request,
                        query.level,
                        query.is_active,
                        query.media_mode,
                        base_level + 1,
                    )
                return result

            qs = Category.objects.select_related(
                "symbol_detailed",
                "symbol_simple",
                "symbol_mono",
            ).prefetch_related("children")
            if query.is_active:
                qs = qs.active()

            roots = qs.roots().order_by("order", "slug")
            result = {}
            for root in roots:
                result[root.slug] = get_descendants_map(
                    root, request, query.level, query.is_active, query.media_mode, 0
                )
            return result


class _SymbolSvgPath(pydantic.BaseModel):
    """Path parameters for the category symbol redirect."""

    variant: SymbolVariantEnum
    slug: str


class _SymbolSvgParentPath(_SymbolSvgPath):
    """Variant + parent + slug (dotted category under an explicit parent)."""

    parent: str


def _category_symbol_redirect(
    variant: SymbolVariantEnum,
    slug: str,
):
    """Resolve the symbol URL for a category or raise 400/404."""
    category, paths = Category.objects.find_by_slug(slug, is_active=True)

    if category is None:
        if paths:
            raise APIError(
                {
                    "code": "ambiguous_category",
                    "detail": f"Slug '{slug}' is not unique. "
                    f"Use one of: {', '.join(paths)}",
                },
                status_code=HTTPStatus.BAD_REQUEST,
            )
        raise_not_found(f"Category '{slug}' not found")

    if variant == SymbolVariantEnum.detailed:
        symbol = category.symbol_detailed
    elif variant == SymbolVariantEnum.simple:
        symbol = category.symbol_simple
    else:  # mono
        symbol = category.symbol_mono

    if symbol is None:
        raise_not_found(f"No {variant} symbol found for category {slug!r}")

    if not symbol.svg_file:
        raise_not_found(f"SVG file not found for symbol {symbol.slug}")

    return symbol.svg_file.url


class CategorySymbolSvgParentController(ApiController):
    """Redirect to the SVG icon for a category with explicit parent."""

    @modify(
        operation_id="get_category_symbol_svg_with_parent",
        headers=cache_headers(CACHE_MAX_AGE),
    )
    def get(self, parsed_path: Path[_SymbolSvgParentPath]) -> None:
        """Redirect to a category SVG (with parent).

        Variant options: detailed, simple, mono
        Example: /v1/categories/symbol/detailed/map/transport.svg

        If the category doesn't have a symbol for the variant, returns 404.
        """
        full_slug = f"{parsed_path.parent}.{parsed_path.slug}"
        url = _category_symbol_redirect(parsed_path.variant, full_slug)
        raise RedirectTo(url, status_code=HTTPStatus.FOUND)


class CategorySymbolSvgController(ApiController):
    """Redirect to the SVG icon for a category."""

    @modify(
        operation_id="get_category_symbol_svg",
        headers=cache_headers(CACHE_MAX_AGE),
    )
    def get(self, parsed_path: Path[_SymbolSvgPath]) -> None:
        """Redirect to the SVG icon for a category.

        Variant options: detailed, simple, mono
        Slug can be a simple slug (e.g., 'transport') or root category

        If the category doesn't have a symbol for the variant, returns 404.
        """
        url = _category_symbol_redirect(parsed_path.variant, parsed_path.slug)
        raise RedirectTo(url, status_code=HTTPStatus.FOUND)


def get_categories_markdown(request: HttpRequest) -> HttpResponse:
    """The category tree as a compact Markdown index for LLM agents.

    Categories are the entry vocabulary of the map (hut types, amenities,
    overlays ...): agents use this to translate user terms ("bivouac",
    "winter room") into API slugs before searching. Localized via the
    same lang parameter as the JSON API (category names are modeltrans).
    """
    from http import HTTPStatus

    from server.apps.translations.schema import LANGUAGE_CODES

    lang = request.GET.get("lang", "de")
    if lang not in LANGUAGE_CODES:
        # Plain view (external_path): no dmr error handling - answer
        # the same 422 JSON the typed endpoints would produce.
        import json

        return HttpResponse(
            json.dumps(
                {"code": "validation_error", "detail": f"Unknown language {lang!r}."}
            ),
            content_type="application/json",
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    with override(lang):
        return _categories_markdown(request)


def _categories_markdown(request: HttpRequest) -> HttpResponse:
    """Markdown index; localized names via the active language."""
    lines = [
        "# Wodore categories",
        "",
        (
            "Hierarchy by indentation; the slug is what the API expects"
            " (e.g. `/v1/huts/huts?search=` or category filters)."
        ),
        "",
    ]
    categories = (
        Category.objects.filter(is_active=True)
        .select_related("parent")
        .order_by("parent__slug", "order", "slug")
    )
    for category in categories:
        indent = "  " if category.parent_id else ""
        lines.append(f"- {indent}{category.name} `{category.slug}`")
    lines += [
        "",
        "---",
        "",
        (
            "Data: [Wodore](https://wodore.com) · JSON tree:"
            " /v1/categories/tree/{parent_slug}"
        ),
    ]
    response = HttpResponse(
        "\n".join(lines) + "\n", content_type="text/markdown; charset=utf-8"
    )
    response["Cache-Control"] = "public, max-age=3600"
    return response


paths: list[Any] = [
    external_path(
        "index.md",
        get_categories_markdown,
        openapi=None,
        name="get_categories_markdown",
    ),
    path(
        "tree/<path:parent_slug>",
        CategoryTreeController.as_view(),
        name="get_category_tree",
    ),
    path(
        "list/<path:parent_slug>",
        CategoryListController.as_view(),
        name="get_category_list_all",
    ),
    path(
        "map/<path:parent_slug>",
        CategoryMapController.as_view(),
        name="get_category_map_all",
    ),
    path(
        "symbol/<str:variant>/<str:parent>/<str:slug>.svg",
        CategorySymbolSvgParentController.as_view(),
        name="get_category_symbol_svg_with_parent",
    ),
    path(
        "symbol/<str:variant>/<str:slug>.svg",
        CategorySymbolSvgController.as_view(),
        name="get_category_symbol_svg",
    ),
]
