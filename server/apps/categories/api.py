from typing import Any

from ninja import Query, Router

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from server.apps.api.query import FieldsParam
from server.apps.translations import LanguageParam, override, with_language_param

from .models import Category
from .schemas import CategoryDetailSchema, CategorySchema, CategoryTreeSchema

router = Router()


@router.get(
    "/",
    response=list[CategorySchema],
    exclude_unset=True,
    operation_id="get_categories",
)
@with_language_param("lang")
def get_categories(
    request: HttpRequest,
    response: HttpResponse,
    lang: LanguageParam,
    fields: Query[FieldsParam[CategorySchema]],
    parent_slug: str | None = Query(
        None, description="Filter by parent slug (use 'root' for top-level categories)"
    ),
    active_only: bool = Query(True, description="Only return active categories"),
) -> Any:
    """
    Get a list of categories.

    Can be filtered by parent to navigate the hierarchy.
    """
    fields.update_default(include=["slug", "name", "order", "symbol_simple"])

    # Build query
    qs = Category.objects.all()

    if active_only:
        qs = qs.active()

    # Filter by parent
    if parent_slug == "root":
        qs = qs.roots()
    elif parent_slug:
        parent = get_object_or_404(Category, slug=parent_slug)
        qs = qs.children_of(parent)

    # Order results
    qs = qs.order_by("order", "slug")

    with override(lang):
        return fields.validate(list(qs))


@router.get(
    "/tree",
    response=list[CategoryTreeSchema],
    exclude_unset=True,
    operation_id="get_category_tree",
)
@with_language_param("lang")
def get_category_tree(
    request: HttpRequest,
    lang: LanguageParam,
    active_only: bool = Query(True, description="Only include active categories"),
) -> Any:
    """
    Get complete category hierarchy as a tree structure.

    Returns root categories with nested children.
    """
    qs = Category.objects.prefetch_related("children")

    if active_only:
        qs = qs.active()

    # Get root categories
    roots = qs.roots().order_by("order", "slug")

    def build_tree(category: Category) -> dict:
        """Recursively build tree structure."""
        children_qs = category.children.all()
        if active_only:
            children_qs = children_qs.filter(is_active=True)

        return {
            "slug": category.slug,
            "name": category.name_i18n,
            "order": category.order,
            "level": category.get_level(),
            "children": [
                build_tree(child) for child in children_qs.order_by("order", "slug")
            ],
        }

    with override(lang):
        return [build_tree(root) for root in roots]


@router.get(
    "/by-path/{path:path}",
    response=CategoryDetailSchema,
    exclude_unset=True,
    operation_id="get_category_by_path",
)
@with_language_param()
def get_category_by_path(
    request: HttpRequest,
    path: str,
    lang: LanguageParam,
    fields: Query[FieldsParam[CategoryDetailSchema]],
) -> Any:
    """
    Get a category by hierarchical path.

    Supports paths like:
    - /categories/by-path/accommodation/hut
    - /categories/by-path/accommodation/hut/selfhut

    Traverses the hierarchy from root to leaf, ensuring each slug is a child of the previous.
    """
    fields.update_default("__all__")

    # Split path into slugs
    slugs = [s for s in path.split("/") if s]

    if not slugs:
        from ninja.errors import HttpError

        raise HttpError(400, "Path cannot be empty")

    # Traverse hierarchy
    current_parent = None
    category = None

    for i, slug in enumerate(slugs):
        try:
            if current_parent is None:
                # Root level
                category = Category.objects.get(
                    slug=slug, parent__isnull=True, is_active=True
                )
            else:
                # Child level
                category = Category.objects.get(
                    slug=slug, parent=current_parent, is_active=True
                )
            current_parent = category
        except Category.DoesNotExist:
            from ninja.errors import HttpError

            path_so_far = "/".join(slugs[: i + 1])
            raise HttpError(404, f"Category '{slug}' not found in path '{path_so_far}'")

    # Prefetch children for the final category
    category = Category.objects.prefetch_related("children").get(id=category.id)

    with override(lang):
        return fields.validate(category)


@router.get(
    "/{slug}",
    response=CategoryDetailSchema,
    exclude_unset=True,
    operation_id="get_category",
)
@with_language_param()
def get_category(
    request: HttpRequest,
    slug: str,
    lang: LanguageParam,
    fields: Query[FieldsParam[CategoryDetailSchema]],
    parent_slug: str | None = Query(
        None,
        description="Parent slug to disambiguate if same slug exists at multiple levels",
    ),
) -> Any:
    """
    Get a single category by slug.

    If the same slug exists at multiple hierarchy levels, use parent_slug to specify.
    """
    fields.update_default("__all__")

    # Build query filters
    filters = {"slug": slug, "is_active": True}

    if parent_slug == "root":
        filters["parent__isnull"] = True
    elif parent_slug:
        parent = get_object_or_404(Category, slug=parent_slug)
        filters["parent"] = parent

    category = get_object_or_404(
        Category.objects.prefetch_related("children"), **filters
    )

    with override(lang):
        return fields.validate(category)
