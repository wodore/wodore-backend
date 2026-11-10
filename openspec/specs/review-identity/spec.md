# review-identity Specification

## Purpose
TBD - created by archiving change reviews-mangrove. Update Purpose after archive.
## Requirements
### Requirement: One reviewer keypair per account
Each user account SHALL hold at most one Open Reviews reviewer keypair (ES256
P-256), minted lazily on the account's first review write action. The
private key SHALL be stored encrypted at rest under a dedicated key
(`ORA_KEY_ENCRYPTION_KEY`, independent of the Django secret; its
insecure default SHALL be refused outside development/test environments)
and SHALL NOT be served by any endpoint of this change. The public key
(`kid` PEM, whitespace-normalized single-line form) SHALL be stored for
ownership lookups. The user foreign keys of the reviewer models SHALL use
`on_delete=PROTECT` so that deleting an account without the erasure path
fails loudly instead of destroying the only key able to sign delete
actions for the account's reviews.

#### Scenario: Lazy minting

- **WHEN** a user account performs its first review write
- **THEN** a keypair is minted and persisted encrypted; subsequent writes reuse it

#### Scenario: Keys never public

- **WHEN** any public endpoint of this change is called
- **THEN** no private key material of any account is included in the response

#### Scenario: Account deletion is guarded

- **WHEN** a user with reviews is deleted without running the erasure path
- **THEN** the database refuses the deletion (protected foreign key) rather than silently losing the signing key

### Requirement: Server-side signing
All Mangrove JWTs for a user (reviews and actions) SHALL be signed
server-side by the backend using the account's stored key. Users SHALL
NEVER submit pre-signed JWTs through the API; the API accepts review
content, not signatures. The signing service SHALL produce MaReSt-compliant
headers (`alg: ES256`, `typ: JWT`, single-line `kid` PEM, `jwk` JSON
string with `key_ops: ["verify"]`) and claims.

#### Scenario: Content in, JWT out

- **WHEN** a user submits review content
- **THEN** the backend constructs and signs the JWT; the user's client never sees or provides key material or a signature

#### Scenario: Standard-compliant JWT

- **WHEN** a signed review JWT is decoded
- **THEN** it verifies against its embedded `kid`/`jwk` and satisfies the Open Reviews Review Standard claims rules

### Requirement: Ownership enforcement before signing
Edit and delete actions SHALL be signed only after the backend verifies
that the target review belongs to the caller: its signature found in the
submission log under the caller's user with the caller's current key, or
— for targets not in the log — the upstream review record whose `kid`
equals the caller's (whitespace-insensitive comparison). Otherwise the
action SHALL be refused (403) without signing or relaying. Report-abuse
actions carry no ownership requirement (signed with the reporter's key).

#### Scenario: Ownership check precedes relay

- **WHEN** a user requests a delete of a review signed by another key
- **THEN** the request is refused before any JWT is constructed

### Requirement: PII-safe reviewer defaults
The reviewer profile SHALL keep a display `nickname` used as review
metadata, which SHALL default to a minted non-identifying name. The
system SHALL NOT derive nicknames or any review metadata from account
email, real name, or other account PII, and the accepted metadata subset
carries no such fields. A per-review `nickname` in the request payload
SHALL override the profile default.

#### Scenario: Minted default nickname

- **WHEN** a user mints a reviewer key without choosing a nickname
- **THEN** their reviews carry a minted nickname unrelated to their account identity data

#### Scenario: Per-review override

- **WHEN** a submission carries an explicit `nickname`
- **THEN** that review's metadata uses it; the profile default is unchanged

### Requirement: Erasure path
The system SHALL provide a management command that, for a given user,
signs and relays `delete` actions for every review authorable by the
account (from the submission log), treating upstream refusals for
already-deleted reviews as success, and then destroys the reviewer key,
profile and submission-log rows (the one documented exception to the
log's append-only rule). Erasure SHALL NOT delete or hide reviews
authored by other accounts.

#### Scenario: Full erasure

- **WHEN** the erasure command runs for a user with two submitted reviews
- **THEN** delete actions are relayed for both, the local key/profile/log rows are destroyed, and the user's reviews are marked deleted upstream

#### Scenario: Erasure leaves others untouched

- **WHEN** the erasure command runs
- **THEN** no review authored by another account is deleted or hidden beyond existing blacklist state

#### Scenario: Idempotent erasure

- **WHEN** a delete action is refused upstream because the review is already deleted
- **THEN** erasure continues and treats that target as erased

