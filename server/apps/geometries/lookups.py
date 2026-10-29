"""Custom database lookups for the geometries app.

``ilike`` renders ``<expr> ILIKE <pattern>`` directly. Django's
built-in ``icontains`` compiles to ``UPPER(expr) LIKE UPPER(pattern)``
— a different expression than the column, so the per-language
``gin_trgm_ops`` GIN indexes (which serve ``ILIKE`` case-insensitively
by themselves) cannot be used and the planner falls back to sequence
scans. Registered on ``CharField`` (subclasses inherit), imported from
``models/__init__`` so registration happens at app load.
"""

from typing import Any, override

from django.db.models import CharField, Lookup


class ILike(Lookup):
    """``field__ilike="%pattern%"`` → ``field ILIKE '%pattern%'``."""

    lookup_name = "ilike"

    @override
    def as_sql(self, compiler: Any, connection: Any) -> tuple[str, tuple[Any, ...]]:
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        params = (*lhs_params, *rhs_params)
        return f"{lhs} ILIKE {rhs}", params


CharField.register_lookup(ILike)
