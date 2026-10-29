# Design: geoplace-category-tree

## Context

Supersedes the `PLACE_KINDS` code-only approach shipped in #451. The
PO refined the model: the kind IS the specific category
(`accommodation.hut`), the contract group is its parent
(`accommodation`), and a namespace root (`map`) separates map
categories from vocabulary trees. The contract belongs in the DB
(admin-editable, `CategoryExtraSchema` parity).

## Decisions

1. **Four tree levels** (identifiers stay 2-level):
   ```
   map          (namespace root, parent=None, identifier="root.map")
   └── amenity  (super-root, parent=map)
       └── accommodation  (contract group, identifier root)
           └── hut        (kind, identifier child)
   ```
   Identifier computation: the **contract group** (2nd level) is the
   identifier root — `accommodation.hut`, not `amenity.accommodation.hut`.
   The super-root and namespace root are structural parents for
   grouping, not identifier parts. The existing 2-level identifier
   algorithm works unchanged as long as it operates from the contract
   group level.

2. **`CategoryKindContract` in the DB** — admin-editable:
   ```python
   class CategoryKindContract(TimeStampedModel):
       category = OneToOneField(Category)  # the contract group
       allowed_classifiers = ManyToManyField(
           Category,
           related_name="kind_contracts",
           limit_choices_to={"parent__parent__parent__slug": "map"},
       )
       has_operations = BooleanField(default=False)
       has_seasonality = BooleanField(default=False)
   ```
   Seeded from `PLACE_KINDS` (code), then admin can: add
   `service.express` classifier to transport, enable operations for
   tourism, disable seasonality for shopping — without a deploy.

3. **`GeoPlace.detail_type` → `GeoPlace.kind_slug`** — the super-root
   slug replaces the 5-value enum. Same derive-but-store pattern:
   derived on write from the first category's ancestry (category →
   parent → parent = super-root), stored as a CharField for tiles SQL.
   No check constraint on values (the tree validates); indexed for
   tile filtering.

4. **Namespace root (`map`)** — separates map categories from
   vocabulary trees (`mode.*`, `role.*`, `relations.*`, `link_type.*`,
   `season.*` — these remain parentless). This makes
   `parent__isnull=True` cleanly find ONLY vocabulary roots + the map
   root, while contract groups are found by `parent__parent__slug=
   "map"` or equivalently `parent__parent__parent=None`.

5. **Operations/seasonality gated by contract** — the write path
   checks `CategoryKindContract.has_operations` /
   `has_seasonality` before creating rows. A transport stop without
   a contract that enables operations can't get one.

6. **Drop + reimport** — categories are staging-only; the tree
   restructure is a seed migration creating the new hierarchy and
   re-parenting existing categories. GeoPlaces are reimported after.

7. **`is_protected` extended** — super-roots and the map root are
   protected (slug + parent readonly). Contract groups are NOT
   protected (admins may re-parent a group under a different
   super-root). Vocabulary trees stay protected as shipped in #451.

## Risks / Trade-offs

- [3-level parent traversal] — queries walking to the super-root need
  `parent__parent` (2 joins instead of 1). Acceptable for the kind
  derivation (done once on write, not per-read).
- [Identifier stability] — `accommodation.hut` identifiers don't
  change (the contract-group level is unchanged). Super-roots get
  identifiers like `amenity` (no namespace prefix).
- [Drop + reimport is destructive] — accepted: staging only, no
  production deployment exists yet.

## Migration Plan

1. Schema: `CategoryKindContract` model migration.
2. Data: seed migration creates `map` → `amenity`/`admin`/`natural`
   → re-parents existing roots under super-roots → seeds contracts
   from `PLACE_KINDS` → marks super-roots protected.
3. Code: `detail_type` → `kind_slug` rename; validation reads DB
   contract; write paths check contract booleans.
4. Tiles: view SQL reads `kind_slug`; tile function updated.
5. Drop + reimport categories and GeoPlaces on staging.

## Follow-ups

- Hut → GeoPlace data migration (next change).
- Availability Phase D/E (reads `kind_slug` for dN_type).
- Transport schedules (may get their own contract fields).
