"""Convert amenity phones JSON into typed tel: links (external-link-uris).

Every ``AmenityDetail.phones`` entry becomes a normalized E.164
``uri.phone`` ``ExternalLink`` (``phonenumbers`` normalization, region
chained from the place's ``country_code`` → ``CH``) plus a
``GeoPlaceExternalLink`` association to the amenity's place — also
populating the previously-empty place-links table. Idempotent (keyed on
normalized URL + place); unparseable numbers are printed for review,
never silently dropped. The ``phones`` column itself is retained one
release for rollback (cleanup deferred — task 5.3).

Historical models only — no app-code imports (the parties.0002
precedent): identifier generation and phone normalization are
reimplemented inline (``phonenumbers`` is a library import, not app
code).

Reverse is a no-op: the JSON source is retained, links are
re-derivable.
"""

from typing import Any

import phonenumbers

from django.db import migrations
from django.db.models import Q

_DEFAULT_REGION = "CH"

import secrets
import string

_IDENTIFIER_CHARSET = string.ascii_lowercase + string.digits


def _unique_identifier(ExternalLink: Any) -> str:
    """Mirror ExternalLink.generate_unique_identifier (6 chars, retry)."""
    length = 6
    while True:
        candidate = "".join(secrets.choice(_IDENTIFIER_CHARSET) for _ in range(length))
        if not ExternalLink.objects.filter(identifier=candidate).exists():
            return candidate
        length += 1


def _normalize_e164(number: str, region: str | None) -> str | None:
    """Inline copy of external_links.phone.normalize_phone_e164."""
    cleaned = (number or "").strip()
    if not cleaned or ";" in cleaned:
        return None
    try:
        parsed = phonenumbers.parse(cleaned, region or _DEFAULT_REGION)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def convert_phones(apps: Any, schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    ExternalLink = apps.get_model("external_links", "ExternalLink")
    GeoPlaceExternalLink = apps.get_model("geometries", "GeoPlaceExternalLink")
    AmenityDetail = apps.get_model("geometries", "AmenityDetail")

    phone_kind = Category.objects.get(parent__slug="uri", slug="phone")

    # Meta.ordering references name_i18n which historical models lack.
    details = AmenityDetail.objects.filter(
        ~Q(phones=[]) & ~Q(phones__isnull=True)
    ).order_by()
    unparseable: list[str] = []
    created_links = 0
    created_associations = 0

    for detail in details.iterator(chunk_size=500):
        # CountryField values on historical models are Country objects,
        # not plain strings — extract the ISO code for phonenumbers.
        cc = detail.geo_place.country_code
        region = (
            getattr(cc, "code", None) or (cc if isinstance(cc, str) else None)
        ) or _DEFAULT_REGION
        order = GeoPlaceExternalLink.objects.filter(geo_place=detail.geo_place).count()
        for entry in detail.phones or []:
            raw = entry.get("number", "") if isinstance(entry, dict) else str(entry)
            e164 = _normalize_e164(raw, region)
            if e164 is None:
                unparseable.append(f"{detail.geo_place.slug}: {raw!r}")
                continue
            url = f"tel:{e164}"
            link = ExternalLink.objects.filter(url=url).first()
            if link is None:
                label = (entry.get("label") if isinstance(entry, dict) else None) or ""
                link = ExternalLink(
                    identifier=_unique_identifier(ExternalLink),
                    url=url,
                    label=label,
                    uri_kind_id=phone_kind.pk,
                    run_health_check=False,
                    review_status="done",
                    is_active=True,
                    is_public=True,
                )
                link.save()
                created_links += 1
            _, created = GeoPlaceExternalLink.objects.get_or_create(
                geo_place=detail.geo_place,
                external_link=link,
                defaults={"order": order},
            )
            if created:
                created_associations += 1
            order += 1

    print(
        f"external-link-uris: phones -> tel: links: {created_links} links, "
        f"{created_associations} associations, {len(unparseable)} unparseable"
    )
    for item in unparseable[:20]:
        print(f"  unparseable (kept in JSON for review): {item}")
    if len(unparseable) > 20:
        print(f"  … and {len(unparseable) - 20} more")


class Migration(migrations.Migration):
    dependencies = [
        ("external_links", "0011_uri_kind_column"),
        ("geometries", "0054_alter_geoplace_slug_and_more"),
    ]

    operations = [
        migrations.RunPython(convert_phones, migrations.RunPython.noop),
    ]
