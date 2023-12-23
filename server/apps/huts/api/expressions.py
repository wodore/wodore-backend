"""
Creates GeoJSON for a FeatureCollection using specified geometric field,
and adds extra fields as properties on each feature. An all-database
alternative to serialization, e.g.: https://docs.djangoproject.com/en/3.1/ref/contrib/gis/serializers/
Usage:
from django.contrib.gis.db import models
class Geo(models.Model):
   name = models.CharField(max_length=32)
   code = models.CharField(max_length=32)
   geom = models.MultiPolygonField(srid=4326, geography=True)
   
...
from expressions import GeoJSON
>>> geojson = Geo.objects.filter(**kwargs).aggregate(GeoJSON(geom_field='geom', fields=['name', 'code']))['geojson']
{'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': {'type': 'MultiPolygon', 'coordinates': [ ... ]
"""

from django.contrib.gis.db.models import GeometryField
from django.contrib.gis.db.models.functions import AsGeoJSON, GeomOutputGeoFunc
from django.contrib.postgres.aggregates import JSONBAgg
from django.db.models import Func, JSONField
from django.db.models.expressions import F, Value
from django.db.models.functions import Cast

__all__ = ["AsGeoJSON", "JsonBuildObject", "Simplify", "GeoJSON"]


class JsonBuildObject(Func):
    # with gratitude to Schinckel
    # https://schinckel.net/2019/07/30/subquery-and-subclasses/
    function = "jsonb_build_object"
    output_field = JSONField()


class Simplify(GeomOutputGeoFunc):
    function = "ST_Simplify"


class GeoJSON(JsonBuildObject):
    contains_aggregate = True
    output_field = JSONField()

    def __init__(self, geom_field, fields=[], simplify=True, precision=0.0025, decimals=3):
        expressions = [Value("type"), Value("FeatureCollection"), Value("features")]

        geometry = F(geom_field)

        if simplify:
            # force geometry for simplify support
            # so it works nicely with geography fields
            geometry = Simplify(Cast(geometry, GeometryField()), precision)

        # I tried subclassing AsGeoJSON to force JSONField
        # but couldn't get it to work right because
        # CharField is somewhere in the inheritance.
        # We are building a JSON object, though.
        geojson = Cast(AsGeoJSON(geometry, precision=decimals), JSONField())

        properties = []

        for field in fields:
            properties.append(Value(field))
            properties.append(F(field))

        features = JsonBuildObject(
            *[
                Value("type"),
                Value("Feature"),
                Value("geometry"),
                geojson,
                Value("properties"),
                JsonBuildObject(*properties),
            ]
        )

        expressions.append(JSONBAgg(features))

        super(GeoJSON, self).__init__(*expressions)

    @property
    def default_alias(self):
        # convenience; just expect a 'geojson' key
        return "geojson"
