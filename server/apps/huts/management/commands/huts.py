import os, sys
from typing import Tuple
import click
import traceback
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError
from huts.models import HutOrganizationAssociation, HutSource, ReviewStatusChoices, Hut, HutType
import organizations
from organizations.models import Organization
from huts.services.osm import OsmService
from huts.services.sources import HutSourceService
from huts.schemas import HutSourceTypes
from huts.schemas.hut import HutSchema
from huts.schemas.hut_osm import HutOsm0Convert
from django.core.management import call_command
from django.db import transaction

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
from pathlib import Path
from huts.models import HutType
from server.core.management import CRUDCommand


def init_huts_db(
    hut_sources: list[HutSource],
    init: bool = False,
    update_existing: bool = False,
    overwrite_existing_fields: bool = False,
    extern_slug=None,
    commit_per_hut: bool = False,
) -> Tuple[int, int]:
    # hut_service = HutService(session=s)
    # osm_schemas = [HutOsm0Convert(source=h.source_data) for h in osm_huts]
    # hut_schemas = [HutSchema(**h.model_dump()) for h in osm_schemas]
    added_huts = 0
    failed_huts = 0
    hut_counter = 0
    fails = []
    default_type, _created = HutType.objects.get_or_create(slug="unknown")
    organization, _created = Organization.objects.get_or_create(slug="osm")
    hut_types = {ht.slug: ht for ht in HutType.objects.all()}
    for hut_src in hut_sources:
        hut_counter += 1
        hut_osm_schema = HutOsm0Convert(source=hut_src.source_data)  # TODO: make generic
        hut = HutSchema(**hut_osm_schema.model_dump())
        _name = f"  Hut {str(hut_counter): <3} '{hut.name.get('de')}'"
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
            review_status=Hut.ReviewStatusChoices.done if init else Hut.ReviewStatusChoices.review,
            **i18n_fields,
        )
        try:
            with transaction.atomic():
                db_hut.save()
                new_org = HutOrganizationAssociation(
                    hut=db_hut, organization=organization, props=hut.props, source_id=hut_src.source_id
                )
                new_org.save()
                db_hut.refresh_from_db()
                hut_src.hut = db_hut
                hut_src.save()
                click.secho(f" ({db_hut.slug})", dim=True)
            added_huts += 1
        except IntegrityError as e:
            err_msg = str(e).split("\n")[0]
            click.secho(f" {'('+db_hut.slug+')':<20} E: {err_msg}", dim=True)
            failed_huts += 1

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
    # click.echo(f"Done, added {number} huts")
    if fails:
        click.secho("This hut failed:", fg="red")
    for f in fails:
        click.echo(f"- {f.name}")
    return added_huts, failed_huts


def _expect_organization(organization: str, selected_organization: str | None, or_none=True) -> bool:
    return (selected_organization is None and or_none) or (selected_organization or "").lower() == organization.lower()


def add_huts_function(parser: "Command", offset, limit, init, update, force, selected_organization, **kwargs):
    total_entries = HutSource.objects.all().count()
    if total_entries == 0:
        parser.stdout.write(parser.style.WARNING("No entries in 'huts.HutSource', run first: 'app hut_sources --add'"))
        sys.exit(1)

    if _expect_organization("osm", selected_organization, or_none=True):
        parser.stdout.write("Get OSM data where 'huts.HutSource.slug == osm'.")
        osm_huts = list(HutSource.objects.filter(organization__slug="osm").all()[offset : offset + limit])
        new_huts = len(osm_huts)
        parser.stdout.write(
            parser.style.NOTICE(f"Going to fill table with {new_huts} entries and an offset of {offset}")
        )
        added, failed = init_huts_db(
            osm_huts, init=init
        )  # , update_existing=update_existing, overwrite_existing_fields=overwrite_existing_fields)
        if added:
            parser.stdout.write(parser.style.SUCCESS(f"Successfully added {added} new hut{'s' if failed > 1 else ''}"))
        if failed:
            parser.stdout.write(parser.style.ERROR(f"Failed to add {failed} hut{'s' if failed > 1 else ''}"))
    else:
        parser.stdout.write(parser.style.WARNING(f"Selected organization '{selected_organization}' not supported."))


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
        parser.add_argument("--organization", help="Organization slug, only add this one, otherwise all", type=str)

    def handle(self, init, organization, *args, **options):
        super().handle(kwargs_add={"init": init, "selected_organization": organization}, **options)
