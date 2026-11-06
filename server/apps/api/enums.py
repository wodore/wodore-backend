"""Shared API enums (single definitions, imported across apps)."""

from enum import Enum


class IncludeModeEnum(str, Enum):
    """Include mode for nested objects - controls level of detail.

    Used by search/nearby/detail endpoints for categories, sources,
    symbols, collections: ``no`` excludes the field, ``slug`` returns
    slugs only, ``all`` returns the full nested object.
    """

    no = "no"
    slug = "slug"
    all = "all"
