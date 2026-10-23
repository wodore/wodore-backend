# Design: geoplace-parties

## Context

Two parallel "entity behind a place" mechanisms exist today:

- **Geoplaces**: `AmenityDetail.brand` — FK to `Category`, scoped in the
  admin to the `root.brand` subtree. The OSM import
  (`geoplaces_import_osm`) get_or_creates a brand Category for every
  single-value OSM `brand` tag. Brands-as-categories cannot carry a URL
  or their own identity data and pollute the classification vocabulary.
- **Huts**: `Hut.hut_owner` — FK to `owners.Owner` (slug, i18n name, url,
  note, contacts M2M), populated from hut-services `owner` data.

The Hut → GeoPlace migration (see
`geoplace-capacity-and-types-via-categories`) needs one shared home, and
the *relation* an entity plays toward a place (operator, brand, owner,
authority, …) must be expressible without code changes per role. The
codebase already answered this shape question once: `GeoPlaceCategory.
classifier` is a Category FK scoped to the `season` parent because a
free-text/enum "loses category machinery (i18n, admin, symbols, future
classifiers)". Reusable building blocks: `ExternalLink` (i18n
label/description/url, link types, review workflow, health checks) and
the through-model association pattern in `geometries`.

`Organization` was considered as the entity home and deferred: it is the
data-source/portal entity (booking config, `link_hut_pattern`,
attribution, logos) used by availability integrations and link
auto-detection; minting hundreds of OSM brands into the table behind
booking-source pickers is a semantic hazard today. Nothing in this
design blocks convergence later (portals become parties with a source
role; `ExternalLink.source` re-points then).

Naming: **Party** follows ISO 19115-1 (`CI_Party` + `CI_RoleCode`) and
the classic party-role data model (Hay; Siebel/Oracle `S_PARTY`): the
entity is neutral, the *relation* carries the semantics. "Relation"/
"related" names the association side, not the entity — hence
`GeoPlaceParty` + `role.*` categories.

## Goals / Non-Goals

**Goals:**
- One neutral `Party` entity for brand, owner, and operator semantics.
- Localized name + multiple, ordered, health-checked external links.
- Open, localized, admin-manageable role vocabulary (`role.*`
  categories) as the association classifier; multiple roles per
  place–party pair via multiple rows.
- Replace `AmenityDetail.brand`; stop minting brand categories.
- Merge `Owner` data into Party (Owner rows remain until huts removal).
- Expose parties via API (additive) and admin.

**Non-Goals:**
- No owners-app removal (retires with the huts app).
- No `Organization` absorption (convergence possible later).
- No party logos, no contacts on parties (links replace them).
- No person-type parties (org-only; a `person` subtype is a future
  extension if hut-warden-style contacts ever migrate).
- No hut-side changes beyond the import mapping (`Hut.hut_owner` stays).

## Decisions

1. **New `Party` model in a new `parties` app** (slug, `name` i18n via
   modeltrans, `note` i18n optional, `is_active`, `is_public`,
   `review_status`). Alternatives rejected: generalizing `owners.Owner`
   in place (breaks `Hut.hut_owner` mid-migration); reusing
   `Organization` (see Context).

2. **Links: M2M to `ExternalLink` through `PartyLink` (order field)**,
   mirroring `GeoPlaceExternalLink`. One link entity can serve a place
   and a party; health checks and i18n come for free. Alternative: URL
   fields/JSON list on Party — rejected: duplicates an existing,
   richer mechanism.

3. **Role is a Category classifier scoped to the `role` parent, not an
   enum.** `GeoPlaceParty` (geometries; CASCADE on place, RESTRICT on
   party and role) carries `role` FK → Category under parent `role`
   (children seeded: `operator`, `brand`, `owner`, `authority`), unique
   per `(geo_place, party, role)`; multiple roles = multiple rows, one
   classifier per row — mirroring how `season` classifiers work on
   category associations. Validation (`role.parent.slug == "role"`)
   runs in `clean()` and explicitly in the schema import path, like the
   capacity change's decision 3. Alternatives rejected: a `role`
   TextChoices enum — closed vocabulary, no i18n/admin extensibility,
   and "Operator" as the model name would be a misnomer once brand and
   owner roles exist; M2M roles on a single association row — breaks
   the one-classifier-per-row pattern and complicates uniqueness/
   ordering for no gain.

