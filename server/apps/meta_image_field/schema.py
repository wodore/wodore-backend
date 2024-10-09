from pydantic import BaseModel


class MetaImageAreaSchema(BaseModel):
    x1: float = 0
    x2: float = 1
    y1: float = 0
    y2: float = 1


class MetaImageSchema(BaseModel):
    crop: MetaImageAreaSchema | None = None
    focal: MetaImageAreaSchema | None = None
    width: int
    height: int


"""
Example:
{
  "crop": {
    "x1": 0,
    "x2": 1,
    "y1": 0,
    "y2": 1
  },
  "focal": {
    "x1": 0.2,
    "x2": 0.81,
    "y1": 0.08,
    "y2": 0.76
  },
  "width": 3072,
  "height": 2304
}
"""
