"""Provision parties from existing Owner rows at migrate time.

OpenSpec ``geoplace-parties``: environments that only run ``migrate``
receive the owner-derived parties without a manual ``import_parties``
step. The command remains the re-sync tool for Owner rows arriving
later (design decision 5); this migration is the initial-provisioning
shortcut. The role-category side of the same provisioning is seeded by
``geometries.0052``.

Historical models only — no app-code imports (``services.merge_owner``
would drift with future refactors), and historical models strip
``save()`` overrides, so ``ExternalLink``'s identifier generation is
replicated inline (lowercase+digits, 6 chars, collision retry — same
shape as ``generate_unique_identifier``). New links carry an explicit
label; no title extraction or health checks run here, by design.

Reverse is a no-op: parties remain on rollback (data re-derivable,
same safety posture as geometries.0053).
"""

import secrets
import string

from django.db import migrations

_IDENTIFIER_CHARSET = string.ascii_lowercase + string.digits


def _unique_identifier(ExternalLink) -> str:
    """Mirror ExternalLink.generate_unique_identifier (6 chars, retry)."""
    length = 6
    while True:
        candidate = "".join(secrets.choice(_IDENTIFIER_CHARSET) for _ in range(length))
        if not ExternalLink.objects.filter(identifier=candidate).exists():
            return candidate
        length += 1


def merge_owners(apps, schema_editor):
    Owner = apps.get_model("owners", "Owner")
    Party = apps.get_model("parties", "Party")
    PartyLink = apps.get_model("parties", "PartyLink")
    ExternalLink = apps.get_model("external_links", "ExternalLink")

    # ``order_by()`` clears the model's default ordering — the
    # historical Owner carries ``Lower("name_i18n")`` from its
    # migration options, and modeltrans virtual fields do not exist on
    # historical models, so resolving the ordering would raise
    # FieldError before the first row is fetched.
    for owner in Owner.objects.all().order_by().iterator(chunk_size=500):
        i18n = {
            key: value
            for key, value in (owner.i18n or {}).items()
            if key.startswith(("name_", "note_"))
        }
        party, _created = Party.objects.get_or_create(
            slug=owner.slug,
            defaults={"name": owner.name or owner.slug, "i18n": i18n},
        )

        if not owner.url:
            continue
        link = ExternalLink.objects.filter(url=owner.url).first()
        if link is None:
            link = ExternalLink(
                url=owner.url,
                label=owner.name or owner.slug,
                identifier=_unique_identifier(ExternalLink),
            )
            link.save()  # historical models use base Model.save(); skip_health_check has no effect here
        PartyLink.objects.get_or_create(party=party, external_link=link)


class Migration(migrations.Migration):
    dependencies = [
        ("external_links", "0009_add_template_fields"),
        ("owners", "0011_owner_upd_mod_a69e3013_and_more"),
        ("parties", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(merge_owners, migrations.RunPython.noop),
    ]
