# Design: external-link-uris

## Context

`ExternalLink` (`server/apps/external_links/models.py`) is a rich,
reusable entity: i18n `label`/`description`/`url` (per-language URL
variants), a review workflow, HTTP health monitoring (`last_checked`,
`response_code`, `failure_count`, the `response_code_valid` DB check
constraint), `is_template`/`template_vars` placeholder URLs, a `source`
→ Organization FK, and a short unique `identifier`. It is associated to
places via `GeoPlaceExternalLink` (order, unique `(geo_place,
external_link)`) and to parties via `PartyLink`. Two facts shape this
change:

- **It is HTTP-only by construction.** `url = URLField(...)` — Django's
  `URLField` only validates `http`/`https`/`ftp`, so `tel:`/`mailto:`
  are rejected at the field layer. `save()` auto-detects the source
  organization by URL domain, auto-extracts a `<title>` over the
  network, and runs `check_health()` which issues `requests.head(url)`.
  None of that is meaningful for a phone or e-mail URI. There is **no
  `clean()`** today — validation beyond the field validators does not
  exist, so a scheme/kind consistency check is new surface.
- **The typed dimension it has is the wrong one for transport.**
  `link_type` → Category is a *purpose* (`website`, `osm_edit`,
  `reservation`, `warden`, …), minted loosely and unrelated to the URL
  scheme. The codebase already answered "open, localized, admin-
  manageable classifier, not an enum" for place–party roles
  (`geoplace-parties`: a `role` parent category with `role.*` children,
  itself modelled on the `season.*` classifier). The same shape fits a
  transport dimension exactly.

