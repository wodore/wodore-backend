import typing as t
from collections.abc import MutableMapping
from typing import Any

from slugify import slugify

from modeltrans.manager import MultilingualManager

from server.core.managers import BaseManager


class OwnerManager(MultilingualManager, BaseManager):
    def get_or_create(self, defaults: MutableMapping[str, Any] | None = None, **kwargs: Any) -> tuple[Any, bool]:
        """A convenience method for looking up an object with the given kwargs, creating one if necessary.

        Args:
            slug(str): Slug of the owner, used for lookup, if a new one is created and not `name` is supplied it is used as name (as caption).
            name(str): Name of the owner, used for lookup or create a new one. If no slug is supplied it creates one from the `name` (slugified).
            defaults:  Dictionary with default field values in case it is created.

        Returns:
            Tuple of (`object`, `created`), where object is the retrieved or created object and created is a boolean specifying whether a new object was created.
        """
        qs = self.get_queryset()
        name: str | None = kwargs.get("name")
        slug: str | None = kwargs.get("slug")
        if defaults is None:
            defaults = {}
        if name is None and slug is None:
            err_msg = "Either 'name' or 'slug' is required"
            raise UserWarning(err_msg)
        params: dict[str, str] = {}
        if slug is not None:
            params["slug"] = slug
        if name is not None:
            params["name"] = name
        try:
            return (qs.get(**params), False)
        except self.model.DoesNotExist:
            pass
        # no owner exixts, create new one
        comment = defaults.get("comment", "")
        if slug is None and name is not None:
            slug = slugify(name)
        if name is None and slug is not None:
            name = slug.capitalize()

        slug = defaults.get("slug", slug)  # get slug from default and reduce it if needed
        if slug is not None and len(slug) > 50:
            comment += f"\nSlug reduced from '{slug}'."
            slug = slugify(" ".join(slug.split("-")), max_length=50, word_boundary=True)

        defaults["comment"] = comment.strip()
        if "name" not in defaults:
            defaults["name"] = name
        if "slug" not in defaults:
            defaults["slug"] = slug
        owner = self.model(**defaults)
        owner.save()
        return (owner, True)


# HutManager = _HutManager.from_queryset(BaseQuerySet)
