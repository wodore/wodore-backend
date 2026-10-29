# Tasks: geoplace-category-tree

> Claude review applied (needs-fixes verdict): 3 P0 critical bugs,
> 3 P1 breaking, 5 P2 missing consumers, 2 P3 design guards.
> Categories staging-only: drop + reimport.

## 1. Schema & seed

- [ ] 1.1 `CategoryKindContract` model: OneToOne on Category (the
      contract group), `allowed_classifiers` M2M to Category with
      `limit_choices_to={"parent__isnull": True}` (P0-F1: vocabulary
      roots are parentless — the map-tree traversal filter shows
      nothing), `has_operations`/`has_seasonality` booleans; migration
- [ ] 1.2 Seed migration: create `map` namespace root → `amenity`/
      `admin`/`natural` super-roots → re-parent existing root
      categories under the appropriate super-root → seed contracts
      from `PLACE_KINDS` → mark super-roots + map root `is_protected`
- [ ] 1.3 `GeoPlace.detail_type` → `kind_slug`: rename migration +
      drop enum check constraint (free-form slug, indexed) + update
      GeoPlace.Meta index (P2-F11) + update tiles_view.py model
      field (P2-F9) + update forms.py admin fieldset (P2-F8)

## 2. Contract-driven validation & resolution fixes

- [ ] 2.1 `kind_for()` reads the DB contract instead of `PLACE_KINDS`
      (code registry becomes seed source only); classifier validation
      reads `CategoryKindContract.allowed_classifiers` M2M
- [ ] 2.2 GeoPlaceOperation writes check `has_operations`;
      GeoPlaceSeasonality writes check `has_seasonality`
- [ ] 2.3 `place_detail_type()` → `place_kind_slug()`: derive
      super-root slug from category ancestry — with a depth guard
      (P3-F12: a depth-3 contract-group category walks to "map", not
      a super-root — skip those categories)
- [ ] 2.4 Fix `CategoryQuerySet.resolve_slug()` fallback (P0-F2):
      `managers.py:80` does `get(slug=..., parent__isnull=True)` with
      NO fallback — add the same `filter(slug=child, parent__slug=
      parent).first()` fallback as `_resolve_category_from_identifier`
- [ ] 2.5 Fix `import_geoplaces.py` accommodation lookup (P0-F3):
      line ~687 uses `filter(slug="accommodation", parent__isnull=
      True).first()` which returns None after tree change — switch to
      `identifier="amenity.accommodation"` or `slug="accommodation",
      parent__slug="amenity"`

## 3. Consumer updates

- [ ] 3.1 Tiles view SQL: `gp.detail_type` → `gp.kind_slug`;
      recreate view migration
- [ ] 3.2 Update ALL `parent__isnull=True` contract-group queries
      (P1-F4): `api.py:178` (category filter panel), `admin/
      _geoplace.py:539` (admin filter widget), `_geoplace.py:904`
      (dedup filter) — switch to `parent__parent__slug="map"` or
      equivalent
- [ ] 3.3 Update `generate_place_relations.py` (P1-F5): lines 83,
      88, 115 use `detail_type=` ORM filters → `kind_slug=`
- [ ] 3.4 Update `DetailType` comparisons in write path (P1-F6):
      `_geoplace.py:1212,1228,1501,1539` — `DetailType.AMENITY` →
      `"amenity"`, `DetailType.ADMIN` → `"admin"` (string compares
      on kind_slug)
- [ ] 3.5 Update input schemas (P2-F7): `schemas/_input.py` write-
      side `detail_type: DetailType` fields → remove or rename to
      `kind_slug`; update API output schemas (`api.py:638,646`)
- [ ] 3.6 Verify OSM config files (P2-F10): 4 `config/osm_*.py`
      files with `detail_type="amenity"` — confirm whether constructor
      kwargs (remove) or config-dict keys (trace and update)
- [ ] 3.7 Admin: `CategoryKindContractAdmin` (autocomplete category +
      classifiers M2M widget + booleans); GeoPlace admin kind_slug
      readonly

## 4. Verification

- [ ] 4.1 Tests: contract model CRUD, classifier validation against
      DB M2M, operations/seasonality gating, kind_slug derivation
      (with depth guard), identifier stability, resolve_slug fallback,
      import accommodation lookup
- [ ] 4.2 Full suite + pyrefly + makemigrations --check
- [ ] 4.3 Drop + reimport categories and wodore GeoPlaces on lane DB;
      spot-check tree structure, contracts, imports
- [ ] 4.4 Work doc; PR with `type:feature` + `api:added` + `BUILD`
