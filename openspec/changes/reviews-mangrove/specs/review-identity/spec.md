## ADDED Requirements

### Requirement: One reviewer keypair per account
Each user account SHALL hold at most one Mangrove reviewer keypair (ES256
P-256), minted lazily on the account's first review write action. The
private key SHALL be stored encrypted at rest under a dedicated key
(`MANGROVE_KEY_ENCRYPTION_KEY`, independent of the Django secret) and
SHALL NOT be served by any public endpoint. The public key (`kid` PEM,
whitespace-normalized) SHALL be stored for ownership lookups. An account
without a key SHALL be able to read reviews and to hold an account; only
writing mints the key.

#### Scenario: Lazy minting

- **WHEN** a user account performs its first review write
- **THEN** a keypair is minted and persisted encrypted; subsequent writes reuse it

#### Scenario: Keys never public

- **WHEN** any public or third-party endpoint is called
- **THEN** no private or public key material of any account is included in the response

### Requirement: Server-side signing
All Mangrove JWTs for a user (reviews and actions) SHALL be signed
server-side by the backend using the account's stored key. Users SHALL
NEVER submit pre-signed JWTs through the API; the API accepts review
content, not signatures. The signing service SHALL produce MaReSt-compliant
headers (`alg: ES256`, `typ: JWT`, `kid` PEM, `jwk` JSON string with
`key_ops: ["verify"]`) and claims.

#### Scenario: Content in, JWT out

- **WHEN** a user submits review content
- **THEN** the backend constructs and signs the JWT; the user's client never sees or provides key material or a signature

#### Scenario: Standard-compliant JWT

- **WHEN** a signed review JWT is decoded
- **THEN** it verifies against its embedded `kid`/`jwk` and satisfies the Mangrove Review Standard claims rules

### Requirement: Ownership enforcement before signing
Edit and delete actions SHALL be signed only after the backend verifies
locally that the target review's key id equals the caller's current
reviewer key; otherwise the action SHALL be refused (403) without signing
or relaying. Report-abuse actions carry no ownership requirement (signed
with the reporter's key).

#### Scenario: Ownership check precedes relay

- **WHEN** a user requests a delete of a review signed by another key
- **THEN** the request is refused before any JWT is constructed

### Requirement: PII-safe reviewer defaults
The reviewer profile SHALL keep a display `nickname` used as review
metadata, which SHALL default to a minted non-identifying name. The
system SHALL NOT derive nicknames or any review metadata from account
email, real name, or other account PII, and SHALL reject submitted
metadata that would carry such data beyond the allowed standard fields.

#### Scenario: Minted default nickname

- **WHEN** a user mints a reviewer key without choosing a nickname
- **THEN** their reviews carry a minted nickname unrelated to their account identity data

### Requirement: Key import and export (opt-in)
The system SHALL provide authenticated endpoints to export the account's
private key as a JWK string (compatible with MapComplete and
mangrove.reviews import formats) and to import an existing JWK, re-deriving
its `kid` and rebinding the account to it (one active key per account).
Both actions SHALL be explicitly opt-in by the owner, and export SHALL
require re-authentication. (Delivered in a later implementation phase of
this change; the data model SHALL support it from the start.)

#### Scenario: Export requires ownership and re-auth

- **WHEN** an authenticated owner requests the identity export without a fresh re-authentication
- **THEN** the endpoint refuses; with fresh re-authentication it returns the JWK string

#### Scenario: Import rebinds authorship

- **WHEN** the owner imports a JWK that already authored reviews on other subjects
- **THEN** subsequent edit/delete requests for those reviews pass the ownership check under the new binding

### Requirement: Erasure path
The system SHALL provide a management command (and account-deletion hook)
that, for a given user, signs and relays `delete` actions for every
review authorable by the account (submission log plus upstream kid
listing, covering imported keys), then destroys the reviewer key, profile
and submission-log rows. Erasure SHALL NOT delete reviews authored by
other accounts.

#### Scenario: Full erasure

- **WHEN** the erasure command runs for a user with two submitted reviews
- **THEN** delete actions are relayed for both, the local key/profile/log rows are destroyed, and the user's reviews are marked deleted upstream

#### Scenario: Erasure leaves others untouched

- **WHEN** the erasure command runs
- **THEN** no review authored by another account is deleted or hidden beyond existing blacklist state
