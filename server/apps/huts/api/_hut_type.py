from ninja import Query

from django.conf import settings
from django.http import HttpRequest

from server.apps.api.query import FieldsParam
from server.apps.translations import (
    LanguageParam,
    override,
    with_language_param,
)

from ..models import HutType
from ..schemas import HutTypeDetailSchema
from ._router import router


def _get_hut_types(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    lang: LanguageParam,
    fields: Query[FieldsParam[HutTypeDetailSchema]],
) -> list[HutTypeDetailSchema]:
    qs = HutType.objects.all().order_by("level", "slug")
    fields.update_default(HutType.FIELDS)
    media_url = request.build_absolute_uri(settings.MEDIA_URL)
    with override(lang):
        hts = fields.validate(list(qs))
        for h in hts:
            for repl in ["icon", "symbol", "symbol_simple"]:
                if hasattr(h, repl):
                    setattr(h, repl, getattr(h, repl).replace("/media/", media_url))
        return hts


@router.get(
    "types/list",
    response=list[HutTypeDetailSchema],
    exclude_unset=True,
    operation_id="get_hut_types",
)
@with_language_param("lang")
def get_hut_types(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    lang: LanguageParam,
    fields: Query[FieldsParam[HutTypeDetailSchema]],
) -> list[HutTypeDetailSchema]:
    return _get_hut_types(request=request, lang=lang, fields=fields)


@router.get(
    "types/records",
    response=dict[str, HutTypeDetailSchema],
    exclude_unset=True,
    operation_id="get_hut_type_records",
)
@with_language_param("lang")
def get_hut_type_records(  # type: ignore  # noqa: PGH003
    request: HttpRequest,
    lang: LanguageParam,
    fields: Query[FieldsParam[HutTypeDetailSchema]],
) -> dict[str, HutTypeDetailSchema]:
    hts = _get_hut_types(request, lang, fields)
    return {ht.slug: ht for ht in hts}
