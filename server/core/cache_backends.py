"""Custom cache backends.

``SampledCullDatabaseCache`` — a ``DatabaseCache`` whose cull check runs
only on a sampled fraction of writes. Django's ``DatabaseCache`` (up to and
including 6.1.x) executes ``SELECT COUNT(*) FROM <table>`` before **every**
write (``set``/``add``/``touch``) to decide whether ``MAX_ENTRIES`` was
exceeded. That is a full table scan: the cache tables store multi-KB base64
pickles, so the count alone costs 15–20 ms at staging scale — repeated for
every cache write a request performs (provider result caches, response
envelopes, version keys), which APM groups as an N+1 pattern (Sentry issue
155299999, transaction ``/v1/geo/images/hut/{hut_slug}``).

Upstream fixed exactly this in Django 6.2 (ticket #32785): the count/cull
check is gated behind ``OPTIONS["CULL_PROBABILITY"]`` (default 0.1 — the
check runs on 10% of writes; ``0`` disables culling entirely). This module
backports that gate verbatim onto the 6.1 implementation this project runs.

**Remove this module when the project upgrades to Django >= 6.2**: switch
the ``BACKEND`` of the affected aliases back to
``django.core.cache.backends.db.DatabaseCache`` and keep the identical
``OPTIONS`` (the upstream default probability is also 0.1, so no other
change is needed). This is **enforced, not just documented**: the
``core.E001`` system check (``server/core/checks.py``) fails startup —
and CI — on Django >= 6.2 while any alias still points at this module,
so the 6.2 dependency bump cannot ship without the removal.
"""

import base64
import pickle
import random
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.db import DatabaseCache
from django.db import DatabaseError, connections, models, router, transaction
from django.utils.timezone import now as tz_now


class SampledCullDatabaseCache(DatabaseCache):
    """``DatabaseCache`` that samples the per-write cull check.

    Behavior is identical to ``DatabaseCache`` except that the
    ``SELECT COUNT(*)`` cull check runs with probability
    ``OPTIONS["CULL_PROBABILITY"]`` (default 0.1) instead of on every
    write. Culling semantics (``MAX_ENTRIES``, ``CULL_FREQUENCY``) are
    unchanged; the table may transiently exceed ``MAX_ENTRIES`` by the
    writes that skip the check — the same trade-off upstream chose for
    Django 6.2 (ticket #32785).

    The ``_base_set`` override below is Django's own implementation
    (6.1.x body, 6.2 gate) kept verbatim apart from lint markers — diff it
    against ``django/core/cache/backends/db.py`` when bumping Django patch
    versions.
    """

    # Type-only declarations: django-stubs does not expose the parent's
    # private ``_table`` attribute and ``_cull`` method.
    _table: str
    _cull: Callable[[str, Any, datetime, int], None]

    def __init__(self, table: str, params: dict[str, Any]) -> None:
        super().__init__(table, params)
        options = params.get("OPTIONS", {})
        try:
            self._cull_probability = float(options.get("CULL_PROBABILITY", 0.1))
        except (TypeError, ValueError):
            self._cull_probability = 0.1

    def _base_set(
        self,
        mode: str,
        key: str,
        value: Any,
        timeout: float | None = DEFAULT_TIMEOUT,
    ) -> bool:
        timeout = self.get_backend_timeout(timeout)
        db = router.db_for_write(self.cache_model_class)
        connection = connections[db]
        quote_name = connection.ops.quote_name
        table = quote_name(self._table)

        with connection.cursor() as cursor:
            now = tz_now()
            now = now.replace(microsecond=0)
            if timeout is None:
                # Vendored: naive sentinel, adapted by
                # adapt_datetimefield_value below.
                exp = datetime.max  # type: ignore[reportCallIssue]  # noqa: DTZ901
            else:
                tz = UTC if settings.USE_TZ else None
                exp = datetime.fromtimestamp(timeout, tz=tz)
            exp = exp.replace(microsecond=0)
            if self._cull_probability and random.random() <= self._cull_probability:
                cursor.execute(  # pi-lens-ignore: python-sql-injection — vendored Django cache backend, identifiers pre-quoted via quote_name()
                    "SELECT COUNT(*) FROM %s" % table
                )
                num = cursor.fetchone()[0]
                if num > self._max_entries:
                    self._cull(db, cursor, now, num)
            pickled = pickle.dumps(value, self.pickle_protocol)
            # The DB column is expecting a string, so make sure the value is a
            # string, not bytes. Refs #19274.
            b64encoded = base64.b64encode(pickled).decode("latin1")
            try:
                # Note: typecasting for datetimes is needed by some 3rd party
                # database backends. All core backends work without
                # typecasting, so be careful about changes here - test suite
                # will NOT pick regressions.
                with transaction.atomic(using=db):
                    cursor.execute(  # pi-lens-ignore: python-sql-injection — vendored Django cache backend, identifiers pre-quoted via quote_name()
                        "SELECT %s, %s FROM %s WHERE %s = %%s"
                        % (
                            quote_name("cache_key"),
                            quote_name("expires"),
                            table,
                            quote_name("cache_key"),
                        ),
                        [key],
                    )
                    result = cursor.fetchone()

                    if result:
                        current_expires = result[1]
                        expression = models.Expression(
                            output_field=models.DateTimeField()
                        )
                        for converter in connection.ops.get_db_converters(
                            expression
                        ) + expression.get_db_converters(connection):
                            current_expires = converter(
                                current_expires, expression, connection
                            )

                    exp = connection.ops.adapt_datetimefield_value(exp)
                    if result and mode == "touch":
                        cursor.execute(  # pi-lens-ignore: python-sql-injection — vendored Django cache backend, identifiers pre-quoted via quote_name()
                            "UPDATE %s SET %s = %%s WHERE %s = %%s"
                            % (table, quote_name("expires"), quote_name("cache_key")),
                            [exp, key],
                        )
                    elif result and (
                        mode == "set"  # type: ignore[reportPossiblyUnbound]  # vendored: guarded by `result and`
                        or (mode == "add" and current_expires < now)  # type: ignore[reportPossiblyUnbound]  # vendored: guarded by `result and`
                    ):
                        cursor.execute(  # pi-lens-ignore: python-sql-injection — vendored Django cache backend, identifiers pre-quoted via quote_name()
                            "UPDATE %s SET %s = %%s, %s = %%s WHERE %s = %%s"
                            % (
                                table,
                                quote_name("value"),
                                quote_name("expires"),
                                quote_name("cache_key"),
                            ),
                            [b64encoded, exp, key],
                        )
                    elif mode != "touch":
                        cursor.execute(  # pi-lens-ignore: python-sql-injection — vendored Django cache backend, identifiers pre-quoted via quote_name()
                            "INSERT INTO %s (%s, %s, %s) VALUES (%%s, %%s, %%s)"
                            % (
                                table,
                                quote_name("cache_key"),
                                quote_name("value"),
                                quote_name("expires"),
                            ),
                            [key, b64encoded, exp],
                        )
                    else:
                        return False  # touch failed.
            except DatabaseError:
                # To be threadsafe, updates/inserts are allowed to fail
                # silently
                return False
            else:
                return True
