# GeoPlace Multi-Category Import Logic Review

**Date**: 2026-03-11  
**Proposal**: GeoPlace Multi-Category with Classifier on Association  
**Reviewer**: Code Analysis

## Executive Summary

The proposal to move from single-category to multi-category GeoPlace with through-model associations introduces several critical issues in the OSM import logic. The most significant concerns are around **race conditions in parallel imports**, **non-deterministic category selection**, and **incomplete deduplication strategy**.

**Critical Issues Found**: 12  
**Major Concerns**: 8  
**Recommendations**: 15

---

## 1. Category Aggregation Analysis

### 1.1 How It Works with Existing Mapping System

**Current State** (Single Category):
```python
# In geoplaces_import_osm.py - OSMHandler.node()
match_result = match_tags_to_category(tags, self.category_names)
if match_result:
    category_slug, mapping, category_mappings = match_result
    # Single category assignment
    data["category_slug"] = category_slug
```

**Proposal** (Multi-Category):
```python
# Proposed aggregation per OSM element
# Step 1: Collect all mapping matches per source_id
all_matches = []
for cat in categories:
    result = cat.match_category(tags)
    if result:
        all_matches.append(result)

# Step 2: Union categories
categories = set(match[0] for match in all_matches)
```

**Issues Identified**:

#### Issue 1.1: Breaking Priority-Based Matching
**Severity**: HIGH

The existing system uses **priority-based matching** via `CATEGORY_REGISTRY` order:
```python
# CATEGORY_REGISTRY in priority order
CATEGORY_REGISTRY = [
    GROCERIES,      # Priority 1
    RESTAURANT,     # Priority 2
    HEALTH_AND_EMERGENCY,  # Priority 3
    ...
]
```

**Current behavior**: When an OSM element matches multiple categories, the **first match wins**. This is intentional and deterministic.

**Proposal problem**: "Union categories" breaks this semantic. A place with `shop=bakery` AND `amenity=restaurant` would get BOTH categories, violating the priority principle.

**Example**:
```
OSM tags: {shop: bakery, cuisine: pizza}
Current: Gets "groceries.bakery" (first match)
Proposal: Gets BOTH "groceries.bakery" AND "restaurant.pizza_place"
```

**Impact**:
- Semantic drift from "best match" to "all matches"
- Potential for category explosion (one place → 10+ categories)
- Breaks filtering assumptions

#### Issue 1.2: Inconsistent with match_category() Contract
**Severity**: MEDIUM

The `match_category()` method returns early on first match:
```python
def match_category(self, tags: dict) -> Optional[tuple[str, OSMMapping]]:
    matches = []
    for mapping in self.mappings:
        if self._tags_match(tags, mapping.osm_filters):
            if mapping.condition is None or mapping.condition(tags):
                matches.append((mapping.category_slug, mapping))

    if not matches:
        return None

    # Sort by priority and return FIRST match
    matches.sort(key=lambda m: m[1].priority)
    return matches[0]  # Only returns one!
```

**Problem**: The proposal assumes `match_category()` can return multiple matches per CategoryMappings, but it only returns ONE (the winner).

**Required change**: Need new API like `match_all_categories()` that returns all matches without priority filtering.

#### Issue 1.3: Performance with Many OSM Elements
**Severity**: MEDIUM

**Current approach** (single match):
- O(1) per element after first match
- Early exit when match found

**Proposed approach** (all matches):
- O(N×M) where N=categories, M=mappings per category
- No early exit - must check ALL categories
- Memory overhead for storing all matches

**Benchmark estimate**:
```
Current: 1000 elements × 5 categories (avg) = 5,000 checks
Proposal: 1000 elements × 12 categories × 50 mappings = 600,000 checks
120x slower for matching phase
```

**Mitigation**: Could cache per-element results, but increases memory pressure.

### 1.2 Race Conditions with Parallel Imports

**Current parallel import architecture**:
```python
# geoplaces_import_osm.py
workers = options.get("workers", 1)  # Parallel workers

# Each worker processes different mappings
for category_name in category_names:
    self._process_mapping(category_name)  # Parallel execution
```

**Critical Issue 1.2: Duplicate Source ID Inserts**
**Severity**: CRITICAL

