# Proposal: geoplace-operators

## Why

"AmenityDetail.brand" models the *entity behind a place* as a Category FK —
but categories classify places, not entities: the brand has no home for a
URL, grows the category vocabulary with one entry per OSM chain brand
(the import mints categories on the fly), and reuses category i18n for what
is really an organization name. Huts have the same concept hut-coupled:
`Hut.hut_owner` → `Owner` (slug, i18n name, url, contacts). The Hut →
GeoPlace migration needs one first-class entity for both — an `Operator`
with a localized name and multiple external links — associated to GeoPlace
with a role (`operator` vs `brand`), replacing the brand-category workaround.

## What Changes

- New `Operator` model (new `operators` app): unique slug, localized name
  (modeltrans, like `Owner`), optional localized note, `is_active`/`is_public`
  flags; **links via M2M to the existing `ExternalLink`** (i18n labels,
  link types, health checks) with explicit ordering.
- New `GeoPlaceOperatorAssociation` through model (geometries): `role`
  enum (`operator`, `brand`), unique per `(geo_place, operator, role)`.
- **Replace `AmenityDetail.brand`** — data migration converts existing
  brand Categories to `Operator` rows (role `brand`) and creates the
  associations; the FK, its admin autocomplete, and `BrandInput` are
  removed. Not a public API break: `brand` never appeared in public
  responses (admin/import only).
- OSM import stops minting brand categories: the `brand` tag maps to an
  Operator (role `brand`, get_or_create by slug); the `operator` tag now
  also maps to an Operator (role `operator`) instead of only feeding the
  place name.
- Owner merge: management command converts `owners.Owner` rows to
  Operator (slug, name, note preserved; url → ExternalLink); the wodore
  hut import (schema-path rewrite from
  `geoplace-capacity-and-types-via-categories`) links `hut_owner` →
  association with role `operator`. The `Owner` model itself stays for
  `Hut` until the huts app is removed.
- API: GeoPlace responses gain `operators` (additive, under the
  `fields[places]` selection; registered in the API changelog per
  `api-conventions`); admin gains an Operator admin and a GeoPlace
  inline; the amenity admin loses the brand field.

## Capabilities

### New Capabilities

- `geoplace-operators`: Requirements for the Operator entity (localized
  name, multiple ordered external links), the role-based GeoPlace
  association, the brand-category replacement (migration + import
  changes), the Owner merge, and read/write paths (API, admin, imports).

### Modified Capabilities

(none — `brand` is not part of any public API contract or existing spec;
`geoplace-category-attributes` — the sibling open change — is unaffected.)

## Impact

- **New app**: `server/apps/operators/` (`Operator`, admin, management
  command, migrations incl. data migration from brand categories).
- **Models**: `server/apps/geometries/models/_associations.py`
  (GeoPlaceOperatorAssociation), `server/apps/geometries/models/_amenity_detail.py`
  (drop `brand`), `server/apps/external_links` (reuse, no change).
- **Import**: `geoplaces_import_osm` (brand/operator tag mapping),
  `import_geoplaces` wodore handler (hut_owner → operator association;
  coordinates with the capacity change's rewrite).
- **API**: `server/apps/geometries/schemas/_output.py`, `api.py`
  (`operators` on place responses, fields[places] selection, changelog
  entry).
- **Admin**: Operator admin (+ TABS entry), GeoPlace operator inline,
  AmenityDetail admin without brand.
- **Data**: brand Categories (`root.brand` subtree) migrate into
  Operators; the category subtree itself is retired after migration
  (left in place for rollback, removed with a later cleanup).
- **Non-goals**: removing the owners app or `Owner` (retires with huts);
  operator logos (add later if needed, `Organization`-style); contacts on
  operators (Owner contacts die with the huts app; links replace them);
  changing `Organization` (it stays the data-source/portal entity).