Contact data is in the wrong place. 58,064 `AmenityDetail` rows hold
phones as JSON (`[{"number": "+423 370 23 23", "label": null}]`),
served onto the `amenity` block by `build_amenity_detail`
(`detail.phones or []`) and typed by `AmenityDetailSchema.phones`. The
place-links table `GeoPlaceExternalLink` has **0 rows** in dev data —
the OSM import mints link entities but attaches none yet. The unified
place detail endpoint (`place-detail-endpoint`, PR #418) establishes
the `fields[places]`-selectable optional-member pattern
(`categories`/`sources`/`amenity`/`parties`) and the slug-only breaking
transition amended into the single *unreleased* API version
(`server/apps/apiversions/registry.py`). `geoplace-parties` established
the place-level link-serialization shape (`build_parties_data`:
`links: [{url, label}]` via `PartyLinkSchema`) and the resolved-symbol
helper (`resolve_symbol_urls(obj, {"request": …})` over
`symbol_color`/`symbol_mono`).

## Goals / Non-Goals

**Goals:**
- Links carry **typed URIs** — `tel:`, `mailto:`, `http(s)` — as
  first-class `ExternalLink` rows.
- A new, admin-extensible **URI-kind** category dimension (icons +
  scheme + health policy as metadata), independent of the loose
  `link_type` purposes.
- Scheme ↔ kind consistency and URI well-formedness enforced at save
  time and in write paths.
- Health checking scoped to web links only; `tel:`/`mailto:` exempt.
- Phones normalized to E.164 and migrated from JSON into `uri.phone`
  links + place associations (populating the empty place-links table).
- One `links` member on the place detail response, selectable like its
  sibling members.
- The amenity `phones` member retired cleanly in the pre-release
  breaking window.

**Non-Goals:**
- No change to the loose `link_type` purposes (orthogonal dimension).
- No immediate drop of the `AmenityDetail.phones` column (kept one
  release for rollback, cleanup later — brand-subtree doctrine).
- No bulk attachment of existing website links to places (OSM-import
  wiring, separate change).
- No Jinja2 link templating (Organization-convergence contract, owned
  by `geoplace-parties` decision 8).
- No `person`/vCard URIs, `sms:`/`geo:` schemes, or click-to-call
  frontend behaviour (add kinds on demand once a consumer needs them).

## Decisions

1. **URI kinds are a Category vocabulary, not an enum — a second
   dimension beside `link_type`.** A data migration seeds a `uri`
   parent with children `uri.phone`, `uri.email`, `uri.website`
   (slug-fixed, ordered, idempotent), mirroring the `role.*` seed. A
   new nullable `ExternalLink.uri_kind` FK → Category (RESTRICT; scoped
   to the `uri` parent in `clean()` and the admin, like `role`) records
   the transport. Each URI-kind category carries, in its `extra` JSON,
   its accepted URL **schemes** and a **health-check** flag
   (`uri.phone` → `{"schemes": ["tel"], "health_check": false}`,
   `uri.email` → `{"schemes": ["mailto"], "health_check": false}`,
   `uri.website` → `{"schemes": ["http", "https"], "health_check":
   true}`), plus curated Symbol icons (`symbol_color`/`symbol_mono`).
   Why metadata-on-category rather than hardcoded: adding `uri.fax`
   (`fax:`, no health check) or `uri.whatsapp` becomes a migration +
   admin act, zero code. `link_type` is **untouched** — a link is both
   a *purpose* (reservation) and a *transport* (uri.phone); conflating
   them would collapse two independent axes. Alternatives rejected: a
   `TextChoices` scheme enum (closed, no i18n/admin/icons, no metadata
   home); reusing `link_type` for transport (overloads one FK with two
   orthogonal meanings and breaks the existing purpose vocabulary);
   deriving the kind purely from the URL scheme at read time (loses the
   admin-managed icon/label and the ability to carry per-kind policy).

2. **`url` becomes scheme-aware: CharField + scheme validators.**
   `URLField` is replaced by a `CharField(max_length=200)` (same column
   type and width — no data rewrite) whose validators dispatch on
   scheme: http(s) keep Django's `URLValidator`; `tel:` and `mailto:`
   get format validators (RFC 3966 digits/`+`/separators for `tel`,
   an address check for `mailto`). i18n stays (`TranslationField` wraps
   the base field, so per-language `url_de`/… remain) and every
   language variant is validated identically. Alternatives rejected:
   keeping `URLField` and storing phones as `https://` shims (lies about
   the resource, breaks click-to-call); a separate `tel`/`email` column
   per kind (fragments the one-URL-per-link model and the i18n/health
   machinery). 200 chars is retained for parity (web URLs already fit;
   `tel:`/`mailto:` are short); bump only if a real URL overflows.

3. **Consistency validation in `clean()` and the write paths.**
   `ExternalLink.clean()` (new) validates, for every populated language
   URL, that the URL scheme is in `uri_kind.extra["schemes"]` —
   `tel:` ⇔ `uri.phone`, `mailto:` ⇔ `uri.email`, `http(s)` ⇔
   `uri.website` — and that the URI parses for that scheme; a link with
   `uri_kind` null is treated as a website (http/https required), so
   the 92k existing links stay valid after a backfill to `uri.website`.
   Mirrored explicitly in the schema/import write paths (the
   `GeoPlaceParty.clean()` + `_write_party_associations` precedent:
   `save()` does not run `clean()`, so validation must be re-asserted
   where imports write). `save()`'s web-only auto-behaviours —
   `_auto_detect_source`, `_auto_extract_title`, `check_health` — are
   gated behind "is this a web (http/https) URL", so a `tel:` save
   never performs network I/O. Alternatives rejected: a DB check
   constraint for scheme/kind (cannot express "scheme ∈ the kind's
   `extra` list" across a join — advisory model-layer validation plus
   the write-path mirror is the enforceable shape, same conclusion as
   `GeoPlaceParty`).

4. **Health-check policy is per URI kind.** The health-check selector
   (the management command / task that walks links and writes
   `last_checked`/`response_code`/`failure_count` + the review-status
   transitions) filters to kinds whose `extra["health_check"]` is true
   (web), skipping `tel:`/`mailto:`. The existing per-link
   `run_health_check` boolean remains an override (a web link can still
   opt out, e.g. templates without example values). `check_health()`
   itself refuses non-web URLs defensively. The `response_code_valid`
   constraint is unchanged and still holds — exempt links simply never
   set `response_code` (it stays null, which the constraint already
   permits). Alternatives rejected: a global "skip non-http" guard
   buried in `check_health` only (the *selector* would still load and
   iterate them — the policy belongs at selection); dropping the
   constraint (unnecessary — null is already valid).

5. **Phones normalize to E.164, then migrate into typed links.** New
   `tel:` URLs are built from `phonenumbers` (Google libphonenumber
   port, new dependency) parsed output formatted as E.164
   (`+<country><subscriber>`, e.g. `+423 370 23 23` → `tel:+4233702323`),
   defaulting the region from the place's `country_code` when a number
   is national. A data migration walks every `AmenityDetail.phones`
   entry and, idempotently (keyed on the normalized `tel:` URL +
   place), get_or_creates a `uri.phone` `ExternalLink` (label from the
   phone entry's `label`, `skip_health_check=True`, `run_health_check=
   False`) and a `GeoPlaceExternalLink` to the detail's place —
   populating the empty place-links table. Unparseable numbers are
   **not** dropped: they are recorded (review status / migration log)
   for manual follow-up. The migration reimplements normalization and
   identifier generation on historical models (no app-code imports, per
   the `parties.0002` precedent). Alternatives rejected: storing raw
   strings as `tel:` without normalization (defeats dedup and
   click-to-call portability); a one-shot management command only (a
   migration guarantees `migrate`-time delivery, with a re-runnable
   command available for late-arriving imports if needed).

6. **The `links` member mirrors `parties`.** A `prefetch_links`
   (`link_associations__external_link__uri_kind__symbol_color`/`_mono`)
   and a `build_links_data(place, request)` presenter produce
   `links: [{uri, url, label, symbol}]`, where `uri` is the URI-kind
   identifier (`uri.phone`), `url` the localized URL, `label` the i18n
   label, and `symbol` the resolved color/mono URLs of the *kind*
   (`resolve_symbol_urls` over the `uri_kind` category — the same helper
   `categories`/`parties` use). Only active, public, review-`done`
   links are surfaced (public-API parity with `build_parties_data`).
   `links` is an optional member of `GeoPlaceDetailSchema` under
   `fields[places]`, a sibling of `categories`/`sources`/`parties`,
   with nested `fields[links]` narrowing; `field_selected` gating skips
   the prefetch when unselected. Because `place-detail-api`
   (`place-detail-endpoint`, PR #418) owns the `fields[places]`
   allowlist and the "unknown field name → 400" rule, the dependency is
   bi-directional and additive — exactly how that spec folded in
   `parties`: if `external-link-uris` lands first in an environment, the
   `links` member is absent and not yet a valid `fields[places]` name,
   becoming valid when both are present. The changelog picks the
   additive member up automatically at release.

7. **Retire the amenity `phones` member in the unreleased breaking
   window.** Once phones are links, `AmenityDetailSchema.phones`,
   `build_amenity_detail`'s `phones` key, the amenity input `phones`,
   and `phones` in `AmenityDetail._trackable_fields` are removed —
   phones are served only via `links` (`uri.phone`). Removing a
   response member is breaking, but the registry has exactly one
   *unreleased* version (already carrying the slug-only transition); the
   runbook mandates amending it (never stacking), so this change extends
   that `VersionChange` description with the `phones` removal (sunset
   window 0, zero consumers — the geo surface is pre-release; same
   doctrine and precedent as the 2026-10-02 no-consumer removal and
   PR #418's `get_amenity` removal), regenerates and commits the
   snapshot, and ships labels `api:breaking` + `type:feature`. No
   downgrade transform is needed for a removal with zero consumers. The
   `AmenityDetail.phones` **column** is retained one release for
   rollback (the migrated data is re-derivable from the `uri.phone`
   links) and dropped in a later cleanup — the brand-subtree doctrine
   from `geoplace-parties`.

## Risks / Trade-offs

- **[Scheme/kind consistency is model-layer only, not a DB
  constraint]** → cannot be expressed as a single-column CHECK (the
  valid scheme set lives in the related category's `extra`); mitigated
  by `clean()` plus explicit write-path mirroring (the `GeoPlaceParty`
  conclusion). Pure-`.save()`/raw-SQL writes bypass it — accepted,
  identical to the role validation already shipped.
- **[Phone normalization is lossy / region-ambiguous]** → national
  numbers need a default region; derived from the place `country_code`,
  and unparseable numbers are flagged for review, never silently
  dropped or mangled. `phonenumbers` is the de-facto standard
  (libphonenumber), so parsing matches platform expectations.
- **[`links` is nearly empty until website attachment lands]** →
  after this change the place-links table holds phone associations
  only; website `ExternalLink`s stay unattached until the OSM import
  wires them (separate change). The member is honest (surfaces what
  exists) and the migration already proves the association path.
- **[URLField → CharField loosens field-level URL validation]** → the
  scheme-dispatch validators restore per-scheme strictness (http(s)
  still gets `URLValidator`); the net effect is *more* precise, not
  less.
- **[Breaking the amenity block]** → accepted by the owner (pre-release,
  zero consumers); one clean registry boundary, client regenerated.
- **[URI-kind vocabulary drift]** → curated like `role`/`season`: new
  kinds via spec delta + migration; RESTRICT guards in-use deletion.

## Migration Plan

1. Data migration: `uri` parent + `uri.phone`/`uri.email`/`uri.website`
   children (schemes + health policy in `extra`, idempotent), then wire
   the curated Symbol icons once imported.
2. Model migration: `url` URLField → scheme-aware CharField +
   validators; add nullable `uri_kind` FK; `clean()` + `save()` web-
   gating; backfill existing (http/https) links to `uri.website`.
3. Health-check selector + `check_health()` respect the per-kind
   policy.
4. `phonenumbers` dependency; data migration converting
   `AmenityDetail.phones` → `uri.phone` links + `GeoPlaceExternalLink`
   associations (E.164, idempotent, unparseable flagged).
5. API: `links` member (`prefetch_links`/`build_links_data`,
   `LinkSchema`, `field_selected` gating, nested `fields[links]`);
   remove the amenity `phones` member (schema, presenter, input,
   tracking).
6. Registry: amend the unreleased `VersionChange` (amenity `phones`
   removal), regenerate + commit the snapshot; labels at PR time.
7. Verification: lane-DB dry-runs of both data migrations (vocabulary;
   phone conversion counts before/after, idempotency, unparseable
   tally), full lane test suite, work doc.
8. Rollback: steps 1–5 are additive except the amenity `phones` schema
   removal (ships with its data migration in one deploy); rollback
   restores the response member (data preserved in `uri.phone` links
   and the retained `AmenityDetail.phones` column).

## Open Questions

- Default phone region when `country_code` is absent — fall back to
  `CH` (the data is Alpine-centric) or leave unparseable and flag?
  Lean: try `country_code`, then `CH`, then flag.
- Should `uri.email` links be de-duplicated across places the way
  phones are (one link entity reused), or always minted per place? Lean:
  same get_or_create-by-URL dedup as phones — one `mailto:` entity,
  many associations.
- Icon source set — Material Symbols vs Lucide for phone/mail/link —
  resolved by the Iconify agent during curation; both are licensing-
  clean through the symbols pipeline.
