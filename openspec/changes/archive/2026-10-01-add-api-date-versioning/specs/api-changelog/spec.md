# Spec Delta: api-changelog

## ADDED Requirements

### Requirement: Separate API changelog
The project SHALL generate `CHANGELOG_API.md` with git-cliff from a dedicated `cliff-api.toml`, including only PRs labeled `api:breaking`, `api:added`, `api:deprecated` or `api:fixed`, grouped by API tags matching `api/YYYY-MM-DD`, independent of the backend `CHANGELOG.md`.

#### Scenario: Generating the API changelog
- **WHEN** a maintainer runs git-cliff with `cliff-api.toml`
- **THEN** only `api:*` labeled PRs appear, grouped per API tag and label

#### Scenario: Non-breaking API changes between versions
- **WHEN** an `api:added` PR lands between two API version tags
- **THEN** its entry appears under a "Live in all versions" heading

#### Scenario: Backend changelog unaffected
- **WHEN** the backend changelog is generated with `cliff.toml`
- **THEN** its content and grouping are unchanged

### Requirement: Breaking changes require a version
A PR labeled `api:breaking` SHALL add a `VersionChange` registry entry and a snapshot, and SHALL be released with a matching `api/<version>` tag whose changelog entry matches the `VersionChange` description.

#### Scenario: Breaking PR without version
- **WHEN** a PR has the `api:breaking` label but no new registry entry
- **THEN** CI fails with a message explaining the required steps
