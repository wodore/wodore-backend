# Feature Graph Implementation Plan

## Summary

Implementation of semantic relationships between GeoPlaces using the existing Category model for relation types, plus unified operating mode model.

**Key Implementation Points:**

1. Store only one direction (use `part_of` only)
2. Remove `parent` field from GeoPlace (all hierarchy via relations)
3. Use `relation` as unified field name across all M2M models
4. Use `operating.*` for modes, `brand` for brands (separate)
5. Months as 12 integer fields (0-100) for performance and DB validation
6. Hours as simple string (not queried, display only)
7. Rename GeoPlaceAccommodation → GeoPlaceOperation (generic for all place types)
8. Remove AmenityDetail entirely (replaced by GeoPlaceOperation)
9. Phones via ExternalLink with `tel:` URIs

## Code Review Findings (2026-03-13)

Comprehensive review identified **17 affected files** across 5 tiers:

### Critical Files (Tier 1)

1. `geometries/models/_amenity_detail.py` - **DELETE ENTIRE FILE**
2. `geometries/models/_associations.py` - Rename `classifier` → `relation` (line 227, 265)
3. `external_links/models.py` - Rename `link_type` → `relation` (line 58, 175)
4. `geometries/models/_geoplace.py` - Remove `parent` field (line 135-145), AmenityDetail imports (1052, 1204)
5. `geometries/models/__init__.py` - Update exports, remove AmenityDetail

### High Priority (Tier 2)

6. `geometries/schemas/_output.py` - Update AmenityDetailSchema (lines 116-162)
7. `geometries/schemas/_input.py` - Update OperatingStatus imports, field types (lines 32-37)
8. `geometries/api.py` - Update amenity filtering/serialization (lines 661-752)
9. `external_links/admin.py` - Replace "link_type" → "relation" in admin

### Critical for Data Import (Tier 3)

10. `geometries/management/commands/geoplaces_import_osm.py` - **HEAVY USAGE**
    - Lines 176, 179: opening_hours/brand extraction
    - Lines 1050-1074: AmenityDetailInput creation
    - Lines 1439-1530: Brand category handling
    - Replace all AmenityDetailInput → GeoPlaceOperationInput
11. `geometries/management/commands/test_import_performance.py` - AmenityDetail usage (lines 817, 852, 1030, 1064)

### Admin & Exports (Tier 4)

12. `geometries/admin/_geoplace.py` - Remove AmenityDetail import
13. `geometries/schemas/__init__.py` - Update schema exports

### Migration Files (Tier 5)

- 6 migrations needed in correct order (see Migration Steps below)

---

## Models Overview

### New Models

1. **GeoPlaceRelation** - Spatial/infrastructure graph
2. **GeoPlaceOperation** - Operating modes with capacity/hours/months (replaces AmenityDetail)

### Updated Models

1. **GeoPlace** - Remove `parent`, add graph helper methods
2. **GeoPlaceCategory** - Rename `classifier` → `relation`
3. **ExternalLink** - Rename `link_type` → `relation`

### Note on inverse_relation

**Decision:** NOT adding `inverse_relation` field to Category model.

**Rationale:**

- Reverse queries work by swapping `from_place`/`to_place` fields
- Django ORM already handles bidirectional navigation via `related_name`
- No functional requirement for semantic inverse mapping
- Can be added later if UI/API needs semantic labels (e.g., "contains" vs "part_of")
- Keeps implementation simpler and more flexible

**Example without inverse_relation:**

```python
# Forward: Hut → part_of → Municipality
hut.outgoing_relations.filter(relation__slug="part_of")

# Reverse: Municipality ← part_of ← Hut (just swap query)
municipality.incoming_relations.filter(relation__slug="part_of")
```

If needed later, a separate `relation_reverse` category could be added for display purposes only.

### Removed Models

1. **AmenityDetail** - Fully replaced by GeoPlaceOperation

---

## 1. Month Enum (NEW)

**File:** `server/apps/geometries/models/_operation.py` (new file)

