# HutType endpoints removed - now use Category API instead
# from ._hut_type import get_hut_types
# Import availability endpoint BEFORE _hut to ensure route order
# (specific routes like 'availability.geojson' must come before catch-all '/{slug}')
from server.apps.availability.api import get_hut_availability_geojson

# Import other endpoint modules
from ._booking import get_hut_bookings
from ._hut_meta import get_hut_meta

# Import hut endpoints last (contains /{slug} catch-all) — the Markdown
# and map variants MUST register BEFORE the catch-all, or '{slug}.md' /
# '{slug}/map.png' URLs are swallowed by /{slug}. Import order is
# load-bearing; keep isort out.
# isort: off
from ._hut_markdown import get_hut_markdown
from ._hut_map import get_hut_map
from ._hut import get_huts

# isort: on
from ._router import router