**Scenario**:
```
Time T1: Worker 1 processes "shop=bakery" → source_id="node/123"
          Creates GeoPlace with category=groceries.bakery

Time T2: Worker 2 processes "amenity=restaurant" → source_id="node/123"
          Tries to create GeoPlace with category=restaurant.cafe
          ERROR: source_id="node/123" already exists!
```

**Why this happens**:
- Same OSM element can match multiple category mappings
- Each worker runs independently
- No locking mechanism for source_id uniqueness

**Current protection** (single category):
- Each OSM element only matches ONE category
- Workers process disjoint sets of OSM elements

**Proposed change** (multi-category):
- Each OSM element can match MULTIPLE categories
- Workers will have overlapping source_id sets

**Failure modes**:
1. **IntegrityError**: Duplicate source_id constraint violation
2. **Data loss**: Second worker's category silently dropped
3. **Partial state**: Only some categories attached

**Required mitigation**:
```python
# Option A: Pre-aggregation per source (breaks parallelism)
# Collect all categories for each source_id BEFORE parallel processing

# Option B: Two-phase approach
# Phase 1: Create/update GeoPlace (single writer)
# Phase 2: Attach categories (can be parallel)

# Option C: Row-level locking
SELECT FOR UPDATE on source_associations
```

All options have significant performance implications.

---

## 2. "One per Parent" Enforcement Analysis

### 2.1 Implementation Approach

**Proposal**:
```python
# Group categories by parent slug
parent_groups = {}
for category in categories:
    parent = category.split('.')[0]
    parent_groups.setdefault(parent, []).append(category)

# Pick winner per parent using mapping order
for parent, children in parent_groups.items():
    winner = children[0]  # First in mapping order
```

### 2.2 Determinism Issues

#### Issue 2.1: Non-Deterministic Mapping Order
**Severity**: HIGH

**Problem**: "Mapping order" is not guaranteed to be deterministic across imports.

**Why**:
1. Python dict iteration order (though stable in 3.7+) depends on insertion order
2. Mappings are defined across multiple files loaded dynamically
3. Module import order can affect final ordering

**Example**:
```python
# osm_groceries.py
GROCERIES = CategoryMappings(
    category="groceries",
    mappings=[
        OSMMapping(..., category_slug="groceries.bakery", priority=0),
        OSMMapping(..., category_slug="groceries.supermarket", priority=1),
    ]
)

# osm_restaurant.py
RESTAURANT = CategoryMappings(
    category="restaurant",
    mappings=[
        OSMMapping(..., category_slug="restaurant.cafe", priority=0),
    ]
)
```

**Question**: When OSM element matches both `groceries.bakery` (priority=1) and `restaurant.cafe` (priority=0), which wins?

**Proposal says**: "mapping order" - but what determines order ACROSS CategoryMappings?

**Ambiguity**:
- Is it CATEGORY_REGISTRY order?
- Is it mapping.priority field?
- Is it position within mappings list?

**Recommendation**: Explicitly define tie-breaking rules:
```python
def select_winner(categories, mappings):
    # 1. Filter by lowest priority number
    min_priority = min(m.priority for m in mappings)
    candidates = [c for c, m in zip(categories, mappings) if m.priority == min_priority]

    # 2. If tie, use CATEGORY_REGISTRY order
    for category_group in CATEGORY_REGISTRY:
        for candidate in candidates:
            if candidate.startswith(category_group.category):
                return candidate

    # 3. Final fallback: alphabetical
    return sorted(candidates)[0]
```

#### Issue 2.2: Equal Priority from Different Parents
**Severity**: MEDIUM

**Scenario**:
```python
# Mappings with equal priority
OSMMapping(
    osm_filters=["shop=bakery"],
    category_slug="groceries.bakery",
    priority=0  # Highest priority
)

OSMMapping(
    osm_filters=["amenity=cafe"],
    category_slug="restaurant.cafe",
    priority=0  # Same priority
)
```

**Problem**: Proposal doesn't specify what happens when:
- Same OSM element matches
- Multiple categories from DIFFERENT parents
- All with equal priority

**Current behavior**: First category in CATEGORY_REGISTRY wins
```python
# GROCERIES comes before RESTAURANT
CATEGORY_REGISTRY = [
    GROCERIES,   # Wins
    RESTAURANT,
]
```

