from ninja import ModelSchema

from .models import Symbol


class SymbolSchema(ModelSchema):
    """Schema for Symbol model - returns all fields."""

    class Meta:
        model = Symbol
        fields = Symbol.get_fields_all()
        fields_optional = Symbol.get_fields_all()


class SymbolOptional(ModelSchema):
    """Schema for Symbol model with all fields optional."""

    class Meta:
        model = Symbol
        fields = Symbol.get_fields_all()
        fields_optional = Symbol.get_fields_all()


# TODO: Add SymbolTagSchema if tags are implemented in the future
# class SymbolTagSchema(ModelSchema):
#     class Meta:
#         model = SymbolTag
#         fields = "__all__"
