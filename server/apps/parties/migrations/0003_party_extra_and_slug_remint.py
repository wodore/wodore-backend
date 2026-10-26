"""Party identity moves to ``extra.osm_name``; slugs re-mint short.

OpenSpec change ``party-slug-minting`` (revised design): the import
identity lives in the ``extra`` JSONB (``osm_name`` — the normalized
source name; owner slugs ride the same key), not in a dedicated
column. ``extra`` backfills from ``slug`` — the identity mapping for
every existing row, because the slug *was* the normalized-name import
key (0053 brand conversion, the OSM import, the owner merge).

Slugs then re-mint as short readable identifiers via the generic
``mint_short_slug`` helper (flexible 5-8 suffix, geoplace concept),
chunked after the 0054 pattern: collision domain in one set, stream
``.only()`` rows, ``bulk_update`` batches, retry while a minted slug
is taken. The slug column shrinks to varchar(15) AFTER the re-mint
(legacy slugs are up to 50 chars — the ALTER would fail before).

Reverse: no-op — re-minted slugs are not recoverable (same call as
the geoplace re-mint).
"""

import re
from typing import Any

from django.contrib.postgres.indexes import GinIndex
from django.db import DEFAULT_DB_ALIAS, migrations, models

from server.core.utils import mint_short_slug

#: Rows processed per bulk_update statement — matches 0054.
CHUNK_SIZE = 2_000

#: Minted slug shape: base ≤ 9 alphanumerics, hyphen, 5-8 char suffix.
#: Re-runs only touch slugs that do not already match it (the 0054
#: re-runnability pattern: a retried or crashed-then-rolled-back run
#: finds nothing left to change).
_MINTED_RE = re.compile(r"^[a-z0-9]{1,9}-[a-z0-9]{5,8}$")


def _db_alias(schema_editor: Any) -> str:
    return (
        schema_editor.connection.alias
        if schema_editor is not None
        else DEFAULT_DB_ALIAS
    )


def backfill_extra(apps: Any, schema_editor: Any) -> None:
    Party = apps.get_model("parties", "Party")
    objects = Party.objects.using(_db_alias(schema_editor))
    # .order_by() clears the historical model's default ordering
    # (Lower on name_i18n — a modeltrans field that does not exist at
    # this migration state; the 0054 lesson).
    for party in (
        objects.order_by("id")
        .only("id", "slug", "extra")
        .iterator(chunk_size=CHUNK_SIZE)
    ):
        extra = dict(party.extra or {})
        if "osm_name" not in extra:
            extra["osm_name"] = party.slug
            objects.filter(pk=party.pk).update(extra=extra)


def re_mint_slugs(apps: Any, schema_editor: Any) -> None:
    Party = apps.get_model("parties", "Party")
    objects = Party.objects.using(_db_alias(schema_editor))

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
        .only("id", "slug", "name", "extra")
        .iterator(chunk_size=CHUNK_SIZE)
    )
    for party in parties:
        # Same name resolution as the 0053 conversion: localized name
        # first, then the identity title-cased as a human-ish fallback.
        key = str((party.extra or {}).get("osm_name") or party.slug or "party")
        name = party.name or key.replace("_", " ").title()
        new_slug = mint_short_slug(name, fallback="party")
        while new_slug in taken:
            new_slug = mint_short_slug(name, fallback="party")
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
            name="extra",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Additional attributes (import identity, provenance, ...)",
                verbose_name="Extra",
            ),
        ),
        migrations.RunPython(backfill_extra, migrations.RunPython.noop),
        migrations.RunPython(re_mint_slugs, migrations.RunPython.noop),
        # The slug column shrinks to 15 chars only AFTER the re-mint —
        # legacy slugs (normalized names, up to 50 chars) would fail
        # the ALTER TABLE otherwise.
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
        # Last, so the data migrations above run on the un-indexed
        # table (index name matches Django's autodetected migration).
        migrations.AddIndex(
            model_name="party",
            index=GinIndex(fields=["extra"], name="parties_par_extra_75c6dd_gin"),
        ),
        # blank=True is form-level only (save() mints); the constraint
        # keeps the column non-empty for direct writes (review comment 3).
        migrations.AddConstraint(
            model_name="party",
            constraint=models.CheckConstraint(
                condition=models.Q(("slug", ""), _negated=True),
                name="parties_party_slug_not_empty",
            ),
        ),
    ]