```python
from enum import IntEnum

class Month(IntEnum):
    """Month enumeration (1-based, matching calendar and database fields)."""
    JANUARY = 1
    FEBRUARY = 2
    MARCH = 3
    APRIL = 4
    MAY = 5
    JUNE = 6
    JULY = 7
    AUGUST = 8
    SEPTEMBER = 9
    OCTOBER = 10
    NOVEMBER = 11
    DECEMBER = 12
```

**Why 1-based?** Matches database fields (`month_01`, `month_02`) and human intuition (June = 6th month).

---

## 2. GeoPlaceRelation Model (NEW)

**File:** `server/apps/geometries/models/_associations.py`

```python
class GeoPlaceRelation(TimeStampedModel):
    """
    Semantic relationships between GeoPlaces.

    Uses Category for relation types (part_of, near, serves).
    Stores only one direction - reverse queries swap from_place/to_place.

    Examples:
        Hut → part_of → Municipality → part_of → Canton
        Bus Stop → serves → Village

    Reverse queries work by swapping fields:
        Municipality ← part_of ← Hut (incoming_relations)
    """

    from_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="outgoing_relations",
        verbose_name=_("From Place"),
    )

    to_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="incoming_relations",
        verbose_name=_("To Place"),
    )

    relation = models.ForeignKey(
        Category,
        on_delete=models.RESTRICT,
        db_index=True,
        related_name="geoplace_relations",
        verbose_name=_("Relation Type"),
        limit_choices_to=models.Q(parent__slug="relations"),
    )

    confidence = models.FloatField(
        default=1.0,
        verbose_name=_("Confidence"),
        help_text=_("Confidence score for auto-generated relations (0.0-1.0)"),
    )

    extra = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = _("Geo Place Relation")
        verbose_name_plural = _("Geo Place Relations")
        ordering = ["from_place", "relation__order"]
        indexes = [
            models.Index(fields=["from_place", "relation"], name="gpr_from_rel_idx"),
            models.Index(fields=["to_place", "relation"], name="gpr_to_rel_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["from_place", "to_place", "relation"],
                name="geoplace_relation_unique_triple",
            ),
            models.CheckConstraint(
                check=~models.Q(from_place=models.F("to_place")),
                name="geoplace_relation_no_self_loop",
            ),
        ]

    def __str__(self):
        return f"{self.from_place.name_i18n} → {self.relation.slug} → {self.to_place.name_i18n}"
```

**File:** `server/apps/geometries/models/_associations.py` (new section)

```python
class GeoPlaceRelation(TimeStampedModel):
    """
    Semantic relationships between GeoPlaces.

    Uses Category for relation types (part_of, near, serves).
    Stores only one direction.

    Examples:
        Hut → part_of → Municipality
        Bus Stop → serves → Village
    """

    from_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="outgoing_relations",
        verbose_name=_("From Place"),
    )

    to_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="incoming_relations",
        verbose_name=_("To Place"),
    )

    relation = models.ForeignKey(
        Category,
        on_delete=models.RESTRICT,
        db_index=True,
        related_name="geoplace_relations",
        verbose_name=_("Relation Type"),
        limit_choices_to=models.Q(parent__slug="relations"),
    )

    confidence = models.FloatField(
        default=1.0,
        verbose_name=_("Confidence"),
        help_text=_("Confidence score for auto-generated relations (0.0-1.0)"),
    )

    extra = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = _("Geo Place Relation")
        verbose_name_plural = _("Geo Place Relations")
        ordering = ["from_place", "relation__order"]
        indexes = [
            models.Index(fields=["from_place", "relation"], name="gpr_from_rel_idx"),
            models.Index(fields=["to_place", "relation"], name="gpr_to_rel_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["from_place", "to_place", "relation"],
                name="geoplace_relation_unique_triple",
            ),
            models.CheckConstraint(
                check=~models.Q(from_place=models.F("to_place")),
                name="geoplace_relation_no_self_loop",
            ),
        ]

    def __str__(self):
        return f"{self.from_place.name_i18n} → {self.relation.slug} → {self.to_place.name_i18n}"
```

---

## 3. GeoPlaceOperation Model (NEW)

