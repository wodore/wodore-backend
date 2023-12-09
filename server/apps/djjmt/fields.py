from copy import deepcopy
from typing import Annotated, Any
from django.conf import settings

# from django.db.models import JSONField
from django_jsonform.models.fields import JSONField

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _
from django.forms import CharField
from django.db.models import TextField
from ninja import Query
from pydantic import BaseModel, ConfigDict, Field

from .utils import get_normalised_language, normalise_language_code


LANGUAGE_CODES = [lang[0] for lang in settings.LANGUAGES]

# class TranslationSchema(BaseModel):
#    de: str = ""
#    en: str = ""
#    fr: str = ""
#    it: str = ""


from pydantic import BaseModel, create_model

lang_kwargs: Any = {lang[0]: (str | None, Field("", description=lang[1])) for lang in settings.LANGUAGES}
TranslationSchema = create_model("TranslationSchema", **lang_kwargs, __doc__="Translations")


class TranslationJSONField(JSONField):
    description = _("A JSON object with translations")

    def __init__(self, base_field, langs=None, **kwargs):
        self.base_field = base_field
        # _schema = deepcopy(TRANS_SCHEMA)
        self.langs = langs or settings.LANGUAGES
        kwargs["schema"] = deepcopy(self._schema)
        defaults = {"default": dict, "blank": True}
        defaults.update(kwargs)
        super().__init__(**defaults)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["base_field"] = self.base_field
        if self.langs is not None:
            kwargs["langs"] = self.langs
        return name, path, args, kwargs

    @property
    def non_db_attrs(self):
        return super().non_db_attrs + ("langs", "base_field")

    @property
    def _schema(self):
        keys = {}
        widget = "textarea" if isinstance(self.base_field, TextField) else "text"
        for lang in self.langs:
            keys[lang[0]] = {"type": "string", "title": lang[1], "widget": widget}
        schema = {"type": "dict", "keys": keys}
        return schema

    def contribute_to_class(self, cls, name, **kwargs):
        """
        Attach the custom translation descritor to the
        model attribute to control access to the field values.
        """
        super().contribute_to_class(cls, name, **kwargs)
        _obj = TranslationJSONFieldDescriptor(field=self)
        setattr(cls, name, _obj)

    def validate(self, value, model_instance):
        super().validate(value, model_instance)


class TranslationJSONFieldDescriptor:
    def __init__(self, field):
        self.field = field

    def __get__(self, instance, owner, raw=False, lang=None) -> str | dict:
        """
        Controls read access to a TranslationJSONField.

        :param raw: if True, will return the whole dict
        :param lang: custom lang
        :returns: value from the dict based on active language.
                  If the language key is missing, will return None.
        """
        if instance is None:
            return self

        field_name = self.field.attname
        data = instance.__dict__.get(field_name, {})
        if raw is True:
            return data
        if lang is None:
            lang = get_normalised_language()
        if lang is None:
            return data
        if lang not in data:  # get fallback
            lang = normalise_language_code(settings.LANGUAGE_CODE)
        val = data.get(lang, None)
        if val is None or val.lower() == "__none__":
            return ""
        elif not val:
            lang = normalise_language_code(settings.LANGUAGE_CODE)
            val = data.get(lang, None)
            if val.lower() != "__none__":
                return val
        return val

    def __set__(self, instance, value):
        """
        Controls write access to a TranslationJSONField.

        If the passed value is a dict, will treat it as the raw value of the field
        and store it as an attribute on the descriptor for later use.
        Otherwise will set the passed value on the dict based on the active language.
        """
        data = instance.__dict__
        field_name = self.field.attname
        if not field_name in data:
            data[field_name] = {}
        if isinstance(value, str):
            lang = get_normalised_language()
            if lang is None:
                lang = "de"  # TODO use fallback default
                # raise ImproperlyConfigured("Enable translations to use TranslationJSONField.")
            # if value is None or value.lower() == "__none__":
            #    if lang in data[field_name]:
            #        del data[field_name][lang]
            # else:
            data[field_name][lang] = value
        else:
            # json_value = value.copy()
            # for k, v in json_value.items():
            #    if v is None or v.lower() == "__none__":
            #        del value[k]
            data[field_name] = value

    # def __str__(self):
    # return self.get(lang="de")


class TranslationJSONRawFieldDescriptor:
    def __init__(self, field_name):
        self.field_name = field_name

    def __get__(self, instance, owner):
        """
        Return the raw value of the TranslationJSONField
        by accessing and calling the field descriptor explicitly
        and passing the `raw` param.
        """
        descriptor = getattr(type(instance), self.field_name)
        return descriptor.__get__(instance, self, raw=True)

    def __set__(self, instance, value):
        setattr(instance, self.field_name, value)


LanguageParam = Annotated[
    str | None,
    Query(
        None,
        description=f"Select language code: {', '.join(LANGUAGE_CODES)} or _empty_ for all.",
        # example=settings.LANGUAGE_CODE,
        pattern=f"({'|'.join(LANGUAGE_CODES)})",
    ),
]
