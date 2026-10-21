# MapProxy raster tile facades (dev stack)

One MapProxy instance, three raster layers for the wodore basemaps —
part of the dev `docker compose up` stack (like martin), serving on
port **8091**:

| Layer | Content | Format |
|---|---|---|
| `world_topo` | OpenTopoMap (worldwide) merged with basemap.at (AT) and swisstopo pixelkarte (CH+LI), pixel-perfect country clips | **WebP** |
| `world_satellite` | ESRI World Imagery | **WebP** |
| `europe_topo` | legacy PNG alias of the same merge (frontend demo basemap name) | PNG |

```
tiles: http://localhost:8091/mapproxy/tiles/world_topo/webmercator/{z}/{x}/{y}.webp
       http://localhost:8091/mapproxy/tiles/world_satellite/webmercator/{z}/{x}/{y}.webp
       http://localhost:8091/mapproxy/tiles/europe_topo/webmercator/{z}/{x}/{y}.png
```

The wodore styles reference the facades via implementation-agnostic
`/raster/tiles/...` paths — an edge route rewrites them to mapproxy in
staging/prod; the lane dev tile router does it in development. The
prod reference is the burginfra martin nginx-cache tier
(`k8s/apps/wodore/apps/martin/base/nginx-cache-config.conf`):

```nginx
# Stable raster facade: /raster/* -> the mapproxy backend
# (served under its internal /mapproxy/ prefix). Swap the
# upstream here to replace the implementation without changing
# any client URL.
location /raster/ {
    rewrite ^/raster/(.*)$ /mapproxy/$1 break;
    proxy_pass http://wd-mapproxy:80;
    expires 7d;
    add_header Cache-Control "public, immutable";
    # + the shared proxy_cache tiles tier; the cache key includes
    # the query string, so the styles' ?v=N param busts every layer
    # (edge tier + browser immutable caches) at once.
}
```

Dev (lane tile router, `/tmp/lane-tile-router/router.conf`) mirrors
this: `/raster/*` → `django-local-mapproxy`, everything else →
martin-lane, with the same 7d immutable browser caching.

## WebP serving (recipe from the burginfra kapproxy deployment)

* caches declare `format: image/webp` with `request_format: image/png`
  (merge canvas with alpha) and `image: transparent: false`
* the raster URL template must end in `.webp` — only that extension
  is routable on the `/tiles` (XYZ, top-left origin) endpoint
* **single-source passthrough gotcha**: `TileCreator._query_sources`
  shortcuts single sources *without a clipping coverage* — the raw
  source bytes are then stored undecoded. Fine for detectable formats
  (OpenTopoMap `.png` re-encodes to webp), but the extensionless ESRI
  tile URL makes the format undetectable and raw jpeg bytes would be
  served under the `.webp` route (browsers sniff and render, but no
  size win). The `esri_world_imagery` source therefore carries a
  world-wide coverage with `clip: true` — a visual no-op that forces
  the merge path and guarantees real WebP (~20% smaller than the jpeg
  passthrough at equal quality).
* MapProxy 7.0.0 gotchas: single-cache layers, no num_levels
  overrides, file cache (not mbtiles), nw origin for XYZ.

## Pre-seeding (optional)

`seed.yaml` pre-warms the `europe_topo` cache z0–12 (~5 GB):

```
docker compose exec mapproxy mapproxy-seed -f /mapproxy/config/mapproxy.yaml /mapproxy/config/seed.yaml
```

(The mount in docker-compose.yml only exposes `mapproxy.yaml`,
the boundary geojsons and `cache_data/`; add a seed mount when
needed.)

The cache directory (`cache_data/`) is a bind volume — after a
`format:` change, wipe it so old tiles do not linger in the previous
encoding.
