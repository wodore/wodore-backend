from typing import Any

import msgspec
from ninja.renderers import BaseRenderer
from pydantic import BaseModel


def encoder_hook(obj: Any) -> Any:
    """See ninja.responses.NinjaJSONEncoder."""
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    # Raise a NotImplementedError for other types
    raise NotImplementedError(f"Objects of type {type(obj)} are not supported")


class MsgSpecRenderer(BaseRenderer):
    "msgspec json encoder"
    media_type = "application/json"

    def render(self, request, data, *, response_status):
        return msgspec.json.encode(data, enc_hook=encoder_hook)
