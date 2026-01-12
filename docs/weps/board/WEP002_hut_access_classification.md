---
draft: false
date:
  created: 2026-01-11
  updated: 2026-01-11
slug: wep002
categories:
  - WEP
  - Huts
  - Accessibility
tags:
  - WEP002
  - huts
  - accessibility
  - routing
  - classification
  - isochrones
---

# `WEP 2` Hut Access Classification

Transport mode categorization system for Alpine huts.
<!-- more -->

This should give for each hut a list of how it can be accessed:

* By foot (including difficulty)
* By mountain bike
* By ski
* By car
* Public transport (time ranges: <2h, <4h, <6h, <8h), covered in [WEP003](WEP003_public_transport_access.md)

## Reachability Test & Access Classification

**Goal:** Categorize huts by transport accessibility for display and filtering.

**Profiles to test:** foot, bike, car, ski, inaccessible.

**Workflow:**

1. Compute isochrone per hut for each profile.
2. If isochrone is empty or does not connect to main trail/road:
   * Mark as unreachable for that mode
3. Classify huts based on accessible modes:
   * Example:
     * "Easy hiking": reachable by `foot`
     * "Ski winter access": reachable by `ski``
     * "Bike": reachable by `bike` profile
     * "Car": reachable by `car` profile
     * "Alpine only": no accessible mode
4. Store classification in DB for fast filtering and visualization.

**Optional:** integrate difficulty factor for hiking or seasonal restrictions (ski season).

## Classification Examples

### Swiss Alpine Huts

* **Höhernmässli Hütte**: "Alpine only" (no road access, 4h hike)
* **Berggasthaus Aescher**: "Easy hiking" (cable car nearby, 15min walk)  
* **SAC Cabane Mont Fort**: "Ski winter access" (ski lift, 30min ski)

### Storage in PostGIS

```sql
CREATE TABLE hut_access_classifications (
    hut_id UUID REFERENCES huts(id),
    profile VARCHAR(20), -- foot, bike, car, ski
    accessible BOOLEAN,
    max_travel_time INTEGER, -- minutes
    difficulty_level VARCHAR(10), -- easy, moderate, difficult
    season VARCHAR(10), -- summer, winter, all
    updated_at TIMESTAMP
);
```

## Implementation Notes

* Use GraphHopper isochrone feature
* Store results in PostGIS with spatial indexing
* Update classifications seasonally (ski vs hiking profiles)
