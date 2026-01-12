---
draft: true
date:
  created: 2026-01-11
  updated: 2026-01-11
slug: wep003
categories:
  - WEP
  - Huts
  - Public Transport
tags:
  - WEP003
  - huts
  - public-transport
  - gtfs
  - accessibility
  - routing
---

# `WEP 3` Public Transport Access

GTFS integration and transit analysis for hut accessibility.
<!-- more -->

## Public Transport Close to Huts

**Goal:** Identify accessible transit stops for each hut, depending on seasonal access.

**Workflow:**

1. **Candidate selection**: find all PT stops within a radius (e.g., 30 km) of the hut.
2. **One-to-many matrix routing**: compute shortest paths from hut to each candidate stop using GraphHopper profiles (foot in summer, ski in winter).
3. **Filter unreachable stops**: remove stops that exceed maximum travel time (e.g., 5h) or dead-end edges.
4. **Store results in DB**:
   * `hut_id | stop_id | profile | travel_time | distance`
5. **User query**: when a user requests huts reachable by transit, check intersection between precomputed hut-accessible stops and user isochrone + GTFS availability.

**Advantages:**

* Reduces matrix calculations compared to full hut → all stops.
* Efficient even for hundreds of huts.
* Supports seasonal profiles.

## Implementation Notes

* Use GraphHopper one-to-many matrix API for hut → PT stop computations
* Use PostGIS spatial functions for intersection (ST_Intersects, ST_DWithin)
