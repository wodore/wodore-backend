import click

from server.apps.organizations.models import Organization
from server.core.management.base import CRUDCommand

from ...models import HutSource, ReviewStatusChoices
from ...schemas import HutSourceTypes
from ...schemas.status import CreateOrUpdateStatus
from ...services.osm import OsmService
from ...services.sources import HutSourceService

# from django.conf import settings
# import shutil
# from djjmt.utils import override


def add_hut_source_db(
    huts: HutSourceTypes,
    reference: str,
    # update_existing: bool = False, overwrite_existing_fields: bool=False,
    init: bool,
    extern_slug=None,
):
    hut_source_service = HutSourceService()
    organization_id = Organization.get_by_slug(slug=reference).id
    source_huts = []
    number = 0
    for hut in huts:
        number += 1
        shut = HutSource(
            source_id=hut.get_id(),
            point=hut.get_db_point(),
            organization_id=organization_id,
            name=hut.get_name(),
            source_data=hut.dict(),
        )
        review_status = ReviewStatusChoices.done if init else ReviewStatusChoices.new
        shut, status = hut_source_service.create(shut, new_review_status=review_status)
        _hut_name = shut.name if len(shut.name) < 18 else shut.name[:15] + ".."
        _name = f"  Hut {number!s: <3} {'`'+shut.source_id+'`':<15} {_hut_name:<20} {'('+str(shut.organization)+')':<8}"
        click.echo(f"{_name: <48}", nl=False)
        status_color = {
            CreateOrUpdateStatus.updated: "yellow",
            CreateOrUpdateStatus.created: "green",
            CreateOrUpdateStatus.exists: "blue",
            CreateOrUpdateStatus.ignored: "grey",
        }
        click.secho(f"  ... {status:<8}", fg=status_color.get(status, "red"), nl=False)
        click.secho(f" (#{shut.id})", dim=True)
        # print(f"{shut}: {status}")
        # shut.save()
        source_huts.append(shut)
    return source_huts
    # async with session as s:
    #    source_service = HutSourceService(session = s)
    #    number = 0
    #    fails = []
    #    for hut in source_huts:
    #        _hut_name = hut.source_data.get_name() if len(hut.source_data.get_name()) <18 else hut.source_data.get_name()[:15] + ".."
    #        _name = f"  Hut {str(number): <3} {'`'+hut.source_id+'`':<5} {_hut_name:<20} ({hut.ref_slug})"
    #        click.echo(f"{_name: <48}", nl=False)
    #        try:
    #            hut, status = await source_service.create(hut,
    #                                commit=commit_per_hut,
    #                                #update_existing=update_existing, overwrite_existing_fields=overwrite_existing_fields,
    #                                ref_slug=extern_slug)
    #            number += 1
    #        except OperationalError as e:
    #            fails.append(hut)
    #            click.secho(f"  ... failed", fg="red")
    #            click.secho(e, dim=True)
    #            continue
    #        click.secho(f"  ... {status}", fg="green", nl=False)
    #        click.secho(f" ({hut.id})", dim=True)
    #    click.echo(f"Done, added {number} huts")
    #    if fails:
    #        click.secho("This hut failed:", fg="red")
    #    for f in fails:
    #        click.echo(f"- {f.name}")
    #    if not commit_per_hut:
    #        try:
    #            #await hut_service.session.commit()
    #            await session.commit()
    #        except OperationalError as e:
    #            click.secho(f"Failed to commit any hut", fg="red")
    #            click.secho(e, dim=True)
    # await async_engine.dispose() # TODO: why? shoudl use yield session generator


def _expect_organization(organization: str, selected_organization: str | None, or_none=True) -> bool:
    return (selected_organization is None and or_none) or (selected_organization or "").lower() == organization.lower()


def add_hutsources_function(
    parser: "Command", offset, limit, init, update, force, lang, selected_organization, **kwargs
):
    if _expect_organization("osm", selected_organization, or_none=True):
        osm_service = OsmService()
        parser.stdout.write(f"Get OSM data from '{osm_service.request_url}'")
        osm_huts = osm_service.get_osm_hut_list_sync(limit=limit, offset=offset, lang=lang)
        parser.stdout.write(f"Got {len(osm_huts)} results back, start filling database:")
        # click.secho("Fill table with OSM data", fg="magenta")
        huts = add_hut_source_db(osm_huts, reference="osm", init=init)
        parser.stdout.write(parser.style.SUCCESS(f"Successfully added {len(huts)} new huts"))
    else:
        parser.stdout.write(parser.style.WARNING(f"Selected organization '{selected_organization}' not supported."))


