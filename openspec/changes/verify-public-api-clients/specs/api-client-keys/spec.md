## ADDED Requirements

### Requirement: Client keys are stored as hashes only

The key registry MUST store only a hash of each key. The full key MUST be
shown exactly once, at issuance, and MUST NOT be recoverable afterwards.
Validation MUST be by hash lookup of the presented key.

#### Scenario: Issuance returns the key once

- **WHEN** a new client key is issued
- **THEN** the full key is returned in the command/creation output and only
  its hash is persisted

#### Scenario: Key material is not retrievable

- **WHEN** an operator lists existing keys or opens one in the admin
- **THEN** no full key material is displayed or stored anywhere

### Requirement: Keys are issued, rotated, and revoked operationally

Keys MUST support issuance (with a name and platform tag, e.g. `web`,
`android`), rotation (new key issued, old entry deactivated), and
revocation (deactivation takes effect on the next request) via a management
command and via the Django admin. Revocation MUST NOT require a restart.

#### Scenario: Issue via management command

- **WHEN** an operator runs the client-keys command to create a key for
  platform `web`
- **THEN** a new active registry entry exists and the key is printed once

#### Scenario: Rotation supersedes the old key

- **WHEN** an existing key is rotated
- **THEN** the old key stops working and the new key is active immediately,
  without a restart

#### Scenario: Revocation is immediate

- **WHEN** a key is deactivated in the admin
- **THEN** the next request presenting it is rejected with `403`

### Requirement: Key usage is observable

Each key MUST record observable usage telemetry (at minimum last-use
timestamp and a request counter) with at most bounded staleness so that
per-client traffic and leaked-key detection are possible without
per-request synchronous writes.

#### Scenario: Successful gated request updates telemetry

- **WHEN** a request authenticates with a key
- **THEN** the key's usage counter and last-use timestamp advance within a
  bounded interval

### Requirement: Per-key rate budgets are configurable

Each key MUST carry its own rate-limit budget, with a sensible default from
settings, so a specific client can be throttled or loosened independently.

#### Scenario: Key-specific budget overrides the default

- **WHEN** a key has a custom budget lower than the default and exceeds it
- **THEN** its requests are limited by its own budget