```python
from django.contrib.gis.db import models
from django.core.validators import MaxValueValidator
from django.utils.translation import gettext_lazy as _
from server.core.models import TimeStampedModel


class GeoPlaceOperation(TimeStampedModel):
    """
    Operating mode details for any place type.

    Generic model used for:
    - Accommodations: capacity = beds, months = availability
    - Restaurants: capacity = seats, months = open months
    - Shops: capacity = NULL, months = open months
    - Museums: capacity = max visitors, months = seasonal hours
    - Medical: capacity = NULL, months = open months

    The relation field MUST match a relation used in GeoPlaceCategory.

    Example:
      GeoPlaceCategory(place=hut, category=alpine_hut, relation=operating.standard)
      GeoPlaceOperation(place=hut, relation=operating.standard, capacity=170)
    """

    geo_place = models.ForeignKey(
        "GeoPlace",
        related_name="operations",
        on_delete=models.CASCADE
    )

    relation = models.ForeignKey(
        "categories.Category",
        limit_choices_to=models.Q(parent__slug="operating"),
        verbose_name=_("Operating Mode"),
        help_text=_("Must match a relation in GeoPlaceCategory for this place"),
        on_delete=models.RESTRICT,
    )

    # Capacity (meaning depends on place type)
    capacity = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=_("Capacity: beds for huts, seats for restaurants, max visitors for museums")
    )

    # Monthly opening percentage (0-100%, NULL = unknown)
    # Using separate int fields for performance and DB validation
    month_01 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("January")
    )
    month_02 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("February")
    )
    month_03 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("March")
    )
    month_04 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("April")
    )
    month_05 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("May")
    )
    month_06 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("June")
    )
    month_07 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("July")
    )
    month_08 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("August")
    )
    month_09 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("September")
    )
    month_10 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("October")
    )
    month_11 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("November")
    )
    month_12 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)],
        verbose_name=_("December")
    )

    # Opening hours (simple string, OSM-compatible or free text)
    hours = models.TextField(
        blank=True,
        default="",
        help_text=_('OSM format or text: "Mo-Fr 08:00-18:00", "24/7", "by appointment"')
    )

    # Flexible extra data (JSONB)
    extra = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Structured details: {"staffed": true, "services": ["restaurant"], "price_per_night": 85}')
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [["geo_place", "relation"]]
        verbose_name = _("Operating Mode")
        verbose_name_plural = _("Operating Modes")
        ordering = ["relation__order"]
        indexes = [
            models.Index(fields=["geo_place", "relation"]),
            models.Index(fields=["month_07"]),  # Summer queries
            models.Index(fields=["month_12"]),  # Winter queries
        ]

    def __str__(self):
        capacity_str = f"{self.capacity}" if self.capacity else "no capacity"
        return f"{self.geo_place.name_i18n} ({self.relation.slug}): {capacity_str}"

    @property
    def months(self) -> "MonthAccessor":
        """Dict-like accessor for month percentages using Month enum.

        Examples:
            >>> op.months[Month.JANUARY] = 0
            >>> op.months[Month.JULY] = 100
            >>> value = op.months[Month.JUNE]
            >>> all_months = op.months.to_dict()
        """
        return MonthAccessor(self)
```

---

## 3. GeoPlaceOperation Model (NEW)

**File:** `server/apps/geometries/models/_operation.py`

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._operation import GeoPlaceOperation

