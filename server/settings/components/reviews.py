"""Reviews settings — Mangrove integration (openspec: reviews-mangrove).

All ``MANGROVE_*`` decidables live here; production values come from
Infisical (see the runbook note in AGENTS.md § Reviews). The
key-encryption secret is refused its dev default outside
development/test, mirroring the built-in OIDC provider's stance.
"""

import os

from server.settings.components import config

_IS_DEV_OR_TEST = os.environ.get("DJANGO_ENV") in ("development", "test")

#: Kill-switch: when false, writes answer 503 ``service_unavailable`` and
#: reads degrade to empty collections (frontend keeps working, just
#: reviewless). Rollback path for upstream incidents — and the production
#: default until the rollout explicitly enables it (together with the
#: key-encryption secret, see below).
MANGROVE_ENABLED: bool = config("MANGROVE_ENABLED", cast=bool, default=_IS_DEV_OR_TEST)

#: Original Mangrove Server base URL (OpenAPI 0.4.1 at deploy time).
MANGROVE_API_BASE_URL: str = config(
    "MANGROVE_API_BASE_URL", default="https://api.mangrove.reviews"
)

#: Upstream timeouts (seconds) — connect / read.
MANGROVE_TIMEOUT_CONNECT: float = config(
    "MANGROVE_TIMEOUT_CONNECT", cast=float, default=5.0
)
MANGROVE_TIMEOUT_READ: float = config("MANGROVE_TIMEOUT_READ", cast=float, default=10.0)

#: GET retry budget for idempotent reads (submits never retry).
MANGROVE_GET_RETRIES: int = config("MANGROVE_GET_RETRIES", cast=int, default=2)

#: Uncertainty radius ``u`` of every hut subject URI (meters, 0 < u ≤ 10000).
MANGROVE_U_RADIUS: int = config("MANGROVE_U_RADIUS", cast=int, default=30)

#: Local cache TTLs (seconds) for the proxied list / summary payloads.
#: Lists default to 15 minutes; write-through merging keeps a fresh
#: author's own review visible immediately regardless of the TTL.
MANGROVE_CACHE_TTL_LIST: int = config("MANGROVE_CACHE_TTL_LIST", cast=int, default=900)
MANGROVE_CACHE_TTL_SUMMARY: int = config(
    "MANGROVE_CACHE_TTL_SUMMARY", cast=int, default=900
)

#: Anonymous read cache TTL surfaced as ``Cache-Control`` (seconds) —
#: short so foreign-review lag stays bounded (design D6).
MANGROVE_PUBLIC_MAX_AGE: int = config("MANGROVE_PUBLIC_MAX_AGE", cast=int, default=120)

#: Per-user rolling 24 h write quotas (design O7): submissions and
#: edit+delete combined. Counted from the submission log.
MANGROVE_QUOTA_SUBMIT: int = config("MANGROVE_QUOTA_SUBMIT", cast=int, default=5)
MANGROVE_QUOTA_EDIT: int = config("MANGROVE_QUOTA_EDIT", cast=int, default=20)

#: ``metadata.client_id`` stamped on Wodore-submitted reviews (frontend
#: origin URI per MaReSt).
MANGROVE_CLIENT_ID: str = config("MANGROVE_CLIENT_ID", default="https://wodore.com")


def _csv_hosts(value: str) -> list[str]:
    """decouple cast: comma-separated host list -> stripped non-empty entries."""
    return [host.strip() for host in value.split(",") if host.strip()]


#: Image hosts allowed at SERVING time: ``images[].src`` URLs on other
#: hosts are dropped from responses (never mutated upstream). Default is
#: dump-verified: 1022 of 1025 persisted image URLs in the 2026-11-08
#: dataset dump live on this host (design D9).
MANGROVE_IMAGE_HOST_ALLOWLIST: list[str] = config(
    "MANGROVE_IMAGE_HOST_ALLOWLIST",
    cast=_csv_hosts,
    default="files.mangrove.reviews",
)

#: Review-read rate throttles (per client IP): burst per minute / daily.
MANGROVE_THROTTLE_READ_BURST_PER_MIN: int = config(
    "MANGROVE_THROTTLE_READ_BURST_PER_MIN", cast=int, default=60
)
MANGROVE_THROTTLE_READ_DAILY: int = config(
    "MANGROVE_THROTTLE_READ_DAILY", cast=int, default=10000
)
#: Batch-summary throttle (per client IP, per minute) — map-badge loads.
MANGROVE_THROTTLE_BATCH_PER_MIN: int = config(
    "MANGROVE_THROTTLE_BATCH_PER_MIN", cast=int, default=30
)

# ── Read-only provider: refuges.info ────────────────────────────────
#
# Comments API (``GET /api/commentaires?id_point=…``) — verified live
# 2026-11-08: 19–54 text comments on sampled refuges; every response
# carries ``copyright … CC By-Sa 2.0``. Served with per-review source +
# license + link; never re-published into Mangrove (BY-SA relicensing).

MANGROVE_REFUGES_INFO_ENABLED: bool = config(
    "MANGROVE_REFUGES_INFO_ENABLED", cast=bool, default=True
)
MANGROVE_REFUGES_INFO_API_BASE: str = config(
    "MANGROVE_REFUGES_INFO_API_BASE", default="https://www.refuges.info"
)

# ── Reviewer key custody ─────────────────────────────────────────────
#
# The per-account ES256 private keys are encrypted at rest with Fernet
# under keys derived from these secrets (MultiFernet: first entry is the
# primary, the rest stay decryptable — rotation is add-new-keep-old,
# documented in AGENTS.md § Reviews). Independent from DJANGO_SECRET_KEY
# on purpose.

_DEV_KEY_ENCRYPTION_KEYS: list[str] = [
    "dev-only-insecure-mangrove-key-encryption-secret-do-not-use-in-prod"
]

_raw_key_secret: str = config("MANGROVE_KEY_ENCRYPTION_KEY", default="")
if _raw_key_secret:
    MANGROVE_KEY_ENCRYPTION_KEYS: list[str] = [
        _raw_key_secret,
        *[
            h.strip()
            for h in config("MANGROVE_KEY_ENCRYPTION_KEYS_OLD", default="").split(",")
            if h.strip()
        ],
    ]
elif _IS_DEV_OR_TEST or not MANGROVE_ENABLED:
    # Dev/test always uses the committed default; a reviews-disabled
    # deployment may boot without the secret (writes answer 503, keys are
    # never minted) — mirroring the built-in provider's "refuse only when
    # the feature is active" stance.
    MANGROVE_KEY_ENCRYPTION_KEYS = _DEV_KEY_ENCRYPTION_KEYS
else:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "MANGROVE_ENABLED is true but MANGROVE_KEY_ENCRYPTION_KEY is not "
        "configured. Reviewer private keys must be encrypted at rest with a "
        "dedicated secret (Infisical) — the committed dev default is only "
        "allowed in development/test (mirrors LOCAL_AUTH_PRIVATE_KEY_JWK's "
        "stance)."
    )
