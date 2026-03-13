# Feature Graph Implementation Plan

## Summary

Implementation of semantic relationships between GeoPlaces using the existing Category model for relation types, plus unified operating mode model.

**Key Decisions:**

1. ✅ No `source` field in GeoPlaceRelation (keep it simple)
2. ✅ Store only one direction (use `part_of` only)
3. ✅ Remove `parent` field from GeoPlace (all hierarchy via relations)
4. ✅ Use `relation` as unified field name across all M2M models
5. ✅ Use `operating.*` for modes, `brand` for brands (separate)
6. ✅ Months as 12 integer fields (0-100) for performance and DB validation
7. ✅ Hours as simple string (not queried, display only)
8. ✅ Rename GeoPlaceAccommodation → GeoPlaceOperation (generic for all place types)
9. ✅ Remove AmenityDetail entirely (replaced by GeoPlaceOperation)
10. ✅ Phones via ExternalLink with `tel:` URIs

---

## Models Overview

### New Models

1. **GeoPlaceRelation** - Spatial/infrastructure graph
2. **GeoPlaceOperation** - Operating modes with capacity/hours/months (replaces AmenityDetail)

### Updated Models

1. **Category** - Add `inverse_relation` field
2. **GeoPlace** - Remove `parent`, add graph helper methods
3. **GeoPlaceCategory** - Rename `classifier` → `relation`
4. **ExternalLink** - Rename `link_type` → `relation`

### Removed Models

1. **AmenityDetail** - Fully replaced by GeoPlaceOperation

---

## 1. Category Model - Add Inverse Relations

**File:** `server/apps/categories/models.py`

**Add field after `default`:**

```python
inverse_relation = models.ForeignKey(
    "self",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="inverse_of",
    verbose_name=_("Inverse Relation"),
    help_text=_("Inverse relation for bidirectional semantics. Example: 'part_of' ↔ 'contains'"),
    limit_choices_to=models.Q(parent__slug="relations") | models.Q(slug="relations"),
)
```

**Add constraint:**

```python
models.CheckConstraint(
    check=~models.Q(inverse_relation=models.F("id")),
    name="inverse_relation_not_self"
),
```

---

## 2. GeoPlaceRelation Model (NEW)

**File:** `server/apps/geometries/models/_associations.py`

```python
class GeoPlaceRelation(TimeStampedModel):
    """
    Semantic relationships between GeoPlaces.

    Uses Category for relation types (part_of, near, serves).
    Stores only one direction - inverse semantics in Category.inverse_relation.

    Examples:
        Hut → part_of → Municipality → part_of → Canton
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

**File:** `server/apps/geometries/models/_operation.py` (new file)

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

    def get_month_percentage(self, month: int) -> int | None:
        """Get opening percentage for month (1-12). Returns None if unknown."""
        if 1 <= month <= 12:
            return getattr(self, f"month_{month:02d}")
        return None

    def set_month_percentage(self, month: int, percentage: int | None):
        """Set opening percentage for month (1-12)."""
        if 1 <= month <= 12:
            if percentage is not None and not (0 <= percentage <= 100):
                raise ValueError(f"Percentage must be 0-100, got {percentage}")
            setattr(self, f"month_{month:02d}", percentage)
```

---

## 4. Update GeoPlaceCategory

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

## 5. Update ExternalLink

**File:** `server/apps/external_links/models.py`

**Rename field:**

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

## 6. GeoPlace Helper Methods

**File:** `server/apps/geometries/models/_geoplace.py`

**Remove `parent` field (around line 55)**

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

## 7. Update Exports

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

