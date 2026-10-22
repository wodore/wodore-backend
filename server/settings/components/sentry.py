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


# --- Python 3.14 shield-cancellation noise --------------------------------
#
# CPython 3.14 rewrote ``asyncio.shield``: when the awaiting side is
# cancelled while the shielded inner future is still pending, a later
# exception on that inner future is reported through the event loop's
# exception handler ("… exception in shielded future") instead of being
# silently swallowed. asgiref's sync↔async bridge shields its
# ``run_in_executor`` dispatches and converts task cancellation into
# ``set_exception(CancelledError())`` on the bridged future — so under
# ASGI every client disconnect mid-request (uvicorn cancels the request
# task on ``http.disconnect``) now emits an asyncio ERROR log, which the
# LoggingIntegration ships as an error event. One per aborted request,
# e.g. a browser cancelling an admin page load (issue 154471293):
# benign — the client is gone, there is nothing to fix server-side.
# The exception-type check keeps real shielded exceptions flowing.


def _is_shielded_cancel_noise(event: dict) -> bool:
    """True for asyncio's "CancelledError exception in shielded future"
    log events — client-abort noise from the py3.14 shield rework, not
    an application error."""
    if event.get("logger") != "asyncio":
        return False
    message = (event.get("logentry") or {}).get("message") or ""
    if "exception in shielded future" not in message:
        return False
    values = (event.get("exception") or {}).get("values") or []
    return bool(values) and values[-1].get("type") == "CancelledError"


# --- Django 6.1 post-disconnect request_finished noise ----------------------
#
# Django 6.1 revamped ASGI disconnect handling: ASGIHandler.handle()
# races listen_for_disconnect() against response processing inside a
# TaskGroup. On a mid-request client abort (uvicorn surfaces
# http.disconnect; browsers drop in-flight admin-autocomplete XHRs as
# the user keeps typing) the response task is cancelled — and Django
# then still fires request_finished (by design since #35059) so the
# cleanup receivers (close_old_connections, close_caches,
# reset_urlconf) run. That dispatch adapts the sync receivers with a
# thread-sensitive sync_to_async whose CurrentThreadExecutor has
# already been marked broken by the cancellation cascade
# (run_until_future's done-callback breaks the executor on ANY
# completion, cancellation included), so asgiref raises "already quit
# or is broken" (the asgiref#491/#526 failure family). It escapes the
# ASGI app unhandled (issue 155259431) but is benign — the client is
# gone. Verified unfixed upstream: Django 6.1.2, asgiref 3.12.1 and
# django/main (as of 2026-10) all still contain this exact path.
#
# The frame checks keep real misuse visible: the same RuntimeError from
# application code (e.g. sync_to_async in a fire-and-forget task that
# outlives its request context — asgiref#526's original report) carries
# no dispatcher.asend + ASGIHandler frames and still reports.


def _in_frame(frame: dict, function: str, module: str, path: str) -> bool:
    """True when a Sentry stacktrace frame is the given function of the
    given module (module preferred; filename suffix as fallback — the
    SDK's frame shape varies between capture paths)."""
    if frame.get("function") != function:
        return False
    return frame.get("module") == module or str(frame.get("filename") or "").endswith(
        path
    )


def _is_current_thread_executor_noise(event: dict) -> bool:
    """True for the RuntimeError asgiref raises when Django's
    post-disconnect request_finished dispatch hits the request's
    already-broken CurrentThreadExecutor — client-abort teardown noise,
    not an application error."""
    for value in (event.get("exception") or {}).get("values") or []:
        if value.get("type") != "RuntimeError":
            continue
        if "CurrentThreadExecutor already quit or is broken" not in str(
            value.get("value") or ""
        ):
            continue
        frames = (value.get("stacktrace") or {}).get("frames") or []
        signal_dispatch = any(
            _in_frame(
                frame,
                function="asend",
                module="django.dispatch.dispatcher",
                path="django/dispatch/dispatcher.py",
            )
            for frame in frames
        )
        asgi_handler = any(
            _in_frame(
                frame,
                function=function,
                module="django.core.handlers.asgi",
                path="django/core/handlers/asgi.py",
            )
            for frame in frames
            for function in ("handle", "__call__")
        )
        if signal_dispatch and asgi_handler:
            return True
    return False


def _before_send(event: dict, hint: dict) -> dict | None:
    """Sentry init hook: error events."""
    if _is_shielded_cancel_noise(event):
        return None  # client aborted the request; not actionable
    if _is_current_thread_executor_noise(event):
        return None  # ditto: post-disconnect request_finished teardown
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
