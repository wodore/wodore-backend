Title: GeoPlace multi-category with classifier on association
Date: 2026-03-11

Goal

- Move from single GeoPlace.place_type to multi-category associations.
- Keep one GeoPlace per OSM element (source_id unique), but allow multiple categories.
- Enforce "one category per parent" during import only (no DB constraint).
- Add a classifier field to the association (not on GeoPlace) for future filtering.

High-level changes

1) Model changes

- Add a through model for GeoPlace <-> Category:
  - GeoPlaceCategory: (geo_place FK, category FK, classifier FK [Category], order/priority optional if needed)
  - constraints: unique (geo_place, category) to prevent duplicate links
- Replace GeoPlace.place_type (FK) with many-to-many to Category:
  - GeoPlace.categories = ManyToManyField(Category, through=GeoPlaceCategory, related_name="geo_places")
- Migrate existing GeoPlace.place_type into GeoPlaceCategory entries.
- Remove place_type usage once migration is complete (no backwards compatibility required).

2) Schema changes

- Input schemas:
  - GeoPlaceBaseInput.place_type_identifier -> place_type_identifiers: list[str]
  - Update helpers: get_name_dict, resolve categories, etc., accept list
- GeoPlace.update_or_create:
  - Accept list of identifiers; resolve categories and attach to GeoPlaceCategory
  - If existing GeoPlace found by source_id or dedup, update associations

3) Import behavior changes (OSM)

- Aggregate categories per OSM element before upsert
  - Collect all mapping matches per source_id, union categories
- Enforce "one per parent" during import (primary categories):
  - Group categories by parent slug; pick a winner per parent
  - Winner rule: mapping order
- Attach categories via GeoPlaceCategory
- For special cases (seasonal, off-season, winter_room):
  - Use classifier FK (Category) on the association
  - Example: category=accommodation.hut, classifier=season.winter_room
  - Do not add any classifier during the import, this is needed later

4) API changes

- Replace place_type in responses with list of categories
  - include_place_type -> include_categories
  - fields should return list of category slugs or full objects
- Filters:
  - place_type__... -> categories__...
  - parent filters -> categories__parent__...
- Query performance: add indexes on join table

5) Admin changes

- Replace place_type display with category list
- Filters updated to categories

6) Dedup changes

- Dedup still uses source_id first
- Category-based dedup keeps the same
- Ensure per-source aggregation to avoid duplicate source_id inserts during parallel import
- if duplicate is found add additional category (if different parent)

7) Migrations / data handling

- Migration steps (no backward compatibility required):
  1. Create GeoPlaceCategory model + M2M on GeoPlace.
  2. Data migration: for each GeoPlace with place_type, create GeoPlaceCategory.
  3. Drop place_type field.

## Open Questions & Resolutions

### 1. API Breaking Change Strategy

**Question**: Should we maintain backward compatibility with versioning?
**Resolution**: **No** - GeoPlaces are still in staging/dev, no backward compatibility needed. Direct breaking change is acceptable.

### 2. Deduplication Logic with Multiple Categories

**Question**: How does dedup work with multiple categories? Which parent to use?
**Resolution**: Updated algorithm:

1. Search for OSM source_id → if found, use this GeoPlace to update information and add new categories
2. Do dedup → check if already exists with parent category (check associations for any `startswith` match on parent slug)
   - If exists, skip it (no updates)
   - This is mainly to find an existing per-category entry
3. Very close bbox search: **Removed** - no longer needed with source_id + category parent dedup

**Implementation Example**:

```python
# Check if place has any category with matching parent
existing_place = GeoPlace.objects.filter(
    category_associations__category__parent__slug__startswith=parent_slug
).first()
if existing_place:
    # Skip dedup, place already exists with this parent category
    return existing_place, False
```

### 3. Category Removal Strategy

**Question**: How to handle category removal during re-import?
**Resolution**: Already covered by existing infrastructure:

- `source_id` is in `GeoPlaceSourceAssociation`
- `modified` and `created` fields exist on `TimeStampedModel`
- Cleanup stage handles removal of stale categories

**Open Question**: What happens when OSM data changes and removes a category?

- Option A: Keep old category (historical data)
- Option B: Remove category not in current import (cleanup)
- **Decision**: TBD - ignore for now, revisit during import implementation

