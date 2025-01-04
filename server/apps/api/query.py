from enum import Enum
from typing import Any, Generic, Literal, Sequence, Type, TypeVar

# if TYPE_CHECKING:
from ninja import ModelSchema, Query, Schema
from ninja.errors import HttpError
from ninja.orm import create_schema
from pydantic import TypeAdapter
from pydantic.fields import FieldInfo

TSchema = TypeVar("S_co", bound=Schema)  # , covariant=True)

# this does not work
# FieldsParam = Annotated[Fields[S_co], Query()]
# tried https://docs.pydantic.dev/latest/concepts/types/#generics (did not work)


class FieldsParam(Schema, Generic[TSchema]):
    """Specify which fields to return when query models."""

    include: Any = Query(
        None,
        description="Comma separated list with field names, use `__all__` in order to include every field.",
        # example="__all__",
    )
    exclude: Any = Query(
        None,
        description="Comma separated list with field names, if set it uses all fields except the excluded ones.",
    )

    @property
    def _schema(self) -> Type[Schema] | None:
        try:
            return self.__pydantic_generic_metadata__["args"][0]
        except (IndexError, ValueError):
            return None

    @property
    def _db_model(self) -> Type[ModelSchema] | None:
        if self._schema is not None:
            return self._schema.Meta.model

    @property
    def available_field_names(self) -> list[str]:
        return list(self._available_fields.keys())

    @property
    def required_field_names(self) -> list[str]:
        return [
            name for name, info in self._available_fields.items() if info.is_required()
        ]

    @property
    def _available_fields(self) -> dict[str, FieldInfo]:
        if self._schema is not None:
            return self._schema.model_fields
        return {}

    def _check_fields(self, fields: list[str]):
        """Check if all fields names are allowed, otherwise send error."""
        fields_set = set(fields)
        available_set = set(self.available_field_names)
        missing_set = fields_set - available_set
        if missing_set:
            possible_names = f"Possible names: {', '.join(self.available_field_names)}."
            if len(missing_set) == 1:
                msg = f"'{list(missing_set)[0]}' is not a valid field name! {possible_names}"
            else:
                msg = f"'{', '.join(list(missing_set))}' are not valid field names! {possible_names}"
            raise HttpError(400, msg)

    def get_valid_fields(self, fields: list[str] | str | None) -> list[str]:
        if isinstance(fields, str):
            if fields == "__all__":
                fields_list = self.available_field_names
            else:
                fields_list = [f.strip() for f in fields.split(",") if f.strip()]
        elif fields is None:
            fields_list = []
        else:
            fields_list = fields
        self._check_fields(fields_list)
        return fields_list

    def get_include(self) -> list[str]:
        include = self.get_valid_fields(self.include)
        exclude = self.get_valid_fields(self.exclude)
        if not include and exclude:
            include = self.available_field_names
        else:
            include += self.required_field_names
        ## add i18n use to get translations
        if self._db_model and hasattr(self._db_model, "i18n"):
            i18n_fields = list(self._db_model.i18n.field.fields)
            include += [f"{i}_i18n" for i in include if i in i18n_fields]
        return list(set(include) - set(exclude))

    def get_schema(self) -> Type[Schema] | None:
        if self._db_model:
            return create_schema(self._db_model, fields=self.get_include())
        return None

    def type_adapter(self, _type: Any | None = None):
        """Returns a pydantic TypeAdapter object."""
        if _type is not None:
            objs = TypeAdapter(
                _type[self.get_schema()]
            )  # .validate_python(list(Organization.objects.all()))
        else:
            objs = TypeAdapter(
                self.get_schema()
            )  # .validate_python(list(Organization.objects.all()))
        return objs

    def validate(
        self,
        _obj: Any | None = None,
        validator: Literal["python", "json", "strings"] = "python",
    ) -> list[TSchema]:
        if isinstance(_obj, list):
            return getattr(self.type_adapter(list), f"validate_{validator}")(_obj)
        return getattr(self.type_adapter(), f"validate_{validator}")(_obj)

    def update_default(self, include: str | Sequence[str]) -> None:
        if not isinstance(include, str):
            include = list(include[:])
        if self.include is None and self.exclude is None:
            if isinstance(include, list):
                include = ",".join(include)
            self.include = include


class TristateEnum(str, Enum):
    """Tristate enum with `true`, `false` and `unset`."""

    true = "true"
    false = "false"
    unset = "unset"

    @property
    def bool(self) -> bool | None:
        """Returns either `None`, `True` or `False`."""
        if self.value == "unset":
            return None
        return self.value == "true"