class MonthAccessor:
    """Dict-like accessor for month percentages using Month enum.

    Provides a clean API for accessing month fields:
    - op.months[Month.JULY] = 100
    - value = op.months[Month.JUNE]
    - all_months = op.months.to_dict()
    """

    def __init__(self, operation: "GeoPlaceOperation") -> None:
        self._operation = operation

    def __setitem__(self, month: Month, value: int | None) -> None:
        """Set percentage for month using Month enum.

        Args:
            month: Month enum value (e.g., Month.JULY)
            value: Percentage 0-100, or None for unknown

        Raises:
            TypeError: If month is not a Month enum
            ValueError: If percentage is not in range 0-100
        """
        if not isinstance(month, Month):
            raise TypeError(
                f"Use Month enum (e.g., Month.JULY), got {type(month).__name__}"
            )
        if value is not None and not (0 <= value <= 100):
            raise ValueError(f"Percentage must be 0-100, got {value}")
        setattr(self._operation, f"month_{month.value:02d}", value)

    def __getitem__(self, month: Month) -> int | None:
        """Get percentage for month using Month enum.

        Args:
            month: Month enum value (e.g., Month.JULY)

        Returns:
            Opening percentage (0-100) or None if unknown

        Raises:
            TypeError: If month is not a Month enum
        """
        if not isinstance(month, Month):
            raise TypeError(
                f"Use Month enum (e.g., Month.JULY), got {type(month).__name__}"
            )
        return getattr(self._operation, f"month_{month.value:02d}", None)

    def to_dict(self) -> dict[str, int | None]:
        """Convert all months to {month_name: percentage} dict.

        Returns:
            Dict with keys 'JANUARY', 'FEBRUARY', etc.
        """
        return {month.name: self[month] for month in Month}

    def __repr__(self) -> str:
        return f"<MonthAccessor for {self._operation.geo_place.name_i18n}>"
```

---

## 4. GeoPlaceCategory - Rename Field

**File:** `server/apps/geometries/models/_associations.py`

**Rename field:**

```python
class GeoPlaceCategory(TimeStampedModel):
    geo_place = models.ForeignKey(...)
    category = models.ForeignKey(...)

    # RENAMED from 'classifier'
    relation = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classifications",
        help_text=_("Operating mode, brand, or role for this category"),
    )

    extra = models.JSONField(default=dict, blank=True)
```

---

## 6. ExternalLink - Rename Field

**File:** `server/apps/external_links/models.py`

```python
class ExternalLink(TimeStampedModel):
    # RENAMED from 'link_type'
    relation = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name="external_links",
        verbose_name=_("Link Type"),
        limit_choices_to=models.Q(parent__slug="link_types"),
    )
```

---

## 7. GeoPlace - Remove Parent & Add Helper Methods

**File:** `server/apps/geometries/models/_geoplace.py`

**Remove `parent` field** (around line 55)

**Add helper methods:**

```python
def add_relation(self, to_place: "GeoPlace", relation_slug: str, **kwargs):
    """Add semantic relation to another place."""
    from ._associations import GeoPlaceRelation

    relation_cat = Category.objects.get(slug=relation_slug, parent__slug="relations")

    return GeoPlaceRelation.objects.update_or_create(
        from_place=self,
        to_place=to_place,
        relation=relation_cat,
        defaults={**kwargs, "is_active": True}
    )[0]

def get_related_places(self, relation_slug: str = None, direction: str = "outgoing"):
    """Get related places via semantic relations."""
    from ._associations import GeoPlaceRelation

    if direction == "outgoing":
        qs = GeoPlaceRelation.objects.filter(from_place=self)
        field = "to_place"
    else:
        qs = GeoPlaceRelation.objects.filter(to_place=self)
        field = "from_place"

    if relation_slug:
        qs = qs.filter(relation__slug=relation_slug)

    return GeoPlace.objects.filter(id__in=qs.values_list(f"{field}__id", flat=True))
```

---

## 8. Update Exports

**File:** `server/apps/geometries/models/__init__.py`

```python
from ._associations import (
    GeoPlaceCategory,
    GeoPlaceImageAssociation,
    GeoPlaceSourceAssociation,
    GeoPlaceExternalLink,
    GeoPlaceRelation,  # NEW
)
from ._operation import GeoPlaceOperation  # NEW
from ._geoplace import GeoPlace, DetailType

# Remove AmenityDetail from imports

