# Design: geoplace-operators

## Context

Two parallel "entity behind a place" mechanisms exist today:

- **Geoplaces**: `AmenityDetail.brand` — FK to `Category`, scoped in the
  admin to the `root.brand` subtree. The OSM import
  (`geoplaces_import_osm`) get_or_creates a brand Category for every
  single-value OSM `brand` tag. Brands-as-categories cannot carry a URL
  or their own identity data and pollute the classification vocabulary.
- **Huts**: `Hut.hut_owner` — FK to `owners.Owner` (slug, i18n name, url,
  note, contacts M2M), populated from hut-services `owner` data.

The Hut → GeoPlace migration (see `geoplace-capacity-and-types-via-categories`)
needs one shared home. Reusable building blocks: `ExternalLink` (i18n
label/description/url, link types, review workflow, health checks) and
the association pattern in `geometries` (through models with order).

`Organization` was considered and rejected as the home: it is the
data-source/portal entity (booking config, `link_hut_pattern`,
attribution, logos) — SAC-the-portal (source) and SAC Bern-the-section
(operator) are different entities, and mixing roles would taint source
semantics used by availability and link auto-detection.

## Goals / Non-Goals

**Goals:**
- One `Operator` entity for brand and owner/operator semantics.
- Localized name + multiple, ordered, health-checked external links.
- Role-based association to GeoPlace (`operator`, `brand`).
- Replace `AmenityDetail.brand`; stop minting brand categories.
- Merge `Owner` data into Operator (Owner rows remain until huts removal).
- Expose operators via API (additive) and admin.

**Non-Goals:**
- No owners-app removal (retires with the huts app).
- No operator logos, no contacts on operators (links replace them).
- No changes to `Organization` (stays the source/portal entity).
- No hut-side changes beyond the import mapping (`Hut.hut_owner` stays).

## Decisions

1. **New `Operator` model in a new `operators` app** (slug, `name` i18n
   via modeltrans, `note` i18n optional, `is_active`, `is_public`).
   Alternative: generalize `owners.Owner` in place — rejected for now:
   renaming Owner breaks `Hut.hut_owner` mid-migration; a parallel model
   lets huts keep working while geoplaces move first. The merge command
   copies data; the owners app retires with huts later. Alternative:
   reuse `Organization` — rejected (see Context).

2. **Links: M2M to `ExternalLink` through `OperatorLink` (order field)**,
   mirroring `GeoPlaceExternalLink`. One link entity can serve a place
   and an operator; health checks and i18n come for free. Alternative:
   URL fields/JSON list on Operator — rejected: duplicates an existing,
  richer mechanism.

3. **Association with role, unique `(geo_place, operator, role)`.**
   `GeoPlaceOperatorAssociation` (geometries, CASCADE on place, RESTRICT
   on operator) with `role: operator | brand` (TextChoices, DB-checked).
   The same operator may appear as both brand and operator of a place
   (rare but legal); one row per role per pair. Role — not two models —
   keeps the entity vocabulary single and the API shape uniform.
   `order` on the association for deterministic display.

4. **Brand replacement is a migration, not a sync.** Data migration:
   for each `AmenityDetail` with `brand`, get_or_create Operator
   (slug from category, name from category i18n) + association
   (role `brand`); then remove the FK, the admin autocomplete, and
   `BrandInput`. OSM import maps `brand` tag → Operator(role `brand`)
   and additionally `operator` tag → Operator(role `operator`) — today
   the operator tag only influences place naming. `root.brand` category
   subtree stays in the DB for rollback; cleanup in a later change.

5. **Owner merge via management command** (`import_operators`):
   Owner → Operator by slug (name/note carried over, url → ExternalLink),
   idempotent, dry-run capable. The wodore hut import rewrite (capacity
   change) then creates associations from `hut_owner` with role
   `operator`. Command — not data migration — because Owner rows keep
   arriving from hut imports until cutover; re-runnable sync beats a
   one-shot migration.

6. **API: additive `operators` on place responses** under the
   `fields[places]` sparse-fieldset selection (nested narrowing via
   `fields[operators]` → slug-only, following the sparse-fieldsets
   conventions): `[{role, slug, name, links}]`. `brand` was never in
   public responses, so no version bump; changelog entry per
   `api-conventions`.

7. **Admin tracking mirrors the capacity change's decision**: the
   operator inline formset save marks the place `is_modified` and
   records the association in `protected_fields` (associations carry no
   automatic `GeoPlaceDetailBase` tracking).

## Risks / Trade-offs

- [Two vocabularies during transition (Owner + Operator)] → Merge
  command is idempotent and cheap; Owner is read-only after cutover.
- [Brand categories linger as dead vocabulary] → Explicitly out of
  scope; a later cleanup change removes `root.brand` once no
  associations reference it.
- [OSM `operator` tag values are noisy free text] → get_or_create by
  slugified value with a `review_status`-style review flag on Operator
  (reuse the existing review pattern) rather than auto-trusting; single
  values only (skip `;` lists, as the brand mapping already does).
- [Losing brand-category symbols/ordering in UI] → Operators never had
  symbols; frontend renders name + links (links are the point).
- [Role enum may grow (authority, franchisee…)] → TextChoices + DB
  check constraint is cheap to extend via migration; vocabulary is
  closed per spec delta.

## Migration Plan

1. Create `operators` app (model, admin, TABS entry) + association in
   geometries; migrations.
2. Data migration: brand Categories → Operators (role `brand`) +
   associations; remove `AmenityDetail.brand` (+ admin/schema/import
   updates: `BrandInput` → `OperatorInput`).
3. OSM import mapping switch (`brand`/`operator` tags).
4. `import_operators` merge command (Owner → Operator), then extend the
   wodore hut import to write operator associations.
5. API `operators` field + changelog entry; tests; lane-DB dry-runs of
   the data migration and both imports.
6. Rollback: steps are additive except the brand FK removal — the FK
   drop ships with its data migration in one deploy; rollback restores
   the column (data preserved in Operator rows, re-derivable).

## Open Questions

- Operator `review_status`: reuse the `new/review/work/done` pattern
  from ExternalLink for OSM-minted operators, or trust them like the
  brand categories were trusted? Lean: add the flag, default `done`
  for migrated brands, `review` for operator-tag minted.
- Should the association carry dates/source info (who asserted this
  operator)? Lean: no — source provenance lives in
  `GeoPlaceSourceAssociation` per place; keep the association minimal.
