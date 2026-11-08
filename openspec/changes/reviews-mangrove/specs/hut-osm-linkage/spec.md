## ADDED Requirements

### Requirement: Recurring OSM linkage job
The system SHALL run a recurring scheduled job (django-q2; management
command `reviews_osm_sync`) that, for every public+active hut, finds or
verifies a matching OpenStreetMap element via the Overpass API using
candidate queries around the hut location (tourism-hut-class tags) and
deterministic scoring (distance + name similarity). The job SHALL respect
Overpass rate limits (single-threaded, backoff on throttling) and SHALL
operate without any permission or agreement beyond the ODbL license
attribution already present on the `osm` organization records.

#### Scenario: Scheduled run completes

- **WHEN** the scheduled job runs over the hut corpus
- **THEN** every public+active hut is considered exactly once per pass and the run is rate-limited against Overpass

#### Scenario: Overpass throttled

- **WHEN** Overpass answers 429 during a run
- **THEN** the job backs off and resumes (or defers to the next schedule) instead of hammering the endpoint

### Requirement: Unambiguous auto-linking
The job SHALL write or update a `HutSource` row for the `osm`
organization — following the existing linkage pattern (`source_id` =
numeric OSM id; `source_data` JSON with `osm_type`, `center_lat/lon`,
relevant tag subset, and element version when available) — when scoring
yields exactly one candidate above the configured thresholds (distance
and name similarity). Existing links whose element no longer matches
SHALL be flagged for review rather than silently rewritten.

#### Scenario: Unique match writes HutSource

- **WHEN** an unlinked hut has exactly one Overpass candidate within thresholds
- **THEN** a `HutSource` (org `osm`) row is created with the element's data

#### Scenario: Stale link flagged

- **WHEN** a previously linked OSM element moved or was deleted
- **THEN** the job flags the link for manual review instead of auto-rewriting or auto-dropping it

### Requirement: Ambiguity review queue
The job SHALL park ambiguous candidates (multiple plausible matches, or a
single below-threshold match) as link-candidate records in an
admin-managed review queue (Unfold) carrying the hut, the scored
candidates and the reason; staff accept (writes the `HutSource`) or
reject (clears the record). Auto-linking SHALL NOT act on ambiguous
cases.

#### Scenario: Two similar candidates queue

- **WHEN** two OSM elements score above threshold for one hut
- **THEN** no link is written automatically and a queue record with both candidates awaits staff decision

#### Scenario: Staff decision executes

- **WHEN** staff accepts one queued candidate
- **THEN** the `HutSource` row is written and the queue record resolved

### Requirement: OSM id stamping on reviews
When a hut has a current OSM link, review submissions for that hut SHALL
carry `metadata.osm_id` in the standard format (`node/ID[/VERSION]`,
`way/ID[/VERSION]`, `relation/ID[/VERSION]`, ≤50 chars). Huts without a
link SHALL submit without the field (the subject URI stays slug-based and
MUST NOT depend on OSM ids).

#### Scenario: Linked hut stamps osm_id

- **WHEN** a review is submitted for a hut linked to OSM way 123
- **THEN** the signed JWT metadata carries `osm_id: "way/123"` (with version when the sync captured one)

#### Scenario: Unlinked hut submits cleanly

- **WHEN** a hut has no OSM link
- **THEN** the review is submitted without `osm_id` and succeeds
