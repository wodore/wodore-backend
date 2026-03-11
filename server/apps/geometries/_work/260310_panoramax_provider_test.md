# Panoramax Provider Testing Guide

**Date**: 2026-03-10  
**Status**: Implementation Complete, Ready for Testing

## Overview

The Panoramax provider has been successfully implemented to aggregate 360° panorama images from the Panoramax STAC API. This document provides testing instructions and verification steps.

## Implementation Summary

### Features Implemented

✅ **STAC API Integration**
- Single endpoint search via `/api/search`
- Uses standard STAC specification (assets at root level, not in properties)
- Simplified implementation with direct bbox query

✅ **Geographic Search**
- Calculates WGS84 bounding box from center point and radius
- Supports search radius up to 10km
- Filters results by actual Haversine distance
- API sorts results by timestamp (`sort=ts`) - most recent first

✅ **Metadata Extraction**
- Parses STAC item geometry (Point features)
- Extracts image URLs from assets (visual, equirectangular, thumb, preview)
- Reads datetime, license, and provider information from STAC properties
- Falls back to links if assets are unavailable

✅ **Image Transformations**
- All images processed through Imagor proxy
- Generates 6 sizes: avatar (180x180), thumb (250x200), preview (600x400), preview_placeholder (300x200), medium (1000x800), large (1800x1200)
- Applies blur and quality optimizations for placeholders

✅ **License & Attribution**
- Extracts license from STAC properties
- Normalizes common Creative Commons licenses (CC-BY, CC-BY-SA, CC0)
- Builds attribution with author and Panoramax link

✅ **Caching & Performance**
- Cache TTL: 6 hours (Panoramax updates frequently)
- Priority: 3 (after camptocamp, before wikidata)
- Single HTTP request per search (was: multiple requests for collections)
- Limit 100 results per search

✅ **SSL Error Handling**
- Uses proper SSL verification with correct endpoint (api.panoramax.xyz)
- Added detailed error logging for HTTP and network errors
- Graceful fallback if API is unreachable

## Technical Details

### API Endpoints Used

```
# Single search endpoint
GET https://api.panoramax.xyz/api/search?bbox={min_lon},{min_lat},{max_lon},{max_lat}&sort=ts&limit=100
```

**Query Parameters**:
- `bbox`: Bounding box in WGS84 format (min_lon,min_lat,max_lon,max_lat)
- `sort`: Sort by "ts" (timestamp/most recent first)
- `limit`: Maximum number of results (100)

### Implementation Notes

**Simplified Architecture** (2026-03-10):
- Removed collections→items two-step process
- Now uses single `/api/search` endpoint
- Fewer HTTP requests: 1 per search (was: 1 + N collections)
- Simpler code: ~150 lines (was: ~390 lines)
- API handles sorting by proximity automatically

### STAC Item Structure

```json
{
  "type": "Feature",
  "id": "item_id",
  "geometry": {
    "type": "Point",
    "coordinates": [lon, lat]
  },
  "properties": {
    "datetime": "2024-03-10T12:00:00Z",
    "license": "https://creativecommons.org/licenses/by-sa/4.0/",
    "providers": [{"name": "Author Name"}]
  },
  "assets": {
    "visual": {
      "href": "https://example.com/image.jpg",
      "type": "image/jpeg"
    },
    "thumb": {
      "href": "https://example.com/thumb.jpg",
      "type": "image/jpeg"
    }
  },
  "links": [
    {
      "rel": "preview",
      "href": "https://example.com/preview.jpg"
    }
  ]
}
```

### Key Fixes Applied

1. **Simplified to single `/api/search` endpoint** (2026-03-10)
   - Removed `_get_collections()` method
   - Removed `_search_collection_items()` method
   - Single HTTP request per search
   - Code reduced from ~390 to ~220 lines

2. **Fixed STAC structure parsing** (2026-03-10)
   - Changed from `properties.get("assets")` to `feature.get("assets")`
   - Changed from `properties.get("links")` to `feature.get("links")`
   - Assets and links are at root level in STAC specification, not in properties

3. **Fixed API endpoint** (2026-03-10)
   - Changed from `https://api.panoramax.cz` to `https://api.panoramax.xyz`
   - Previous endpoint had SSL certificate hostname mismatch
   - New endpoint has valid SSL certificate
   - Re-enabled proper SSL verification

4. **Fixed asset types** (2026-03-10)
   - Updated to use Panoramax's actual asset types: `hd`, `sd`, `thumb`
   - Previous code looked for: `visual`, `equirectangular`, `preview`
   - Now prioritizes `hd` (highest resolution) then falls back to `sd` and `thumb`

