from typing import Callable, Literal, Optional, Union

from pydantic import BaseModel, PrivateAttr, validator

# from sqlmodel import SQLModel
from rich import print as rprint

# TODO: move to config
LOCALES = Literal["de", "en", "fr", "it"]

# global variables to save locales
_current_locale: LOCALES = "de"
_fallback_locale: LOCALES = "de"

DEFAULT_LOCALE: LOCALES = "de"
DEFAULT_FALLBACK_LOCALE: LOCALES = "de"


def set_current_locale(lang: Optional[LOCALES]):
    global _current_locale
    _current_locale = DEFAULT_LOCALE if lang is None else lang


def get_current_locale() -> LOCALES:
    global _current_locale
    return _current_locale


def set_fallback_locale(lang: Optional[LOCALES]):
    global _fallback_locale
    _fallback_locale = DEFAULT_FALLBACK_LOCALE if lang is None else lang


def get_fallback_locale() -> LOCALES:
    global _fallback_locale
    return _fallback_locale


class Translations(BaseModel):
    de: Optional[str] = None
    en: Optional[str] = None
    fr: Optional[str] = None
    it: Optional[str] = None
    __locale: LOCALES = PrivateAttr()
    __fallback_locale: LOCALES = PrivateAttr()
    __fallback: bool = PrivateAttr()
    __ignore_errors: bool = PrivateAttr()
    __locale_factory: Optional[Callable] = PrivateAttr()
    __fallback_locale_factory: Optional[Callable] = PrivateAttr()

    def __init__(
        self,
        default_value: str = None,
        locale: Optional[LOCALES] = None,
        fallback_locale: Optional[LOCALES] = None,
        fallback: bool = True,
        ignore_errors: bool = True,
        locale_factory: Optional[Callable] = None,
        fallback_locale_factory: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.__locale = locale
        self.__fallback_locale = fallback_locale
        self.__fallback = fallback
        self.__ignore_errors = ignore_errors
        self.__locale_factory = locale_factory
        self.__fallback_locale_factory = fallback_locale_factory
        if default_value is not None:
            self.set(default_value)

    @property
    def _(self) -> str:
        """Get default translation"""
        return self.get()

    def get(
        self,
        locale: Optional[LOCALES] = None,
        default_locale: Optional[LOCALES] = None,
        fallback: Optional[bool] = None,
    ) -> str:
        lang = self.get_locale() if locale is None else locale
        default_lang = (
            self.get_fallback_locale() if default_locale is None else default_locale
        )
        fallback = self.__fallback if fallback is None else fallback and default_lang
        out = getattr(self, lang)
        if not out and fallback:
            out = getattr(self, default_lang, out)
        return out

    def set(
        self,
        value: Union[str, dict, "Translations"],
        locale: Optional[LOCALES] = None,
        ignore_errors: Optional[bool] = None,
    ):
        ignore_errors = self.__ignore_errors if ignore_errors is None else ignore_errors
        if isinstance(value, str):
            lang = self.get_locale() if locale is None else locale
            try:
                setattr(self, lang, value)
            except Exception:
                print(ignore_errors)
                if not ignore_errors:
                    raise ValueError(f"Cannot set '{lang}: {value}'")
            return value
        if isinstance(value, Translations):
            value = value.dict()
        if isinstance(value, dict):
            for lang, value in value.items():
                self.set(value, locale=lang, ignore_errors=ignore_errors)
            return value
        if not ignore_errors:
            err_msg = f"Cannot set '{lang}: {value}' ({type(value)})"
            raise ValueError(err_msg)
        return value

    def set_locale(self, locale: LOCALES):
        self.__locale = locale

    def set_fallback_locale(self, locale: LOCALES):
        self.__fallback_locale = locale

    def set_fallback(self, fallback: bool):
        self.__fallback = fallback

    def get_fallback(self) -> bool:
        return self.__fallback

    def get_locale(self) -> LOCALES:
        if self.__locale is not None:
            return self.__locale
        if self.__locale_factory is not None:
            return self.__locale_factory()
        lang = get_current_locale()
        if lang:
            return lang
        return self.get_fallback_locale()

    def get_fallback_locale(self) -> LOCALES:
        if self.__fallback_locale is not None:
            return self.__fallback_locale
        if self.__fallback_locale_factory is not None:
            return self.__fallback_locale_factory()
        return get_fallback_locale()

    @classmethod
    def get_validator(cls, field: str) -> "Translations":
        return validator(field, allow_reuse=True, pre=True)(cls.validator)

    @classmethod
    def validator(cls, value: Union[str, dict, "Translations"]) -> "Translations":
        _t = None
        if isinstance(value, str):
            out = {get_current_locale(): value}
            _t = Translations(**out)
        elif isinstance(value, dict):
            _t = Translations(**value)
        if value is None:
            out = {get_current_locale(): value}
            _t = Translations()
        if _t:
            return _t
        assert isinstance(value, Translations)
        return value

    class TransField(BaseModel):
        field: str
        locale: Optional[LOCALES] = None
        default_locale: Optional[LOCALES] = None
        fallback: Optional[bool] = None
        ignore_errors: Optional[bool] = None
        translated_field: bool = True

        # @classmethod
        # def get_validator(cls, field:str, ref_field:str) -> "Translations":
        #    return validator(field, allow_reuse=True, pre=True)(cls.validator)

        # @classmethod
        # def _vali(cls, ref_field:str):
        #    def validator(cls, value:Union[str,dict,cls]) -> cls:
        #        if isinstance(value, str):
        #            return cls(field=value)
        #        #if value is None:
        #            #return cls()
        #        assert isinstance(value, cls)
        #        return value

    # @classmethod
    # def __modify_schema__(cls, field_schema):
    #    field_schema.update(
    #        title=cls.__name__,
    #        description="Latitude (y) in WGS84"
    #    )


class TranslationModel(BaseModel):
    """Example:
    name_t : Translatable = Translatable(locale="en")
    _name_t = Translatable.get_validator('name_t')
    name:str = Translation(field="name_t") #, default_locale="fr", locale="en")
    """

    def __setattr__(self, key, val):
        orig = None
        try:
            orig = super().__getattribute__(key)
        except AttributeError:
            # super().__setattr__(key, val)
            orig = None
        if orig and getattr(orig, "translated_field", None):
            getattr(self, orig.field).set(
                val, locale=orig.locale, ignore_errors=orig.ignore_errors
            )
        else:
            super().__setattr__(key, val)

    def __getattr__(self, key):
        # try:
        if hasattr(super(), "__getattr__"):
            return super().__getattr__(key)
        if key[0] == "_":
            return super().__getattr__(key)
        return None
        # except:
        # raise

    def __getattribute__(self, key):
        orig = None
        try:
            orig = super().__getattribute__(key)
        except AttributeError:
            # return
            # super().__getattribute__(key)
            try:
                orig = super().__getattr__(key)
            except:
                raise
            # orig = Undefined
        if getattr(orig, "translated_field", None):
            return getattr(self, orig.field).get(
                locale=orig.locale,
                default_locale=orig.default_locale,
                fallback=orig.fallback,
            )
        return orig

    # class Config:
    #    validate_assignment = True
    #    json_encoders = {
    #        'Translations.Field': lambda a: f'JSON',
    #    }


if __name__ == "__main__":
    from rich import print as rprint

    class Demo(TranslationModel):
        name_t: Translations = Translations(locale="en")
        _name_t = Translations.get_validator("name_t")
        name: str = Translations.TransField(field="name_t")

        bio_t: Translations = Translations(locale="fr")
        _bio_t = Translations.get_validator("bio_t")
        bio = Translations.TransField(field="bio_t")

        number: int = 10

    demo = Demo(name_t="Tobias", bio_t="test")
    rprint(demo)
    rprint(f"name: {demo.name}")
    rprint(f"bio: {demo.bio}")
    demo.name = "English"
    demo.bio = "French"
    rprint(f"name: {demo.name}")
    rprint(f"bio: {demo.bio}")
    demo.bio_t.set_locale("it")
    rprint(f"name: {demo.name}")
    rprint(f"bio: {demo.bio}")
    demo.bio = "Italy"
    rprint(f"bio: {demo.bio}")
