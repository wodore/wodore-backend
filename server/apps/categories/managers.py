from modeltrans.manager import MultilingualQuerySet

from server.core.managers import BaseMutlilingualManager


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
