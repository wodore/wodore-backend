# Design: multi-pack icon search

## Context

`/v1/icons` facets its candidate set in `_facet_base` before ranked search.
`pack` maps to `pack__slug=<slug>` — one pack per request.

## Goals / Non-Goals

- Goals: one request searching a chosen set of packs; single-slug requests
  behave exactly as before.
- Non-Goals: pack ranking/reordering hints, per-pack limits, a separate
  `packs` array parameter (query-param arrays are awkward for cache keys and
  hand testing; comma-joined strings match the `search` term convention).

## Decisions

- **Comma-separated `pack`, not a new param**: additive, self-describing,
  and the raw value already feeds the ETag cache key — distinct values
  produce distinct keys for free.
- **Union semantics with tolerant parsing**: strip whitespace, drop empty
  segments; unknown slugs add nothing (a facet, not a validator).
- **`pack__slug__in`**: the base queryset stays a single filter chain; the
  scan cap (`_FACET_LIMIT`) and stable `(order, pack, slug)` sort are
  untouched.

## Risks / Trade-offs

- A union of many packs grows the ranking scan set up to the existing cap;
  no new failure mode (the cap behavior predates this change).
- Clients must not rely on pack ORDER in the parameter — results are
  ordered by rank then `(order, pack, slug)`, not by parameter order.
