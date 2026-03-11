# Image Provider Enhancements - Implementation Plan

## Overview

This document outlines the enhancements needed for image URLs and source tracking across all providers.

## Changes Required

### 1. **ImageResult Dataclass** (base.py) ✅ COMPLETED

**Added fields**:
- `width: int | None` - Image width in pixels
- `height: int | None` - Image height in pixels  
- `is_portrait: bool | None` - True if height > width
- `source_found: list[str] | None` - Sources where image was found
- `source_organization: dict[str, Any] | None` - Organization info
- **Removed**: `author_url` (no longer needed)

### 2. **ImagePropertiesSchema** (_images.py) ✅ COMPLETED

**Updated URLs structure**:
```python
# Old structure (removed):
- avatar
- thumb
- preview
- preview_placeholder
- medium
- large

# New structure:
{
  "original": str,
  "placeholder": str | None,
  "portrait": {
    "small": str,
    "medium": str,
    "large": str
  } | None,
  "landscape": {
    "small": str,
    "medium": str,
    "large": str
  } | None,
  "preferred": str | None  # Auto-selected based on orientation
}
```

**Added fields**:
- `width: int | None`
- `height: int | None`
- `is_portrait: bool | None`
- `source_found: list[str] | None`
- `source_organization: dict[str, Any] | None`
- **Removed**: `author_url`

### 3. **Provider Updates Needed**

Each provider needs to be updated to:

1. **Remove `author_url`** from ImageResult calls
2. **Extract dimensions** from API responses
3. **Calculate orientation** (is_portrait = height > width)
4. **Generate new URL structure** with portrait/landscape variants
5. **Add source tracking** (source_found, source_organization)

#### Panoramax Provider
- ✅ Already has width/height in assets
- Update URL generation to use new structure
- Remove author_url parameter

#### Wikimedia Commons Provider  
- ✅ Already has width/height in imageinfo
- Add source_found=["wikidata"] or ["commons"]
- Add source_organization from provider metadata
- Update URL generation

#### Camptocamp Provider
- Extract dimensions from image details API
- Add source_found=["camptocamp"]
- Update URL generation
- Remove author_url

#### Wodore Provider
- Extract dimensions from Image model
- Add source_found=["wodore"]
- Add source_organization from internal data
- Update URL generation

### 4. **URL Generation Logic**

```python
def generate_image_urls(image_url: str, width: int, height: int) -> dict:
    """Generate orientation-aware image URLs."""
    from server.apps.images.transfomer import ImagorImage

    imagor_img = ImagorImage(image_url)
    is_portrait = height > width if width and height else None

    urls = {
        "original": image_url,
        "placeholder": imagor_img.transform(
            size="300x200", quality=5, blur=3
        ).get_full_url(),
    }

    if is_portrait:
        urls["portrait"] = {
            "small": imagor_img.transform(size="250x400").get_full_url(),
            "medium": imagor_img.transform(size="400x640").get_full_url(),
            "large": imagor_img.transform(size="600x960").get_full_url(),
        }
    else:
        urls["landscape"] = {
            "small": imagor_img.transform(size="400x250").get_full_url(),
            "medium": imagor_img.transform(size="640x400").get_full_url(),
            "large": imagor_img.transform(size="960x600").get_full_url(),
        }

    urls["preferred"] = (
        urls.get("portrait", {}).get("medium") if is_portrait
        else urls.get("landscape", {}).get("medium")
    )

    return urls, width, height, is_portrait
```

### 5. **Source Organization Example**

```python
# For Wikimedia Commons
source_organization = {
    "name": "Wikimedia Foundation",
    "url": "https://wikimediafoundation.org/",
    "logo": "https://commons.wikimedia.org/wiki/Commons:Logo.svg"
}

# For Camptocamp
source_organization = {
    "name": "Camptocamp",
    "url": "https://www.camptocamp.org/",
    "logo": "https://www.camptocamp.org/assets/logo.png"
}
```

## Implementation Priority

### Phase 1: Critical (Do Now)
1. ✅ Update ImageResult dataclass
2. ✅ Update ImagePropertiesSchema
3. Remove `author_url` from all ImageResult calls
4. Update ImageResult to_feature() to pass new fields

### Phase 2: High Priority (Next Session)
1. Update URL generation for Panoramax (has dimensions)
2. Update URL generation for Wikimedia Commons (has dimensions)
3. Extract dimensions and add to ImageResult

### Phase 3: Medium Priority
1. Update URL generation for Camptocamp
2. Update URL generation for Wodore
3. Add source_found tracking
4. Add source_organization data

### Phase 4: Low Priority (Future)
1. Update stub providers (Flickr, Mapillary)
2. Add comprehensive source mapping
3. Add source_requested logic

## Migration Notes

**Breaking Changes**:
- Frontend must update to use new URL structure
- `author_url` field removed from API response
- New orientation-based URLs require frontend updates

**Backward Compatibility**:
- Can add old avatar/thumb/preview fields alongside new structure during transition
- Frontend can check for both old and new formats

## Testing Checklist

After implementation:
- [ ] Panoramax images show portrait/landscape URLs
- [ ] Wikimedia Commons images include dimensions
- [ ] Camptocamp attribution no longer shows dict
- [ ] All images have orientation detected
- [ ] Preferred URL returns correct orientation
- [ ] Source tracking appears in responses
