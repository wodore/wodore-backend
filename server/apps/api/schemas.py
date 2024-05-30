# from typing import Literal

from ninja import Schema


class ResponseSchema(Schema):
    # status: Literal["success"]
    message: str
    id: int
