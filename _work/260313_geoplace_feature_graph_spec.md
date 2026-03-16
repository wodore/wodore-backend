
# GeoPlace Feature Graph Specification

## Overview

The **feature graph** introduces semantic relationships between geographic entities in the system.
It allows efficient querying of spatial hierarchies and contextual relationships without relying on expensive spatial operations.

The design builds on the existing **GeoPlace** and **Category** models and does **not require a separate relation-type model**, because the existing `Category` hierarchy can define relation semantics.

The system therefore consists of three main concepts:

* **GeoPlace** – geographic entities (POIs, villages, stops, peaks, huts, etc.)
* **Category** – classification and relation semantics
* **Associations** – linking GeoPlaces to other entities using a category-defined relation

This creates a lightweight **semantic graph of geographic features**.

---

# Goals

The feature graph should enable:

* Fast hierarchical queries without spatial operations
* Flexible semantic relationships between entities
* Extensibility for new entity types (routes, organizations, regions)
* Reuse of the existing **Category model for relation types**
* Simple relational queries and strong referential integrity

---

# Core Concept

A **relationship** connects two entities using a **Category that defines the relation type**.

Example:

```
Monte Rosa Hut ── located_in ──> Zermatt
Monte Rosa Hut ── owned_by ──> SAC
Bus Stop A ── serves ──> Village B
Route X ── passes ──> Monte Rosa Hut
```

Each edge consists of:

```
source_entity
target_entity
relation_category
```

---

# Relation Types via Category

Relation semantics are defined by the existing **Category model**.

Example category hierarchy:

```
relations
 ├─ located_in
 ├─ part_of
 ├─ owned_by
 ├─ serves
 ├─ access_point
 ├─ near
 └─ passes
```

These categories describe **how two entities are related**.

Because `Category` already supports hierarchy, relation groups can be organized naturally.

Example:

```
relations
 ├─ spatial
 │   ├─ located_in
 │   ├─ part_of
 │   └─ near
 │
 ├─ infrastructure
 │   ├─ serves
 │   └─ access_point
 │
 └─ ownership
     └─ owned_by
```

---

# GeoPlace Relationships

A dedicated association table links two GeoPlaces.

Conceptual structure:

```
GeoPlaceRelation
    from_geoplace
    to_geoplace
    relation_category
```

Example records:

| From  | Relation   | To           |
| ----- | ---------- | ------------ |
| Hut   | located_in | Valley       |
| Hut   | located_in | Municipality |
| Hut   | owned_by   | SAC          |
| Stop  | serves     | Village      |
| Route | passes     | Hut          |

---

# Category Relationships

The existing **GeoPlace ↔ Category** relationship already describes feature classification.

Example:

```
GeoPlaceCategory
    geoplace
    category
```

Example records:

| GeoPlace | Category   |
| -------- | ---------- |
| Hut      | alpine_hut |
| Hut      | restaurant |
| Hut      | toilet     |

This remains unchanged but can be extended with an optional **relation role** if needed.

Example:

```
GeoPlaceCategory
    geoplace
    category
    role (primary / amenity / facility)
```

---

# Route Relationships

Routes typically have different properties (LineString geometry, ordered nodes).
They should therefore remain a separate model.

Example:

```
Route
    geometry
    metadata
```

Routes can connect to GeoPlaces using a relation table:

```
RouteRelation
    route
    geoplace
    relation_category
```

Example relations:

| Route        | Relation  | GeoPlace |
| ------------ | --------- | -------- |
| Tour Route   | passes    | Hut      |
| Hiking Trail | starts_at | Village  |
| Hiking Trail | ends_at   | Summit   |

---

# Example Graph

```
Monte Rosa Hut
    ├─ located_in → Zermatt
    ├─ located_in → Valais
    ├─ owned_by → SAC
    └─ near → Glacier

Zermatt
    └─ part_of → Valais

Route A
    ├─ passes → Monte Rosa Hut
    └─ starts_at → Zermatt
```

---

# Benefits

## Faster Queries

Spatial queries:

```
ST_Within(hut, municipality)
```

Graph queries:

```
hut → located_in → municipality
```

Graph queries avoid expensive geometry operations.

---

## Flexible Relationships

Supports many relationship types:

* administrative hierarchy
* ownership
* infrastructure connections
* route connections
* proximity relationships

---

## Extensible System

New entity types can be introduced without redesigning the schema.

Examples:

```
Organization
MountainRange
TransportLine
Route
```

They simply participate in relationships.

---

# Typical Queries

### Find huts in a valley

```
hut → located_in → valley
```

### Find huts owned by SAC

```
hut → owned_by → SAC
```

### Find huts along a route

```
route → passes → hut
```

### Find stops serving a village

```
stop → serves → village
```

---

# Relation Generation

Relations can be generated automatically during import.

Examples:

### Spatial containment

```
if ST_Within(place, municipality):
    create relation located_in
```

### Proximity

```
if distance(stop, village) < 200m:
    create relation serves
```

### Source metadata

```
osm operator tag → owned_by
```

---

# Indexing

Recommended indexes:

```
GeoPlaceRelation(from_geoplace)
GeoPlaceRelation(to_geoplace)
GeoPlaceRelation(relation_category)
```

These allow fast lookup for graph traversal.

---

# Design Principles

The feature graph follows these principles:

* reuse existing **Category model**
* avoid polymorphic relations
* maintain strong foreign keys
* keep entity models independent
* support future entity types

---

# Result

The system becomes a **lightweight geographic knowledge graph** built on top of relational models.

It enables:

* hierarchical geographic queries
* fast lookups without spatial operations
* extensible semantic relationships
* integration of routes, infrastructure, and organizations
