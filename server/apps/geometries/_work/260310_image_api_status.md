# Image API Implementation Status

**Date**: 2026-03-10  
**Session**: Continuing from previous conversation about image aggregation API

## Overview
Implementing a geo-image aggregation API for the wodore-backend project that fetches images from multiple sources (Wodore internal database, Wikidata, Camptocamp, etc.) based on coordinates.

## Completed ✅

### 1. Core Infrastructure
- ✅ Provider base class with registry system
- ✅ ImageResult dataclass for internal format
- ✅ Provider priority-based deduplication
- ✅ Parallel async fetching from all providers
- ✅ Cache precision levels for coordinate rounding

### 2. Providers Implemented

#### WodoreProvider (Internal Database)
- ✅ GeoPlace support with image associations
- ✅ Hut support with image associations
- ✅ Extracts QID from GeoPlace.osm_tags
- ✅ Extracts QID from Hut.hut_sources(OSM).source_data.tags.wikidata
- ✅ Filters: is_active=True, review_status="approved", license.is_public=True
- ✅ Uses Imagor for all image transformations
- ✅ Both providers registered: WodoreProvider(place_type="geoplace") and WodoreProvider(place_type="hut")

#### WikidataProvider
- ✅ Extracts QIDs from GeoPlaces and Huts
- ✅ Queries Wikidata REST API for P18 (image) property
- ✅ Resolves Wikimedia Commons URLs
- ✅ Extracts license info from Commons API
- ✅ Uses Imagor for all image transformations
- ⚠️ **STATUS: Not returning images yet - needs debugging**

#### CamptocampProvider
- ✅ Fixed bbox calculation (Web Mercator EPSG:3857)
- ✅ Fixed geometry parsing from nested JSON
- ✅ Fixed images location from associations.images array
- ✅ Web Mercator to WGS84 coordinate conversion
- ✅ Uses Imagor for all image transformations
- ✅ Successfully fetching waypoints and images

### 3. Image Transformations (Imagor)
All providers use consistent image sizes:
- ✅ avatar: 180x180 (square, no rounded corners)
- ✅ thumb: 250x200
- ✅ preview: 600x400
- ✅ preview-placeholder: 300x200 (quality=5, blur=3)
- ✅ medium: 1000x800
- ✅ large: 1800x1200

### 4. API Endpoint
- ✅ `/v1/geo/places/images/nearby`
- ✅ Searches both GeoPlaces and Huts within radius
- ✅ Passes both to providers
- ✅ Returns GeoJSON FeatureCollection
- ✅ Metadata includes geoplaces_found and huts_found
- ✅ Comprehensive DEBUG logging

### 5. Logging
- ✅ Added server.apps.geometries logger in settings
- ✅ DEBUG level showing all steps
- ✅ Shows GeoPlaces and Huts found with QIDs
- ✅ Shows images per provider
- ✅ Search radius expansion logs

## Known Issues ⚠️

### 1. WikidataProvider Not Returning Images
**Status**: QID extraction works, but no images returned

**Debugging needed**:
- Check if Wikidata QID is actually being extracted
- Verify Wikidata API call is successful
- Check if P18 property exists for the QID
- Verify image URL construction
- Check Commons API responses

**Test coordinates**: 46.55553, 8.15223 (should be a hut with Wikidata images)

### 2. Placeholder Providers
These providers are registered but not implemented:
- FlickrProvider (placeholder)
- MapillaryProvider (placeholder)
- PanoramaxProvider (placeholder)

## File Structure

```
server/apps/geometries/
├── providers/
│   ├── __init__.py (exports all providers)
│   ├── base.py (base classes, registry, utilities)
│   ├── wodore.py (internal database images)
│   ├── wikidata.py (Wikidata/Wikimedia Commons)
│   ├── camptocamp.py (Camptocamp.org)
│   ├── flickr.py (placeholder)
│   ├── mapillary.py (placeholder)
│   └── panoramax.py (placeholder)
├── schemas/
│   └── _images.py (ImagePropertiesSchema, GeoJSON schemas)
└── api.py (endpoint implementation, provider registration)
```

## Database Schema

