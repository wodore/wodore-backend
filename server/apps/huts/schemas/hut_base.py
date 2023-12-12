#!/usr/bin/env ipython -i
# import datetime
# import json
# from typing import Optional
# from fastapi.encoders import jsonable_encoder
# import sqlalchemy as sa
# from sqlalchemy.dialects.postgresql import JSONB
import importlib
from abc import abstractmethod

# from ..hut import Hut
from benedict import benedict
from pydantic import BaseModel, Field
from rich.panel import Panel
from rich.text import Text

from .point import Point


def _str_to_class(module_name, class_name):
    """Return a class instance from a string reference"""
    try:
        module_ = importlib.import_module(module_name)
        try:
            class_ = getattr(module_, class_name)
        except AttributeError:
            raise UserWarning(f"Class {class_name} does not exist")
    except ImportError:
        raise UserWarning(f"Module {module_name} does not exist")
    return class_


class HutBaseSource(BaseModel):
    # TODO: does not work, needs to be added on parent
    source_class: str = Field(default_factory=lambda: __class__.__name__)
    convert_class: str = Field(default_factory=lambda: __class__.__name__.replace("Source", "Convert"))

    @abstractmethod
    def get_id(self) -> str:
        return str(self.id)

    @abstractmethod
    def get_name(self) -> str:
        return self.name

    @abstractmethod
    def get_point(self) -> Point:
        return Point(lat=0, lon=0)

    # @abstractmethod
    # def get_hut(self, include_refs: bool = True) -> Hut:
    #    # _convert = HutSourceConvert(**self.dict())
    #    _convert = self
    #    hut = Hut.from_orm(_convert)
    #    if include_refs:
    #        hut.refs = []
    #    return hut

    @classmethod
    def get_fields(cls, alias=False):
        return list(cls.schema(alias).get("properties").keys())

    @classmethod
    def get_printable_fields(cls, alias=False):
        return list(cls.schema(alias).get("properties").keys())

    def rich(self, fields="printable", hide_none: bool = False):
        obj = benedict(self.dict())
        if fields == "printable":
            fields = self.get_printable_fields()
        elif fields == "all":
            fields = self.get_fields()
        elif not isinstance(fields, (list, tuple)):
            raise UserWarning("'fields' neet to be either 'printable', 'all', or a list with fileds")
        content = [Text("")]
        for field in fields:
            # value = getattr(self,field)
            value = obj.get(field)
            if not value and hide_none:
                continue
            value = str(value) if value else ("x", "magenta")
            _text = Text.assemble(f"{field}", (f" {'.'*(25-len(field))} ", "green"), value, overflow="crop")
            content.append(_text)
        content = Text("\n").join(content)
        output = Panel(
            content, title_align="left", title=f"[green]{self.get_id()}[/green] ──── [bold]{self.get_name()}[/bold]"
        )
        return output

    class Config:
        # orm_mode = True
        # validate_assignment = True
        populate_by_name = True
        from_attributes = True
        # underscore_attrs_are_private = True
