## ADDED Requirements

### Requirement: Pin materialization of provider results
The system SHALL store external provider results as rows of the existing
`Image` model, deduplicated by `(source_org, source_ident)`, with the file
field left empty and the large servable source URL in `source_url_raw`.
Re-syncs SHALL update mutable fields (URLs, dimensions, license metadata) of
existing pins without duplicating them.

#### Scenario: First sync creates pins

- **WHEN** `geoimages_pin` runs for a hut with fresh provider results
- **THEN** one `Image` row is created per unique `(source_org, source_ident)`, each linked to the hut

#### Scenario: Re-sync updates instead of duplicating

- **WHEN** a later sync returns an image that is already pinned
- **THEN** the existing row's mutable fields are updated and no duplicate row or association is created

### Requirement: Score-based pin ordering
Hut-image associations SHALL use a `score` field (renamed from `order`) as the
position: pins are served in descending score order with a deterministic
tiebreaker. New pins SHALL receive their provider score; syncs SHALL NOT
overwrite the score of existing associations. The original provider score
SHALL be preserved in `image_meta.provider_score`.

#### Scenario: New image lands at its natural position

- **WHEN** a re-sync finds a new image whose provider score is higher than existing pins
- **THEN** it is served ahead of all lower-scored pins without any existing pin changing position

#### Scenario: Manual curation survives sync

- **WHEN** an admin edits a pin's score and a later sync completes
- **THEN** the edited score is unchanged and ordering reflects the edit

### Requirement: Lazy pinning on first visit
A hut without pins SHALL be served by running the existing live provider
pipeline in-request and writing the results through as pins in the same
request; no prior warm-up run SHALL be required.

#### Scenario: First visitor triggers write-through

- **WHEN** a request hits a hut that has no pins
- **THEN** the response is built from the live provider pipeline and the same results are persisted as pins

#### Scenario: Second request uses pins

- **WHEN** the hut is requested again after the write-through
- **THEN** the response is served from pins without provider involvement

### Requirement: Queued refresh for stale pins
When a request finds a hut's pins older than 24 hours, the system SHALL only
enqueue a background refresh task (django-q2) and respond immediately from the
existing pins. The refresh SHALL be debounced per hut. Provider calls SHALL
occur exclusively in sync paths (background refresh, forced sync, lazy first
visit), never on the plain hot path.

#### Scenario: Stale pins enqueue, visitor is not delayed

- **WHEN** a request arrives for a hut whose pins are 25 hours old
- **THEN** the response returns from pins/response cache without waiting for providers and at most one refresh task is enqueued for that hut within the debounce window

#### Scenario: Fresh pins enqueue nothing

- **WHEN** a request arrives for a hut whose pins are 1 hour old
- **THEN** no background task is enqueued

### Requirement: Pin visibility control
Only pins with `review_status=approved` and active state SHALL be served.
Hiding all pins of a hut SHALL yield an empty gallery (live fill-up does not
apply once pins exist).

#### Scenario: Hidden pin disappears

- **WHEN** an admin sets a pin's review status to hidden/rejected
- **THEN** subsequent responses for that hut exclude the pin

### Requirement: Pin management command
A `geoimages_pin` management command SHALL support `--all`, `--hut=<slug>`, and
`--dry-run` modes and be schedulable as a recurring q2 task for a monthly
hygiene sweep of rarely visited huts.

#### Scenario: Single-hut sync

- **WHEN** `geoimages_pin --hut=laemmeren --dry-run` runs
- **THEN** it reports the pins it would create/update without writing
