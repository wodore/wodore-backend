---
draft: true
date:
  created: 2026-01-11
  updated: 2026-01-11
slug: wep004-external-source-routing
categories:
  - WEP
  - Routing
  - Data Sources
tags:
  - WEP004
  - routing
  - swisstopo
  - osm
  - hiking
  - ski-touring
  - data-integration
---

# `WEP 4` Routing on External Data Sources

Swisstopo data integration for hiking and ski touring routes.
<!-- more -->

## Swisstopo

This document describes a **practical, reproducible workflow** to convert SwissTopo hiking trail data (GPKG) into OSM-compatible data and use it with **Valhalla** for hiking routing. It also lays the foundation for later improvements such as **source preference** and **ski touring routing**.

### Data Source: swissTLM3D

The dataset is derived from **swissTLM3D** (Topographic Landscape Model of Switzerland).

#### Official Documentation

The [**Datensatzkatalog swissTLM3D (PDF)**](https://www.swisstopo.admin.ch/de/landschaftsmodell-swisstlm3d) defines:

* Feature classes
* Attribute names
* Value domains (coded values)
* Semantics of fields such as `wanderwege`, `befahrbarkeit`, `belagsart`, etc.

### Relevant fields

From your GPKG, the following fields are important for routing (from `TLM_STRASSEN`):

* `objektart` – **Way / road type including implied width**, expressed as a *named class* (e.g. *"1 m Weg"*, *"2 m Weg"*, *"Markierte Spur"*, *"Klettersteig"*)
* `wanderwege` – hiking route classification (*Wanderweg*, *Bergwanderweg*, *Alpinwanderweg*)
* `stufe` – **NOT hiking difficulty** (vertical / technical level at crossings)
* `befahrbarkeit` – passability / access
* `belagsart` – surface type
* `richtungsgetrennt` – direction-separated geometry
* `name` – trail name

All remaining fields are administrative metadata and are ignored for routing.

### Target OSM Tagging Model

Reference: [OSM Hiking Wiki](https://wiki.openstreetmap.org/wiki/Hiking)

#### Base tags (always applied)

```
highway=path
foot=yes
source=swisstopo
```

#### Hiking difficulty

SwissTopo **does not encode hiking difficulty in `stufe`**.

Difficulty is derived from **named classifications**:

* `wanderwege` (primary)
* `objektart` (secondary, e.g. *Klettersteig*)

These are mapped to `sac_scale`, which Valhalla understands natively:

| Swiss classification | OSM tag                   |
| -------------------- | ------------------------- |
| Wanderweg            | sac_scale=hiking          |
| Bergwanderweg        | sac_scale=mountain_hiking |
| Alpinwanderweg       | sac_scale=alpine_hiking   |

#### Access / passability

```
access=yes | no | permissive
```

#### Surface

```
surface=paved | gravel | ground | rock
```

#### Direction (only if applicable)

```
oneway=yes
```

#### Name

```
name=<trail name>
```

### Toolchain

#### Required tools

```bash
pip install ogr2osm
sudo apt install gdal-bin osmium-tool
```

#### Processing flow

```
GPKG (swisstopo)
  ↓ ogr2osm + translation script
OSM XML
  ↓ osmium
OSM PBF
  ↓ Routing service build
Routing
```

### Example ogr2osm Translation Script

Save as **`swisstopo_wanderwege.py`**

**Important notes:**

* `objektart` defines way type and width
* `stufe` is NOT used for hiking difficulty

This script generates clean OSM tags, maps hiking difficulty, handles access and surface, and produces routing-compatible data:

```python
def filter_tags(attrs):
    tags = {}

    # Base tags
    tags["highway"] = "path"
    tags["foot"] = "yes"
    tags["source"] = "swisstopo"

    # Name
    if attrs.get("name"):
        tags["name"] = attrs["name"]

    # Objektart → way type / width (use names, not IDs)
    objektart = str(attrs.get("objektart", "")).lower()

    if "1 m weg" in objektart:
        tags.update({"highway": "path", "width": "1"})
    elif "2 m weg" in objektart:
        tags.update({"highway": "path", "width": "2"})
    elif "markierte spur" in objektart:
        tags.update({"highway": "path", "trail_visibility": "good"})
    elif "klettersteig" in objektart:
        tags.update({
            "highway": "via_ferrata",
            "sac_scale": "demanding_alpine_hiking"
        })
    elif "fahrstrasse" in objektart or "strasse" in objektart:
        tags.update({"highway": "track"})

    # Wanderwege → sac_scale (authoritative)
    wanderwege = str(attrs.get("wanderwege", "")).lower()

    if "wanderweg" in wanderwege:
        tags["sac_scale"] = "hiking"
    elif "bergwanderweg" in wanderwege:
        tags["sac_scale"] = "mountain_hiking"
    elif "alpinwanderweg" in wanderwege:
        tags["sac_scale"] = "alpine_hiking"

    # Access / passability
    befahrbarkeit = str(attrs.get("befahrbarkeit", "")).lower()
    if befahrbarkeit in ("wahr", "true", "ja"):
        tags["access"] = "yes"
    elif befahrbarkeit in ("falsch", "false", "nein"):
        tags["access"] = "no"
    else:
        tags["access"] = "permissive"

    # Surface
    belag = str(attrs.get("belagsart", "")).lower()
    if "asphalt" in belag or "beton" in belag:
        tags["surface"] = "paved"
    elif "kies" in belag or "schotter" in belag:
        tags["surface"] = "gravel"
    elif "fels" in belag or "felsen" in belag:
        tags["surface"] = "rock"
    else:
        tags["surface"] = "ground"

    # Direction separation
    if str(attrs.get("richtungsgetrennt", "")).lower() in ("ja", "true", "1"):
        tags["oneway"] = "yes"

    return tags
```

#### Run the conversion

```bash
ogr2osm wanderwege.gpkg \
  -t swisstopo_wanderwege.py \
  -o wanderwege.osm
```

Convert to PBF:

```bash
osmium cat wanderwege.osm -o wanderwege.pbf
```

## Data Sources & Access

### Swisstopo Data Portal

* **swissTLM3D**: Authoritative topographic landscape model
* **Download**: [swisstopo geoportal](https://shop.swisstopo.admin.ch/)
* **License**: Free for non-commercial use, requires registration

### GTFS for Switzerland

* **SBB/CFF/FFS**: [opentransportdata.swiss](https://opentransportdata.swiss/)
* **Regional providers**: Various cantonal transport operators
* **Update frequency**: Daily for major operators

## Next Steps

* Create GraphHopper and BRouter custom profiles
* Add trail running bias for running-specific routing
* Implement ski touring routing with winter-specific data
* Integrate seasonal data updates (summer/winter trail networks)
