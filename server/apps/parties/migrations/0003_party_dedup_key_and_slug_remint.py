"""Split party identity from the public slug (``party-slug-minting``).

``dedup_key`` backfills from ``slug`` — the identity mapping for every
existing row, because the slug *was* the normalized-name import key
(0053 brand conversion, the OSM import, the owner merge). Uniqueness is
enforced after the backfill; slugs then re-mint as short readable
identifiers (``{base}-{suffix}`` ≤ 15 chars, hyphen style — geoplace
concept) from the localized names, chunked after the 0054 pattern:
collision domain in one set, stream ``.only()`` rows, ``bulk_update``
batches, retry while a minted slug is taken.

Reverse: no-op — re-minted slugs are not recoverable (the old values
live in git/migration history; same call as the geoplace re-mint).
"""

import re
import secrets
import string
from typing import Any

from django.db import DEFAULT_DB_ALIAS, migrations, models

#: Rows processed per bulk_update statement — matches 0054.
CHUNK_SIZE = 2_000

#: Same collision-domain shape as the geoplace re-mint: with ~10^3
#: parties the set is trivially small; the retry loop makes uniqueness
#: certain regardless.
_ALPHABET = string.ascii_lowercase + string.digits


#: Minted slug shape: base ≤ 9 alphanumerics, hyphen, 5 alphanumerics.
#: Re-runs only touch slugs that do not already match it (the 0054
#: re-runnability pattern: a retried or crashed-then-rolled-back run
#: finds nothing left to change).
_MINTED_RE = re.compile(r"^[a-z0-9]{1,9}-[a-z0-9]{5}$")


def _mint(base: str) -> str:
    """Mint ``{base≤9}-{5 alnum}`` ≤ 15 chars (0054 shape)."""
    sanitized = base.lower().replace("_", "-").strip("-")
    sanitized = "".join(c for c in sanitized if c.isalnum() or c == "-")
    base = sanitized.replace("-", "")[:9] or "party"
    return f"{base}-{''.join(secrets.choice(_ALPHABET) for _ in range(5))}"[:15]


def backfill_dedup_keys(apps: Any, schema_editor: Any) -> None:
    Party = apps.get_model("parties", "Party")
    db_alias = (
        schema_editor.connection.alias
        if schema_editor is not None
        else DEFAULT_DB_ALIAS
    )
    objects = Party.objects.using(db_alias)
    # .order_by() clears the historical model's default ordering
    # (Lower on name_i18n — a modeltrans field that does not exist on
    # the historical model; the 0054 lesson).
    for party in (
        objects.filter(dedup_key__isnull=True)
        .order_by()
        .only("id", "slug")
        .iterator(chunk_size=CHUNK_SIZE)
    ):
        objects.filter(pk=party.pk).update(dedup_key=party.slug)


def re_mint_slugs(apps: Any, schema_editor: Any) -> None:
    Party = apps.get_model("parties", "Party")
    db_alias = (
        schema_editor.connection.alias
        if schema_editor is not None
        else DEFAULT_DB_ALIAS
    )
    objects = Party.objects.using(db_alias)

    # Party has no default ordering, but .order_by() keeps that explicit
    # against future model changes (0054 lesson: default ordering can
    # reference fields that do not exist at a migration state).
    taken: set[str] = set(
        objects.values_list("slug", flat=True)
        .order_by()
        .iterator(chunk_size=CHUNK_SIZE)
    )

    minted = 0
    batch: list[Any] = []
    parties = (
        objects.exclude(slug__regex=_MINTED_RE.pattern)
        .order_by("id")
        .only("id", "slug", "name", "dedup_key", "i18n")
        .iterator(chunk_size=CHUNK_SIZE)
    )
    for party in parties:
        # Same name resolution as the 0053 conversion: localized name
        # first, then the key title-cased as a human-ish fallback.
        key = party.dedup_key or party.slug or "party"
        name = party.name or key.replace("_", " ").title()
        new_slug = _mint(name)
        while new_slug in taken:
            new_slug = _mint(name)
        taken.add(new_slug)
        party.slug = new_slug
        batch.append(party)
        if len(batch) >= CHUNK_SIZE:
            objects.bulk_update(batch, ["slug"], batch_size=CHUNK_SIZE)
            minted += len(batch)
            batch = []
    if batch:
        objects.bulk_update(batch, ["slug"], batch_size=CHUNK_SIZE)
        minted += len(batch)
    if minted:
        print(f"party-slug-minting: re-minted {minted} party slugs", flush=True)


class Migration(migrations.Migration):
    dependencies = [
        ("parties", "0002_merge_owners_into_parties"),
    ]

    operations = [
        migrations.AddField(
            model_name="party",
            name="dedup_key",
            field=models.SlugField(
                blank=True,
                db_index=True,
                help_text="Normalized name - the import identity (auto-derived when blank)",
                max_length=50,
                null=True,
                unique=True,
                verbose_name="Dedup key",
            ),
        ),
        migrations.RunPython(backfill_dedup_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="party",
            name="dedup_key",
            field=models.SlugField(
                blank=True,
                db_index=True,
                help_text="Normalized name - the import identity (auto-derived when blank)",
                max_length=50,
                null=False,
                unique=True,
                verbose_name="Dedup key",
            ),
        ),
        # The slug column shrinks to 15 chars only AFTER the re-mint —
        # legacy slugs (normalized names, up to 50 chars) would fail
        # the ALTER TABLE otherwise.
        migrations.RunPython(re_mint_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="party",
            name="slug",
            field=models.SlugField(
                blank=True,
                db_index=True,
                help_text="Short public identifier; minted from the name when left blank",
                max_length=15,
                unique=True,
                verbose_name="Slug",
            ),
        ),
    ]
