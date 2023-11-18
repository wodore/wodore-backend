from ninja.parser import Parser

import msgspec

from typing import Any, Type, cast

from django.http import HttpRequest

from ninja.types import DictStrAny


def decoder_hook(type: Type, obj: Any) -> Any:
    # `type` here is the value of the custom type annotation being decoded.
    # if type is complex:
    #    # Convert ``obj`` (which should be a ``tuple``) to a complex
    #    real, imag = obj
    #    return complex(real, imag)
    # Raise a NotImplementedError for other types
    raise NotImplementedError(f"Objects of type {type} are not supported")


class MsgSpecParser(Parser):
    "msgspec json decoder"

    def parse_body(self, request: HttpRequest) -> DictStrAny:
        return cast(DictStrAny, msgspec.json.decode(request.body, dec_hook=decoder_hook))
