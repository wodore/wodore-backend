#!/usr/bin/env python
import asyncio
import os
import sys
import json
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import List, Literal, Sequence

import click
from geojson_pydantic import FeatureCollection
import requests
import xmltodict
from asyncify import asyncify
from easydict import EasyDict
from rich import print as rprint

from server.apps.huts.schemas.hut import HutSchema
from server.apps.huts.schemas.hut_refuges_info import RefugesInfoFeatureCollection, HutRefugesInfo0Source

# from server.apps.huts.schemas.point import Point

if __name__ == "__main__":  # only for testing
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    sys.path.append(root_dir)
    from icecream import ic
    from rich.traceback import install

    install(show_locals=False)

# from app.models.hut import Hut
# from server.apps.huts.schemas.hut_osm import HutOsm0Source

REFUGES_HUT_TYPES = {7: "cabane-non-gardee", 10: "refuge-garde", 9: "gite-d-etape", 28: "batiment-en-montagne"}


# @lru_cache(10)
def refuges_info_request(
    url: str,
    limit: str | int = "all",
    type_points: Sequence[int] = [7, 10, 9, 28],
    massif: Sequence[int] = [12, 339, 407, 45, 342, 20, 29, 343, 412, 8, 344, 408, 432, 406, 52, 9],
    text_format: Literal["texte", "markdown"] = "markdown",
    format: Literal["geojson", "xml", "csv"] = "geojson",
    detail: bool = True,
    **params,
) -> RefugesInfoFeatureCollection | EasyDict | bytes:
    params["nb_points"] = limit
    params["type_points"] = ",".join([str(t) for t in type_points])
    params["massif"] = ",".join([str(m) for m in massif])
    params["format"] = format
    params["format_texte"] = text_format
    params["detail"] = "complet" if detail else "simple"
    r = requests.get(url, params=params)
    if format == "geojson":
        data = json.loads(r.content)
        return RefugesInfoFeatureCollection(**data)
    if format == "xml":
        return EasyDict(xmltodict.parse(r.content))
    return r.content


# https://www.refuges.info/api/massif?nb_points=all&format=xml&type_points=7,10,9,28&massif=12,339,407,45,342,20,29,343,412,8,344,408,432,406,52,9
class RefugesInfoService:
    def __init__(self, request_url: str = "https://www.refuges.info/api/massif", log=False):
        self.request_url = request_url
        self._log = log
        self._cache = {}

    def _echo(self, *args, **kwargs):
        if self._log:
            click.secho(*args, **kwargs)

    def get_hut_list(
        self,
        limit: str | int = "all",
        type_points: Sequence[int] = [7, 10, 9, 28],
        massif: Sequence[int] = [12, 339, 407, 45, 342, 20, 29, 343, 412, 8, 344, 408, 432, 406, 52, 9],
        **params,
    ) -> List[HutRefugesInfo0Source]:
        self._echo(f"  .. get refuges.info data from {self.request_url}", dim=True)
        fc: RefugesInfoFeatureCollection = refuges_info_request(
            url=self.request_url, limit=limit, type_points=type_points, massif=massif, detail=True, **params
        )  # type: ignore  # noqa: PGH003
        huts = []
        for feature in fc.features:
            refuges_hut = HutRefugesInfo0Source(feature=feature, id=feature.properties.id)
            huts.append(refuges_hut)
        self._echo("  ... done", fg="green")
        return huts

    # async def get_hut_list(self, limit: int = 5000, lang: str = "de"):  # -> List[HutOsm0Source]:
    #    db_huts = await asyncify(self.get_hut_list_sync)(limit=limit, lang=lang)
    #    return db_huts

    # @lru_cache(10)
    # async def get_hut_list(self, limit: int = 5000, lang: str = "de") -> List[Hut]:
    #    huts = []
    #    osm_huts = await self.get_osm_hut_list(limit=limit, lang=lang)
    #    huts = [h.get_hut() for h in osm_huts]
    #    return huts


async def main():
    # limit = 10
    refuges_service = RefugesInfoService(log=True)
    huts = refuges_service.get_hut_list(limit=20)  # , massif=(12,))
    for h in huts:
        # rprint(h.rich(hide_none=True))
        rprint(h)

    # huts = await refuges_service.get_osm_hut_list(limit)
    # for h in huts:
    #    # rprint(h.rich(hide_none=True))
    #    rprint(h)
    ## huts = await osm_service.get_hut_list(limit)
    ## for h in huts:
    ##    click.echo(f"{h.name} ({h.slug})")


if __name__ == "__main__":
    asyncio.run(main())