__all__ = [
    "GeoPlace",
    "GeoPlaceCategory",
    "GeoPlaceImageAssociation",
    "GeoPlaceSourceAssociation",
    "GeoPlaceExternalLink",
    "GeoPlaceRelation",  # NEW
    "GeoPlaceOperation",  # NEW
    "DetailType",
    # Remove AmenityDetail
]
```

---

## 9. Category Fixtures

**File:** `server/apps/categories/fixtures/relation_categories.json`

```json
[
  {
    "model": "categories.category",
    "pk": 1000,
    "fields": {
      "slug": "relations",
      "name": "Relations",
      "description": "Semantic relationship types between places",
      "order": 999,
      "is_active": true,
      "parent": null,
      "color": "#999999"
    }
  },
  {
    "model": "categories.category",
    "pk": 1010,
    "fields": {
      "slug": "part_of",
      "name": "Part Of",
      "description": "Universal containment hierarchy",
      "order": 10,
      "is_active": true,
      "parent": 1000,
      "color": "#4B8E43"
    }
  },
  {
    "model": "categories.category",
    "pk": 1011,
    "fields": {
      "slug": "near",
      "name": "Near",
      "description": "Proximity (symmetric)",
      "order": 11,
      "is_active": true,
      "parent": 1000,
      "color": "#4B8E43"
    }
  },
  {
    "model": "categories.category",
    "pk": 1020,
    "fields": {
      "slug": "serves",
      "name": "Serves",
      "description": "Infrastructure service",
      "order": 20,
      "is_active": true,
      "parent": 1000,
      "color": "#E67E22"
    }
  },
  {
    "model": "categories.category",
    "pk": 2000,
    "fields": {
      "slug": "operating",
      "name": "Operating Modes",
      "description": "Operating/service modes for places",
      "order": 100,
      "is_active": true,
      "parent": null,
      "color": "#3498DB"
    }
  },
  {
    "model": "categories.category",
    "pk": 2010,
    "fields": {
      "slug": "standard",
      "name": "Standard Operation",
      "description": "Main operation mode (e.g., summer, full service)",
      "order": 10,
      "is_active": true,
      "parent": 2000,
      "color": "#3498DB"
    }
  },
  {
    "model": "categories.category",
    "pk": 2020,
    "fields": {
      "slug": "reduced",
      "name": "Reduced Operation",
      "description": "Reduced operation (e.g., winter, limited service)",
      "order": 20,
      "is_active": true,
      "parent": 2000,
      "color": "#95A5A6"
    }
  },
  {
    "model": "categories.category",
    "pk": 2030,
    "fields": {
      "slug": "emergency",
      "name": "Emergency Only",
      "description": "Emergency access only",
      "order": 30,
      "is_active": true,
      "parent": 2000,
      "color": "#E74C3C"
    }
  },
  {
    "model": "categories.category",
    "pk": 3000,
    "fields": {
      "slug": "link_types",
      "name": "Link Types",
      "order": 200,
      "is_active": true,
      "parent": null,
      "color": "#9B59B6"
    }
  },
  {
    "model": "categories.category",
    "pk": 3010,
    "fields": {
      "slug": "website",
      "name": "Website",
      "order": 10,
      "is_active": true,
      "parent": 3000,
      "color": "#9B59B6"
    }
  },
  {
    "model": "categories.category",
    "pk": 3020,
    "fields": {
      "slug": "booking",
      "name": "Booking",
      "order": 20,
      "is_active": true,
      "parent": 3000,
      "color": "#9B59B6"
    }
  },
  {
    "model": "categories.category",
    "pk": 3030,
    "fields": {
      "slug": "social",
      "name": "Social Media",
      "order": 30,
      "is_active": true,
      "parent": 3000,
      "color": "#9B59B6"
    }
  },
  {
    "model": "categories.category",
    "pk": 3040,
    "fields": {
      "slug": "phone",
      "name": "Phone",
      "order": 40,
      "is_active": true,
      "parent": 3000,
      "color": "#9B59B6"
    }
  },
  {
    "model": "categories.category",
    "pk": 4000,
    "fields": {
      "slug": "brand",
      "name": "Brand",
      "description": "Brand or operator identifier (independent of operating mode)",
      "order": 300,
      "is_active": true,
      "parent": null,
      "color": "#F39C12"
    }
  }
]
```

---

## 10. Usage Examples

### Monte Rosa Hut - Complete Setup

```python
from django.contrib.gis.geos import Point
from server.apps.geometries.models import GeoPlace, GeoPlaceCategory, GeoPlaceOperation
from server.apps.categories.models import Category

