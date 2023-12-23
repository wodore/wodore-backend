# type: ignore  # noqa: PGH003
# TODO: add types
import sys
import typing as t

import click
from hut_services import BaseService
from pydantic import BaseModel

from django.conf import settings
from django.contrib.gis.geos import Point as dbPoint
from django.db import DataError, IntegrityError, transaction
from django.utils.text import slugify

from server.apps.organizations.models import Organization
from server.apps.owners.models import Owner
from server.core.management import CRUDCommand

from ...models import Hut, HutSource


def init_huts_db(
    hut_sources: list[HutSource],
    init: bool = False,
    update_existing: bool = False,
    overwrite_existing_fields: bool = False,
    extern_slug=None,
    commit_per_hut: bool = False,
) -> t.Tuple[int, int]:
    added_huts = 0
    updated_huts = 0
    failed_huts = 0
    hut_counter = 0
    fails = []
    for hut_src in hut_sources:
        hut_counter += 1
        _name = f"  Hut {hut_counter!s: <3} '{hut_src.name}'"
        click.echo(f"{_name: <48}", nl=False)
        try:
            db_hut, created = Hut.update_or_create(hut_source=hut_src, review=init)
            click.secho(f" {'('+db_hut.slug+')':<30}", dim=True, nl=False)
            if created:
                click.secho("created", fg="green")
                added_huts += 1
            else:
                updated_huts += 1
                click.secho("updated", fg="magenta")
        except IntegrityError as e:
            err_msg = str(e).split("\n")[0]
            click.secho(f" {'('+hut_src.organization.slug+'-'+hut_src.source_id+')':<20} E: {err_msg}", dim=True)
            failed_huts += 1
            fails.append(hut_src)
        except NotImplementedError as e:
            err_msg = str(e).split("\n")[0]
            click.secho(f" {'('+hut_src.organization.slug+'-'+hut_src.source_id+')':<20} E: {err_msg}", dim=True)
            failed_huts += 1
            fails.append(hut_src)
        # try:
        #    hut, status = await hut_service.create_or_update(
        #        hut,
        #        commit=commit_per_hut,
        #        update_existing=update_existing,
        #        overwrite_existing_fields=overwrite_existing_fields,
        #        ref_slug=extern_slug,
        #    )
        #    number += 1
        # except OperationalError as e:
        #    fails.append(hut)
        #    continue
        # click.secho(f"  ... {status:<8}", fg="green", nl=False)
    if fails:
        click.secho("This huts failed:", fg="red")
    for f in fails[:8]:
        click.echo(f"- {f.name}")
    if len(fails) > 8:
        click.secho(f"- and {len(fails) - 8} more ...", fg="yellow", dim=False)
    # click.secho(f"Done, added {added_huts} huts", fg="green")
    return added_huts, updated_huts, failed_huts


def _expect_organization(organization: str, selected_organization: str | None, or_none=True) -> bool:
    return (selected_organization is None and or_none) or (selected_organization or "").lower() == organization.lower()


def add_huts_function(obj: "Command", offset, limit, init, update, force, selected_organization, **kwargs):
    total_entries = HutSource.objects.all().count()
    if total_entries == 0:
        obj.stdout.write(obj.style.WARNING("No entries in 'huts.HutSource', run first: 'app hut_sources --add'"))
        sys.exit(1)

    # if _expect_organization("osm", selected_organization, or_none=True):
    #    parser.stdout.write("Get OSM data where 'huts.HutSource.slug == osm'.")
    if selected_organization:
        src_huts = list(
            HutSource.objects.filter(organization__slug=selected_organization).all()[offset : offset + limit]
        )
    else:
        src_huts = list(HutSource.objects.all()[offset : offset + limit])
    new_huts = len(src_huts)
    obj.stdout.write(obj.style.NOTICE(f"Going to fill table with {new_huts} entries and an offset of {offset}"))
    added, updated, failed = init_huts_db(
        src_huts, init=init
    )  # , update_existing=update_existing, overwrite_existing_fields=overwrite_existing_fields)
    if added:
        obj.stdout.write(obj.style.SUCCESS(f"Successfully added {added} new hut{'s' if added > 1 else ''}"))
    if updated:
        obj.stdout.write(obj.style.SUCCESS(f"Successfully updated {updated} hut{'s' if updated > 1 else ''}"))
    if failed:
        obj.stdout.write(obj.style.ERROR(f"Failed to add {failed} hut{'s' if failed > 1 else ''}"))
    # else:
    #    parser.stdout.write(parser.style.WARNING(f"Selected organization '{selected_organization}' not supported."))


class Command(CRUDCommand):
    # help = ""
    model = Hut
    model_names = "huts"
    add_function = add_huts_function
    use_limit_arg = True
    use_offset_arg = True
    use_update_arg = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument("-i", "--init", action="store_true", help="Initial data fill")
        parser.add_argument(
            "-O", "--orgs", "--organization", help="Organization slug, only add this one, otherwise all", type=str
        )

    def handle(self, init, orgs, *args, **options):
        super().handle(kwargs_add={"init": init, "selected_organization": orgs}, **options)
