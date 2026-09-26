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

# Email is the login identifier (matches the fixture users and the
# frontend's Zitadel-era username field).
ACCOUNT_LOGIN_METHODS = {"username": False, "email": True}

# No self-service email verification yet (admin-created accounts);
# revisit when self-registration opens up.
ACCOUNT_EMAIL_VERIFICATION = "none"

# Do not reveal whether an account exists (login/reset responses).
ACCOUNT_PREVENT_ENUMERATION = True

# Brute-force protection on top of django-axes (already in the backends).
ACCOUNT_RATE_LIMITS = {
    "login": "5/5m/ip+username",
    "login_failed": "10/5m/ip+username",
    "reset_password": "5/5m/email",
}

# Argon2 first; falls back to the other hashers for existing passwords.
# (Overridden to MD5 in the test environment.)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]
