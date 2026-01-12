# GeoPlace App - Implementation Proposal

## Overview

The `geoplace` app will provide canonical, curated geographic place data for the Wodore platform. It follows a clear separation between external source data (`external_geonames`) and domain models (`geoplace`).

## Import Pipeline: GeoNames → GeoPlace

### Step 1: Feature Configuration

Configure which GeoNames features to import in admin:

- Enable features (e.g., T.PK, S.RSTN, P.PPL), already possible in the admin
- Map to GeoPlaceType (e.g., T.PK → peak, S.RSTN → train_station)
- Set importance weights

### Step 2: Import Command

Create `import_geoplaces` management command:

```bash
# Import from enabled GeoNames features
app import_geoplaces --source geonames

# Dry run to see what would be imported
app import_geoplaces --source geonames --dry-run

# Limit to specific countries
app import_geoplaces --source geonames --countries ch,fr,it

# Update existing places
app import_geoplaces --source geonames --update
```

### Step 3: Importance Calculation

```python
def calculate_importance(place_source: PlaceSource, feature: Feature) -> float:
    """
    Calculate importance score for search ranking.

    Base formula:
    - Population-based: log10(population) * 10
    - Feature-based: feature.importance_weight * base_score
    - Capital cities: +20
    - Major cities: +10
    - Train stations: +5
    """

    base = 5.0

    # Population bonus
    if place_source.population:
        base += min(math.log10(place_source.population) * 2, 20)

    # Feature code bonuses
    feature_bonuses = {
        "PPLC": 20,  # Capital
        "PPLA": 10,  # First-order admin seat
        "RSTN": 5,   # Train station
        "PK": 3,     # Peak
    }
    base += feature_bonuses.get(place_source.feature_code, 0)

    # Feature weight multiplier
    base *= feature.importance_weight

    return min(base, 100.0)  # Cap at 100
```

### Step 4: Deduplication

Handle multiple sources for the same place:

```python
def find_or_create_geoplace(place_source: PlaceSource) -> GeoPlace:
    """
    Find existing GeoPlace or create new one.
    Uses location proximity and name similarity.
    """

    # Search for existing places within 30m
    candidates = GeoPlace.objects.filter(
        location__distance_lt=(place_source.location, D(m=30)),
        place_type=feature.default_place_type,
    ).annotate(
        distance=Distance("location", place_source.location)
    ).order_by("distance")[:5]

    # Check name similarity
    for candidate in candidates:
        similarity = calculate_name_similarity(
            candidate.name,
            place_source.name
        )
        if similarity > 0.8:  # High confidence match
            return candidate, False

    # Create new place
    return create_geoplace_from_source(place_source), True
```

## Admin Interface

### GeoPlaceAdmin

Similar to HutAdmin but simplified:

```python
@admin.register(GeoPlace)
class GeoPlaceAdmin(ModelAdmin):
    list_display = (
        "name_display",
        "place_type",
        "country_code",
        "elevation",
        "importance",
        "is_public",
    )
    list_filter = (
        "is_public",
        "is_active",
        "is_verified",
        "place_type__category",
        "place_type",
        "country_code",
    )
    search_fields = ("name", "slug")

    fieldsets = (
        ("Identification", {
            "fields": ("slug", "name", "place_type")
        }),
        ("Location", {
            "fields": ("location", "elevation", "country_code")
        }),
        ("Description", {
            "fields": ("description", "note")
        }),
        ("Status", {
            "fields": ("is_active", "is_public", "is_verified", "importance")
        }),
        ("Translations", {
            "classes": ["collapse"],
            "fields": [...]
        }),
    )
```

## API Endpoints

### Search Endpoint

```python
@router.get("geoplace/search", response=list[GeoPlaceSearchSchema])
def search_geoplaces(
    request: HttpRequest,
    q: str = Query(..., description="Search query"),
    limit: int = Query(15, description="Max results"),
    types: list[str] | None = Query(None, description="Filter by place type slugs"),
    categories: list[str] | None = Query(None, description="Filter by category"),
    countries: list[str] | None = Query(None, description="Filter by country codes"),
    threshold: float = Query(0.1, description="Similarity threshold"),
    score: Filter by score
) -> Any:
    """
    Fuzzy search for geographic places.
    Returns results ordered by importance and relevance.
    """
    pass
```

### Proximity Endpoint

```python
@router.get("geoplace/nearby", response=list[GeoPlaceSchema])
def nearby_geoplaces(
    request: HttpRequest,
    lat: float,
    lon: float,
    radius: float = Query(10000, description="Radius in meters"),
    types: list[str] | None = Query(None),
) -> Any:
    """Find places near coordinates."""
    pass
```

## Testing Strategy

1. **Unit Tests**: Model methods, importance calculation
2. **Integration Tests**: Import pipeline, deduplication
3. **API Tests**: Search endpoints, filtering
4. **Migration Tests**: HutType → GeoPlaceType data integrity

## Deployment Plan

1. Create `geoplace` app and models
2. Run migrations (creates tables)
3. Migrate HutType → GeoPlaceType (data migration)
4. Import GeoNames data for Alpine region
5. Enable search endpoints
6. Update frontend to use new endpoints
7. Deprecate HutType in next major version

## Future Enhancements

- **OSM Integration**: Enrich places with OpenStreetMap data
- **Routing**: Add routing graph for trails
- **Photos**: Link to image collections
- **Reviews**: User-generated content
- **Opening Hours**: Structured opening time data
- **Contact Information**: Phone, website, email
- **Wikimedia Integration**: Pull descriptions from Wikipedia
