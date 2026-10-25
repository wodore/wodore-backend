"""Scheme-aware URL storage and the uri_kind FK (external-link-uris).

Backfill first, constraint second (the place-detail-endpoint
slug-invariant pattern): the ``url`` URLField becomes a CharField (same
column type/width — no data rewrite), ``uri_kind`` is added nullable,
one bulk UPDATE points every existing link at ``uri.website`` (task
2.6 — never per-row saves), then the column goes NOT NULL.
"""

from typing import Any

import pgtrigger

from django.db import connection, migrations, models

import server.apps.external_links.uri


def backfill_uri_kinds(apps: Any, schema_editor: Any) -> None:
    """One bulk UPDATE — never per-row saves (task 2.6).

    Wrapped in ``pgtrigger.ignore()``: the upd_mod trigger would fire
    per row (92k rows → beyond the 15s statement timeout) and this
    metadata backfill must not churn ``modified`` anyway.
    """
    Category = apps.get_model("categories", "Category")
    ExternalLink = apps.get_model("external_links", "ExternalLink")
    website = Category.objects.get(parent__slug="uri", slug="website")
    # pgtrigger's ignore wrapper adds per-row overhead on a 92k-row
    # UPDATE — beyond the default 15s statement timeout. One-time
    # migration statement: lift the timeout for this transaction
    # (SET LOCAL applies until commit).
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = 0")
    with pgtrigger.ignore():
        updated = ExternalLink.objects.filter(uri_kind__isnull=True).update(
            uri_kind_id=website.pk
        )
    remaining = ExternalLink.objects.filter(uri_kind__isnull=True).count()
    if remaining:
        msg = f"uri_kind backfill left {remaining} NULL rows"
        raise RuntimeError(msg)
    print(f"external-link-uris: backfilled {updated} links to uri.website")


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0021_category_created_category_modified_and_more"),
        ("external_links", "0010_uri_kinds"),
        # parties.0002 creates ExternalLink rows on the historical model
        # (no uri_kind) — it MUST run before the column goes NOT NULL on
        # fresh databases; its links are backfilled by the step below.
        ("parties", "0002_merge_owners_into_parties"),
    ]

    operations = [
        migrations.AlterField(
            model_name="externallink",
            name="url",
            field=models.CharField(
                db_index=True,
                help_text=(
                    "The URL of the external link (translatable - defaults to "
                    "first language). Any scheme its URI kind accepts: "
                    "http(s), tel:, mailto:"
                ),
                max_length=200,
                validators=[server.apps.external_links.uri.validate_url_for_scheme],
                verbose_name="URL",
            ),
        ),
        migrations.AddField(
            model_name="externallink",
            name="uri_kind",
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                help_text=(
                    "Transport kind of the URL (uri.phone / uri.email / "
                    "uri.website); derived from the URL's scheme on save"
                ),
                limit_choices_to={"parent__slug": "uri"},
                null=True,
                on_delete=models.deletion.RESTRICT,
                related_name="+",
                to="categories.category",
                verbose_name="URI Kind",
            ),
        ),
        migrations.RunPython(backfill_uri_kinds, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="externallink",
            name="uri_kind",
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                help_text=(
                    "Transport kind of the URL (uri.phone / uri.email / "
                    "uri.website); derived from the URL's scheme on save"
                ),
                limit_choices_to={"parent__slug": "uri"},
                null=False,
                on_delete=models.deletion.RESTRICT,
                related_name="+",
                to="categories.category",
                verbose_name="URI Kind",
            ),
        ),
    ]
