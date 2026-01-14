"""
HutTypeHelper - wrapper around Category model for hut types.

This provides a clean interface to access Category objects for hut types.
Hut types are categories under the configured parent (default: accommodation).
"""

from collections import defaultdict
from typing import TYPE_CHECKING

from descriptors import cachedclassproperty

from django.conf import settings

from server.apps.categories.models import Category

if TYPE_CHECKING:
    from server.apps.categories.models import Category as CategoryType


class HutTypeHelper:
    """
    Helper class for accessing hut type categories.

    Hut types are categories under the configured parent (default: accommodation).
    This provides a clean interface to the Category model for hut type operations.
    """

    _parent_cache: "CategoryType | None" = None
    _values_cache: dict[str, "CategoryType"] | None = None

    @classmethod
    def _get_parent(cls) -> "CategoryType":
        """Get the parent category for hut types (cached)."""
        if cls._parent_cache is None:
            parent_path = settings.HUTS_CATEGORY_PARENT
            category, paths = Category.objects.find_by_slug(parent_path)
            if category is None:
                raise ValueError(
                    f"Hut category parent '{parent_path}' not found. "
                    f"Available paths: {', '.join(paths) if paths else 'none'}"
                )
            cls._parent_cache = category
        return cls._parent_cache

    @classmethod
    def get(cls, slug: str) -> "CategoryType":
        """
        Get a hut type category by slug.

        Args:
            slug: Category slug (e.g., "hut", "bivouac")

        Returns:
            Category instance or default/unknown if not found
        """
        parent = cls._get_parent()
        category = Category.objects.by_slug(slug, parent=parent)
        if category is None:
            return cls.get_default_type()
        return category

    @classmethod
    def get_default_type(cls) -> "CategoryType":
        """Get the default/unknown hut type."""
        parent = cls._get_parent()
        return Category.get_default_type(parent=parent)

    @cachedclassproperty
    def default_type(cls) -> "CategoryType":
        """Returns the default 'unknown' hut type."""
        return cls.get_default_type()

    @cachedclassproperty
    def values(cls) -> dict[str, "CategoryType"]:
        """
        Returns a dictionary with slug: Category relationship.
        If a key is not found, the 'unknown' type is returned.

        This mimics the old HutType.values behavior.
        """
        if cls._values_cache is None:
            parent = cls._get_parent()
            vals: dict[str, Category] = defaultdict(cls.get_default_type)
            vals.update(
                {
                    cat.slug: cat
                    for cat in Category.objects.filter(parent=parent, is_active=True)
                }
            )
            cls._values_cache = vals
        return cls._values_cache

    @classmethod
    def clear_cache(cls):
        """Clear cached parent and values (useful for tests)."""
        cls._parent_cache = None
        cls._values_cache = None
