"""django-allauth settings for the built-in account management
(spec: account-management).

App/middleware/backend *registrations* live in ``components/registry.py``
(loaded last, after the environment files); this component only defines
allauth behavior and the Argon2 password hasher. It loads *before* the
environment files, so ``environments/test.py`` can still override
``PASSWORD_HASHERS`` with the fast MD5 hasher.
"""

# Accounts are created by admins / the fixture command; no self-signup.
ACCOUNT_SIGNUP_ENABLED = False

# Login identifiers: email only (no username).
# Methods: password, emailed one-time code, and passkey (below).
ACCOUNT_LOGIN_METHODS = {"username": False, "email": True}

# Login by emailed one-time code ("magic code") alongside the password.
# Requires a working email backend in production.
ACCOUNT_LOGIN_BY_CODE_ENABLED = True

# No self-service email verification yet (admin-created accounts);
# revisit when self-registration opens up.
ACCOUNT_EMAIL_VERIFICATION = "none"

# MFA: authenticator apps (TOTP), WebAuthn security keys / passkeys, and
# recovery codes. Passkeys additionally work as a passwordless *login*
# method on the unified login page. (Phone/SMS and social login are
# deliberately not enabled.)
MFA_SUPPORTED_TYPES = ["totp", "webauthn", "recovery_codes"]
MFA_PASSKEY_LOGIN_ENABLED = True

# Do not reveal whether an account exists (login/reset responses).
ACCOUNT_PREVENT_ENUMERATION = True

# Brute-force protection on top of django-axes (already in the backends).
# Format: "attempts/window[/per]" with per ∈ {ip, user, key} — "key" is
# the login identifier (email), giving per-account lockout on failures.
ACCOUNT_RATE_LIMITS = {
    "login": "10/5m, 30/1h",
    "login_failed": "10/5m/key, 50/1h/ip",
    "reset_password": "5/5m, 20/1h",
}

# Argon2 first; falls back to the other hashers for existing passwords.
# (Overridden to MD5 in the test environment.)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]