### GeoPlace
- `osm_tags`: JSONField with Wikidata QID at osm_tags['wikidata']
- `image_associations`: Reverse FK to images

### Hut
- `hut_sources`: FK to HutSource
- `image_set`: Reverse FK to images

### HutSource (OSM)
- `source_data`: JSONField with OSM data
- `source_data['tags']['wikidata']`: Contains QID

### Image
- `is_active`: Boolean
- `review_status`: "approved", "review", etc.
- `license`: FK to License (has `is_public` field)

## API Response Format

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [lon, lat]
      },
      "properties": {
        "source": "wodore|wikidata|camptocamp",
        "source_id": "unique_id",
        "image_type": "flat|360",
        "distance_m": 123.45,
        "license": {...},
        "attribution": "HTML string",
        "urls": {
          "original": "...",
          "avatar": "...",
          "thumb": "...",
          "preview": "...",
          "medium": "...",
          "large": "..."
        },
        "place": {
          "id": 123,
          "slug": "place-name",
          "name": "Place Name"
        }
      }
    }
  ],
  "metadata": {
    "total": 10,
    "sources_queried": ["wodore", "wikidata", "camptocamp"],
    "query_radius_m": 50.0,
    "center": {"lat": 46.55553, "lon": 8.15223},
    "geoplaces_found": 1,
    "huts_found": 1
  }
}
```

## Testing

### Endpoint
```bash
curl "http://localhost:8000/v1/geo/places/images/nearby?lat=46.55553&lon=8.15223&radius=100"
```

### Expected Results
- Should find 1 hut at those coordinates
- Should extract QID from OSM source
- Should return images from:
  - Wodore (internal database)
  - Wikidata (if working)
  - Camptocamp (working)

## Next Steps

1. **Debug WikidataProvider**
   - Add more detailed logging
   - Verify API responses
   - Check P18 property extraction

2. **Implement remaining providers** (optional):
   - Flickr
   - Mapillary
   - Panoramax

3. **Add caching** (if needed):
   - Per-provider cache with different TTLs
   - Cache invalidation strategy

4. **Performance optimization**:
   - Add indexes if needed
   - Optimize queries
   - Consider rate limiting for external APIs

## Session Notes

### Changes Made This Session
1. Added comprehensive DEBUG logging throughout all providers
2. Fixed Camptocamp bbox calculation (Web Mercator)
3. Fixed Camptocamp geometry parsing
4. Added Imagor transformations to all providers
5. Removed rounded corners from avatar images
6. Added review status and license filters
7. Added Hut support to WodoreProvider
8. Updated API to query both GeoPlaces and Huts
9. Fixed QID extraction from Hut.hut_sources.source_data.tags

### Issues Fixed
- ✅ Camptocamp bbox was using wrong coordinate system
- ✅ Camptocamp geometry wasn't being parsed correctly
- ✅ Images weren't using Imagor proxy
- ✅ Avatar images had rounded corners (not appropriate for landscapes)
- ✅ No filtering for review status and license visibility
- ✅ Huts weren't being queried
- ✅ QID extraction from Huts was using wrong path

### Current Blocker
- WikidataProvider extracts QIDs correctly but doesn't return images
- Need to investigate why no images are fetched despite successful QID extraction

## Investigation Needed - QID Extraction

### Hypothesis
The QID extraction from Hut sources might not be working because:
1. The organization slug might not be "osm" (could be "OSM", "openstreetmap", etc.)
2. The source_data structure might be different than expected
3. The tags might be nested differently
4. There might not be any OSM sources with wikidata tags

### Debugging Steps to Try
1. Check what organization slugs actually exist in the database
2. Look at actual source_data JSON structure
3. Add more detailed logging to see what's happening
4. Test with a specific hut that's known to have Wikidata images

### Code to Add for Debugging
Add this to wodore.py and wikidata.py to debug:
```python
# Log all available sources for debugging
for source in hut.hut_sources.all():
    logger.debug(f"  Source: {source.organization.slug}, source_data keys: {source.source_data.keys() if source.source_data else 'None'}")
    if source.source_data and isinstance(source.source_data, dict):
        logger.debug(f"    source_data: {source.source_data}")
```