# 1. Create GeoPlace
hut = GeoPlace.objects.create(
    name="Monte Rosa Hut",
    slug="monte-rosa-huette",
    location=Point(7.86667, 45.88333),
    elevation=2883,
    country_code="CH",
)

# 2. Add categories with operating modes
alpine_hut = Category.objects.get(slug="alpine_hut")
unattended = Category.objects.get(slug="unattended_hut")
restaurant = Category.objects.get(slug="restaurant")
sac_brand = Category.objects.get(slug="sac", parent__slug="brands")

operating_std = Category.objects.get(slug="standard", parent__slug="operating")
operating_red = Category.objects.get(slug="reduced", parent__slug="operating")
brand_relation = Category.objects.get(slug="brand")

# Categories for standard mode
GeoPlaceCategory.objects.create(geo_place=hut, category=alpine_hut, relation=operating_std)
GeoPlaceCategory.objects.create(geo_place=hut, category=restaurant, relation=operating_std)

# Categories for reduced mode
GeoPlaceCategory.objects.create(geo_place=hut, category=unattended, relation=operating_red)

# Brand (independent of operating mode)
GeoPlaceCategory.objects.create(geo_place=hut, category=sac_brand, relation=brand_relation)

# 3. Add operating modes
from server.apps.geometries.models import Month

summer_op = GeoPlaceOperation.objects.create(
    geo_place=hut,
    relation=operating_std,
    capacity=170,
)

# Use Month enum for clarity
summer_op.months[Month.JUNE] = 75      # yesish (opening transition)
summer_op.months[Month.JULY] = 100     # fully open
summer_op.months[Month.AUGUST] = 100   # fully open
summer_op.months[Month.SEPTEMBER] = 100  # fully open
summer_op.months[Month.OCTOBER] = 25    # noish (closing transition)
summer_op.hours = "24/7"
summer_op.extra = {"staffed": True, "services": ["restaurant", "shower"], "price_per_night": 85}
summer_op.save()

winter_op = GeoPlaceOperation.objects.create(
    geo_place=hut,
    relation=operating_red,
    capacity=20,
)

# Winter season
winter_op.months[Month.OCTOBER] = 100
winter_op.months[Month.NOVEMBER] = 100
winter_op.months[Month.DECEMBER] = 100
winter_op.months[Month.JANUARY] = 100
winter_op.months[Month.FEBRUARY] = 100
winter_op.months[Month.MARCH] = 100
winter_op.months[Month.APRIL] = 100
winter_op.months[Month.MAY] = 100
winter_op.hours = "emergency access - key required"
winter_op.extra = {"staffed": False, "services": ["emergency_shelter"]}
winter_op.save()

# 4. Add spatial relations
zermatt = GeoPlace.objects.get(slug="zermatt")
hut.add_relation(zermatt, "part_of")

# 5. Add phone number via ExternalLink
from server.apps.external_links.models import ExternalLink

phone_type = Category.objects.get(slug="phone", parent__slug="link_types")
phone = ExternalLink.objects.create(
    url="tel:+41279672215",
    label="Hut Reception",
    relation=phone_type
)
hut.external_links.add(phone)
```

### Queries

```python
from server.apps.geometries.models import Month

# Get capacity for July
summer_op = hut.operations.filter(month_07__gte=75).first()
summer_capacity = summer_op.capacity if summer_op else 0

# Using Month enum
july_value = summer_op.months[Month.JULY]  # 100

# Get all months as dict
all_months = summer_op.months.to_dict()
# {'JANUARY': None, 'FEBRUARY': None, ..., 'JUNE': 75, 'JULY': 100, ...}

# Get categories for standard operation
summer_categories = hut.categories.filter(
    category_associations__relation__slug="standard"
)
# Returns: [alpine_hut, restaurant]

# Get brand
brand = hut.categories.filter(
    category_associations__relation__slug="brand"
).first()
# Returns: sac

# Find all huts open in summer (July >= 75%)
summer_huts = GeoPlace.objects.filter(
    operations__month_07__gte=75
).distinct()

