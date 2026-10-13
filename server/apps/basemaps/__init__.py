"""Basemaps app — backend-defined map layers (overlays and basemaps).

Single source of truth for what renders on the map: styles, parameters
(variables and widgets), category-driven filters/legends, attributions,
device-tier variants. Served via the map catalog and style endpoints
(see ``api.py``); WEP010 phase 1 (``MapproxyLayer`` & friends) extends
this app when it lands.
"""