### 4. Admin UX Display Format

**Question**: How should categories display in admin?
**Resolution**:

- **List view**: Structured display `"Shop → Bakery | Accommodation → Hut"`
- **Detail view**: Inline editing for `GeoPlaceCategory` associations

### 5. Classifier Field Usage

**Question**: When will classifiers be used if not during import?
**Resolution**: Field is added for future flexibility but not used currently:

- Example use case: Accommodation with same GeoPlace but different categories based on season
  - category=accommodation.hut, classifier=season.winter_room
  - category=accommodation.hotel, classifier=season.summer_room
- Allows flexible seasonal categorization without duplicating GeoPlace
- No classifier added during import (manual/admin only for now)

### 6. Migration Safety

**Question**: What if data migration fails?
**Resolution**: Acceptable risk:

- No rollback plan needed
- Can drop all imported data before migration if needed
- Development/staging environment only

### 7. Performance Optimization

**Question**: How to handle M2M join performance impact (2-10x slower)?
**Resolution**: Critical optimization strategy:

- Add composite indexes BEFORE migration
- Use `prefetch_related('categories__parent')` everywhere in list views
- Implement caching for GeoPlace queries (places don't change often)
- Monitor query performance and add additional indexes as needed

### 8. Validation Requirements

**Question**: How to validate input with multiple categories?
**Resolution**:

- **Minimum**: Require at least 1 category (empty list not allowed)
- **Validation**: Validate all identifiers before processing
- **Error handling**: Raise clear error for invalid category identifiers

### 9. Through Model Design

**Question**: Do we need `order` field and `related_name`?
**Resolution**:

- **`order` field**: Not needed - already handled by `category.order`
- **`related_name`**: Add for clarity and consistency:
  - `geo_place` FK: `related_name="category_associations"`
  - `category` FK: `related_name="geo_place_associations"`
  - `classifier` FK: `related_name="classifications"`

**Final Through Model Design**:

```python
class GeoPlaceCategory(TimeStampedModel):
    """Through model for GeoPlace <-> Category with optional classifier."""

    geo_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="category_associations",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.RESTRICT,
        db_index=True,
        related_name="geo_place_associations",
    )
    classifier = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classifications",
        help_text="Optional classifier for this association (e.g., seasonal status)",
    )

    class Meta:
        db_table = "geometries_geoplace_category"
        verbose_name = _("Geo Place Category Association")
        verbose_name_plural = _("Geo Place Category Associations")
        ordering = ["geo_place", "category"]  # Uses category.order for sorting
        indexes = [
            models.Index(fields=["category", "geo_place"]),
            models.Index(fields=["geo_place", "category"]),
            models.Index(fields=["classifier"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["geo_place", "category"],
                name="geoplacecategory_unique_place_category",
            ),
        ]

    def __str__(self) -> str:
        classifier_str = f" [{self.classifier.slug}]" if self.classifier else ""
        return f"{self.geo_place.name_i18n} → {self.category.identifier}{classifier_str}"
```

### 10. Edge Case Handling

**Question**: What about conflicting categories during dedup?
**Resolution**:

- **Conflict example**: `shop.bakery` vs `shop.supermarket` (same parent)
- **Resolution**: Use first category, second is deduped and skipped
- **Re-import**: Ignore for now (not fully specified yet)
- **Smart replace**: Already handled by dedup logic (first wins per parent)

### 11. Index Requirements

**Question**: What indexes are needed?
**Resolution**:

- **Required**:
  - `GeoPlaceCategory(geo_place_id, category_id)` unique (via constraint)
  - `GeoPlaceCategory(category_id, geo_place_id)` for category filters
  - `GeoPlaceCategory(classifier_id)` for future classifier filtering
- **Not needed**: `(geo_place_id, order)` - order handled by `category.order`

### 12. N+1 Query Prevention

**Question**: How to avoid N+1 queries when listing places?
**Resolution**:

- Always use `queryset.prefetch_related('categories__parent')` in list views
- For full category details: `prefetch_related('categories__parent', 'categories__symbol_detailed', ...)`
- Monitor query patterns with Django Debug Toolbar or django-silk

## Impacts / Risks

### Critical

- **API breaking change**: `place_type` → `categories` list (acceptable in dev/staging)
- **Query performance**: M2M joins are 2-10x slower without optimization
  - **Mitigation**: Add indexes before migration, use prefetch_related, implement caching
- **Import logic complexity**: Need aggregation to avoid duplicate association errors
  - **Mitigation**: Per-source aggregation, "one per parent" enforcement

### Medium

- **Deduplication changes**: Source_id + category parent matching
  - **Mitigation**: Clear algorithm, remove bbox proximity search
- **Admin UX changes**: Display format and filter updates
  - **Mitigation**: Structured display, inline editing, clear M2M filter behavior
- **Category removal during re-import**: Not fully specified
  - **Mitigation**: Ignore for now, revisit during import implementation

### Low

- **Migration safety**: No rollback plan
  - **Acceptable**: Dev/staging only, can drop/reimport data
- **Classifier field**: Added but not used
  - **Acceptable**: Future flexibility, no overhead

## Implementation Checklist

### Phase 1: Model & Migration (Week 1)

- [x] Create `GeoPlaceCategory` through model with proper indexes
- [x] Add M2M field to `GeoPlace` (keep `place_type` for migration)
- [x] Create data migration: migrate existing `place_type` to `GeoPlaceCategory`
- [x] Add verification step to ensure all places have categories
- [x] Drop `place_type` field
- [ ] Run tests on development data

### Phase 2: Admin Updates (Week 1)

- [x] Update admin list display with structured category format
- [x] Replace `place_type` filters with `categories` filters
- [x] Add inline editing for `GeoPlaceCategory`
- [x] Update admin search to work with categories
- [x] Test admin performance with prefetch_related

### Phase 3: Import Logic (Week 2)

- [x] Update OSM import to aggregate categories per element
- [x] Implement "one per parent" enforcement during import
- [x] Update deduplication logic:
  - Source_id matching first
  - Category parent matching (check associations)
  - Remove bbox proximity search
- [x] Update `GeoPlace.update_or_create()` to handle category lists
- [x] Add validation for empty category lists
- [x] Test import with parallel processing

### Phase 4: API Changes (Week 1)

- [x] Update input schemas: `place_type_identifier` → `place_type_identifiers`
- [x] Update output schemas: `place_type` → `categories`
- [x] Update helpers: `resolve_categories_from_identifiers()`
- [x] Update filters: `place_type__*` → `categories__*`
- [x] Add `.distinct()` to M2M filter queries
- [x] Update API documentation

### Phase 5: Performance Optimization (Week 1)

- [x] Add indexes before migration
- [x] Update all list views to use `prefetch_related('categories__parent')`
- [x] Update detail views with full prefetch
- [x] Implement caching for GeoPlace queries
- [x] Benchmark query performance before/after
- [x] Add monitoring for slow queries

### Phase 6: Testing & Validation (Week 1)

- [x] Unit tests for through model
- [x] Integration tests for import with multiple categories
- [x] Performance tests for M2M queries
- [x] Load test with 10k+ places
- [x] Verify N+1 query prevention

**Total Estimated Time**: 6-7 weeks

## Suggested Indexes

### GeoPlaceCategory

```python
class Meta:
    indexes = [
        # Primary lookup: find all categories for a place (reverse lookup)
        models.Index(fields=['category', 'geo_place']),

        # Reverse lookup: find all places for a category (most common filter)
        models.Index(fields=['geo_place', 'category']),

        # Classifier filtering (future use)
        models.Index(fields=['classifier']),
    ]
    constraints = [
        models.UniqueConstraint(
            fields=['geo_place', 'category'],
            name='geoplacecategory_unique_place_category'
        ),
    ]
```

### Query Optimization Patterns

```python
# List views - minimal prefetch
queryset = GeoPlace.objects.prefetch_related('categories__parent')

# Detail views - full prefetch
queryset = GeoPlace.objects.prefetch_related(
    'categories__parent',
    'categories__symbol_detailed',
    'categories__symbol_simple',
    'categories__symbol_mono'
)

# Filter optimization - use subquery if needed
category_ids = Category.objects.filter(
    parent__slug__in=category_parents
).values_list('id', flat=True)

queryset = GeoPlace.objects.filter(
    categories__id__in=category_ids
).distinct()
```
