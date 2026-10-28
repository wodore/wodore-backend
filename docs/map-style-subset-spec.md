# Map style subset spec (profile `subset`, revision 0.1)

The map layer catalog serves styles in two profiles
([`style-profiles-subset`](https://github.com/wodore/wodore-backend/blob/main/openspec/changes/style-profiles-subset/)
design D1–D4): `full` — complete
[MapLibre style spec v8](https://maplibre.org/maplibre-style-spec/) documents —
and `subset` — a strict, machine-checkable subset renderable by a
Leaflet-class engine (the no-WebGL fallback map, frontend PRs #352/#359).
A subset document is a valid full MapLibre style **by construction**;
any full renderer can consume it. One deliberate qualification: the
wodore/Martin `encoding: "mlt"` vector-source marker is our extension
(stock validators ignore unknown source keys).

This document is the human-readable mirror of the enforcement code:
the pure-Python walker in
`server/apps/basemaps/validation.py` (`validate_subset_style`) is the
authority; if this page and the walker disagree, the walker wins and
this page gets fixed.

## Top-level keys

| Allowed key | Notes |
| --- | --- |
| `version` | must be `8` (structural check, both profiles) |
| `name`, `metadata` | free-form |
| `sources`, `layers` | see below |
| `sprite`, `glyphs` | may sit unused on raster-only documents (the seeded raster styles carry `glyphs`) |

Everything else — `terrain`, `sky`, `light`, `projection`, … — is out.
Compare the [full style root structure](https://maplibre.org/maplibre-style-spec/).

## Sources

Closed key sets per type (see the [sources chapter](https://maplibre.org/maplibre-style-spec/sources/)):

| Type | Allowed keys | Notes |
| --- | --- | --- |
| `raster` | `type`, `tiles`, `maxzoom`, `tileSize`, `attribution` | |
| `vector` | `type`, `tiles`, `minzoom`, `maxzoom`, `attribution`, `encoding` | inline MLT tile URLs (`.mlt` URL space) with `encoding: "mlt"` (value enforced); single `source-layer` consumed by layers; **no TileJSON `url` links** |
| `geojson` | `type`, `data` | `data` must be a URL **string** (inline data objects are out); `{{token}}` runtime params allowed inline, e.g. `?date={{date}}` |

`promoteId` is deliberately not whitelisted — clients key features by
the tile-provided id.

## Layers

Allowed layer keys: `id`, `type`, `source`, `source-layer`, `minzoom`,
`maxzoom`, `paint`, `layout` (see the
[layers chapter](https://maplibre.org/maplibre-style-spec/layers/)).

**Layer types**: `raster`, `circle`, `symbol` (sprite-pack icon +
simple text). `fill`, `fill-extrusion`, `line`, `heatmap` are out.

**Layout keys per type** — `raster`/`circle`: none; `symbol`:
`icon-image`, `icon-size`, `icon-allow-overlap`, `text-field`,
`text-font`, `text-size`, `text-anchor`, `text-offset`. SDF text layout
properties (variable anchors, letter spacing, …) are out, as is
`layout.visibility`.

**Paint properties** (closed set; `icon-size`/`text-size` are layout
properties in the full spec but are accepted in either slot here):

- circle: `circle-color`, `circle-radius`, `circle-opacity`,
  `circle-stroke-color`, `circle-stroke-width`
- raster: `raster-opacity`, `raster-fade-duration`
- symbol: `icon-size`, `icon-color`, `icon-opacity`, `icon-translate`,
  `text-size`, `text-color`, `text-opacity`, `text-halo-color`,
  `text-halo-width`, `text-translate`

## Expressions

Recursive, any depth (see the
[expressions chapter](https://maplibre.org/maplibre-style-spec/expressions/)):

- Operators: `get`, `has`, `match`, `case`, `in`, `==`, `interpolate`,
  `literal`.
- `interpolate` accepts **zoom input only**:
  `["interpolate", ["linear"], ["zoom"], z1, v1, …]` with literal
  number zoom stops; `["linear"]` is legal only inside `interpolate`.
- Expression vs literal array follows MapLibre's own rule, by shape: a
  list whose first element is a lowercase/hyphenated identifier
  (operator name shape) is an expression — anything else
  (`["Noto Sans Regular"]` for `text-font`, numeric pairs) is a literal
  array and must contain scalars only.
- `match` labels and `in` haystacks accept a scalar, a literal SET of
  scalars (`["residential", "service"]`) or an expression with a
  whitelisted operator head — plain label strings are the common case
  and are not misread as operator names in these positions.
- Standalone `"{{slug}}"` parameter token nodes are valid wherever a
  value is expected.
- Out: `feature-state`, `image`, `coalesce`, data-driven paint outside
  the whitelist, and every operator not listed above.

## Worked examples

### (a) Minimal valid subset raster overlay

```json
{
  "version": 8,
  "name": "mtb",
  "sources": {
    "wd-mtb": {
      "type": "raster",
      "tiles": ["https://tile.waymarkedtrails.org/mtb/{z}/{x}/{y}.png"],
      "tileSize": 256,
      "maxzoom": 18
    }
  },
  "glyphs": "{{env:MARTIN_TILE_URL}}/font/{fontstack}/{range}",
  "layers": [
    {
      "id": "wd-mtb",
      "type": "raster",
      "source": "wd-mtb",
      "minzoom": 8,
      "paint": { "raster-opacity": "{{mtb.opacity}}" }
    }
  ]
}
```

### (b) The availability status disc — `match` on `d0_status`

The `wd-huts-occupation` shape (circle color from a feature property;
vector MLT source):

```json
{
  "version": 8,
  "name": "occupation",
  "sources": {
    "wd-bookings": {
      "type": "vector",
      "tiles": ["{{env:MARTIN_TILE_URL}}/availability/{z}/{x}/{y}.mlt?date={{date}}&days=4"],
      "encoding": "mlt",
      "minzoom": 5,
      "maxzoom": 9
    }
  },
  "layers": [
    {
      "id": "wd-huts-occupation",
      "type": "circle",
      "source": "wd-bookings",
      "source-layer": "default",
      "paint": {
        "circle-color": [
          "match", ["get", "d0_status"],
          "available", "#346751",
          "full", "#C60018",
          "#888888"
        ]
      }
    }
  ]
}
```

### (c) `transport-stops`-style circle — `case`/`in`/`get` + zoom `interpolate`

```json
{
  "version": 8,
  "name": "transport-stops",
  "sources": {
    "transport-stops": {
      "type": "geojson",
      "data": "https://example.org/bav_list.geojson"
    }
  },
  "layers": [
    {
      "id": "transport-stops",
      "type": "circle",
      "source": "transport-stops",
      "paint": {
        "circle-color": [
          "case",
          ["in", "train", ["get", "types"]], "#C60018",
          ["in", "bus", ["get", "types"]], "#2d327d",
          "#0079C7"
        ],
        "circle-radius": [
          "interpolate", ["linear"], ["zoom"],
          7, ["case", ["in", "train", ["get", "types"]], 3, 1],
          16, 9
        ]
      }
    }
  ]
}
```

(The seeded document additionally carries `promoteId` and a default
`layout.visibility` — a subset variant is a trivial re-author: drop
both.)

### (d) Invalid — rejected with the walker's reason

```json
{
  "version": 8,
  "name": "bad",
  "sources": {"x": {"type": "geojson", "data": "https://example.org/x.geojson"}},
  "layers": [
    {
      "id": "x",
      "type": "circle",
      "source": "x",
      "paint": {"circle-color": ["feature-state", "color"]}
    }
  ]
}
```

Walker rejection: `layers[0].paint.circle-color: operator 'feature-state'
is not whitelisted (subset v0.1)` — `feature-state` requires renderer
state a Leaflet-class engine does not keep. A `fill` layer instead
yields `layers[0].type: layer type 'fill' is not whitelisted (allowed:
circle, raster, symbol)`.

## Clustering — `config.clustering`

Clustering is a **layer-config rendering hint**, never style-document
content (the MapLibre spec allows `cluster` only on geojson sources; on
a vector source it would break subset validity). It rides the overlay
row's `config` JSONB and serves two modes with one schema: client-side
clustering today, precomputed DB clusters later (same properties read
from cluster features — config unchanged).

```json
"config": {
  "clustering": {
    "enabled": true,
    "source": "wd-huts",
    "groupByProperty": "type_standard_slug",
    "radius": 48,
    "maxZoom": 11,
    "bubble": {
      "colorProperty": "type_standard_color",
      "iconProperty": "type_standard_identifier",
      "countProperty": "point_count"
    }
  }
}
```

- `groupByProperty` — only features sharing the value cluster together
  (huts / self-catering huts / tents …); features lacking the property
  form one null bucket.
- `bubble` — either **property references** (renderer computes the
  dominant value per group; deterministic category color/icon when
  grouped) or **literal fallbacks**:
  `"bubble": {"color": "#346751", "icon": "mono/accommodation.unknown"}`.

## Versioning: `profile` + `version`

Each variant row records the **rules its document was validated
against** in `version` — unrelated to the document's internal
`"version": 8` and to the payload's `style_version` cache token:

| Profile | `version` value | Meaning |
| --- | --- | --- |
| `full` | a `@maplibre/maplibre-gl-style-spec` release, e.g. `26.4.4` | validated against that spec release (styl) |
| `subset` | the subset revision, currently `0.1` | validated against this whitelist (`SUBSET_REVISION`) |

Widening the whitelist bumps the subset revision (`0.2`, …) and rows
re-validate against the new rules — widening is additive, no client
breaks (a subset row never displaces a full row for full-capable
clients at the same tier).

## Validation flow (summary)

- **Saves** (`MapLayer.clean()`): structural checks → parameter-token
  check → subset walker (subset rows) → styl (best-effort subprocess
  when a binary is on PATH; E-codes block unless on the row's
  `styl_ignored_rules` list, `["*"]` skips styl entirely; W-codes
  surface next to a blocking error). Absent binary: silent skip.
- **Seed** (`map_seed`): walker + styl called directly in the upsert
  (update_or_create bypasses clean()); external-derived rows carry
  `styl_ignored_rules: ["*"]`.
- **CI**: `validate_map_styles` sweep in the tests job (no styl binary
  required); the `map-style-spec` job hard-gates authored full styles
  with styl over the `dump_map_styles` output + fixtures. The seed's
  `["*"]` rows are the single source of truth: the dump skips them and
  writes `_skipped.txt`, which also gates the static fixture files (the
  one fixture without a seed row — `wd-outdoor-base-ofm`, retired by
  migration 0007 — is skipped explicitly).

See the basemaps section in `AGENTS.md` for the one-paragraph flow.