## 8. Category Fixtures

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
      "inverse_relation": 1011,
      "color": "#4B8E43"
    }
  },
  {
    "model": "categories.category",
    "pk": 1011,
    "fields": {
      "slug": "contains",
      "name": "Contains",
      "order": 11,
      "is_active": true,
      "parent": 1000,
      "inverse_relation": 1010,
      "color": "#4B8E43"
    }
  },
  {
    "model": "categories.category",
    "pk": 1012,
    "fields": {
      "slug": "near",
      "name": "Near",
      "description": "Proximity (symmetric)",
      "order": 12,
      "is_active": true,
      "parent": 1000,
      "inverse_relation": 1012,
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
      "inverse_relation": 1021,
      "color": "#E67E22"
    }
  },
  {
    "model": "categories.category",
    "pk": 1021,
    "fields": {
      "slug": "served_by",
      "name": "Served By",
      "order": 21,
      "is_active": true,
      "parent": 1000,
      "inverse_relation": 1020,
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

## Usage Examples

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
GeoPlaceOperation.objects.create(
    geo_place=hut,
    relation=operating_std,
    capacity=170,
    month_06=75,   # yesish (June - opening transition)
    month_07=100,  # yes
    month_08=100,  # yes
    month_09=100,  # yes
    month_10=25,   # noish (October - closing transition)
    hours="24/7",
    extra={"staffed": True, "services": ["restaurant", "shower"], "price_per_night": 85}
)

GeoPlaceOperation.objects.create(
    geo_place=hut,
    relation=operating_red,
    capacity=20,
    month_10=100,  # yes
    month_11=100,  # yes
    month_12=100,  # yes
    month_01=100,  # yes
    month_02=100,  # yes
    month_03=100,  # yes
    month_04=100,  # yes
    month_05=100,  # yes
    hours="emergency access - key required",
    extra={"staffed": False, "services": ["emergency_shelter"]}
)

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
# Get capacity for July (month 7)
summer_op = hut.operations.filter(month_07__gte=75).first()
summer_capacity = summer_op.capacity if summer_op else 0

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
# Helper to convert fuzzy values to percentages
VALUE_MAP = {
    "no": 0,
    "noish": 25,
    "maybe": 50,
    "yesish": 75,
    "yes": 100,
    "unknown": None,
}

# Convert from old Hut model
def migrate_month_value(old_value: str) -> int | None:
    return VALUE_MAP.get(old_value.lower(), None)
```

---

## Migration Steps

```bash
# 1. Create migrations
app makemigrations categories geometries

# 2. Apply migrations
app migrate

# 3. Load fixtures
app loaddata relation_categories

# 4. Migrate Hut data to GeoPlace (custom script)
# See Hut → GeoPlace migration example below

# 5. Remove AmenityDetail references
# Update any code referencing AmenityDetail
```

### Hut → GeoPlace Migration Example

```python
from django.contrib.gis.geos import Point
from server.apps.huts.models import Hut
from server.apps.geometries.models import GeoPlace, GeoPlaceCategory, GeoPlaceOperation
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

    months_std = {}
    months_red = {}

    for month_num in range(1, 13):
        month_key = f"month_{month_num:02d}"
        old_value = hut.open_monthly.get(month_key, "unknown")
        percentage = VALUE_MAP.get(old_value)

        # Assume standard mode when open, reduced when closed/unknown
        if percentage and percentage >= 50:
            months_std[month_key] = percentage
        else:
            months_red[month_key] = percentage if percentage is not None else 0

    # 5. Create operating modes
    if hut.capacity_open:
        GeoPlaceOperation.objects.create(
            geo_place=place,
            relation=operating_std,
            capacity=hut.capacity_open,
            **months_std,
            extra={"staffed": True}
        )

    if hut.capacity_closed:
        GeoPlaceOperation.objects.create(
            geo_place=place,
            relation=operating_red,
            capacity=hut.capacity_closed,
            **months_red,
            extra={"staffed": False}
        )

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

**Updated Models:** 4

- Category (add inverse_relation)
- GeoPlace (remove parent, add helpers)
- GeoPlaceCategory (rename classifier → relation)
- ExternalLink (rename link_type → relation)

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
