## 1. Model & migration

- [x] 1.1 Add `ExternalAction` to `server/apps/external_links/models.py`:
      `link` FK (CASCADE) → `ExternalLink`, `user` nullable FK → user,
      `kinds` M2M → `Category`, `countries` JSONField (default `list`),
      `order` PositiveSmallIntegerField (default 100), `is_active`
      BooleanField — full pyrefly-strict annotations (repo has no
      baseline)
- [x] 1.2 Add the partial unique constraints (`UNIQUE(link) WHERE user
      IS NULL`, `UNIQUE(user, link) WHERE user IS NOT NULL`) and
      indexes for `(is_active, user)`; migration with the
      `geometries`-style guarded helpers
- [x] 1.3 Constrain `kinds` choices to the `map.*` kind tree:
      `limit_choices_to={"parent__slug": "map", "is_active": True}` for
      the admin widget; validation in `clean()` rejecting categories
      whose `identifier` does not start with `"map."` (`Category.identifier`
      is a stored computed field — ORM queries through `kinds__identifier`
      are safe and indexed)

## 2. API

- [x] 2.1 `GET /v1/links/actions?kind=&iso=&lang=` — dmr controller in a new
      `server/apps/external_links/api.py`: active public rows
      (`user IS NULL`), kind-identifier exact match (or empty kinds;
      omitted `kind` = no kind filter), iso membership (or empty
      countries; case-insensitive, normalized to uppercase), ordered;
      labels localized via the `LanguageQuery` pattern (`lang` varies
      the cache key); response rows carry link `identifier`, i18n
      label, `url` template, `template_vars`; CDN-cacheable headers +
      `api:external_links` cache tag per the ApiCdnCacheMiddleware
      taxonomy (admin save/delete hooks purge it)
- [x] 2.2 `GET /v1/my/links/actions?kind=&iso=&lang=` — authenticated,
      requester's rows only, `Cache-Control: private, no-store`;
      establish the `/v1/my/` policy ONCE as a shared dmr controller
      base class (`MyApiController`: auth guard in dispatch + private
      cache headers + CDN bypass) that future user-scoped controllers
      inherit — plus a namespace-level test proving the policy holds
      for any `/my/` route, not per-view
- [x] 2.3 `GET /v1/links/actions/{identifier}?<template vars>` —
      `{identifier}` is the backing `ExternalLink.identifier`; render
      when a public action exists for the link OR an action owned by the
      requester does — otherwise 404; render via
      `ExternalLink.render_url(**params)` in the request language;
      unknown params ignored, missing vars reported as a validation
      error naming the key(s) (NOT parsed from `template_vars` — reuses
      `render_url`'s `ValueError` as-is)
- [x] 2.4 Register both paths with `name=`/`operation_id` parity (E003/
      E004 startup checks) and regenerate the API types/snapshot
      (`app api_snapshot` / types generation) — include the diff in the
      PR

## 3. Admin & seed

- [x] 3.1 Unfold admin for `ExternalAction` (list/filter by kind,
      country, user, active; inline hint of the link's template vars),
      following the app's existing admin patterns (`@display`,
      TABS registration)
- [x] 3.2 Seed command (additive-only `get_or_create` keyed by link
      URL + scope signature — existing rows are never modified, so
      curator edits are structurally safe; `skip_health_check=True` on
      link saves — the template links carry `template_vars` and would
      otherwise fire network health checks during seeding): planners
      SBB (CH), DB Navigator (DE), ÖBB Scotty (AT); map apps Google
      Maps, Apple Maps, Mapy, Organic Maps (empty kinds — any point,
      global); meteoblue point weather — each backed by a template
      `ExternalLink` with `template_vars` examples (`lat`, `lon`,
      `name`)

## 4. Verification

- [x] 4.1 Model tests: partial unique constraints (public duplicate
      rejected, per-user duplicate rejected, same link for different
      users allowed), `clean()` kind-tree validation
- [x] 4.2 API tests: public filtering (kind/iso/empty semantics,
      ordering), inactive rows excluded, `iso=ch` normalised to CH,
      `lang` produces localised labels and a separate cache entry,
      CDN-cache headers + anonymous access, `/my/` auth rejection +
      private headers + own-rows-only (namespace-level policy test),
      render endpoint (substitution, i18n, public-action open to all,
      user-only action 404 for non-owner)
- [x] 4.3 `inv check.types` (pyrefly strict, 0 errors) and the lane
      test suite green; `api:added` label on the PR (additive
      endpoints, no version bump per the runbook)
