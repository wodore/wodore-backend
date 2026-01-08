from collections import defaultdict

from descriptors import cachedclassproperty
from django_cleanup import cleanup

from modeltrans.fields import TranslationField

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from .managers import CategoryManager


@cleanup.ignore
class Category(models.Model):
    """
    Generic hierarchical category model.

    Can be used for:
    - Hut types (replacing HutType)
    - Place types (peaks, passes, stations, etc.)
    - Hiking grades
    - Transport types
    - Any other categorization needs

    Supports hierarchy via parent/child relationships.
    Each parent can have a default child category.
    """

    FIELDS = (
        "slug",
        "name",
        "description",
        "order",
        "symbol",
        "symbol_simple",
        "icon",
        "parent",
        "default",
        "parent",
    )

    i18n = TranslationField(fields=("name", "description"))
    objects = CategoryManager()

    # Identification
    slug = models.SlugField(
        max_length=50,
        db_index=True,
        help_text=_("Unique identifier within parent level"),
    )

    # Translated fields
    name = models.CharField(
        max_length=100, blank=True, null=True, default="", help_text=_("Category name")
    )
    name_i18n: str

    description = models.TextField(
        max_length=400,
        blank=True,
        null=True,
        default="",
        help_text=_("Category description"),
    )
    description_i18n: str

    # Display and ordering
    order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text=_("Display order (lower values appear first)"),
    )

    # Images (mandatory)
    symbol = models.ImageField(
        max_length=300,
        upload_to="categories/symbols/detailed",
        help_text=_("Detailed symbol for map display"),
    )

    symbol_simple = models.ImageField(
        max_length=300,
        upload_to="categories/symbols/simple",
        help_text=_("Simple symbol for smaller displays"),
    )

    icon = models.ImageField(
        max_length=300,
        upload_to="categories/icons",
        help_text=_("Icon (typically black/monochrome)"),
    )

    # Hierarchy
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("Parent"),
        help_text=_("Parent category in hierarchy"),
        db_index=True,
    )

    default = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="as_default_for",
        verbose_name=_("Default Child"),
        help_text=_("Default child category (used when parent has children)"),
        limit_choices_to=models.Q(parent__isnull=False),
    )

    # Status
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Whether this category is currently active"),
    )

    class Meta:
        verbose_name = _("Category")
        verbose_name_plural = _("Categories")
        ordering = ("parent__order", "order", "slug")
        indexes = (
            GinIndex(fields=["i18n"]),
            models.Index(fields=["parent", "order", "slug"]),
        )
        constraints = [
            models.UniqueConstraint(
                fields=["slug", "parent"], name="unique_slug_per_parent"
            ),
            models.CheckConstraint(
                check=~models.Q(default=models.F("id")), name="default_not_self"
            ),
        ]

    def __str__(self) -> str:
        if self.name_i18n:
            if self.parent:
                return f"{self.parent.name_i18n} → {self.name_i18n}"
            return self.name_i18n
        return self.slug

    def save(self, *args, **kwargs):
        """Auto-generate slug from name if not provided."""
        if not self.slug and self.name_i18n:
            self.slug = slugify(self.name_i18n)
        super().save(*args, **kwargs)

    # Hierarchy helper methods

    def get_ancestors(self, include_self: bool = False) -> list["Category"]:
        """Get all ancestors from root to this category."""
        ancestors = []
        current = self if include_self else self.parent
        while current:
            ancestors.insert(0, current)
            current = current.parent
        return ancestors

    def get_descendants(self, include_self: bool = False) -> models.QuerySet:
        """Get all descendants recursively."""

        descendants_ids = []
        if include_self:
            descendants_ids.append(self.id)

        to_process = [self]
        while to_process:
            current = to_process.pop(0)
            children = list(current.children.all())
            descendants_ids.extend([c.id for c in children])
            to_process.extend(children)

        return Category.objects.filter(id__in=descendants_ids)

    def get_root(self) -> "Category":
        """Get the root category of this hierarchy."""
        current = self
        while current.parent:
            current = current.parent
        return current

    def get_level(self) -> int:
        """Get the depth level (0 = root, 1 = first child, etc.)."""
        level = 0
        current = self.parent
        while current:
            level += 1
            current = current.parent
        return level

    def get_default_or_self(self) -> "Category":
        """Get the default child if set, otherwise return self."""
        return self.default if self.default else self

    # Class methods for backward compatibility with HutType

    @classmethod
    def get_default_type(cls, parent: "Category | None" = None) -> "Category":
        """
        Get the default/unknown category.

        If parent is provided and has a default child, return that.
        Otherwise return the global 'unknown' category (parent=None, slug='unknown').
        """
        if parent and parent.default:
            return parent.default
        return cls.default_type

    @cachedclassproperty
    def default_type(cls) -> "Category":
        """Returns the global 'unknown' category (parent=None, slug='unknown')."""
        obj, _created = cls.objects.get_or_create(
            slug="unknown",
            parent=None,
            defaults={
                "name": "Unknown",
                "order": 999,
                "is_active": True,
            },
        )
        return obj

    @cachedclassproperty
    def values(cls) -> dict[str, "Category"]:
        """
        Returns a dictionary with slug: Category relationship.

        Note: Only includes root-level categories (parent=None).
        If a key is not found, the 'unknown' type is returned.

        For child categories, use get_by_slug() with parent parameter.
        """
        vals: dict[str, Category] = defaultdict(cls.get_default_type)
        vals.update(
            {cat.slug: cat for cat in cls.objects.filter(parent=None, is_active=True)}
        )
        return vals

    @classmethod
    def get_by_slug(
        cls, slug: str, parent: "Category | None" = None, active_only: bool = True
    ) -> "Category | None":
        """
        Get a category by slug and optional parent.

        Args:
            slug: The category slug
            parent: Parent category (None for root categories)
            active_only: Only return active categories

        Returns:
            Category instance or None if not found
        """
        filters = {"slug": slug, "parent": parent}
        if active_only:
            filters["is_active"] = True

        try:
            return cls.objects.get(**filters)
        except cls.DoesNotExist:
            return None
