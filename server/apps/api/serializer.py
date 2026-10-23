"""Project serializer: ninja wire compatibility on dmr.

``PydanticFastSerializer`` with ``exclude_unset=True`` reproduces the
response contract of the former django-ninja setup, where routers were
declared with ``exclude_unset=True``: response models only emit the
fields that were actually set during validation — optional fields the
handler never touched are absent from the JSON, not ``null``.
``exclude_unset`` only affects pydantic models; plain dicts and lists
(the GeoJSON endpoints) pass through unchanged.
"""

from typing import ClassVar

from dmr.plugins.pydantic import PydanticFastSerializer
from dmr.plugins.pydantic.serializer import ToJsonKwargs


class WodoreSerializer(PydanticFastSerializer):
    """JSON-only fast serializer with ``exclude_unset`` dump semantics."""

    __slots__ = ()

    to_json_kwargs: ClassVar[ToJsonKwargs] = {
        "by_alias": True,
        "exclude_unset": True,
    }