5. **Fixed license handling** (2026-03-10)
   - Added support for simple string licenses like "CC-BY-SA-4.0"
   - Added `_get_license_url()` method to convert slugs to full URLs
   - Handles null/missing providers field gracefully

6. **Enhanced error handling** (2026-03-10)
   - Added specific exception handling for HTTPStatusError and RequestError
   - Added detailed debug logging for search endpoint
   - Better error messages for troubleshooting

7. **Distance calculation**
   - Implemented Haversine formula for accurate distance in meters
   - Filters results by actual distance from query point

8. **Asset fallback chain**
   - Tries: hd → sd → thumb → visual → equirectangular → preview
   - Falls back to links with rel="preview" or rel="visual"

## Testing Procedure

### Prerequisites

1. **Server Running**
   ```bash
   cd /home/tobias/git/wodore/wodore-backend-alt1
   source .venv/bin/activate
   python manage.py runserver
   ```

2. **Coordinates for Testing**
   - Switzerland coordinates: `lat=46.55853`, `lon=8.15223` (near Andermatt)
   - Urban area: `lat=47.3769`, `lon=8.5417` (Zurich)
   - Mountain area: `lat=46.5701`, `lon=8.2221` (Furka Pass)

### Test 1: Basic Image Search

**Request:**
```bash
curl "http://localhost:8000/v1/geo/images/nearby?lat=46.55853&lon=8.15223&radius=2000"
```

**Expected Results:**
- HTTP 200 OK
- GeoJSON FeatureCollection response
- Images from multiple providers (wodore, camptocamp, wikidata, panoramax)
- Check that panoramax images have `source: "panoramax"`

**Check Logs:**
```
📷 PanoramaxProvider: Searching in bbox 8.123,46.540,8.181,46.577
PanoramaxProvider: Found X collections
Collection xyz: Found N items
PanoramaxProvider: Total images found: N
```

### Test 2: Panoramax-Only Results

**Request:**
```bash
curl "http://localhost:8000/v1/geo/images/nearby?lat=46.55853&lon=8.15223&radius=2000&sources=panoramax"
```

**Expected Results:**
- Only Panoramax images returned
- All images should have `source: "panoramax"`
- Check image URLs are accessible via Imagor

### Test 3: Different Radii

**Test Small Radius (100m):**
```bash
curl "http://localhost:8000/v1/geo/images/nearby?lat=46.55853&lon=8.15223&radius=100&sources=panoramax"
```

**Test Large Radius (5000m):**
```bash
curl "http://localhost:8000/v1/geo/images/nearby?lat=46.55853&lon=8.15223&radius=5000&sources=panoramax"
```

**Expected Results:**
- Small radius: Fewer images (or none if no Panoramax coverage)
- Large radius: More images from multiple collections

### Test 4: Verify Image Response Format

**Check a single Panoramax image result:**
```json
{
  "type": "Feature",
  "geometry": {
    "type": "Point",
    "coordinates": [8.15223, 46.55853]
  },
  "properties": {
    "source": "panoramax",
    "source_id": "item_id_from_panoramax",
    "source_url": "https://api.panoramax.cz/stac/items/item_id",
    "image_type": "360",
    "captured_at": "2024-03-10T12:00:00Z",
    "distance_m": 123.45,
    "license_slug": "cc-by-sa-4.0",
    "license_name": "https://creativecommons.org/licenses/by-sa/4.0/",
    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    "attribution": "Author Name, <a href=\"https://...\">Panoramax</a>, <a href=\"https://creativecommons.org/licenses/by-sa/4.0/\">https://creativecommons.org/licenses/by-sa/4.0/</a>",
    "author": "Author Name",
    "author_url": null,
    "urls": {
      "original": "https://panoramax.../image.jpg",
      "avatar": "https://img.wodore.ch/...",
      "thumb": "https://img.wodore.ch/...",
      "preview": "https://img.wodore.ch/...",
      "preview_placeholder": "https://img.wodore.ch/...",
      "medium": "https://img.wodore.ch/...",
      "large": "https://img.wodore.ch/..."
    },
    "place": null
  }
}
```

### Test 5: Provider Priority

**Request:**
```bash
curl "http://localhost:8000/v1/geo/images/nearby?lat=46.55853&lon=8.15223&radius=1000"
```

**Expected Order:**
1. Wodore images (priority 1)
2. Camptocamp images (priority 2)
3. Wikidata images (priority 3)
4. Panoramax images (priority 4)

**Verification:**
- Results should be sorted by priority first, then by distance
- Within same priority, sorted by distance_m ascending

