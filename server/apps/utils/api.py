from ninja import Field, Query
from typing import List

from ninja.errors import HttpError
from ninja.orm import create_schema

from ninja import Schema


def fields_query(Model): #fields:List, exclude_default=[]):

    fields = Model.get_fields_all()[:]
    exclude_default = Model.get_fields_exclude()[:]


    """Returns a query which can be used to include and exclude fields"""
    class Fields(Schema):
        include: str|None = Query(None,description=f"Comma separated list, allowed value: {', '.join(fields)}")
        exclude: str|None = Query(",".join(exclude_default),description="Comma separated list, only used if 'include' is not set.")
        allowed_fields: List =  Field(fields, include_in_schema=False)
        _model = Model

        def set_allowed_fields(self, fields:List):
            self.allowed_fields = fields

        def validate_fields(self, fields: List | None):
            if fields is not None and self.allowed_fields:
                for field in fields:
                    if field not in self.allowed_fields:
                        raise HttpError(400, f"'{field}' is not a valid field name! Possible names: {self.allowed_fields}")

        def get_include(self) -> List[str]:
            if self.include is not None:
                _include = [f.strip() for f in self.include.split(",") if f.strip()]
                self.validate_fields(_include)
            else:
                _include = self._model.get_fields_all()
                if self.exclude is None:
                    self.exclude = ",".join(self._model.get_fields_exclude())
                if self.exclude:
                    _exclude = [f.strip() for f in self.exclude.split(",") if f.strip()]
                    _include = list(set(_include) - set(_exclude))
            return _include

        def get_schema(self):
            return create_schema(self._model, fields=self.get_include())

    return Fields