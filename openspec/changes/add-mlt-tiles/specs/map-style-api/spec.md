# map-style-api Delta

## ADDED Requirements

### Requirement: Vector source encoding preservation

The style rendering pipeline SHALL preserve the `encoding` property of
vector source definitions (e.g. `"encoding": "mlt"`) verbatim in both
resolved and tokenized modes, alongside the existing URL absolutization
and token handling. Sources without an `encoding` property SHALL remain
without one — the pipeline SHALL neither inject nor strip the property.

#### Scenario: Resolved mode keeps the MLT encoding

- **WHEN** a style whose huts vector source declares `"encoding": "mlt"` is served in resolved mode
- **THEN** the served document's huts source still carries `"encoding": "mlt"` with absolutized tile URLs

#### Scenario: Tokenized mode keeps the MLT encoding

- **WHEN** the same style is served with `?mode=tokenized`
- **THEN** the source's `"encoding": "mlt"` survives alongside the intact parameter tokens

#### Scenario: Absence is preserved

- **WHEN** a style's vector sources declare no `encoding` property
- **THEN** the served document in both modes contains no `encoding` property on those sources
