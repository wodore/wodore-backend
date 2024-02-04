import sys
from deepl import Translator
from django.conf import settings

from hut_services.core.cache import file_cache
import typing as t
from server.settings.components import config

from hut_services import HutSchema

auth_key: str = config("DEEPL_KEY")  # type: ignore
# auth_key = settings.DEEPL_KEY
translator = Translator(auth_key)
# result = translator.translate_text("Hello, world!", target_lang="fr")
# print(result.text)  # "Bonjour, le monde !"

from .schema import LANGUAGE_CODES
import argostranslate.translate

LangType = t.Literal["de", "fr", "en", "it"]

# https://github.com/argosopentech/argos-translate
# language installation needed:
#   argospm update
#   argospm install translate-en_de
#   argospm install translate-de_en
#   argospm install translate-en_fr
#   argospm install translate-fr_en
#   argospm install translate-en_it
#   argospm install translate-it_en


@file_cache(expire_in_seconds=3600 * 24 * 365)
def _translate(text: str, source_lang: str, target_lang: str) -> str:
    return argostranslate.translate.translate(text, from_code=source_lang, to_code=target_lang)
    # return translator.translate_text(text, source_lang=source_lang, target_lang=target_lang).text


# TODO notes, which is a list
def translate_hut(
    hut: HutSchema, source_lang: LangType | None = None, fields: t.Sequence[str] = ["description"]
) -> HutSchema:
    for field in fields:
        field_value = getattr(hut, field)
        langs: list[LangType] = LANGUAGE_CODES
        if source_lang is None:
            for lang in langs:
                if getattr(field_value, lang):
                    source_lang = lang
                    break
        if source_lang is None:
            continue
        text = getattr(field_value, source_lang)
        translate_to = [l for l in langs if l != source_lang]
        for lang in translate_to:
            if not getattr(field_value, lang):
                # if lang == "en":
                #    target_lang = "EN-GB"
                # else:
                #    target_lang = lang.upper()
                target_lang = lang
                setattr(getattr(hut, field), lang, _translate(text, source_lang=source_lang, target_lang=target_lang))
    return hut