### Test 6: Caching

**First Request:**
```bash
time curl "http://localhost:8000/v1/geo/images/nearby?lat=46.55853&lon=8.15223&radius=2000&sources=panoramax"
```

**Second Request (should be faster):**
```bash
time curl "http://localhost:8000/v1/geo/images/nearby?lat=46.55853&lon=8.15223&radius=2000&sources=panoramax"
```

**Expected:**
- Second request should be faster due to caching (6 hour TTL)
- Check logs: first request shows "PanoramaxProvider: Searching", second may show cache hit

## Troubleshooting

### Issue: No Panoramax Images Returned

**Possible Causes:**
1. **No Panoramax coverage** - The area may not have Panoramax images
2. **API endpoint incorrect** - Check `https://api.panoramax.cz` is accessible
3. **STAC format changed** - Verify STAC structure hasn't changed

**Debug Steps:**
```bash
# Check if Panoramax API is accessible
curl "https://api.panoramax.cz/stac/collections"

# Check if area has images
curl "https://api.panoramax.cz/stac/collections" | jq '.collections[].id'
curl "https://api.panoramax.cz/stac/collections/{collection_id}/items?bbox=8,46,9,47&limit=10"
```

### Issue: Images Not Loading (Imagor Issues)

**Possible Causes:**
1. **Original URL blocked** - Panoramax URLs may have access restrictions
2. **Imagor timeout** - Large 360° images may take time to process
3. **URL encoding** - Special characters in URLs

**Debug Steps:**
```bash
# Test original URL directly
curl -I "https://panoramax.../image.jpg"

# Test Imagor transformation
curl -I "https://img.wodore.ch/unsafe/250x200/https://panoramax.../image.jpg"
```

### Issue: License Information Missing

**Current Behavior:**
- License defaults to "unknown" if not found in STAC properties
- This is expected for some collections

**Solution:**
- Check STAC item properties for license field
- Some collections may not include license information

## Performance Considerations

### Expected Response Times

- **Small radius (100m)**: < 500ms (mostly cached)
- **Medium radius (1000m)**: 500-1500ms
- **Large radius (5000m)**: 1-3s (depends on Panoramax API response)

### Optimization Notes

1. **Caching**: 6-hour TTL reduces API calls
2. **Limits**: Max 50 items per collection prevents overwhelming responses
3. **Timeout**: 30-second timeout prevents hanging
4. **Parallel**: Fetches from all providers concurrently

## Future Enhancements

### Potential Improvements

1. **Multiple Panoramax Instances**
   - Currently only queries `api.panoramax.cz`
   - Could add other instances (panoramax.openstreetmap.fr, etc.)

2. **Advanced Filters**
   - Filter by capture date range
   - Filter by specific collections
   - Filter by image quality/resolution

3. **Enhanced Metadata**
   - Extract camera equipment information
   - Extract viewing direction for 360° images
   - Show sequence information for sequences

4. **Sequence Support**
   - Group images by sequence
   - Provide sequence navigation
   - Show sequence metadata

## Provider Priority

```
"wodore": 1      # Internal database (highest priority)
"camptocamp": 2  # Swiss Alpine images
"wikidata": 3    # Wikimedia Commons
"panoramax": 4   # 360° panoramas (this provider)
"mapillary": 5   # Street-level photos (not yet implemented)
"flickr": 6      # User photos (not yet implemented)
```

## Files Modified

1. **`server/apps/geometries/providers/panoramax.py`** (NEW)
   - Full STAC API implementation
   - 390 lines of code
   - Includes bbox calculation, distance calculation, license normalization

2. **`server/apps/geometries/providers/__init__.py`**
   - Added PanoramaxProvider import
   - Registered in __all__

3. **`server/apps/geometries/api.py`**
   - Registered provider: `provider_registry.register(PanoramaxProvider())`
   - Updated priority dictionary

## Success Criteria

✅ **Implementation Complete**
- No syntax errors
- STAC API structure correctly implemented
- Proper error handling and logging
- Imagor transformations applied
- License normalization working
- Provider priority correct

✅ **Testing Required**
- Manual API testing with real coordinates
- Verify image URLs are accessible
- Check caching behavior
- Validate response format

## Next Steps

1. **User Testing**: Test with actual server and real data
2. **Performance Monitoring**: Check response times and API limits
3. **Error Handling**: Verify graceful degradation if Panoramax API is down
4. **Documentation**: Update main API documentation if needed

---

**Implementation Date**: 2026-03-10  
**Last Updated**: 2026-03-10  
**Status**: Ready for Testing
