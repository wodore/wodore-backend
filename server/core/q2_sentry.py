"""django-q2 error reporter bridging task failures to the Sentry SDK.

django-q2's worker catches every task exception, stores the traceback as
a string result and (outside ``sync=True`` mode) neither re-raises nor
logs at ERROR — so neither the global excepthook nor the logging
integration sees anything. The cluster calls the configured error
reporter's ``report()`` *inside* the except block, which means
``sys.exc_info()`` still holds the live exception: capture it directly
instead of reconstructing events from stored traceback strings.

Registered via the ``djangoq.errorreporters`` entry point (see
``pyproject.toml``) and enabled in ``Q_CLUSTER["error_reporter"]``
(``server/settings/components/common.py``).

No-op when the SDK is not initialized (no ``SENTRY_DSN`` — dev/test/CI).
"""

import sentry_sdk


class SentryErrorReporter:
    """django-q2 error reporter capturing the in-flight task exception."""

    def __init__(self, **kwargs: object) -> None:
        """Accept (and ignore) any ``Q_CLUSTER["error_reporter"]`` config."""

    def report(self) -> None:
        """Capture the exception currently being handled by the q2 worker.

        Called from within the worker's ``except`` block, so
        ``capture_exception()`` (no args) picks up the live
        ``sys.exc_info()`` — same thread, full traceback.
        """
        if not sentry_sdk.get_client().is_active():
            return  # No DSN configured: fully inert.
        sentry_sdk.capture_exception()