class Command(CRUDCommand):
    # help = ""
    model = HutSource
    model_names = "hutsources"
    add_function = add_hutsources_function
    use_limit_arg = True
    use_offset_arg = True
    # use_update_arg = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument("-i", "--init", action="store_true", help="Initial data fill")
        parser.add_argument("--organization", help="Organization slug, only add this one, otherwise all", type=str)
        parser.add_argument("--lang", help="Language to use (de, en, fr, it)", default="de", type=str)

    def handle(self, init, organization, lang, *args, **options):
        super().handle(kwargs_add={"init": init, "selected_organization": organization, "lang": lang}, **options)


# class Command(BaseCommand):
#    help = "Initialize and drop data in Organizations table"
#    suppressed_base_arguments = (
#        "--version",
#        "--settings",
#        "--pythonpath",
#        "--traceback",
#        "--no-color",
#        "--force-color",
#    )
#
#    def __init__(self, *args, **kwargs):
#        super().__init__(*args, **kwargs)
#        self._parser = None
#
#    def add_arguments(self, parser):
#        parser.add_argument("-d", "--drop", action="store_true", help="Drop entries in table")
#        parser.add_argument("-f", "--fill", action="store_true", help="Fill table with default entries")
#        parser.add_argument("-i", "--init", action="store_true", help="Initial data fill")
#        parser.add_argument("-a", "--all", action="store_true", help="Run drop and fill commands")
#        parser.add_argument("-n", "--number", help="Number of entries", required=False, type=int, default=None)
#        self._parser = parser
#
#    def handle(self, drop: bool, fill: bool, all: bool, init: bool, number: int, lang: str = "de", *args, **options):
#        model_name = "HutSource"
#        if drop or all:
#            drop_number = number
#            db = HutSource.objects
#            entries = db.count()
#            if not entries:
#                click.echo(f"No entries for '{model_name}'")
#            else:
#                if drop_number:
#                    if drop_number > entries:
#                        drop_number = entries
#                    pks = db.all()[:drop_number].values_list("pk", flat=True)
#                else:
#                    drop_number = entries
#                    pks = db.all().values_list("pk", flat=True)
#                if click.confirm(f"Delete {drop_number} of {entries} entries?"):
#                    db.filter(pk__in=pks).delete()
#                self.stdout.write(f"Dropped {drop_number} entries from table '{model_name}'")
#
#        if fill or all:
#            if not number:
#                number = 10
#            osm_service = OsmService()
#            osm_huts = osm_service.get_osm_hut_list_sync(limit=number, lang=lang)
#            click.echo("Get OSM data")
#            click.secho("Fill table with OSM data", fg="magenta")
#            huts = add_hut_source_db(osm_huts, reference="osm", init=init)
#        # if drop or all:
#        #    db = Organization.objects
#        #    self.stdout.write(f"Drop {db.count()} entries from table 'Organizations'")
#        #    db.all().delete()
#        #    if not ignore_media and os.path.exists(media_dst):
#        #        self.stdout.write(f"Remove media file folder '{media_dst}'")
#        #        shutil.rmtree(media_dst)
#        # if fill or all:
#        #    self.stdout.write(f"Load data from 'organizations.yaml' fixtures")
#        #    try:
#        #        call_command("loaddata", "organizations", app_label="organizations")
#        #        self.stdout.write(self.style.SUCCESS(f"Successfully loaded data"))
#        #    except Exception as e:
#        #        self.stderr.write(traceback.format_exc())
#        #        self.stdout.write(self.style.ERROR(f"Loaddata failed, fix issues and run again"))
#        #    if not ignore_media:
#        #        self.stdout.write(f"Copy media files from '{media_src}' to '{media_dst}'")
#        #        shutil.copytree(media_src, media_dst, dirs_exist_ok=True)
#        # if save:
#        #    try:
#        #        fixture_path = os.path.relpath(f"{app_root}/fixtures/organizations.yaml")
#        #        call_command("dumpdata", "organizations.Organization", format="yaml", output=fixture_path)
#        #        with open(fixture_path, "r") as file:
#        #            new_lines = []  # remove created and modified
#        #            for line in file.readlines():
#        #                if "    modified: " not in line and "    created: " not in line:
#        #                    new_lines.append(line)
#        #        with open(fixture_path, "w") as file:
#        #            file.writelines(new_lines)
#        #        self.stdout.write(self.style.WARNING(f"Make sure to copy any new/changed logo to '{media_src}'"))
#        #        self.stdout.write(self.style.SUCCESS(f"Successfully saved data to '{fixture_path}'"))
#        #    except Exception as e:
#        #        self.stderr.write(str(e))
#        #        self.stdout.write(self.style.ERROR(f"Save data failed, fix issues and run again"))
#
#        # if not fill and not drop and not all and not save:
#        #    if self._parser is not None:
#        #        self._parser.print_help()
#        #    else:
#        #        self.stdout.write(self.style.NOTICE(f"Missing arguments"))
#
