---
draft: false
date:
  created: 2026-11-08
  updated: 2026-11-08
slug: wep011
categories:
  - WEP
  - Reviews
  - Open Data
tags:
  - wep011
  - mangrove
  - reviews
  - open-data
---

# `WEP 11` Open Decentralized Hut Reviews via Mangrove

Wodore integrates [Mangrove Reviews](https://docs.mangrove.reviews) — the
Open Reviews Association's decentralized, ES256-signed open review dataset
(CC-BY-4.0) — as the hut review system: every hut gets a deterministic
`geo:` subject URI, anonymous visitors read, Wodore accounts write through
a fully proxied backend that holds each account's reviewer keypair
encrypted server-side, and a recurring Overpass job links huts to OSM
elements for review metadata. Full proposal:
[openspec change `reviews-mangrove`](https://github.com/wodore/wodore-backend/tree/main/openspec/changes/reviews-mangrove)
(`proposal.md`, `design.md`, spec deltas, `tasks.md`).

## Why Mangrove, why now

Wodore lists 1585 public huts and has no reviews — and effectively nobody
else does either: the Mangrove dataset holds ~728 reviews in the Alps
bbox, all on Swiss tourism-portal geo subjects, with **zero alpine-hut
coverage** (one MapComplete-theme exception). Mangrove gives us:

- **Ratings, opinions and photos without a review backend** — the dataset,
  signing, spam economics (issuer credibility), abuse reporting and
  aggregation are upstream's problem.
- **Open data alignment** — every review is CC-BY-4.0, published by the
  Open Reviews Association; Wodore contributes to rather than silos the
  commons, matching our OSM-based sourcing ethos. MapComplete and Swiss
  tourism portals already participate.
- **First-mover position** for alpine huts in a system designed for
  cross-client review portability (your identity is your key, not our
  user table).

The risk profile is acceptable: the API (0.2.0) is live and CORS-open but
not frozen — so we pin its contract with recorded fixtures — and reviews
are not booking-critical, so upstream outages degrade gracefully.

## Subject URI recipe (the key decision)

A review attaches to a *subject URI*. Mangrove matches two `geo:` subjects
iff their `q` strings are **byte-identical** and coordinates lie within
the *sum* of both `u` radii — no fuzzy matching anywhere. So Wodore's
subject is a pure function of the hut row:

```text
geo:<lat>,<lon>?q=<hut-slug>&u=<radius>
```

- `q` = the **Wodore slug** — unique, byte-stable, multilingual-proof.
  Hut names are deliberately *not* used: names change with translation
  and rename, which would silently fork subjects.
- `u` = one constant (default 30 m, settings-tunable; extent-based radii
  deferred).
- Coordinates from `Hut.location`, 6 decimals.

Trade-off (accepted): MapComplete subjects use `q=<OSM name>`, so our
subjects don't cross-match today. With ≈0 existing hut reviews there is
nothing to lose, and the standard's **equivalence claims** (credibility-
weighted union-find) are the designated bridge later — an early spike
verifies whether resolution is live on api.mangrove.reviews. Rejected
alternatives: `https`-URL subjects (ecosystem isolation, unproven
equivalence bridging) and a hypothetical `urn:osm` (non-standard, OSM ids
unstable — OSM ids ride in review *metadata* instead).

## Architecture: proxy everything, keys server-side

New Django app `server/apps/reviews`; one `MangroveClient` (httpx,
timeouts, GET-only retries, structlog + Sentry, no review PII in logs) is
the only code that talks upstream. Contract pinned to 0.2.0 via fixtures
so drift fails CI, not requests.

- **Reads (anonymous)**: `GET /v1/huts/{slug}/reviews`, per-hut
  `…/summary`, and a batch summary endpoint for map badges (upstream
  `POST /batch`). Cached subject-keyed with minutes-scale TTL, CDN tag
  `api:reviews`, write-through invalidation on our own writes. Hut
  endpoints and their ETags stay review-blind — review volatility lives
  on separate endpoints.
- **Writes (OIDC-authenticated)**: `POST …/reviews` validates (MaReSt
  limits + metadata allowlist), enriches (`client_id`, `license`,
  `osm_id`), **signs with the account's key and relays**. Edit/delete are
  signed `action` JWTs against the review's `urn:maresi:` id; abuse
  reports relay as `report_abuse` actions. Anonymous = read-only.
- **Identity**: one ES256 keypair per account, minted lazily, **encrypted
  at rest** under a dedicated rotatable secret. The standard explicitly
  supports key-managing submit services — this is what makes edit/delete/
  report and GDPR erasure possible for normal users. Opt-in JWK
  import/export (bring your MapComplete identity) follows in phase 2;
  `did:web` identity is a future note (upstream `/identity` is 404 today).
- **Moderation**: per-user quota, local signature blacklist (a serving
  decision — the open dataset is never mutated by us), relayed abuse
  reports.
- **Sovereignty**: upstream is canonical and open; our append-only
  submission log (verbatim JWTs) archives exactly what Wodore published
  and powers the erasure command.

## OSM linkage

A recurring django-q2 job (`reviews_osm_sync`) queries Overpass (ODbL —
self-serve, no permission needed) for hut-class elements near each hut,
scores distance + name similarity, auto-links unambiguous matches into
the existing `HutSource` (org `osm`) pattern (1166/1585 huts already
linked; the job also fills the 27% gap and verifies existing links), and
parks ambiguous cases in an admin review queue. Linked huts stamp
`metadata.osm_id` (`way/123[/2]` form) on their reviews. Ecosystem
questions (equivalence status, partner onboarding) go to ORA
(hello@open-reviews.net).

## Scope and status

Backend-first and additive: new endpoints only, no `Api-Version` bump.
The openspec change carries implementable backend tasks; frontend work
(hut-page review UI, star ↔ 0/25/50/75/100 rating mapping, map badges,
my-reviews profile) is listed as informative tasks for a separate
frontend proposal. Open decisions — `u` radius policy, image hosting
(relay URLs vs Wodore-side upload), quota defaults, exact DTO shapes —
are flagged with recommendations in the design document.