# Get parent municipality
parent = hut.get_related_places("part_of", direction="outgoing").first()

# Get all phones
phones = hut.external_links.filter(relation__slug="phone")
for phone in phones:
    print(f"{phone.label}: {phone.url}")  # "Hut Reception: tel:+41279672215"
```

### Value Mapping

```python
from server.apps.geometries.models import Month

# Helper to convert fuzzy values to percentages
VALUE_MAP = {
    "no": 0,
    "noish": 25,
    "maybe": 50,
    "yesish": 75,
    "yes": 100,
    "unknown": None,
}

def migrate_month_value(old_value: str) -> int | None:
    """Convert fuzzy value to percentage."""
    return VALUE_MAP.get(old_value.lower(), None)

# Example: Set months using helper
old_data = {
    "jan": "yes",     # 100
    "feb": "yes",     # 100
    "jun": "yesish",  # 75
    "jul": "yes",     # 100
    "oct": "noish",   # 25
    "nov": "no",      # 0
}

for month_name, value in old_data.items():
    month = Month[month_name.upper()]  # "jan" -> Month.JANUARY
    op.months[month] = migrate_month_value(value)
```

---

## Migration Steps

**⚠️ CRITICAL: Follow exact order to avoid foreign key violations**

```bash
# Step 1: Rename fields FIRST (before creating new models)
app makemigrations geometries --name rename_geoplacecategory_classifier_to_relation
app makemigrations external_links --name rename_externallink_link_type_to_relation

# Step 2: Apply rename migrations
app migrate

# Step 3: Create NEW models
app makemigrations geometries --name create_geoplacerelation
app makemigrations geometries --name create_geoplaceoperation

# Step 4: Apply new model migrations
app migrate

# Step 5: Load category fixtures
app loaddata relation_categories

# Step 6: Update ALL code references (see affected files above)
# - Update imports in schemas, api, admin, management commands
# - Replace AmenityDetail → GeoPlaceOperation
# - Add Month enum imports
# - Update month field access to use Month enum

# Step 7: Migrate GeoPlace.parent → GeoPlaceRelation
# Create custom management command: app migrate_parent_to_relations
python manage.py migrate_parent_to_relations

# Step 8: Remove GeoPlace.parent field
app makemigrations geometries --name remove_geoplace_parent

# Step 9: Apply migration
app migrate

# Step 10: Migrate data from AmenityDetail to GeoPlaceOperation
# Create custom management command: app migrate_amenity_to_operation
python manage.py migrate_amenity_to_operation

# Step 11: Delete AmenityDetail model
app makemigrations geometries --name delete_amenitydetail

# Step 12: Final migration
app migrate

# Step 13: Verify data integrity
# - Check GeoPlaceOperation records exist
# - Verify Month enum works correctly
# - Verify relations are correct
# - Test OSM import script
# - Verify API responses
```

### Verification Commands

```bash
# Check for remaining old references
grep -r "AmenityDetail" --include="*.py" server/apps/
grep -r "\.classifier" --include="*.py" server/apps/geometries/
grep -r "\.link_type" --include="*.py" server/apps/external_links/

# Verify new models and Month enum
app shell << 'EOF'
from server.apps.geometries.models import GeoPlaceRelation, GeoPlaceOperation, Month

# Check counts
print(f"GeoPlaceRelation: {GeoPlaceRelation.objects.count()}")
print(f"GeoPlaceOperation: {GeoPlaceOperation.objects.count()}")

# Test Month enum
print(f"Month.JULY value: {Month.JULY.value}")  # Should be 7
print(f"Month.JUNE value: {Month.JUNE.value}")  # Should be 6

# Test month accessor
op = GeoPlaceOperation.objects.first()
if op:
    op.months[Month.JANUARY] = 0
    op.months[Month.JULY] = 100
    print(f"July value: {op.months[Month.JULY]}")  # Should be 100
    print(f"All months: {op.months.to_dict()}")
