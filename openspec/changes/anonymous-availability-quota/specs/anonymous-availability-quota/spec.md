## ADDED Requirements

### Requirement: Free anonymous quota on availability endpoints
Anonymous requests to the availability endpoints SHALL be granted a
configurable number of free requests per reset window (default 20 per
calendar day), counted per visitor fingerprint rather than per IP.

#### Scenario: Casual anonymous use stays free

- **WHEN** an anonymous visitor makes fewer than the quota of availability requests within the window
- **THEN** all requests succeed and carry `X-Quota-Remaining`

#### Scenario: Quota exhaustion requires login

- **WHEN** an anonymous visitor exceeds the free quota within the window
- **THEN** subsequent availability requests answer 429 with error code `anonymous_quota_exceeded` and the reset time in the response

### Requirement: Visitor fingerprint identity
The quota counter key SHALL be a server-side salted hash of a client-supplied
visitor id header; requests without one fall back to the IP + user-agent
hash. Raw fingerprint material SHALL NOT be stored.

#### Scenario: Same visitor across IP changes

- **WHEN** the same visitor (same client visitor id) moves between networks within a window
- **THEN** their quota consumption follows them (one shared counter)

#### Scenario: No visitor id supplied

- **WHEN** a client sends no visitor id header
- **THEN** its requests are counted under the IP + user-agent fallback hash

### Requirement: Authenticated requests bypass the anonymous quota
Requests bearing a valid bearer token SHALL NOT consume or be limited by the
anonymous quota.

#### Scenario: Logged-in user after anonymous exhaustion

- **WHEN** a visitor who exhausted the anonymous quota authenticates and retries
- **THEN** the request succeeds without quota headers affecting it

### Requirement: Configurable reset window
The quota window SHALL be configurable between calendar day (default) and
ISO week, resetting without manual intervention.

#### Scenario: Daily reset

- **WHEN** the calendar day (or ISO week, when configured) rolls over
- **THEN** a previously exhausted anonymous visitor's quota is fully restored

### Requirement: Distinct exhaustion semantics from rate throttling
Quota exhaustion SHALL be distinguishable from rate throttling in the
response body (different error `code`) so clients can present a login
prompt instead of a back-off.

#### Scenario: Client differentiation

- **WHEN** a client receives a 429 with `anonymous_quota_exceeded`
- **THEN** it can show a login call-to-action rather than a retry timer
