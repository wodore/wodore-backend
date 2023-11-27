#!/usr/bin/env python
import asyncio
from pprint import pprint
from typing import List
from asyncify import asyncify
import click
import sys
import overpy
from functools import lru_cache
import os
from rich import print as rprint

if __name__ == "__main__":  # only for testing
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    sys.path.append(root_dir)
    from rich.traceback import install

    install(show_locals=False)

# from app.models.hut import Hut
from huts.schemas.hut_osm import HutOsm0Source


class OsmService:
    def __init__(self, request_url: str = "https://overpass.osm.ch/api/", log=False):
        self.request_url = request_url
        self._log = log
        self._cache = {}

    def _echo(self, *args, **kwargs):
        if self._log:
            click.secho(*args, **kwargs)

    @lru_cache(10)
    def _get_osm_hut_list_sync(self, limit: int = 1, lang: str = "de") -> List[HutOsm0Source]:
        api = overpy.Overpass(url=self.request_url)
        # fetch all ways and nodes
        # SWISS
        lon = [45.7553, 47.6203]
        lat = [5.7127, 10.5796]
        bounder = 100.0
        lon_diff = lon[1] - lon[0]
        lat_diff = lat[1] - lat[0]
        lon_range = lon_diff / bounder * limit
        lon_range = lon_diff if lon_range > lon_diff else lon_range
        lat_range = lat_diff / bounder * limit
        lat_range = lat_diff if lat_range > lat_diff else lat_range
        lon_start = lon[0] + (lon_diff - lon_range) / 2
        lat_start = lat[0] + (lat_diff - lat_range) / 2
        area = f"{lon_start},{lat_start},{lon_start+lon_range},{lat_start+lat_range}"
        self._echo("  .. get osm data from {self.request_url} with query:", dim=True)
        self._echo("     --------------------------", dim=True)
        query = f"""
                [out:json];
                (
                nw["tourism"="alpine_hut"]["name"]({area});
                nw["tourism"="wilderness_hut"]["name"]({area});
                );
                out qt center {limit};
            """
        self._echo(query, dim=True)
        self._echo("     --------------------------", dim=True, nl=False)
        try:
            result = api.query(query)
        except overpy.exception.OverpassGatewayTimeout as e:
            self._echo(" ... failed", fg="red")
            self._echo(e, dim=True)
            return []
        huts = []
        for key, res in {"node": result.nodes, "way": result.ways}.items():
            for h in res:
                osm_hut = HutOsm0Source.model_validate(h)
                osm_hut.osm_type = key
                huts.append(osm_hut)
                # huts.append(h)
        self._echo("  ... done", fg="green")
        return huts

    @lru_cache(10)
    async def get_osm_hut_list(self, limit: int = 5000, lang: str = "de") -> List[HutOsm0Source]:
        db_huts = await asyncify(self._get_osm_hut_list_sync)(limit=limit, lang=lang)
        return db_huts

    # @lru_cache(10)
    # async def get_hut_list(self, limit: int = 5000, lang: str = "de") -> List[Hut]:
    #    huts = []
    #    osm_huts = await self.get_osm_hut_list(limit=limit, lang=lang)
    #    huts = [h.get_hut() for h in osm_huts]
    #    return huts


async def main():
    limit = 10
    osm_service = OsmService(log=True)
    huts = await osm_service.get_osm_hut_list(limit)
    for h in huts:
        # rprint(h.rich(hide_none=True))
        rprint(h)
    # huts = await osm_service.get_hut_list(limit)
    # for h in huts:
    #    click.echo(f"{h.name} ({h.slug})")


if __name__ == "__main__":
    asyncio.run(main())
