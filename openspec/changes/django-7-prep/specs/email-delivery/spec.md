## ADDED Requirements

### Requirement: Mail sending reads configuration from the MAILERS setting

The system SHALL configure mail delivery exclusively through the Django
`MAILERS` setting (a `"default"` entry with `BACKEND` and `OPTIONS`), and
SHALL NOT set any deprecated `EMAIL_*` setting (`EMAIL_BACKEND`, `EMAIL_HOST`,
`EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`,
`EMAIL_USE_SSL`, `EMAIL_TIMEOUT`). Per-environment backend selection
(development console, staging rewrite backend, production SMTP) SHALL be
expressed as the `"default"` mailer's `BACKEND`.

#### Scenario: Feedback mail is delivered through the default mailer

- **WHEN** the feedback endpoint sends an `EmailMessage` without an explicit connection
- **THEN** the message is delivered through `MAILERS["default"]` with the environment's configured backend and options

#### Scenario: Configuration boots without deprecated email settings

- **WHEN** any of the development, staging, or production settings load
- **THEN** no `EMAIL_*` setting is set and `django check` reports no `mail.W001` warning

#### Scenario: Mail-related deprecation warnings are absent

- **WHEN** the test suite runs
- **THEN** no `RemovedInDjango70Warning` for email settings or the email API is emitted by project code

### Requirement: Staging address-rewrite backend preserved under MAILERS

The staging mailer SHALL keep using the address-rewrite backend
(`server.core.email_backends.EmailBackend`) as `MAILERS["default"]["BACKEND"]`,
rewriting `to`, `cc`, and `bcc` recipients as it does today, and SHALL work
when Django instantiates it with the mailer `alias` keyword.

#### Scenario: Staging mail is rewritten

- **WHEN** a message is sent on staging with rewriting enabled
- **THEN** all recipients are rewritten to the configured staging target and the subject carries the original-recipients tag

#### Scenario: Rewriting can be disabled

- **WHEN** `STAGING_EMAIL_REWRITE_ENABLED` is `False`
- **THEN** messages are passed through to the wrapped backend unmodified

### Requirement: Mail delivery health check works without legacy settings

The health-check mail probe SHALL pass with only `MAILERS` configured, either
via a MAILERS-aware `django-health-check` release or via a documented,
narrowly-scoped exception, so mail deliverability monitoring survives the
removal of `EMAIL_*` settings.

#### Scenario: Mail health check evaluates the default mailer

- **WHEN** the health endpoint runs the mail check on a system configured only through `MAILERS`
- **THEN** the check reports the deliverability status of `MAILERS["default"]` and emits no deprecation warning from project configuration
