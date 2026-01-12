from ._router import router

# Import other endpoint modules
from ._booking import get_hut_bookings
# HutType endpoints removed - now use Category API instead
# from ._hut_type import get_hut_types

# Import availability endpoint BEFORE _hut to ensure route order
# (specific routes like 'availability.geojson' must come before catch-all '/{slug}')
from server.apps.availability.api import get_hut_availability_geojson

# Import hut endpoints last (contains /{slug} catch-all)
from ._hut import get_huts
