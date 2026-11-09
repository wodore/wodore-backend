"""Reviews settings — Mangrove integration (openspec: reviews-mangrove).

All ``ORA_*`` decidables live here; production values come from
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
ORA_ENABLED: bool = config("ORA_ENABLED", cast=bool, default=_IS_DEV_OR_TEST)

#: Publishing guard (Opus review B5): there is no Mangrove sandbox —
#: every non-stubbed write publishes permanently to the open dataset.
#: Dev/test/staging default OFF (test suites stub the client); production
#: flips it together with ORA_ENABLED at rollout.
ORA_WRITES_ENABLED: bool = config("ORA_WRITES_ENABLED", cast=bool, default=False)

#: Identity export/import (phase 2). Default OFF until re-auth for
#: export is implemented (Opus final review B3): the private JWK is
#: un-rotatable — a leaked token means permanent identity theft.
ORA_IDENTITY_ENABLED: bool = config("ORA_IDENTITY_ENABLED", cast=bool, default=False)

#: Original Mangrove Server base URL (OpenAPI 0.4.1 at deploy time).
ORA_API_BASE_URL: str = config(
    "ORA_API_BASE_URL", default="https://api.mangrove.reviews"
)

#: Upstream timeouts (seconds) — connect / read.
ORA_TIMEOUT_CONNECT: float = config("ORA_TIMEOUT_CONNECT", cast=float, default=5.0)
ORA_TIMEOUT_READ: float = config("ORA_TIMEOUT_READ", cast=float, default=10.0)

#: GET retry budget for idempotent reads (submits never retry).
ORA_GET_RETRIES: int = config("ORA_GET_RETRIES", cast=int, default=2)

#: Uncertainty radius ``u`` of every hut subject URI (meters, 0 < u ≤ 10000).
ORA_U_RADIUS: int = config("ORA_U_RADIUS", cast=int, default=30)

#: Local cache TTLs (seconds) for the proxied list / summary payloads.
#: Lists default to 15 minutes; write-through merging keeps a fresh
#: author's own review visible immediately regardless of the TTL.
ORA_CACHE_TTL_LIST: int = config("ORA_CACHE_TTL_LIST", cast=int, default=900)
ORA_CACHE_TTL_SUMMARY: int = config("ORA_CACHE_TTL_SUMMARY", cast=int, default=900)

#: Anonymous read cache TTL surfaced as ``Cache-Control`` (seconds) —
#: short so foreign-review lag stays bounded (design D6).
ORA_PUBLIC_MAX_AGE: int = config("ORA_PUBLIC_MAX_AGE", cast=int, default=120)

#: Per-user rolling 24 h write quotas (design O7): submissions and
#: edit+delete combined. Counted from the submission log.
ORA_QUOTA_SUBMIT: int = config("ORA_QUOTA_SUBMIT", cast=int, default=5)
ORA_QUOTA_EDIT: int = config("ORA_QUOTA_EDIT", cast=int, default=20)

#: ``metadata.client_id`` stamped on Wodore-submitted reviews (frontend
#: origin URI per MaReSt).
ORA_CLIENT_ID: str = config("ORA_CLIENT_ID", default="https://wodore.com")


def _csv_hosts(value: str) -> list[str]:
    """decouple cast: comma-separated host list -> stripped non-empty entries."""
    return [host.strip() for host in value.split(",") if host.strip()]


#: Image hosts allowed at SERVING time: ``images[].src`` URLs on other
#: hosts are dropped from responses (never mutated upstream). Default is
#: dump-verified: 1022 of 1025 persisted image URLs in the 2026-11-08
#: dataset dump live on this host (design D9).
ORA_IMAGE_HOST_ALLOWLIST: list[str] = config(
    "ORA_IMAGE_HOST_ALLOWLIST",
    cast=_csv_hosts,
    default="files.mangrove.reviews",
)

#: Review-read rate throttles (per client IP): burst per minute / daily.
ORA_THROTTLE_READ_BURST_PER_MIN: int = config(
    "ORA_THROTTLE_READ_BURST_PER_MIN", cast=int, default=60
)
ORA_THROTTLE_READ_DAILY: int = config(
    "ORA_THROTTLE_READ_DAILY", cast=int, default=10000
)
#: Batch-summary throttle (per client IP, per minute) — map-badge loads.
ORA_THROTTLE_BATCH_PER_MIN: int = config(
    "ORA_THROTTLE_BATCH_PER_MIN", cast=int, default=30
)

# ── Read-only provider: refuges.info ────────────────────────────────
#
# Comments API (``GET /api/commentaires?id_point=…``) — verified live
# 2026-11-08: 19–54 text comments on sampled refuges; every response
# carries ``copyright … CC By-Sa 2.0``. Served with per-review source +
# license + link; never re-published into Mangrove (BY-SA relicensing).

ORA_REFUGES_INFO_ENABLED: bool = config(
    "ORA_REFUGES_INFO_ENABLED", cast=bool, default=True
)
ORA_REFUGES_INFO_API_BASE: str = config(
    "ORA_REFUGES_INFO_API_BASE", default="https://www.refuges.info"
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

_raw_key_secret: str = config("ORA_KEY_ENCRYPTION_KEY", default="")
if _raw_key_secret:
    ORA_KEY_ENCRYPTION_KEYS: list[str] = [
        _raw_key_secret,
        *[
            h.strip()
            for h in config("ORA_KEY_ENCRYPTION_KEYS_OLD", default="").split(",")
            if h.strip()
        ],
    ]
elif _IS_DEV_OR_TEST or not ORA_ENABLED:
    # Dev/test always uses the committed default; a reviews-disabled
    # deployment may boot without the secret (writes answer 503, keys are
    # never minted) — mirroring the built-in provider's "refuse only when
    # the feature is active" stance.
    ORA_KEY_ENCRYPTION_KEYS = _DEV_KEY_ENCRYPTION_KEYS
else:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "ORA_ENABLED is true but ORA_KEY_ENCRYPTION_KEY is not "
        "configured. Reviewer private keys must be encrypted at rest with a "
        "dedicated secret (Infisical) — the committed dev default is only "
        "allowed in development/test (mirrors LOCAL_AUTH_PRIVATE_KEY_JWK's "
        "stance)."
    )