4. **Brand replacement is a migration, not a sync.** Data migration:
   for each `AmenityDetail` with `brand`, get_or_create Party (slug
   from category, name from category i18n) + association (role
   `role.brand`); then remove the FK, the admin autocomplete, and
   `BrandInput`. OSM import maps `brand` tag → Party(role `role.brand`)
   and additionally `operator` tag → Party(role `role.operator`) —
   today the operator tag only influences place naming. `root.brand`
   category subtree stays in the DB for rollback; cleanup in a later
   change.

5. **Owner merge via management command** (`import_parties`):
   Owner → Party by slug (name/note carried over, url → ExternalLink),
   idempotent, dry-run capable. The wodore hut import rewrite (capacity
   change) then creates associations from `hut_owner` with role
   `role.owner` (the field means the legal owner; clubs that also
   operate get a second `role.operator` row from editors or a later
   mapping refinement). Command — not data migration — because Owner
   rows keep arriving from hut imports until cutover; re-runnable sync
   beats a one-shot migration.

6. **API: additive `parties` on place responses** under the
   `fields[places]` sparse-fieldset selection (nested narrowing via
   `fields[parties]` → slug-only, following the sparse-fieldsets
   conventions): `[{role, slug, name, links}]` with `role` as the
   category identifier (e.g. `role.operator`). `brand` was never in
   public responses, so no version bump; changelog entry per
   `api-conventions`.

7. **Admin tracking mirrors the capacity change's decision**: the party
   inline formset save marks the place `is_modified` and records the
   association in `protected_fields` (associations carry no automatic
   `GeoPlaceDetailBase` tracking). Role autocomplete scoped to the
   `role` subtree; party autocomplete by slug/name.

## Risks / Trade-offs

- [Open role vocabulary can drift (synonyms, typos)] → `role` subtree
  is curated like `season`: new roles go through a spec delta +
  migration; category admin guards in-use deletions (RESTRICT).
- [Two vocabularies during transition (Owner + Party)] → Merge command
  is idempotent and cheap; Owner is read-only after cutover.
- [Brand categories linger as dead vocabulary] → Explicitly out of
  scope; a later cleanup change removes `root.brand` once no
  associations reference it.
- [OSM `operator` tag values are noisy free text] → get_or_create by
  slugified value with `review_status=review` on Party for
  operator-tag minted rows (`done` for migrated brands); single values
  only (skip `;` lists, as the brand mapping already does).
- [Role FK deletability] → RESTRICT on both party and role FKs; an
  in-use role/party cannot be deleted silently (unlike `classifier`'s
  SET_NULL, a party association without a role would be meaningless).

## Migration Plan

1. Data migration: `role` parent + children categories (slug-fixed,
   order-stable, idempotent).
2. Create `parties` app (model, links, admin, TABS entry) +
   `GeoPlaceParty` in geometries; migrations.
3. Data migration: brand Categories → Parties (role `role.brand`) +
   associations; remove `AmenityDetail.brand` (+ admin/schema/import
   updates: `BrandInput` → `PartyInput`).
4. OSM import mapping switch (`brand`/`operator` tags).
5. `import_parties` merge command (Owner → Party), then extend the
   wodore hut import to write party associations (role `role.owner`).
6. API `parties` field + changelog entry; tests; lane-DB dry-runs of
   the data migrations and both imports.
7. Rollback: steps are additive except the brand FK removal — the FK
   drop ships with its data migration in one deploy; rollback restores
   the column (data preserved in Party rows, re-derivable).

## Open Questions

- Initial role vocabulary beyond the four seeded children — e.g.
  `authority` (national park service approving a hut) now or when a
  source needs it? Lean: seed only what has data today
  (`operator`, `brand`, `owner`), add `authority` on demand.
- Party `review_status` lifecycle for OSM-minted parties: who reviews,
  and does the admin surface them like external links? Lean: same
  pattern as ExternalLink's review workflow.
