# Proposal: geoplace-parties

## Why

"AmenityDetail.brand" models the *entity behind a place* as a Category FK —
but categories classify places, not entities: the brand has no home for a
URL, grows the category vocabulary with one entry per OSM chain brand
(the import mints categories on the fly), and reuses category i18n for
what is really an organization name. Huts carry the same concept
hut-coupled: `Hut.hut_owner` → `Owner` (slug, i18n name, url, contacts).
The Hut → GeoPlace migration needs one first-class entity for both — and
the relation it plays (operator, brand, owner, …) should be an open,
localized, admin-manageable vocabulary, not a hardcoded enum: a
**Party** (ISO 19115-1 `CI_Party` + role codelist) associated to
GeoPlace through a **role category** (`role.*`), mirroring the
`classifier` → `season.*` pattern already established for
`GeoPlaceCategory`.

## What Changes

- New `Party` model (new `parties` app): unique slug, localized name
  (modeltrans, like `Owner`), optional localized note,
  `is_active`/`is_public`, review flag; **links via M2M to the existing
  `ExternalLink`** (i18n labels, link types, health checks) with
  explicit ordering; **optional symbol** — two nullable Symbol FKs
  (color and mono; parties are not map features, so the map-styling
  primitive variant is omitted).
- New `role` category vocabulary (parent + children `operator`, `brand`,
  `owner`, `source`; `authority` on demand) created by data migration,
  extensible in the category admin — same shape as the `season`
  vocabulary. `source` seeds the vocabulary for the future Organization
  convergence (portals become parties; no data uses it yet).
- New `GeoPlaceParty` through model (geometries) — **place-level:
  applies to every geoplace regardless of `detail_type`** (amenity,
  transport, admin, natural, none), like the category and link
  associations: `role` FK → Category scoped to the `role` parent,
  unique per `(geo_place, party, role)`; **multiple roles = multiple
  association rows** (one role classifier per row).
- **Replace `AmenityDetail.brand`** — data migration converts existing
  brand Categories to Party rows + associations with role
  `role.brand`; the FK, its admin autocomplete, and `BrandInput` are
  removed. Not a public API break: `brand` never appeared in public
  responses (admin/import only).
- OSM import stops minting brand categories: the `brand` tag maps to a
  Party (role `role.brand`, get_or_create by slug); the `operator` tag
  now also maps to a Party (role `role.operator`) instead of only
  feeding the place name.
- Owner merge: management command converts `owners.Owner` rows to Party
  (slug, name, note preserved; url → ExternalLink); the wodore hut
  import (schema-path rewrite from
  `geoplace-capacity-and-types-via-categories`) links `hut_owner` →
  association with role `role.owner`. The `Owner` model itself stays
  for `Hut` until the huts app is removed.
- Source-role link templates (contract recorded here, implementation
  deferred to the Organization convergence): a source-role Party carries
  its portal object-link pattern as a template `ExternalLink` (Jinja2
  `{{var}}` URL, rendered per place at read time from
  `source_id`/`lang`/`slug`/`props`), replacing
  `Organization.link_hut_pattern`. `ExternalLink` template handling
  converges to Jinja2 then — no template rows exist today.
- API: GeoPlace responses gain `parties` (additive, under the
  `fields[places]` selection; registered in the API changelog per
  `api-conventions`); admin gains a Party admin and a GeoPlace inline;
  the amenity admin loses the brand field.

## Capabilities

### New Capabilities

- `geoplace-parties`: Requirements for the Party entity (localized
  name, multiple ordered external links), the `role` category
  vocabulary, the role-classified GeoPlace association, the
  brand-category replacement (migration + import changes), the Owner
  merge, and read/write paths (API, admin, imports).

### Modified Capabilities

(none — `brand` is not part of any public API contract or existing spec;
`geoplace-category-attributes` — the sibling open change — is unaffected
apart from sharing the classifier-pattern vocabulary approach.)

## Impact

- **New app**: `server/apps/parties/` (`Party`, `PartyLink`, admin,
  management command, migrations incl. data migration from brand
  categories and the `role` vocabulary seed).
- **Models**: `server/apps/geometries/models/_associations.py`
  (`GeoPlaceParty`), `server/apps/geometries/models/_amenity_detail.py`
  (drop `brand`), `server/apps/external_links` (reuse, no change),
  `server/apps/categories` (`role` subtree data).
- **Import**: `geoplaces_import_osm` (brand/operator tag mapping),
  `import_geoplaces` wodore handler (hut_owner → party association;
  coordinates with the capacity change's rewrite).
- **API**: `server/apps/geometries/schemas/_output.py`, `api.py`
  (`parties` on place responses, fields[places] selection, changelog
  entry).
- **Admin**: Party admin (+ TABS entry), GeoPlace party inline, AmenityDetail
  admin without brand.
- **Data**: brand Categories (`root.brand` subtree) migrate into
  Parties; the category subtree itself is retired after migration (left
  in place for rollback, removed with a later cleanup).
- **Non-goals**: removing the owners app or `Owner` (retires with
  huts); absorbing `Organization` into Party (the portals/sources may
  converge later — the vocabulary seeds `source` and the design records
  the Jinja link-template contract so convergence lands ready — but
  booking integrations and source pickers stay untouched for now); party
  logos as uploaded images (Organization-style `ImageField` — symbols
  cover curated iconography; revisit at Organization convergence);
  contacts on parties (Owner contacts die with the huts app; links
  replace them); person-type parties (org-only for now).
