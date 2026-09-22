from pathlib import Path
from typing import Any

from decouple import AutoConfig

# Build paths inside the project like this: BASE_DIR.joinpath('some')
# `pathlib` is better than writing to: dirname(dirname(dirname(__file__)))
BASE_DIR = Path(__file__).parent.parent.parent.parent

# Loading `.env` files
# See docs: https://gitlab.com/mkleehammer/autoconfig
_auto_config = AutoConfig(search_path=BASE_DIR.joinpath("config"))

_UNSET = object()


def config(key: str, default: Any = _UNSET, cast: Any = _UNSET) -> Any:
    """Typed wrapper around decouple's AutoConfig.

    decouple is untyped, which makes strict type checkers infer nonsensical
    return types (``bool | Unknown``) for every ``config(...)`` call. This
    wrapper restores a usable signature while keeping decouple's behavior:
    positional or keyword ``default``, keyword ``cast``.
    """
    kwargs: dict[str, Any] = {}
    if default is not _UNSET:
        kwargs["default"] = default
    if cast is not _UNSET:
        kwargs["cast"] = cast
    return _auto_config(key, **kwargs)
