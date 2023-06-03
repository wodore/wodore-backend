from copy import deepcopy
from django.conf import settings
#from django.db.models import JSONField
from django_jsonform.models.fields import JSONField

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _
from django.forms import CharField
from django.db.models import TextField

from .utils import get_normalised_language, normalise_language_code

TRANS_SCHEMA = {
    'type': 'dict', # a list which will contain the items
    'keys': { # or 'properties'
        'de': { 'type': 'string', 'title': "DE" },
        'en': { 'type': 'string', 'title': "EN" },
        'it': { 'type': 'string', 'title': "IT" },
        'fr': { 'type': 'string', 'title': "FR" },
    }
}

class TranslationJSONField(JSONField):
    description = _('A JSON object with translations')

    def __init__(self, base_field, langs=None, **kwargs):
        _schema = deepcopy(TRANS_SCHEMA)
        if isinstance(base_field, TextField):
            for key in _schema["keys"]:
                _schema["keys"][key]["widget"]  = "textarea"
        kwargs["schema"] = _schema
        defaults = {"default": dict, "blank" : True}
        defaults.update(kwargs)
        super().__init__(**defaults)
        self.base_field = base_field
        self.langs = langs or []

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['base_field'] = self.base_field
        if self.langs is not None:
            kwargs['langs'] = self.langs
        return name, path, args, kwargs

    @property
    def non_db_attrs(self):
        return super().non_db_attrs + ("langs", "base_field")

    def contribute_to_class(self, cls, name, **kwargs):
        """
        Attach the custom translation descritor to the
        model attribute to control access to the field values.
        """
        super().contribute_to_class(cls, name, **kwargs)
        #_raw = TranslationJSONRawFieldDescriptor(name)
        #setattr(cls, f'{name}__raw', _raw)
        ##cls._meta.add_field(_raw, private=False)
        _obj = TranslationJSONFieldDescriptor(field=self)
        setattr(cls, name, _obj)

    def validate(self, value, model_instance):
        super().validate(value, model_instance)
        # TODO: check if the keys are valid language codes

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
        data = instance.__dict__
        json_value = data.get(field_name, {})
        if raw is True:
            return json_value

        if lang is None:
            lang = get_normalised_language()
        if lang is None:
            return json_value
            #raise ImproperlyConfigured('Enable translations to use TranslationJSONField.')

        if lang not in json_value:
            lang = normalise_language_code(settings.LANGUAGE_CODE)

        return json_value.get(lang, None)

    def __set__(self, instance, value):
        """
        Controls write access to a TranslationJSONField.

        If the passed value is a dict, will treat it as the raw value of the field
        and store it as an attribute on the descriptor for later use.
        Otherwise will set the passed value on the dict based on the active language.
        """
        data = instance.__dict__
        field_name = self.field.attname
        if field_name in data:
            json_value = data[field_name]
        else:
            json_value = {}
        if isinstance(value, str):
            lang = get_normalised_language()
            if lang is None:
                #lang = 'de' # TODO use fallback default
                raise ImproperlyConfigured('Enable translations to use TranslationJSONField.')
            json_value[lang] = value
        else:
            json_value = value
        data[field_name] = json_value

    #def __str__(self):
        #return self.get(lang="de")


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
