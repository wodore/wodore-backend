import os
import click
import traceback
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError
from huts.models import HutSource, ReviewStatusChoices, Hut, HutType
from organizations.models import Organization
from huts.services.osm import OsmService
from huts.services.sources import HutSourceService
from huts.schemas import HutSourceTypes
from huts.schemas.hut import HutSchema
from huts.schemas.hut_osm import HutOsm0Convert
from django.core.management import call_command

# from django.conf import settings
# import shutil
# from djjmt.utils import override


# def add_hut_source_db(
#    huts: HutSourceTypes,
#    reference: str,
#    # update_existing: bool = False, overwrite_existing_fields: bool=False,
#    init: bool,
#    extern_slug=None,
#    # commit_per_hut: bool = False,
# ):
#    # session_id = str(uuid4())
#    # context = set_session_context(session_id=session_id)
#    # session = await get_return_async_session()
#    hut_source_service = HutSourceService()
#    organization_id = Organization.get_by_slug(slug=reference).id
#    source_huts = []
#    for hut in huts:
#        shut = HutSource(
#            source_id=hut.get_id(),
#            point=hut.get_db_point(),
#            organization_id=organization_id,
#            name=hut.get_name(),
#            source_data=hut.dict(),
#        )
#        review_status = ReviewStatusChoices.done if init else ReviewStatusChoices.new
#        shut, status = hut_source_service.create(shut, new_review_status=review_status)
#        print(f"{shut}: {status}")
#        # shut.save()
#        source_huts.append(shut)
#    return source_huts


def init_huts_db(
    hut_sources: list[HutSource],
    update_existing: bool = False,
    overwrite_existing_fields: bool = False,
    extern_slug=None,
    commit_per_hut: bool = False,
):
    # hut_service = HutService(session=s)
    # osm_schemas = [HutOsm0Convert(source=h.source_data) for h in osm_huts]
    # hut_schemas = [HutSchema(**h.model_dump()) for h in osm_schemas]
    number = 0
    fails = []
    default_type, _created = HutType.objects.get_or_create(slug="unknown")
    organization, _created = Organization.objects.get_or_create(slug="osm")
    hut_types = {ht.slug: ht for ht in HutType.objects.all()}
    for hut_src in hut_sources:
        hut_osm_schema = HutOsm0Convert(source=hut_src.source_data)  # TODO: make generic
        hut = HutSchema(**hut_osm_schema.model_dump())
        _name = f"  Hut {str(number): <3} '{hut.name.get('de')}'"
        click.echo(f"{_name: <48}", nl=False)
        i18n_fields = {}
        for field in ["name", "description", "note"]:
            for code, value in getattr(hut, field).items():
                i18n_fields[f"{field}_{code}"] = value
        db_hut = Hut(
            point=hut.point.db,
            elevation=hut.elevation,
            capacity=hut.capacity,
            url=hut.url,
            is_active=hut.is_active,
            country=hut.country,
            type=hut_types.get(str(hut.type), default_type),
            **i18n_fields,
        )
        try:
            db_hut.save()
            db_hut.organizations.add(organization)
            db_hut.refresh_from_db()
            hut_src.hut = db_hut
            hut_src.save()
            click.secho(f" ({db_hut.slug})", dim=True)
        except IntegrityError:
            click.secho(f" ({db_hut.slug} already exists)", dim=True)

        number += 1
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
        #    click.secho(f"  ... failed", fg="red")
        #    click.secho(e, dim=True)
        #    continue
        # click.secho(f"  ... {status:<8}", fg="green", nl=False)
    click.echo(f"Done, added {number} huts")
    if fails:
        click.secho("This hut failed:", fg="red")
    for f in fails:
        click.echo(f"- {f.name}")
    # if not commit_per_hut:
    #    try:
    #        #await hut_service.session.commit()
    #        await session.commit()
    #    except OperationalError as e:
    #        click.secho(f"Failed to commit any hut", fg="red")
    #        click.secho(e, dim=True)