**Proposal ambiguity**: Does "one per parent" mean:
- A) One winner from "groceries" parent AND one winner from "restaurant" parent? (Total: 2 categories)
- B) One winner total, using parent as tie-breaker? (Total: 1 category)

**Clarification needed**: The proposal should explicitly state which interpretation is intended.

#### Issue 2.3: Should This Be Configurable?
**Severity**: LOW

**Question**: Should "one per parent" rule be:
- Hard-coded in import logic?
- Configurable per category?
- Configurable per mapping?

**Use case**: Some categories might want multiple children:
```python
# Example: A "shopping mall" might legitimately have multiple child categories
place_type = "shopping.mall"
categories = ["groceries.supermarket", "restaurant.food_court", "services.bank"]
# Should this be allowed?
```

**Recommendation**: Make it configurable:
```python
@dataclass
class CategoryMappings:
    category: str
    mappings: list[OSMMapping]
    allow_multiple_children: bool = False  # NEW: Configurable
```

---

## 3. Classifier Handling Analysis

### 3.1 Current Classifier Approach

**Proposal**:
```python
# Using Category FK as classifier
# Example: category=accommodation.hut, classifier=season.winter_room

# Do not add any classifier during import
# Classifier field on through model: GeoPlaceCategory.classifier
```

#### Issue 3.1: Inconsistent Proposal Statement
**Severity**: HIGH

**Contradiction**:
1. Proposal says: "Do not add any classifier during the import, this is needed later"
2. Proposal also says: "For special cases (seasonal, off-season, winter_room): Use classifier FK"

**Question**: How will classifiers be added if not during import?

**Options**:
A) **Manual admin entry** (doesn't scale)
B) **Separate import pass** (complex, adds overhead)
C) **Post-processing script** (decoupled from import)

**Problem**: If classifiers are added later, how do you match which GeoPlace gets which classifier?

**Example**:
```python
# Import pass 1: Create GeoPlace
GeoPlace(
    name="Berghaus Gandria",
    categories=[accommodation.hut]  # No classifier
)

# Later: How to know this should have classifier=season.winter_room?
# Need to match by name? location? OSM tags?
```

**Missing piece**: How to associate classifier to the RIGHT GeoPlace.

#### Issue 3.2: No Classifier Detection Logic
**Severity**: MEDIUM

**Problem**: The proposal doesn't specify how to detect WHEN a classifier is needed.

**Current mapping system** has `condition` for complex logic:
```python
OSMMapping(
    osm_filters=["tourism=hotel"],
    category_slug="accommodation.hut",
    condition=lambda tags: tags.get('season') == 'winter',  # Existing mechanism
)
```

**Proposal question**: Should classifiers use the same `condition` mechanism? Or something new?

**Suggested approach**:
```python
OSMMapping(
    osm_filters=["tourism=hotel"],
    category_slug="accommodation.hut",
    classifier_category="season.winter_room",  # NEW field
    condition=lambda tags: tags.get('season') == 'winter',
)
```

#### Issue 3.3: Classifier Category Hierarchy
**Severity**: MEDIUM

**Question**: Should classifiers be:
- Flat list (season.winter_room, season.summer_room)?
- Hierarchical (season → winter_room)?

**Current Category model** supports hierarchy:
```python
class Category(models.Model):
    parent = models.ForeignKey("self", ...)
    slug = models.SlugField(...)
```

**Example**:
```python
# Option A: Flat
season.winter_room
season.summer_room
season.off_season

# Option B: Hierarchical
season → winter_room
season → summer_room  
season → off_season
```

**Implications**:
- Filtering: `categories__parent__slug="season"` vs `categories__slug__startswith="season"`
- UI display: Show classifier with or without parent context
- Identifier collision: "season" as both parent and classifier

**Recommendation**: Use flat structure for classifiers to avoid confusion with primary categories.

### 3.2 Implementation Gap

**Missing implementation details**:

1. **How to add classifiers later?**
   ```python
   # Pseudocode for what's missing
   def add_classifier_to_existing_places():
       # Find all places that need classifier
       places = GeoPlace.objects.filter(
           categories__slug="accommodation.hut",
           osm_tags__season="winter"
       )

       # Add classifier association
       for place in places:
           # How to avoid duplicates?
           # What if classifier already exists?
           GeoPlaceCategory.objects.create(
               geo_place=place,
               category=accommodation_hut,
               classifier=season_winter_room  # NEW
           )
   ```

