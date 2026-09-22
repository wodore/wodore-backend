"""
This file contains all the settings used in staging.

Inherits from production.py and overrides staging-specific settings.
"""

# Import all production settings
from server.settings.components import config
from server.settings.environments.production import *

# Environment identifier
ENVIRONMENT = "staging"

# Cache configuration - use different prefix to avoid conflicts
if "default" in CACHES:  # pyright: ignore[reportUndefinedVariable]
    CACHES["default"]["KEY_PREFIX"] = "staging"  # pyright: ignore[reportUndefinedVariable]

# Session cookie - different name to prevent conflicts with production
SESSION_COOKIE_NAME = "sessionid_staging"

# Email backend - rewrite recipient emails to controlled domain
EMAIL_BACKEND = "server.core.email_backends.StagingEmailBackend"
STAGING_EMAIL_REWRITE_ENABLED = config(
    "STAGING_EMAIL_REWRITE_ENABLED", cast=bool, default=True
)
# STAGING_EMAIL_REWRITE_TO defaults to DEFAULT_FROM_EMAIL if not set
STAGING_EMAIL_REWRITE_TO = config("STAGING_EMAIL_REWRITE_TO", default=None)
# Additional emails to whitelist (comma-separated)
STAGING_EMAIL_WHITELIST = (
    [email.strip() for email in config("STAGING_EMAIL_WHITELIST", "").split(",")]
    if config("STAGING_EMAIL_WHITELIST", "")
    else []
)

# Add staging-specific middleware for headers
MIDDLEWARE = list(MIDDLEWARE)  # pyright: ignore[reportUndefinedVariable]
# Add robots tag to prevent indexing (environment header is already in common.py)
MIDDLEWARE.insert(0, "server.middleware.headers.RobotsTagMiddleware")
MIDDLEWARE = tuple(MIDDLEWARE)  # pyright: ignore[reportUndefinedVariable]
