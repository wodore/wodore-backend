from typing import Tuple

from geojson_pydantic import Point as geoPoint
from pydantic import BaseModel, condecimal

from django.contrib.gis.geos import Point as dbPoint

from ..GPSConverter import GPSConverter

# from sqlmodel import Field, SQLModel

# from sqlalchemy import func
# from sqlalchemy.types import UserDefinedType, Float


class Longitude(float):
    """Longitude (x) in WGS84"""

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v, **kwargs):
        try:
            v = float(v)
        except ValueError:
            raise TypeError("float required")
        if v < -180 or v > 180:
            raise ValueError("Longitude not in range [-180,180]")
        # return cls(v)
        return v

    def __repr__(self):
        return f"Longitude({super().__repr__()})"

    @classmethod
    def __get_pydantic_json_schema__(cls, field_schema):
        field_schema.update(type="number", example=7.6496971, title=cls.__name__, description="Longitude (x) in WGS84")


# class Latitude(float):
#    """Latitude (y) in WGS84"""
#
#    # @classmethod
#    # def __get_validators__(cls):
#    #    yield cls.validate
#
#    # @classmethod
#    # def validate(cls, v, **kwargs):
#    #    try:
#    #        v = float(v)
#    #    except ValueError:
#    #        raise TypeError("float required")
#    #    if v < -90 or v > 90:
#    #        raise ValueError("Latitude not in range [-180,180]")
#    #    # return cls(v)
#    #    return v
#
#    def __repr__(self):
#        return f"Latitude({super().__repr__()})"
#
#    @classmethod
#    def __get_pydantic_json_schema__(cls, field_schema):
#        field_schema.update(type="number", example=45.9765729, title=cls.__name__, description="Latitude (y) in WGS84")


_EleDecimal = condecimal(max_digits=5, decimal_places=1)


# class Elevation(_EleDecimal):
#    """Elevation in meter above sealevel"""
#
#    # @classmethod
#    # def __get_validators__(cls):
#    #    yield cls.validate
#
#    @model_validator(mode="before")
#    @classmethod
#    def validate(cls, v, **kwargs):
#        if isinstance(v, str):
#            v = v.replace("m", "")
#        try:
#            v = float(v)
#        except ValueError:
#            raise TypeError("float required")
#        if v < -1000 or v > 10000:
#            raise ValueError("Elevation not in range [-1000,1000]")
#        # return cls(v)
#        # return _EleDecimal(v)
#        return float(v)
#
#    def __repr__(self):
#        return f"Elevation({super().__repr__()})"
#
#    @classmethod
#    def __get_pydantic_json_schema__(cls, field_schema):
#        field_schema.update(
#            type="number", example=4478.1, title=cls.__name__, description="Elevation in meter above sealevel"
#        )
#


class Point(BaseModel):
    """Point with longitude, latitude and optional elevation in WSG84"""

    lat: float
    lon: float
    # lat: Latitude
    # lon: Longitude

    @classmethod
    def from_swiss(cls, lat: float, lon: float):
        """
        Takes LV03 or LV95 (newest) coordiates.
        More information:
            https://en.wikipedia.org/wiki/Swiss_coordinate_system
        """
        if lat > 2000000:
            lat -= 2000000
        if lon > 1000000:
            lon -= 1000000
        converter = GPSConverter()
        lat, lon, H = converter.LV03toWGS84(lat, lon, 0)
        return cls(lat=lat, lon=lon)

    @property
    # def lon_lat(self) -> Tuple[Longitude, Latitude]:
    def lon_lat(self) -> Tuple[float, float]:
        return [self.lon, self.lat]

    @property
    def geojson(self) -> geoPoint:
        return geoPoint(coordinates=self.lon_lat, type="Point")

    @property
    def db(self) -> dbPoint:
        return dbPoint(self.lon, self.lat)

    # @property
    # def sql_point(self) -> func.ST_Distance_Sphere:
    #    return func.ST_GeomFromText(f"POINT ({self.lon} {self.lat})")

    # def get_within(self, from_column, inside_radius_m: float):
    #    """Radius in meter"""
    #    return func.ST_Distance_Sphere(from_column, self.sql_point) < inside_radius_m


# class saPoint(UserDefinedType):
#    cache_ok = True
#
#    def get_col_spec(self):
#        return "GEOMETRY"
#
#    #def bind_expression(self, bindvalue):
#    #    return func.ST_GeomFromText(bindvalue, type_=self)
#
#    def column_expression(self, col):
#        return func.ST_AsText(col, type_=self)
#
#    def bind_processor(self, dialect):
#        def process(value):
#            if value is None:
#                return None
#            if isinstance(value, Point):
#                lat = value.lat
#                lng = value.lon
#            else:
#                if isinstance(value, (tuple, list)):
#                    lat, lng = value
#                elif isinstance(value, dict):
#                    lat = value.get("lat")
#                    lng = value.get("lon")
#                else:
#                    UserWarning(f"No coordinates (lat, lon) found, value: '{value}', type '{type(value)}'")
#            return "POINT(%s %s)" % (lng, lat)
#
#        return process
#
#    def result_processor(self, dialect, coltype):
#        def process(value):
#            if value is None:
#                return None
#            # m = re.match(r'^POINT\((\S+) (\S+)\)$', value)
#            # lng, lat = m.groups()
#            lng, lat = value[6:-1].split()  # 'POINT(135.00 35.00)' => ('135.00', '35.00')
#            # return (float(lat), float(lng))
#            return Point(lat=float(lat), lon=float(lng))
#
#        return process
