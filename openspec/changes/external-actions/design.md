# Design: external-actions

## Context

`ExternalLink` (external_links app) owns link destination machinery:
translatable labels/URLs, `{var}` placeholder templates (auto-detected,
`template_vars` examples, `render_url(lang, **kwargs)`), URI-kind
classification, review workflow and periodic health checks. It is a
per-instance content model — links attached to huts and geoplaces via
through models.

The map product needs the opposite shape: a **registry of actions**
("open this kind of thing in app X") — curated, country-scoped,
kind-scoped, later user-owned. Nothing like it exists (verified: no
action/deep-link model in any app).

The kind axis already exists: after the category-tree restructure
(#454/#456), geoplaces carry a `domain` and the `map.*` tree provides
kinds whose **identifiers are 2 slugs and unique per design**
(`Category.identifier`, e.g. `map.transport`). Tile features carry
`adm0_iso` on every stop.

## Goals / Non-Goals

**Goals:**

- One curated registry powering generic "open-in" hand-offs: journey
  planners, map apps, point weather — data, not code, per use case
- Three orthogonal scopes per action: **kinds** (which things), **countries**
  (where), **user** (whose)
- A public, CDN-cacheable list endpoint; a private authenticated user
  endpoint; a server-side render endpoint
- Foundation for custom user actions without schema rework

**Non-Goals:**

- Frontend picker/popup UI (follow-up change)
- The `function` grouping field (dropped by owner decision — flat picker
  ordered by `order`; a nullable Category FK can be added later if
  grouping is ever needed)
- Sub-category-level targeting (kind-level identifiers only; deeper
  targeting deferred until a real use case exists)
- Client-side installed-app detection (Capacitor `<queries>` probing is
  a frontend concern)
- Changing `ExternalLink` itself

## Decisions

**D1 — Thin action row over `ExternalLink`, not templates on the action
model.** `ExternalAction` holds only the scopes (`link`, `user`,
`kinds`, `countries`, `order`, `is_active`); the link row keeps the
URL template, i18n label, placeholder documentation and health checks
(a planner template gets health-checked *with its example vars* for
free). One link may back multiple actions; plain links without actions
are unaffected. Rationale: the registry is a different beast from
per-instance content links — same domain, same app, different model
(mirrors the organizations→parties generalization instinct).

**D2 — `kinds` M2M on the existing `map.*` tree; kind-identifier
matching; empty = any point.** An action applies when the feature's
kind identifier (2 slugs, unique per design) is among the action's
kinds' identifiers — exact match, no ancestor walks (the client passes
the feature's kind; identifiers are unique). `kinds` empty matches any
subject *including category-less points* (a `map`-rooted kind would
not match those). Plural name: M2M convention, consistent with
"uri_kind" being singular only because it is a single FK.

**D3 — `countries` as a JSON list, not a vocabulary.** ISO-3166
alpha-2 codes are an external standard, not admin-curable taxonomy;
empty list = global. The client passes `iso` from data it already has
(`adm0_iso` on tile features) — the endpoint never resolves
coordinates to countries (a future `GET /v1/geo/iso?lat=&lng=` helper
can serve contexts with only coordinates, keeping this endpoint
cacheable). The `iso` parameter is case-insensitive; the server
normalises to uppercase before matching so tile data carrying lowercase
codes (`"ch"`) hits the right rows.

The response includes translated `label` fields (`ExternalLink.label`
via `modeltrans`), so the content varies by language. Both the public
and `/my/` list endpoints accept a `lang` query parameter (following
`LanguageQuery` — the same pattern as the map-layers catalog); the CDN
cache is keyed by `kind + iso + lang`. "Purely query-string-keyed"
holds: `lang` is a query key, not a header.

**D4 — `user` FK now, nullable, with partial unique constraints.**
`UNIQUE(link) WHERE user IS NULL` (one public action per link) and
`UNIQUE(user, link) WHERE user IS NOT NULL` (no per-user duplicates).
Cache split follows the endpoint, not auth-mode merging: the public
endpoint serves `user IS NULL` rows only; the user endpoint serves the
requester's rows. Adding the FK now costs one column and avoids a
constraints migration later.

**D5 — `/v1/my/` namespace as a policy boundary.** Everything under
`/v1/my/*`: auth required, `Cache-Control: private, no-store`, never
CDN — enforced at route level, one place, via a shared dmr controller
base class (`MyApiController`: auth guard in dispatch + private cache
headers + CDN bypass) that future user-scoped controllers inherit.
The public path stays purely query-string-keyed (no `Vary:
Authorization`, no shared-cache risk). This makes the cache-poisoning
class of bug (seen once on hut pages) structurally impossible for
user-scoped responses.

**D6 — Render endpoint reuses `render_url`.**
`GET /v1/links/actions/{identifier}` — `{identifier}` IS the backing
`ExternalLink.identifier` (the action model has none of its own, by
design). Resolution semantics (one public action per link + one per
user per link, per the partial uniques): render when a public action
exists for the link, OR an action owned by the requester does —
otherwise 404. Rendering goes through `ExternalLink.render_url(**params)`
(i18n-aware); missing template variables are reported as a validation
error naming the missing key(s); unknown params are ignored. For
QR/e-mail/llms contexts — client-side rendering (the `{var}` format is
trivial) remains the primary path: opening a stop costs zero
round-trips.

**D7 — No API version bump.** Additive endpoints and a new model; no
existing contract moves (versioning runbook litmus test).

**D8 — Resolvers become URL proxies, deferred; render built-ins
`{lang}`/`{date}`.** Owner decision after testing the first seed
round: services whose deep links need resolution beyond string
templating (MeteoSwiss coords→PLZ, SBB SLOID↔DiDok, smart routing
profiles) will be served by **custom proxy endpoints**
(`/v1/links/proxy/<slug>?lat=&lon=` → 302 to the resolved target)
added in a later change — the `ExternalLink` then simply carries the
proxy URL as its template, with no frontend or render change at all.
No resolver registry on the model. What ships now: the render
endpoint injects two built-in substitution vars — `{lang}` (resolved
UI language via `render_url`'s language parameter; SBB-style
`/{lang}` paths) and `{date}` (client's selected date, default
tomorrow, ISO yyyy-mm-dd; invalid → 400). MeteoSwiss is dropped from
the seed entirely.

## Risks / Trade-offs

- **Template correctness is curation.** A wrong placeholder name in a
  seed row renders a broken link; mitigated by `template_vars`
  examples + health checks and admin review workflow.
- **Kind granularity is coarse.** Targeting is kind-level (2-slug
  identifiers); "just huts, not all accommodation" is not expressible
  until sub-category targeting is added (deferred deliberately).
- **User endpoint returns only user rows** — the client merges public +
  mine locally; a stale public cache could briefly lag behind admin
  edits (bounded by the catalog-style CDN TTL).
- **`/my/` is a new path prefix** — a convention other features must
  follow for the policy to pay off; documented here as the standard.
