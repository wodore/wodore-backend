# Spec Delta: api-conventions (place-detail-endpoint)

## MODIFIED Requirements

### Requirement: Slug identifiers and ISO modified timestamps
Public identifiers in API payloads SHALL be stable, human-readable
slugs; database primary keys SHALL NOT be exposed — except in resource
families that are id-keyed end to end and predate this convention (the
geo places family: `places/search`, `places/nearby` and the place
detail route accept and return the numeric GeoPlace `id`). New
endpoints in such a family SHALL follow the family's identifier
convention (integer path key, `id` in payloads) rather than
introducing a parallel slug key for the same resource; a family
migrates to slug identifiers, if ever, as one coordinated breaking
change with a slug-quality guarantee (stability, readability, slug
exposure in list responses). Content versions/timestamps SHALL be ISO
8601 UTC values derived from the model's `modified` field, and a field
that IS the row's modified timestamp SHALL be named `modified` (not
`version`), so clients can key caches uniformly.

#### Scenario: Resource addressed by slug

- **WHEN** a client fetches or links a single resource in a
  slug-addressable family
- **THEN** it is addressed by slug in the path (e.g.
  `/v1/map/styles/{slug}.json`), and the payload identifies it by slug
  with no numeric PK in the response

#### Scenario: Id-keyed family stays consistent

- **WHEN** a new endpoint is added to an id-keyed family (e.g. the
  unified place detail at `/v1/geo/places/{place_id}`)
- **THEN** it is keyed by the family's numeric identifier and its
  payloads carry that identifier, without introducing a parallel slug
  addressing scheme for the same resource

#### Scenario: Content version field

- **WHEN** a payload exposes the row's last-modified timestamp for
  client caching
- **THEN** the field is named `modified` and carries an ISO 8601 UTC
  string
