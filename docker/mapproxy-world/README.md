# MapProxy "World" — WebP tile facades for the wodore basemaps

Two raster services the wodore-backend basemap fixtures reference via
the implementation-agnostic `/raster/tiles/` facade paths:

| Layer | Content | Encoding |
|---|---|---|
| `world_topo` | OpenTopoMap (worldwide) merged with basemap.at (AT) and swisstopo pixelkarte (CH), pixel-perfect country clips — same recipe as the europe-topo facade, under the name the wd styles expect | real WebP (multi-source merge always re-encodes) |
| `world_satellite` | ESRI World Imagery, cached | real WebP (see the clip trick below) |

```
docker compose up -d
tiles: http://localhost:8091/mapproxy/tiles/world_topo/webmercator/{z}/{x}/{y}.webp
       http://localhost:8091/mapproxy/tiles/world_satellite/webmercator/{z}/{x}/{y}.webp
```

## WebP serving (recipe from the burginfra k8s mapproxy deployment)

* caches declare `format: image/webp` with `request_format: image/png`
  (merge canvas with alpha) and `image: transparent: false`
* the raster URL template must end in `.webp` — only that extension
  is routable on the `/tiles` (XYZ, top-left origin) endpoint
* **single-source passthrough gotcha**: `TileCreator._query_sources`
  shortcuts single sources *without a clipping coverage* — the raw
  source bytes are then stored undecoded. Fine for detectable formats
  (e.g. OpenTopoMap `.png` re-encodes to webp), but the extensionless
  ESRI tile URL makes the format undetectable and raw jpeg bytes
  would be served under the `.webp` route (browsers sniff and render,
  but no size win). The `esri_world_imagery` source therefore carries
  a world-wide coverage with `clip: true` — a visual no-op that
  forces the merge path and guarantees real WebP everywhere
  (~20% smaller than the jpeg passthrough at equal quality).
* MapProxy 7.0.0 gotchas (same as mapproxy-eu-topo): single-cache
  layers, no num_levels overrides, file cache (not mbtiles), nw
  origin for XYZ.

## Deployment notes

* The lane dev tile router (wodore-backend `lane-tile-router`, nginx)
  proxies `/raster/tiles/*` here; staging/prod need the same edge
  route (see the backend work doc).
* The cache directory (`cache_data/`) is a docker volume — after a
  `format:` change, wipe it (`rm -rf cache_data/world_*`) so old
  tiles do not linger in the previous encoding.
