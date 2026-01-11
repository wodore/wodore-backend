from typing import TYPE_CHECKING

from modeltrans.manager import MultilingualQuerySet

from server.core.managers import BaseMutlilingualManager

if TYPE_CHECKING:
    from .models import Category


class CategoryQuerySet(MultilingualQuerySet):
    """Custom queryset for Category model."""

    def active(self):
        """Filter to only active categories."""
        return self.filter(is_active=True)

    def roots(self):
        """Filter to only root-level categories (no parent)."""
        return self.filter(parent__isnull=True)

    def children_of(self, parent):
        """Filter to children of a specific parent."""
        return self.filter(parent=parent)

    def by_slug(self, slug: str, parent=None):
        """Get category by slug and optional parent."""
        filters = {"slug": slug, "parent": parent}
        return self.filter(**filters).first()

    def with_children(self):
        """Prefetch children for efficient hierarchy traversal."""
        return self.prefetch_related("children")

    def with_parent(self):
        """Select related parent for efficient hierarchy traversal."""
        return self.select_related("parent")

    def resolve_slug(
        self, slug_path: str, is_active: bool = True
    ) -> tuple["Category | None", list[str]]:
        """
        Resolve a dot or slash notation slug path to a category (max one parent).

        Args:
            slug_path: Dot-separated slug path with max 2 parts (e.g., "parent.child")
            is_active: Only consider active categories

        Returns:
            Tuple of (category, matching_paths) where:
            - category: The resolved Category if unique, None otherwise
            - matching_paths: List of matching dot-notation paths if multiple found

        Examples:
            - "hut" with single match returns (category, [])
            - "hut" with multiple matches returns (None, ["accommodation.hut"])
            - "accommodation.hut" returns (category, []) if found
            - "invalid" returns (None, [])
        """
        slug_path = slug_path.replace("/", ".")
        slugs = [s.strip() for s in slug_path.split(".") if s.strip()]
        if not slugs or len(slugs) > 2:
            return None, []

        qs = self
        if is_active:
            qs = qs.active()

        if slugs[0] == "root":
            qs = qs.roots()
            del slugs[0]

        if len(slugs) == 1:
            # Single slug - check for uniqueness
            return qs.find_by_slug(slugs[0], is_active)
        else:
            # parent.child format
            parent_slug, child_slug = slugs[0], slugs[1]
            try:
                parent = qs.get(slug=parent_slug, parent__isnull=True)
                category = qs.get(slug=child_slug, parent=parent)
                return category, []
            except self.model.DoesNotExist:
                return None, []
            except self.model.MultipleObjectsReturned:
                return None, []

    def find_by_slug(
        self, slug: str, is_active: bool = True
    ) -> tuple["Category | None", list[str]]:
        """
        Find category by slug, handling ambiguity.

        If multiple categories have the same slug (different parents),
        returns None and a list of fully qualified paths.

        Args:
            slug: Simple slug (e.g., "hut")
            is_active: Only consider active categories

        Returns:
            Tuple of (category, paths) where:
            - category: The Category if unique, None if ambiguous or not found
            - paths: List of dot-notation paths if ambiguous, empty otherwise
        """
        qs = self
        if is_active:
            qs = qs.active()

        # Check if it's already a dot-notation path
        if "." in slug:
            return qs.resolve_slug(slug, is_active=is_active)

        # Find all categories with this slug
        matches = list(qs.filter(slug=slug))

        if len(matches) == 0:
            return None, []
        elif len(matches) == 1:
            return matches[0], []
        else:
            # Multiple matches - return paths
            paths = []
            for cat in matches:
                ancestors = cat.get_ancestors(include_self=True)
                path = ".".join([a.slug for a in ancestors])
                paths.append(path)
            return None, sorted(paths)


class CategoryManager(BaseMutlilingualManager):
    """Custom manager for Category model."""

    def get_queryset(self):
        """Return custom queryset."""
        return CategoryQuerySet(self.model, using=self._db)

    def active(self):
        """Filter to only active categories."""
        return self.get_queryset().active()

    def roots(self):
        """Filter to only root-level categories."""
        return self.get_queryset().roots()

    def children_of(self, parent):
        """Get children of a specific parent."""
        return self.get_queryset().children_of(parent)

    def by_slug(self, slug: str, parent=None):
        """Get category by slug and optional parent."""
        return self.get_queryset().by_slug(slug, parent)

    def resolve_slug(self, slug_path: str, is_active: bool = True):
        """Resolve a dot-notation slug path to a category."""
        return self.get_queryset().resolve_slug(slug_path, is_active)

    def find_by_slug(self, slug: str, is_active: bool = True):
        """Find category by slug, handling ambiguity."""
        return self.get_queryset().find_by_slug(slug, is_active)
