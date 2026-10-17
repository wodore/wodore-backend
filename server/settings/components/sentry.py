"""Error tracking via the Sentry protocol (openspec: add-error-tracking).

Vendor-neutral: the SDK ships to whatever DSN it is given — sentry.io or
Better Stack (Sentry-SDK-compatible ingestion) — so the vendor choice is
an ops decision (swap ``SENTRY_DSN``), never a code change.

Included FIRST in the settings include list (before ``logging.py``): the
logging hook must be installed before ``logging.config.dictConfig`` runs,
and errors raised during settings import itself are still captured.

Activation is DSN-gated: no ``SENTRY_DSN`` -> ``sentry_sdk.init`` is not
called at all and no telemetry leaves the process (dev/test/CI set no
DSN and behave exactly as before this component existed).

Reads only environment variables (python-decouple like every other
component) — it has no ordering dependency on names other components
define: this runs before ``common.py`` sets ``GIT_HASH`` and before the
environment files set ``ENVIRONMENT``, so both are taken from env
directly (``GIT_HASH`` is baked into every image by the docker build;
``DJANGO_ENV`` is always set by ``server/settings/__init__.py`` before
the includes execute).

Release tagging (spec: release/environment attribution): ``release`` is
the commit hash in *both* staging and production — deploys are per-push
to main, so the bumpversion semver is release-cadence, not
deploy-cadence, and a per-environment release scheme would break
cross-env correlation. The semver rides along as an ``app_version`` tag
for human-readable filtering.
"""

import logging
import os
import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version

import sentry_sdk
from decouple import config
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

# k8s probes must never create trace transactions (sentry-sdk 2.72 has no
# `ignore_transactions` option — a small traces_sampler is the supported
# mechanism; see design.md D6).
_HEALTH_PATH_RE = re.compile(r"^/health/")


def _transaction_path(sampling_context: dict) -> str:
    """Best request path available at sampling time.

    The transaction *name* is useless for matching at sampling time: WSGI
    transactions are still named ``"generic WSGI request"`` (the Django
    route resolves only later) and ASGI names are full URLs. Both runtimes
    pass the raw request in the sampling context — read the path from
    there; non-HTTP transactions fall back to their (already-resolved)
    name.
    """
    wsgi_environ = sampling_context.get("wsgi_environ") or {}
    path = wsgi_environ.get("PATH_INFO")
    if not path:
        asgi_scope = sampling_context.get("asgi_scope") or {}
        path = asgi_scope.get("path")
    if not path:
        path = (sampling_context.get("transaction_context") or {}).get("name") or ""
    return path or ""


def _app_version() -> str | None:
    """Package semver (bumpversion-managed), if the project is installed."""
    try:
        return pkg_version("wodore-backend")
    except PackageNotFoundError:  # e.g. vendored/partial installs
        return None


# Resolved once at settings load; attached to every error event in
# ``before_send`` (and every transaction in ``before_send_transaction``)
# — deterministic regardless of scope semantics (the SDK has no
# ``default_tags`` init option in 2.72).
_APP_VERSION = _app_version()


def _stamp_app_version(event: dict) -> dict:
    """Attach the package semver to an error or transaction event."""
    if _APP_VERSION:
        event.setdefault("tags", {})["app_version"] = _APP_VERSION
    return event


def _before_send(event: dict, hint: dict) -> dict:
    """Sentry init hook: error events."""
    return _stamp_app_version(event)


def _before_send_transaction(event: dict, hint: dict) -> dict:
    """Sentry init hook: transaction events (spec: every event carries
    release/environment/app_version — release and environment come from
    init options, the tag from here)."""
    return _stamp_app_version(event)


def _traces_sampler(rate: float):
    """Uniform sampling at ``rate``, health checks always excluded.

    ``rate == 0`` disables tracing entirely (errors-only mode): the
    sampler returns 0 for everything, so no transactions are created.
    """

    def sample(sampling_context: dict) -> float:
        if _HEALTH_PATH_RE.match(_transaction_path(sampling_context)):
            return 0.0
        return rate

    return sample


def _init_error_tracking() -> None:
    """Initialize the Sentry-protocol SDK when a DSN is configured.

    Explicit ``LoggingIntegration`` mirrors the defaults (INFO+ as
    breadcrumbs, ERROR+ as events) so intent is visible: existing
    structlog events — bridged through stdlib logging — become the
    breadcrumb trail without any log-format change.
    """
    dsn = config("SENTRY_DSN", default=None)
    if not dsn:
        return  # DSN-gated: fully inert without it (dev/test/CI).

    rate = config("SENTRY_TRACES_SAMPLE_RATE", cast=float, default=0.05)

    sentry_sdk.init(
        dsn=dsn,
        # Deploy-exact identity, uniform across environments:
        release=config("GIT_HASH", default=None),
        # SENTRY_ENVIRONMENT wins; default is the Django environment
        # (DJANGO_ENV is guaranteed set by settings/__init__.py).
        environment=config(
            "SENTRY_ENVIRONMENT",
            default=os.environ.get("DJANGO_ENV", "development"),
        ),
        # GDPR-safe: no user identities, IPs, cookies or request bodies.
        send_default_pii=False,
        integrations=[
            # Same thresholds as the defaults; explicit for visibility.
            LoggingIntegration(
                level=logging.INFO,  # breadcrumbs
                event_level=logging.ERROR,  # error events from logger.error+
            ),
            # Not auto-enabled; needed for the ASGI runtime
            # (ASGI_ENABLED=1 / uvicorn workers).
            AsyncioIntegration(),
        ],
        traces_sampler=_traces_sampler(rate),
        before_send=_before_send,
        before_send_transaction=_before_send_transaction,
    )


_init_error_tracking()
