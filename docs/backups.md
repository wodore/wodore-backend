# Backups & staging data

Backups are produced and encrypted outside this repository (ops), but this
page is the contract for what a backup must contain, what it may leave out,
and how production data may reach staging. The goal: **no user data ever
leaves production** — developers must not have access to it.

## What every backup may exclude

Ephemeral auth state. Losing it is harmless — users simply log in again:

```bash
pg_dump ... \
  --exclude-table-data='django_session' \
  --exclude-table-data='account_emailconfirmation' \
  --exclude-table-data='usersessions_usersession' \
  --exclude-table-data='oauth2_provider_grant' \
  --exclude-table-data='oauth2_provider_accesstoken' \
  --exclude-table-data='oauth2_provider_refreshtoken' \
  --exclude-table-data='oauth2_provider_idtoken' \
  --exclude-table-data='axes_attempts'   # login-throttle state (IPs, usernames)
```

Keep everything else, notably:

- `accounts_user` — restoring passwords requires the Argon2 hashes
  (and email is the login identifier),
- `mfa_authenticator` — TOTP secrets / recovery codes; dropping them
  locks users out of MFA,
- `account_emailaddress` — verified-email state.

Backups therefore contain personal data: encrypt at rest with keys held by
ops, restrict restore access, and never copy raw dumps to developer
machines. The `cleartokens` cron keeps the token tables small between
backups anyway.

## Staging data policy

Staging must never hold real user data:

- Copy **business data only** (huts, availability, organizations, …) — via
  a targeted sync or a restore that *also* excludes `accounts_user`,
  `account_emailaddress`, and `mfa_authenticator` in addition to the
  tables above.
- If business rows reference users, insert **placeholder users with the
  same UUIDs** (`user-<id>@staging.example.invalid`, fake name, unusable
  password) so foreign keys stay valid and the data shape stays realistic.
- Staging accounts are staging-local (fixture/bootstrap command), never
  imported.
- `contacts.Contact` and `feedbacks.Feedback` hold personal data of real
  people (wardens' emails/phones) — scrub them during the copy (fake
  names, empty email/phone) or exclude them.

User PKs are UUID v4 (`accounts.0003_uuid_pk`), so placeholder users can
re-use production ids without collisions or enumeration leaks.