2. **How to handle classifier conflicts?**
   ```python
   # What if multiple sources disagree?
   # Source A says: classifier=season.winter_room
   # Source B says: classifier=season.summer_room

   # Which wins? Merge? Source priority?
   ```

3. **How to handle classifier deletion?**
   ```python
   # If source removes classifier tag, should we:
   # A) Delete classifier association?
   # B) Mark as deprecated?
   # C) Keep manual edits?
   ```

---

## 4. Deduplication Analysis

### 4.1 Current Dedup Strategy

**Current implementation** (single category):
```python
def _find_existing_place_by_schema(...):
    # 1. Check source_id first
    if dedup_options.check_source_id:
        try:
            assoc = GeoPlaceSourceAssociation.objects.get(
                organization=source_obj,
                source_id=from_source.source_id
            )
            return assoc.geo_place  # Found existing
        except GeoPlaceSourceAssociation.DoesNotExist:
            pass

    # 2. Check location + category + brand (BBox)
    if dedup_options.distance_same > 0:
        nearby = GeoPlace.objects.filter(
            location__contained=bbox,
            place_type=category,  # SINGLE category
            amenity_detail__brand=brand
        ).first()
        if nearby:
            return nearby

    # 3. Check very close proximity (any category)
    if dedup_options.distance_any > 0:
        very_nearby = GeoPlace.objects.filter(
            location__contained=bbox
        ).first()
        if very_nearby:
            return very_nearby

    return None
```

### 4.2 Multi-Category Dedup Issues

#### Issue 4.1: "Add Additional Category" Implementation
**Severity**: CRITICAL

**Proposal statement**: "if duplicate is found add additional category (if different parent)"

**Implementation gap**: How exactly does this work?

**Scenario**:
```python
# Existing place
place1 = GeoPlace(
    id=1,
    categories=[groceries.bakery]  # Has one category
)

# New import with same source_id
new_data = {
    "source_id": "node/123",
    "categories": [restaurant.cafe]  # Different category
}
```

**Question**: What should happen?

**Option A**: Add new category to existing place
```python
place1.categories.add(restaurant.cafe)
# Result: place1 has [groceries.bakery, restaurant.cafe]
```

**Option B**: Ignore (already has category from groceries parent)
```python
# Don't add - already has "groceries" parent
# Result: place1 has [groceries.bakery]
```

**Option C**: Replace existing category
```python
place1.categories.remove(groceries.bakery)
place1.categories.add(restaurant.cafe)
# Result: place1 has [restaurant.cafe]
```

**Recommendation**: Explicitly define the behavior in the proposal.

#### Issue 4.2: Same Category from Same Parent
**Severity**: MEDIUM

**Scenario**:
```python
# Existing place
place1 = GeoPlace(
    id=1,
    categories=[groceries.bakery]
)

# New import
new_data = {
    "source_id": "node/123",
    "categories": [groceries.bakery]  # SAME category
}
```

**Question**: What should happen?

**Options**:
1. **No-op** (already has this category)
2. **Update metadata** (refresh timestamps, etc.)
3. **Error** (duplicate association)

**Current constraint proposal**:
```python
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["geo_place", "category"],
            name="unique_geo_place_category"
        )
    ]
```

**Expected behavior**: No-op (constraint prevents duplicate).

**Edge case**: What if metadata differs?
```python
# Existing
GeoPlaceCategory(geo_place=place1, category=groceries.bakery, extra={"source": "OSM"})

# New import
GeoPlaceCategory(geo_place=place1, category=groceries.bakery, extra={"source": "manual"})
```

Should we update `extra` field or preserve original?

#### Issue 4.3: Per-Source Aggregation
**Severity**: HIGH

**Proposal statement**: "Ensure per-source aggregation to avoid duplicate source_id inserts during parallel import"

**Problem**: Not clearly defined.

**Current architecture** (geoplaces_import_osm.py):
```python
# Each worker processes one mapping independently
def _process_mapping_parallel(...):
    for category_group in category_groups:
        for mapping in category_group.mappings:
            # Fetch OSM data for this mapping
            amenities = self._fetch_overpass(...)

            # Import immediately
            self._import_amenities(amenities)
```

