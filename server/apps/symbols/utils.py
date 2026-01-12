"""
Utility functions for Symbol model resolvers.

This module provides centralized resolver functions that can be reused
across different API schemas to build symbol URL dictionaries.
"""

import typing as t

from django.http import HttpRequest


def resolve_symbol_urls(
    obj: t.Any,
    context: dict[str, t.Any],
    symbol_detailed_field: str = "symbol_detailed",
    symbol_simple_field: str = "symbol_simple",
    symbol_mono_field: str = "symbol_mono",
) -> dict[str, str] | None:
    """
    Resolve symbol URLs from Symbol FK fields on a model instance.

    This centralized resolver function builds a symbol URL dictionary
    containing absolute URLs for the three style variants (detailed, simple, mono).

    Args:
        obj: Model instance with Symbol FK fields (e.g., Category)
        context: Django Ninja context dict containing the request object
        symbol_detailed_field: Name of the detailed symbol FK field (default: symbol_detailed)
        symbol_simple_field: Name of the simple symbol FK field (default: symbol_simple)
        symbol_mono_field: Name of the mono symbol FK field (default: symbol_mono)

    Returns:
        Dictionary with keys 'detailed', 'simple', 'mono' mapping to absolute SVG URLs,
        or None if no symbols are found.

    Example:
        >>> @staticmethod
        >>> def resolve_symbol(obj, context):
        >>>     return resolve_symbol_urls(obj, context)
    """
    request: HttpRequest = context["request"]
    symbol_data = {}

    # Get the Symbol FK objects
    symbol_detailed = getattr(obj, symbol_detailed_field, None)
    symbol_simple = getattr(obj, symbol_simple_field, None)
    symbol_mono = getattr(obj, symbol_mono_field, None)

    # Build URLs if symbols exist and have SVG files
    if (
        symbol_detailed
        and hasattr(symbol_detailed, "svg_file")
        and symbol_detailed.svg_file
    ):
        symbol_data["detailed"] = request.build_absolute_uri(
            symbol_detailed.svg_file.url
        )
    if symbol_simple and hasattr(symbol_simple, "svg_file") and symbol_simple.svg_file:
        symbol_data["simple"] = request.build_absolute_uri(symbol_simple.svg_file.url)
    if symbol_mono and hasattr(symbol_mono, "svg_file") and symbol_mono.svg_file:
        symbol_data["mono"] = request.build_absolute_uri(symbol_mono.svg_file.url)

    return symbol_data if symbol_data else None


def resolve_symbol_url(
    obj: t.Any,
    context: dict[str, t.Any],
    style: str,
) -> str | None:
    """
    Resolve a single symbol URL from a Symbol FK field.

    This helper function resolves a single symbol style URL,
    useful when you need separate fields instead of a nested dict.

    Args:
        obj: Model instance with Symbol FK fields (e.g., Category)
        context: Django Ninja context dict containing the request object
        style: The symbol style to resolve ('detailed', 'simple', or 'mono')

    Returns:
        Absolute SVG URL as a string, or None if symbol not found.

    Example:
        >>> @staticmethod
        >>> def resolve_symbol_detailed(obj, context):
        >>>     return resolve_symbol_url(obj, context, 'detailed')
    """
    request: HttpRequest = context["request"]
    field_name = f"symbol_{style}"

    symbol = getattr(obj, field_name, None)
    if symbol and hasattr(symbol, "svg_file") and symbol.svg_file:
        return request.build_absolute_uri(symbol.svg_file.url)

    return None