class Command(BaseCommand):
    help = "Initialize and drop data in Organizations table"
    suppressed_base_arguments = (
        "--version",
        "--settings",
        "--pythonpath",
        "--traceback",
        "--no-color",
        "--force-color",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._parser = None

    def add_arguments(self, parser):
        parser.add_argument("-d", "--drop", action="store_true", help="Drop entries in table")
        parser.add_argument("-f", "--fill", action="store_true", help="Fill table with default entries")
        parser.add_argument("-i", "--init", action="store_true", help="Initial data fill")
        parser.add_argument("-a", "--all", action="store_true", help="Run drop and fill commands")
        parser.add_argument("-n", "--number", help="Number of entries", required=True, type=int)
        self._parser = parser

    def handle(self, drop: bool, fill: bool, all: bool, init: bool, number: int, lang: str = "de", *args, **options):
        if drop or all:
            db = Hut.objects
            self.stdout.write(f"Drop {db.count()} entries from table 'Hut'")
            db.all().delete()
        elif fill or all:
            # osm_service = OsmService()
            ## t_osm_huts = asyncio.create_task(osm_service.get_osm_hut_list(limit=limit, lang=lang))
            # osm_huts = osm_service.get_osm_hut_list_sync(limit=number, lang=lang)
            # click.echo("Get OSM data")
            ## osm_huts = await t_osm_huts
            # click.secho("Fill table with OSM data", fg="magenta")
            # huts = add_hut_source_db(osm_huts, reference="osm", init=init)
            # print(huts)

            click.echo("Get OSM data")
            osm_huts = list(HutSource.objects.filter(organization__slug="osm").all()[:number])
            # osm_schemas = [HutOsm0Convert(source=h.source_data) for h in osm_huts]
            # hut_schemas = [HutSchema(**h.model_dump()) for h in osm_schemas]
            init_huts_db(
                osm_huts
            )  # , update_existing=update_existing, overwrite_existing_fields=overwrite_existing_fields)

        # if drop or all:
        #    db = Organization.objects
        #    self.stdout.write(f"Drop {db.count()} entries from table 'Organizations'")
        #    db.all().delete()
        #    if not ignore_media and os.path.exists(media_dst):
        #        self.stdout.write(f"Remove media file folder '{media_dst}'")
        #        shutil.rmtree(media_dst)
        # if fill or all:
        #    self.stdout.write(f"Load data from 'organizations.yaml' fixtures")
        #    try:
        #        call_command("loaddata", "organizations", app_label="organizations")
        #        self.stdout.write(self.style.SUCCESS(f"Successfully loaded data"))
        #    except Exception as e:
        #        self.stderr.write(traceback.format_exc())
        #        self.stdout.write(self.style.ERROR(f"Loaddata failed, fix issues and run again"))
        #    if not ignore_media:
        #        self.stdout.write(f"Copy media files from '{media_src}' to '{media_dst}'")
        #        shutil.copytree(media_src, media_dst, dirs_exist_ok=True)
        # if save:
        #    try:
        #        fixture_path = os.path.relpath(f"{app_root}/fixtures/organizations.yaml")
        #        call_command("dumpdata", "organizations.Organization", format="yaml", output=fixture_path)
        #        with open(fixture_path, "r") as file:
        #            new_lines = []  # remove created and modified
        #            for line in file.readlines():
        #                if "    modified: " not in line and "    created: " not in line:
        #                    new_lines.append(line)
        #        with open(fixture_path, "w") as file:
        #            file.writelines(new_lines)
        #        self.stdout.write(self.style.WARNING(f"Make sure to copy any new/changed logo to '{media_src}'"))
        #        self.stdout.write(self.style.SUCCESS(f"Successfully saved data to '{fixture_path}'"))
        #    except Exception as e:
        #        self.stderr.write(str(e))
        #        self.stdout.write(self.style.ERROR(f"Save data failed, fix issues and run again"))

        # if not fill and not drop and not all and not save:
        #    if self._parser is not None:
        #        self._parser.print_help()
        #    else:
        #        self.stdout.write(self.style.NOTICE(f"Missing arguments"))
