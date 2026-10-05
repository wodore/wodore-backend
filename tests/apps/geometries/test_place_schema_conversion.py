"""Place-schema dispatch for mixed GeoPlace/Hut inputs.

The nearby-images controller historically merged huts into the
``geoplaces=`` argument of ``fetch_images_from_providers``; the schema
conversion then read ``geoplace.osm_tags`` unguarded and died with
``AttributeError: 'Hut' object has no attribute 'osm_tags'`` whenever a
hut was in the search results (the exception killed the whole provider
fetch). The dispatch must convert each type with its own converter, and
a type mix-up must degrade gracefully instead of raising.
"""

import asyncio

import pytest

from server.apps.geometries.models import GeoPlace
from server.apps.geometries.providers.schemas import (
    convert_places_to_schemas,
    geoplace_to_schema,
)
from server.apps.huts.models import Hut

pytestmark = [pytest.mark.django_db]


def _first(model):
    obj = model.objects.filter(is_active=True, is_public=True).first()
    assert obj is not None, f"seed data provides no public {model.__name__}"
    return obj


class TestMixedPlaceDispatch:
    def test_geoplaces_and_huts_both_convert(self, seed_data):
        geoplace = _first(GeoPlace)
        hut = _first(Hut)

        schemas = asyncio.run(
            convert_places_to_schemas(geoplaces=[geoplace], huts=[hut])
        )

        assert len(schemas) == 2
        assert {s.slug for s in schemas} == {geoplace.slug, hut.slug}
        for schema in schemas:
            assert schema.lat != 0.0 and schema.lon != 0.0

    def test_hut_mistyped_as_geoplace_degrades_gracefully(self, seed_data):
        # Regression ('Hut' object has no attribute 'osm_tags'): a hut
        # passed through the geoplace path must convert without raising —
        # it just gets no OSM source.
        hut = _first(Hut)

        schema = geoplace_to_schema(hut)

        assert schema.slug == hut.slug
        assert schema.lat == pytest.approx(hut.location.y)
        assert all(s.slug != "osm" for s in schema.sources)

    def test_geoplace_with_osm_tags_keeps_osm_source(self, seed_data):
        geoplace = _first(GeoPlace)
        geoplace.osm_tags = {"id": 424242, "name": "Testberg"}
        geoplace.save(update_fields=["osm_tags"])

        schema = geoplace_to_schema(geoplace)

        osm_sources = [s for s in schema.sources if s.slug == "osm"]
        assert len(osm_sources) == 1
        assert osm_sources[0].source_id == 424242
        assert osm_sources[0].source_data is not None
        assert osm_sources[0].source_data["tags"] == {"id": 424242, "name": "Testberg"}
