# type: ignore  # noqa: PGH003
# TODO: add types
import sys
import json
import typing as t

import click

from django.core.management import call_command
from django.db import IntegrityError
from server.apps.organizations.models import Organization
from server.apps.huts.models import HutType

from server.core import UpdateCreateStatus
from server.core.management import CRUDCommand

from ...models import Hut, HutSource


def init_huts_db(
    hut_sources: list[HutSource],
    review: bool = False,
    force_overwrite: bool = False,  # overwrite exisitng entries
    force_overwrite_include: t.Sequence[str] = [],  # set a list which field which should be overwritten
    force_overwrite_exclude: t.Sequence[str] = [],  #  ... exclude
    force_none: bool = False,  # force t oset value to none (overwrite is needed)
) -> t.Tuple[int, int]:
    added_huts = 0
    updated_huts = 0
    nochange_huts = 0
    failed_huts = 0
    hut_counter = 0
    fails = []
    for hut_src in hut_sources:
        hut_counter += 1
        _name = f"  Hut {hut_counter!s: <3} '{hut_src.name}'"
        click.echo(f"{_name: <48}", nl=False)
        try:
            db_hut, created = Hut.update_or_create(
                hut_source=hut_src,
                review=review,
                force_overwrite=force_overwrite,
                force_overwrite_include=force_overwrite_include,
                force_overwrite_exclude=force_overwrite_exclude,
                force_none=force_none,
            )
            click.secho(f" {'('+db_hut.slug+')':<30}", dim=True, nl=False)
            if created == UpdateCreateStatus.created:
                click.secho("created", fg="green")
                added_huts += 1
            elif created == UpdateCreateStatus.updated:
                updated_huts += 1
                click.secho("updated", fg="magenta")
            elif created == UpdateCreateStatus.no_change:
                nochange_huts += 1
                click.secho("not changed", dim=True)
            else:
                click.secho("unknown state", fg="red")
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
    if fails:
        click.secho("This huts failed:", fg="red")
    for f in fails[:8]:
        click.echo(f"- {f.name}")
    if len(fails) > 8:
        click.secho(f"- and {len(fails) - 8} more ...", fg="yellow", dim=False)
    return added_huts, updated_huts, nochange_huts, failed_huts


def add_huts_function(obj: "Command", offset, limit, update, force, selected_organization, **kwargs):
    force_overwrite = kwargs.get("force_overwrite", False)
    force_overwrite_include = kwargs.get("force_overwrite_include", [])
    force_overwrite_exclude = kwargs.get("force_overwrite_exclude", [])
    review = kwargs.get("review", True)
    force_none = kwargs.get("force_none", False)
    total_entries = HutSource.objects.all().count()
    if total_entries == 0:
        obj.stdout.write(obj.style.WARNING("No entries in 'huts.HutSource', run first: 'app hut_sources --add'"))
        sys.exit(1)

    if selected_organization:
        src_huts = list(
            HutSource.objects.filter(organization__slug=selected_organization).all()[offset : offset + limit]
        )
    else:
        src_huts = list(HutSource.objects.all()[offset : offset + limit])
    new_huts = len(src_huts)
    obj.stdout.write(obj.style.NOTICE(f"Going to fill table with {new_huts} entries and an offset of {offset}"))
    added, updated, nochange, failed = init_huts_db(
        src_huts,
        review=review,
        force_overwrite=force_overwrite,
        force_overwrite_include=force_overwrite_include,
        force_overwrite_exclude=force_overwrite_exclude,
        force_none=force_none,
    )  # , update_existing=update_existing, overwrite_existing_fields=overwrite_existing_fields)
    if added:
        obj.stdout.write(obj.style.SUCCESS(f"Successfully added {added} new hut{'s' if added > 1 else ''}"))
    if updated:
        obj.stdout.write(obj.style.SUCCESS(f"Successfully updated {updated} hut{'s' if updated > 1 else ''}"))
    if nochange:
        obj.stdout.write(obj.style.NOTICE(f"No change for {nochange} hut{'s' if updated > 1 else ''}"))
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
        parser.add_argument(
            "-r",
            "--no-review",
            action="store_true",
            help="Do not change to review status (to 'review' if update, to 'new' if created)",
        )
        parser.add_argument(
            "-O", "--org", "--organization", help="Organization slug, only add this one, otherwise all", type=str
        )
        parser.add_argument("-w", "--overwrite", action="store_true", help="Overwrite existing entries")
        parser.add_argument(
            "-n",
            "--include",
            help=f"a comma separated list with fields to overwrite, per default all. This sets '--overwrite' automatically. Possible values: \"{','.join(Hut.UPDATE_SCHEMA_FIELDS)}\"",
            default="",
        )
        parser.add_argument(
            "-x",
            "--exclude",
            help=f"a comma separated list with fields not to overwrite. This sets '--overwrite' automatically and does not work togehter with '--include'. Possible values: \"{','.join(Hut.UPDATE_SCHEMA_FIELDS)}\"",
            default="",
        )
        parser.add_argument(
            "--set-none",
            action="store_true",
            help="do overwrite existing entries with 'None' if no entry is in the new data (only together with '--overwrite', or '--include/--exclude')",
        )
        parser.add_argument(
            "--delete-all",
            "--da",
            action="store_true",
            help="deletes everything (huts, owners, contacts), limit and offset are not used!",
        )
        parser.add_argument(
            "--add-all",
            "--aa",
            action="store_true",
            help="adds everything (huts, owners, contacts), limits and offset are not used!",
        )

    def handle(
        self,
        no_review: bool,
        org: str,
        overwrite: bool,
        include: str,
        exclude: str,
        set_none: bool,
        delete_all: bool,
        add_all: bool,
        *args,
        **options,
    ):
        force_overwrite_include = [f.strip() for f in include.split(",") if include]
        force_overwrite_exclude = [f.strip() for f in exclude.split(",") if exclude]
        if force_overwrite_exclude or force_overwrite_include:
            overwrite = True
        finished = False
        if delete_all:
            force = options.get("force", False)
            for db in ["huts", "owners", "contacts"]:
                self.stdout.write(self.style.HTTP_INFO(f"Delete all {db}"))
                call_command(db, drop=True, force=force)
            finished = True
        if add_all:
            force = options.get("force")
            if not force:
                force = click.confirm("Force to add all huts?", default=True)
            if not Organization.objects.exists():
                self.stdout.write(self.style.HTTP_INFO("Organizations"))
                call_command("organizations", add=True, force=force)
            if not HutType.objects.exists():
                self.stdout.write(self.style.HTTP_INFO("Add hut types"))
                call_command("hut_types", add=True, force=force)
            limit = options.get("limit", None)
            for params in [
                {"org": "sac", "no_review": True},
                {"org": "wikidata", "include": "location,photos", "no_review": True},
                {"org": "osm", "no_review": True},
                {"org": "hrs", "no_review": True},
                {"org": "refuges", "no_review": False},
            ]:
                self.stdout.write(self.style.HTTP_INFO(f"Add {params.get('org','all')} huts with parameter:"))
                for k, v in params.items():
                    self.stdout.write(self.style.NOTICE(f"  {k+':':<10} '{v}'"))
                call_command("huts", add=True, force=force, limit=limit, **params)
            finished = True
        if finished:
            return
        super().handle(
            kwargs_add={
                "review": not no_review,
                "selected_organization": org,
                "force_overwrite": overwrite,
                "force_overwrite_include": [f.strip() for f in include.split(",") if include],
                "force_overwrite_exclude": [f.strip() for f in exclude.split(",") if exclude],
                "force_none": set_none,
            },
            **options,
        )
