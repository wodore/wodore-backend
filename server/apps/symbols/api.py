from ninja import Query, Router
from django.http import HttpRequest
from django.shortcuts import get_object_or_404

from server.apps.api.query import FieldsParam
from server.apps.translations import LanguageParam, override, with_language_param

from .models import Symbol
from .schema import SymbolOptional

router = Router()


@router.get(
    "/",
    response=list[SymbolOptional],
    exclude_unset=True,
    operation_id="get_symbols",
)
@with_language_param("lang")
def get_symbols(
    request: HttpRequest,
    lang: LanguageParam,
    fields: Query[FieldsParam[SymbolOptional]],
    is_active: bool = Query(
        True, description="Filter by active status (default: True)"
    ),
) -> list[SymbolOptional]:
    """Get a list of all symbols. By default only returns active symbols."""
    fields.update_default(include=["slug", "style", "svg_file", "is_active"])

    symbols = Symbol.objects.filter(is_active=is_active)
    symbols = symbols.select_related("license", "source_org", "uploaded_by_user")

    with override(lang):
        return fields.validate(list(symbols))


@router.get(
    "/by-id/{id}",
    response=SymbolOptional,
    exclude_unset=True,
    operation_id="get_symbol_by_id",
)
@with_language_param()
def get_symbol_by_id(
    request: HttpRequest,
    id: str,
    lang: LanguageParam,
    fields: Query[FieldsParam[SymbolOptional]],
    is_active: bool = Query(
        True, description="Filter by active status (default: True)"
    ),
) -> SymbolOptional:
    """Get a single symbol by UUID."""
    fields.update_default("__all__")
    with override(lang):
        return fields.validate(get_object_or_404(Symbol, id=id, is_active=is_active))


@router.get(
    "/slug/{slug}",
    response=list[SymbolOptional],
    exclude_unset=True,
    operation_id="get_symbols_by_slug",
)
@with_language_param("lang")
def get_symbols_by_slug(
    request: HttpRequest,
    slug: str,
    lang: LanguageParam,
    fields: Query[FieldsParam[SymbolOptional]],
    style: str | None = Query(
        None, description="Filter by style (detailed, simple, mono)"
    ),
    is_active: bool = Query(
        True, description="Filter by active status (default: True)"
    ),
) -> list[SymbolOptional]:
    """Get all style variants for a symbol by slug. By default only returns active symbols."""
    fields.update_default(include=["slug", "style", "svg_file", "is_active"])

    symbols = Symbol.objects.filter(slug=slug, is_active=is_active)

    if style:
        symbols = symbols.filter(style=style)

    symbols = symbols.select_related("license", "source_org", "uploaded_by_user")

    with override(lang):
        return fields.validate(list(symbols))


@router.get(
    "/{style_slug}/{slug}",
    response=SymbolOptional,
    exclude_unset=True,
    operation_id="get_symbol_by_style_and_slug",
)
@with_language_param()
def get_symbol_by_style_and_slug(
    request: HttpRequest,
    style_slug: str,
    slug: str,
    lang: LanguageParam,
    fields: Query[FieldsParam[SymbolOptional]],
    is_active: bool = Query(
        True, description="Filter by active status (default: True)"
    ),
) -> SymbolOptional:
    """Get a single symbol by style and slug. Returns the same schema as by-id endpoint."""
    fields.update_default("__all__")
    with override(lang):
        return fields.validate(
            get_object_or_404(Symbol, slug=slug, style=style_slug, is_active=is_active)
        )


# TODO: Add POST/PUT/DELETE endpoints if needed in the future
# @router.post("/", response=SymbolOptional)
# def create_symbol(request, payload: SymbolCreate):
#     """Create a new symbol."""
#     pass


# TODO: Add SymbolTag endpoints if tags are implemented in the future
# @router.get("/tags/", response=list[SymbolTagSchema])
# def get_tags(request):
#     """Get all symbol tags."""
#     pass