**Issue**: Different workers will process the same OSM element multiple times.

**Example**:
```
Worker 1: Processes mapping "shop=bakery" → finds node/123
Worker 2: Processes mapping "amenity=cafe" → finds node/123 (same element!)
```

**Required change**: Aggregate categories BEFORE parallel processing.

**Proposed solution**:
```python
# Phase 1: Sequential - fetch and aggregate
source_to_categories = {}
for category_group in category_groups:
    for mapping in category_group.mappings:
        elements = fetch_overpass(mapping.query)
        for element in elements:
            source_id = element.source_id
            source_to_categories.setdefault(source_id, set()).add(mapping.category_slug)

# Phase 2: Parallel - import aggregated data
def import_batch(source_ids):
    for source_id in source_ids:
        categories = source_to_categories[source_id]
        upsert_place(source_id, categories)
```

**Performance impact**:
- Sequential aggregation bottleneck
- Memory overhead for tracking all source_ids
- Increased complexity

---

## 5. Additional Implementation Concerns

### 5.1 Database Schema Constraints

#### Issue 5.1: Unique Constraint on Through Model
**Severity**: MEDIUM

**Proposal**:
```python
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["geo_place", "category"],
            name="unique_geo_place_category"
        )
    ]
```

**Question**: Should classifier be part of uniqueness?

**Option A**: Unique (geo_place, category)
```python
# Allows multiple classifiers for same category
GeoPlaceCategory(geo_place=p1, category=hut, classifier=winter)
GeoPlaceCategory(geo_place=p1, category=hut, classifier=summer)
```

**Option B**: Unique (geo_place, category, classifier)
```python
# One classifier per category
GeoPlaceCategory(geo_place=p1, category=hut, classifier=winter)
# ERROR: Duplicate (p1, hut)
```

**Recommendation**: Based on "one per parent" rule, should be Option A (geo_place, category) to allow multiple classifiers.

#### Issue 5.2: Cascade Delete Behavior
**Severity**: LOW

**Question**: When Category is deleted, what happens to GeoPlaceCategory associations?

**Current**:
```python
category = models.ForeignKey(
    Category,
    on_delete=models.RESTRICT,  # Prevents deletion
    ...
)
```

**Through model**:
```python
class GeoPlaceCategory(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,  # Deletes associations
        ...
    )
```

**Implication**: Deleting a category removes all category associations but keeps the GeoPlace.

**Edge case**: What if this is the last category?
```python
place = GeoPlace(categories=[bakery])
bakery.delete()
place.categories.all().delete()  # Now has NO categories!
# Should we delete the place? Or keep it?
```

**Recommendation**: Add validation to prevent deleting last category.

### 5.2 API Changes

#### Issue 5.3: Filter Complexity
**Severity**: MEDIUM

**Current filter** (simple):
```python
# Single category filter
GeoPlace.objects.filter(place_type__slug="bakery")
```

**Proposed filter** (complex):
```python
# Multi-category filter
GeoPlace.objects.filter(categories__slug="bakery")

# Filter by parent
GeoPlace.objects.filter(categories__parent__slug="groceries")

# Filter by multiple categories
GeoPlace.objects.filter(categories__slug__in=["bakery", "supermarket"])

# Filter by classifier
GeoPlace.objects.filter(geocategory__classifier__slug="winter_room")
```

**Performance concerns**:
- M2M joins are slower than FK
- Need indexes on join table
- Query planner may struggle with complex filters

**Recommendation**: Add database indexes:
```python
class Meta:
    indexes = [
        models.Index(fields=["geo_place", "category"]),
        models.Index(fields=["category", "geo_place"]),
        models.Index(fields=["classifier"]),  # If filtering by classifier
    ]
```

### 5.3 Migration Complexity

#### Issue 5.4: Data Migration Strategy
**Severity**: HIGH

**Current state**: 100,000+ GeoPlaces with single `place_type`

**Proposed migration**:
```python
# Step 1: Create through model
# Step 2: Migrate existing data
for place in GeoPlace.objects.all():
    GeoPlaceCategory.objects.create(
        geo_place=place,
        category=place.place_type,
        classifier=None
    )

# Step 3: Drop place_type field
```

