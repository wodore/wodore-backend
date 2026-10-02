"""Hut type schemas.

Note: HutType is now a helper class; these schemas validate against the
Category model. The API still references "hut_type" for backward
compatibility.
"""

import typing as t

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)

from server.apps.categories.models import Category
from server.apps.symbols.utils import resolve_symbol_urls


class HutTypeSchema(BaseModel):
    """Hut type reference (validated from Category ORM objects)."""

    model_config = ConfigDict(from_attributes=True)

    order: int | None = Field(None, validation_alias="order")
    slug: str
    color: str
    name: str | None = Field(None, validation_alias="name_i18n")
    symbol: dict[str, str | None] | None = None

    @model_validator(mode="before")
    @classmethod
    def _resolve_symbol(cls, data: t.Any, info: ValidationInfo) -> t.Any:
        """Resolve symbol URLs from the Symbol FK fields.

        Without a request in the validation context (plain
        ``model_validate`` without context) the symbols stay ``None`` —
        the same behavior the old TypeAdapter-based narrowing had.
        """
        if isinstance(data, Category):
            context = (info.context or {}) if info else {}
            request = context.get("request") if isinstance(context, dict) else None
            if request is None:
                return data
            return {
                "order": data.order,
                "slug": data.slug,
                "color": data.color,
                "name": data.name_i18n,  # noqa: WPS308  # modeltranslation
                "symbol": resolve_symbol_urls(data, {"request": request}),
            }
        return data
