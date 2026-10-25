"""URI-kind vocabulary and curated icons (openspec: external-link-uris).

Data-only migration (the geometries 0052 role-seed precedent): seeds
the ``uri`` category vocabulary — phone/email/website with schemes and
health-check policy in ``extra`` — plus the curated Material Symbols
icons (via the Iconify API, Apache-2.0; refs on the Symbol rows) wired
to the children's symbol FKs.

Standalone on purpose: categories_category carries computedfields
deferred triggers, so row writes and DDL must not share a transaction
("cannot ALTER TABLE ... pending trigger events").

Reverse is a no-op: vocabulary/icons are re-derivable, and link rows
referencing the kinds would block deletion anyway (RESTRICT).
"""

from typing import Any

from django.core.files.base import ContentFile
from django.db import migrations
from django.db.models import Case, Value, When

# slug, name (de, modeltrans source), name_en, schemes, health, icon
URI_CHILDREN = [
    ("phone", "Telefon", "Phone", ["tel"], False, "call", 10),
    ("email", "E-Mail", "Email", ["mailto"], False, "mail", 20),
    ("website", "Website", "Website", ["http", "https"], True, "link", 30),
]

ICON_SOURCES = {
    "call": (
        "https://api.iconify.design/material-symbols/call.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path fill="currentColor" d="M19.95 21q-3.125 0-6.175-1.362t-5.55-3.863t-3.862-5.55T3 4.05q0-.45.3-.75t.75-.3H8.1q.35 0 .625.238t.325.562l.65 3.5q.05.4-.025.675T9.4 8.45L6.975 10.9q.5.925 1.187 1.787t1.513 1.663q.775.775 1.625 1.438T13.1 17l2.35-2.35q.225-.225.588-.337t.712-.063l3.45.7q.35.1.575.363T21 15.9v4.05q0 .45-.3.75t-.75.3"/></svg>',
    ),
    "mail": (
        "https://api.iconify.design/material-symbols/mail.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path fill="currentColor" d="M4 20q-.825 0-1.412-.587T2 18V6q0-.825.588-1.412T4 4h16q.825 0 1.413.588T22 6v12q0 .825-.587 1.413T20 20zm8-7l8-5V6l-8 5l-8-5v2z"/></svg>',
    ),
    "link": (
        "https://api.iconify.design/material-symbols/link.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path fill="currentColor" d="M11 17H7q-2.075 0-3.537-1.463T2 12t1.463-3.537T7 7h4v2H7q-1.25 0-2.125.875T4 12t.875 2.125T7 15h4zm-3-4v-2h8v2zm5 4v-2h4q1.25 0 2.125-.875T20 12t-.875-2.125T17 9h-4V7h4q2.075 0 3.538 1.463T22 12t-1.463 3.538T17 17z"/></svg>',
    ),
}

STYLES = ("color", "mono")


def _symbols_for(Symbol: Any, License: Any, icon: str) -> dict[str, Any]:
    """Curated Symbol rows (color + mono) for one icon, idempotent."""
    source_url, svg = ICON_SOURCES[icon]
    license = License.objects.get(slug="apache-2.0")
    out: dict[str, Any] = {}
    for style in STYLES:
        slug = f"uri-{icon}"
        symbol, _created = Symbol.objects.get_or_create(
            slug=slug,
            style=style,
            defaults=dict(
                svg_file=ContentFile(svg.encode(), name=f"symbols/{slug}-{style}.svg"),
                license=license,
                source_url=source_url,
                source_ident=(
                    f"iconify:material-symbols/{icon} (Apache-2.0), fetched 2026-10-25"
                ),
                search_text="uri typed link phone mail website",
                is_active=True,
            ),
        )
        out[style] = symbol
    return out


def seed_uri_vocabulary(apps: Any, schema_editor: Any) -> None:
    Category = apps.get_model("categories", "Category")
    License = apps.get_model("licenses", "License")
    Symbol = apps.get_model("symbols", "Symbol")

    License.objects.get_or_create(
        slug="apache-2.0",
        defaults=dict(
            name="Apache 2.0",
            fullname="Apache License 2.0",
            url="https://www.apache.org/licenses/LICENSE-2.0",
        ),
    )

    parent, _created = Category.objects.get_or_create(
        slug="uri",
        parent=None,
        defaults=dict(
            name="URI-Art",
            i18n={"name_en": "URI Kind"},
            order=60,
            is_active=True,
        ),
    )
    for slug, name, name_en, schemes, health, icon, order in URI_CHILDREN:
        child, _created = Category.objects.get_or_create(
            slug=slug,
            parent=parent,
            defaults=dict(
                name=name,
                i18n={"name_en": name_en},
                order=order,
                is_active=True,
                extra={"schemes": schemes, "health_check": health},
            ),
        )
        symbols = _symbols_for(Symbol, License, icon)
        child.symbol_color = symbols["color"]
        child.symbol_mono = symbols["mono"]
        child.save(update_fields=["symbol_color", "symbol_mono"])

    # Historical models bypass computedfields — set identifiers
    # explicitly (the categories 0006 / role-seed precedent).
    Category.objects.filter(pk=parent.pk).update(identifier="root.uri")
    Category.objects.filter(parent=parent).update(
        identifier=Case(
            *[When(slug=slug, then=Value(f"uri.{slug}")) for slug, *_ in URI_CHILDREN]
        )
    )


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0021_category_created_category_modified_and_more"),
        ("external_links", "0009_add_template_fields"),
        ("licenses", "0011_alter_license_slug"),
        ("symbols", "0016_content_hash_symbol_files"),
    ]

    operations = [
        migrations.RunPython(seed_uri_vocabulary, migrations.RunPython.noop),
    ]
