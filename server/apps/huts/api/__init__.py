"""Hut API: composes all hut endpoint modules.

Route order is load-bearing and explicit here (no import-order magic):
the availability geojson routes, then specific hut routes, and the
``{slug}`` catch-all LAST. The old ninja setup relied on import order
in this ``__init__``; the list below is the same order, visible.
"""

from server.apps.huts.api._hut import paths as hut_paths

__all__ = ["paths"]

paths = hut_paths