EOF
```

### Hut → GeoPlace Migration Example

```python
from django.contrib.gis.geos import Point
from server.apps.huts.models import Hut
from server.apps.geometries.models import GeoPlace, GeoPlaceCategory, GeoPlaceOperation, Month
from server.apps.categories.models import Category

def migrate_hut_to_geoplace(hut: Hut) -> GeoPlace:
    """Migrate a Hut to GeoPlace with operations"""

    # 1. Create GeoPlace
    place = GeoPlace.objects.create(
        name=hut.name,
        slug=hut.slug,
        description=hut.description,
        location=hut.location,
        elevation=hut.elevation,
        country_code=hut.country_field,
        is_active=hut.is_active,
        is_public=hut.is_public,
        review_status=hut.review_status,
    )

    # 2. Get operating relations
    operating_std = Category.objects.get(slug="standard", parent__slug="operating")
    operating_red = Category.objects.get(slug="reduced", parent__slug="operating")

    # 3. Add categories with operating modes
    GeoPlaceCategory.objects.create(
        geo_place=place,
        category=hut.hut_type_open,
        relation=operating_std
    )

    if hut.hut_type_closed:
        GeoPlaceCategory.objects.create(
            geo_place=place,
            category=hut.hut_type_closed,
            relation=operating_red
        )

    # 4. Migrate open_monthly to percentages
    VALUE_MAP = {"no": 0, "noish": 25, "maybe": 50, "yesish": 75, "yes": 100}

    # 5. Create operating modes using Month enum
    if hut.capacity_open:
        summer_op = GeoPlaceOperation.objects.create(
            geo_place=place,
            relation=operating_std,
            capacity=hut.capacity_open,
            extra={"staffed": True}
        )

        # Set months using Month enum
        for month_num in range(1, 13):
            month_key = f"month_{month_num:02d}"
            old_value = hut.open_monthly.get(month_key, "unknown")
            percentage = VALUE_MAP.get(old_value)

            if percentage and percentage >= 50:
                summer_op.months[Month(month_num)] = percentage

        summer_op.save()

    if hut.capacity_closed:
        winter_op = GeoPlaceOperation.objects.create(
            geo_place=place,
            relation=operating_red,
            capacity=hut.capacity_closed,
            extra={"staffed": False}
        )

        # Set months using Month enum
        for month_num in range(1, 13):
            month_key = f"month_{month_num:02d}"
            old_value = hut.open_monthly.get(month_key, "unknown")
            percentage = VALUE_MAP.get(old_value)

            if percentage is None or percentage < 50:
                winter_op.months[Month(month_num)] = percentage or 0

        winter_op.save()

    # 6. Migrate images, contacts, organizations...
    # (Keep existing migration logic)

    return place
```

---

## Summary

**New Models:** 2

- GeoPlaceRelation (spatial graph)
- GeoPlaceOperation (replaces AmenityDetail + AccommodationDetail)

**Removed Models:** 1

- AmenityDetail (fully replaced)

**Updated Models:** 3

- GeoPlace (remove parent, add helpers)
- GeoPlaceCategory (rename classifier → relation)
- ExternalLink (rename link_type → relation)

**New Enums:**

- Month (IntEnum: JANUARY=1, ..., DECEMBER=12)
- MonthAccessor (dict-like month field accessor)

**Files Affected:** 17

- 5 critical model/schema files
- 2 management commands (OSM import critical)
- 2 API files
- 3 admin files
- 5 supporting files

**Migration Complexity:** MEDIUM

- 12 steps in strict order (renames first, then new models, then data migrations)
- Data migration required (AmenityDetail → GeoPlaceOperation, GeoPlace.parent → GeoPlaceRelation)
- OSM import script needs updates (use Month enum)
- API backward compatibility concerns

**Category Trees:**

- `relations` (part_of, near, serves)
- `operating` (standard, reduced, emergency)
- `link_types` (website, booking, social, phone)
- `brand` (standalone, for brand/operator)

**Benefits:**

- Unified `relation` field naming across all models
- Generic operation model works for all place types
- Native int fields for months (fast, DB-validated)
- Phones via standard ExternalLink pattern
- Brand independent of operating mode
- Reduced data duplication (no detail model unless needed)
