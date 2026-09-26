## ADDED Requirements

### Requirement: Account lifecycle flows
The system SHALL provide django-allauth account flows for login, logout,
password reset, and email address verification, usable by both admin and end
users, with templates that are usable on mobile viewport sizes.

#### Scenario: Login with credentials
- **WHEN** a user submits valid credentials to the login view
- **THEN** an authenticated Django session is established and the user is redirected to the continuation target

#### Scenario: Password reset round trip
- **WHEN** a user requests a password reset and follows the emailed link
- **THEN** the user can set a new password and then log in with it

### Requirement: Password hashing with Argon2
User passwords SHALL be hashed with Argon2 (via the `argon2-cffi` hasher as
the preferred hasher).

#### Scenario: Hasher configuration
- **WHEN** settings load
- **THEN** `PASSWORD_HASHERS` lists the Argon2 hasher first

### Requirement: Brute-force and enumeration protection
The account flows SHALL apply rate limiting to login and password-reset
attempts, and password-reset and email-verification responses SHALL NOT
reveal whether an account exists for a given address.

#### Scenario: Repeated failed logins are throttled
- **WHEN** login fails repeatedly from the same source
- **THEN** further attempts are rate-limited with an error response before authentication is attempted again

#### Scenario: Reset request does not leak accounts
- **WHEN** a password reset is requested for an address with no account
- **THEN** the response is indistinguishable from the registered-address case

### Requirement: MFA availability
Users SHALL be able to enroll TOTP multi-factor authentication with recovery
codes for their own accounts.

#### Scenario: TOTP enrollment and challenge
- **WHEN** a user enrolls a TOTP authenticator and next logs in
- **THEN** login requires a valid one-time code or recovery code

### Requirement: Session management
Users SHALL be able to view and revoke their own active sessions.

#### Scenario: Revoke a session
- **WHEN** a user revokes one of their sessions
- **THEN** subsequent authenticated requests using that session are rejected

### Requirement: Admin login integration
The Django admin login SHALL use the same account system: unauthenticated
`/admin/` requests SHALL be redirected to the unified login view, and
successful staff login SHALL land in the admin.

#### Scenario: Admin redirect
- **WHEN** an anonymous user requests `/admin/`
- **THEN** the response redirects to the account login and preserves the admin continuation target

### Requirement: Dev fixture users command
The system SHALL provide an idempotent management command that creates the
development fixture users and their Django groups (including passwords),
successor to the removed `local_auth_users` command.

#### Scenario: Idempotent bootstrap
- **WHEN** the command runs twice
- **THEN** users and groups exist exactly once with the configured passwords and memberships