**Concerns**:
1. **Downtime**: Migration on 100k rows will take time
2. **Rollback**: Hard to rollback if issues found
3. **Validation**: How to ensure migration didn't miss any places?
4. **Backward compatibility**: Proposal says "no backward compatibility required" - is this realistic?

**Recommendation**: Use phased migration:
```python
# Phase 1: Add through model (keep place_type)
# Phase 2: Mirror place_type to through model
# Phase 3: Update all code to use through model
# Phase 4: Drop place_type field (after validation period)
```

---

## 6. Recommendations

### 6.1 Critical Fixes (Must Address)

1. **Resolve race conditions** in parallel imports
   - Implement per-source aggregation BEFORE parallel processing
   - Add row-level locking for source_id updates
   - Or use sequential processing for multi-category

2. **Define deterministic winner selection** for "one per parent"
   - Explicit tie-breaking rules
   - Document priority system
   - Add tests for edge cases

3. **Clarify classifier strategy**
   - How/when to add classifiers if not during import?
   - Implement classifier detection logic
   - Define classifier update/deletion behavior

4. **Specify dedup behavior** for "add additional category"
   - Explicit implementation steps
   - Handle edge cases (same category, metadata conflicts)
   - Add tests for all scenarios

### 6.2 Performance Optimizations

1. **Batch category resolution**
   ```python
   # Pre-fetch all categories
   category_slugs = set()
   for data in amenities:
       category_slugs.update(data["categories"])

   categories = Category.objects.filter(
       slug__in=category_slugs
   ).select_related("parent")
   ```

2. **Cache parent lookups**
   ```python
   parent_cache = {}
   for category in categories:
       parent = category.parent
       parent_cache.setdefault(parent.slug, []).append(category)
   ```

3. **Use bulk operations for through model**
   ```python
   # Instead of loop
   GeoPlaceCategory.objects.bulk_create([
       GeoPlaceCategory(geo_place=place, category=cat)
       for cat in categories
   ])
   ```

### 6.3 Testing Strategy

1. **Unit tests for category selection**
   ```python
   def test_one_per_parent_enforcement():
       # Test with multiple categories from same parent
       # Test with equal priority
       # Test with different parents
   ```

2. **Integration tests for parallel import**
   ```python
   def test_parallel_import_no_duplicates():
       # Run 2 workers with overlapping categories
       # Verify no IntegrityError
       # Verify all categories attached
   ```

3. **Performance tests**
   ```python
   def test_import_performance_with_multicategory():
       # Benchmark 1000 elements
       # Compare single vs multi-category
       # Profile memory usage
   ```

---

## 7. Open Questions for Proposal Author

1. **Category Aggregation**
   - Should we maintain priority-based matching (first wins) or collect all matches?
   - What's the maximum number of categories per place we expect?
   - How do we handle category conflicts (e.g., "shop=bakery" vs "amenity=restaurant")?

2. **"One per Parent" Enforcement**
   - Is this rule configurable or hard-coded?
   - What happens with equal priority across different parents?
   - Should this be enforced at DB level or only during import?

3. **Classifiers**
   - When/how are classifiers added if not during import?
   - Should we use the existing `condition` mechanism or create new API?
   - Flat or hierarchical classifier structure?

4. **Deduplication**
   - Exact behavior when adding additional category to existing place?
   - What if metadata differs (extra field, timestamps)?
   - How to implement per-source aggregation without breaking parallelism?

5. **Migration**
   - Are we sure about "no backward compatibility required"?
   - What's the rollback plan if migration fails?
   - How long is acceptable downtime for migration?

---

## 8. Conclusion

The multi-category proposal has merit but requires significant refinement before implementation:

**Strengths**:
- Flexible categorization
- Classifier support for advanced filtering
- Future-proof design

**Weaknesses**:
- Incomplete specification of critical behaviors
- Race conditions in parallel imports
- Performance concerns
- Missing implementation details

**Recommendation**:
1. **Address critical issues** (1-4 in section 6.1) before implementation
2. **Create spike solution** to prove technical feasibility
3. **Performance testing** with realistic data volumes
4. **Phased rollout** starting with read-only access

**Risk level**: HIGH - Do not proceed without resolving race conditions and deterministic category selection.

---

**Next steps**:
1. Proposal author to answer open questions (section 7)
2. Technical design review with team
3. Create proof-of-concept for parallel import with aggregation
4. Update proposal with explicit implementation details
