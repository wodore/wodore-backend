---
draft: false
date:
  created: 2026-01-11
  updated: 2026-01-11
slug: wep001
categories:
  - WEP
  - Routing
  - Infrastructure
tags:
  - wep001
  - routing
  - graphhopper
  - valhalla
  - gtfs
  - isochrones
---

# `WEP 1` Routing Service

Core routing engine selection and architecture for Alpine accessibility analysis.
<!-- more -->

## Requirements

* Support for **transit data (GTFS)** with time-dependent routing
* Strong support for **outdoor profiles** (hiking, biking, ski touring)
* Ability to **integrate external data sources** (e.g. Swisstopo hiking trails, ski routes)
* **Custom routing profiles** and weighting (e.g. prefer ski routes, hiking difficulty)
* **Low memory consumption** during graph build and runtime (< 4 GB target)
* **Isochrone generation**, including **transit isochrones**
* **Matrix calculations** (one-to-many, many-to-many)

## Options

### Valhalla

**Overview**
Valhalla is a tile-based routing engine developed by Mapbox, with strong native support for multimodal and public transport routing.

**Advantages**

* First-class **GTFS transit routing** and **transit isochrones**
* Very efficient runtime performance for transit queries
* Tile-based architecture allows partial loading at runtime
* Good default support for car, bike, and pedestrian routing

**Limitations**

* GTFS data is **baked into transit tiles** and must be rebuilt on update
* Frequent GTFS updates are operationally expensive
* Custom outdoor profiles (e.g. ski touring) require **C++ costing model changes**
* Integration of external vector data is complex

**Link**
[https://github.com/valhalla/valhalla](https://github.com/valhalla/valhalla)

### GraphHopper

**Overview**
GraphHopper is a flexible Java-based routing engine with strong support for custom profiles, external data, and precomputation workflows.

**Advantages**

* Excellent support for **custom profiles** via Custom Models (YAML)
* Clear separation between:

  * **Hard profiles** (encoded values, schema, external data – require rebuild)
  * **Soft profiles** (weighting and preferences – no rebuild required)
* Can integrate **external vector data** (e.g. Swisstopo hiking and ski routes)
* Supports **isochrones** and **matrix routing** (one-to-many, many-to-many)
* GTFS transit data is **preprocessed offline** and **loaded at startup**
* Allows **frequent GTFS updates** without rebuilding the road graph
* Lower memory footprint than Valhalla for non-transit-heavy use cases
* Well suited for **static precomputation** (hut isochrones, reachability)

**Limitations**

* Transit isochrones are less mature and slower than Valhalla
* GTFS updates still require preprocessing
* New tags or schema changes require a graph rebuild

**Link**
[https://github.com/graphhopper/graphhopper](https://github.com/graphhopper/graphhopper)

### BRouter

**Overview**
BRouter is a lightweight routing engine focused on biking and hiking, widely used in outdoor navigation tools.

**Advantages**

* Very **low memory usage**
* Highly flexible **programmable profiles**
* Excellent routing quality for hiking and biking
* Fast for single-route calculations

**Limitations**

* No native support for transit
* No isochrones or matrix calculations
* Limited API and server-side capabilities

**Link**
[https://github.com/abrensch/brouter](https://github.com/abrensch/brouter)

### Other Options (Brief)

#### pgRouting

* PostgreSQL-based routing extension
* Useful for custom graph experiments
* Not suitable for large-scale or transit routing

Link: [https://pgrouting.org/](https://pgrouting.org/)

#### OpenTripPlanner (OTP)

* Strong public transport routing
* Heavy memory requirements
* Less flexible for custom outdoor profiles

Link: [https://www.opentripplanner.org/](https://www.opentripplanner.org/)

## Preliminary Conclusion

* **GraphHopper** is the preferred primary routing engine due to:

  * Flexible handling of outdoor and Alpine-specific profiles
  * Practical integration of external data sources (Swisstopo)
  * Clear distinction between build-time schema and runtime weighting
  * Easier and more frequent GTFS updates compared to Valhalla
* **BRouter** can be optionally combined for high-quality hiking and biking time estimation.
* **Valhalla** remains a strong alternative if public transport routing and transit isochrones become the dominant requirement, but at the cost of reduced flexibility and higher operational complexity.

## Infrastructure Integration

### Docker Deployment

* **Memory Target**: < 4 GB RAM for routing service
* **Storage**: PostGIS database for isochrones and results
* **Updates**: Automated GTFS data refresh pipeline

### Performance Targets

* **Single Route**: < 500ms response time
* **Isochrone**: < 2s for 4h radius
* **Matrix (1:100)**: < 10s for hut accessibility analysis
