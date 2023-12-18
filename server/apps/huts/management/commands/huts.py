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

from ...models import Hut, HutOrganizationAssociation, HutSource, HutType
from ...schemas.hut import HutSchema

# from ...schemas.hut_osm import HutOsm0Convert
# from ...schemas.hut_refuges_info import HutRefugesInfo0Convert

SERVICES: dict[str, t.Type[BaseService[BaseModel]]] = settings.SERVICES
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
    init: bool = False,
    update_existing: bool = False,
    overwrite_existing_fields: bool = False,
    extern_slug=None,
    commit_per_hut: bool = False,
) -> t.Tuple[int, int]:
    # hut_service = HutService(session=s)
    # osm_schemas = [HutOsm0Convert(source=h.source_data) for h in osm_huts]
    # hut_schemas = [HutSchema(**h.model_dump()) for h in osm_schemas]
    added_huts = 0
    failed_huts = 0
    hut_counter = 0
    fails = []
    default_type, _created = HutType.objects.get_or_create(slug="unknown")
    # organization, _created = Organization.objects.get_or_create(slug="osm")
    # organization, _created = Organization.objects.get_or_create(slug="refuges")
    hut_types = {ht.slug: ht for ht in HutType.objects.all()}
    for hut_src in hut_sources:
        hut_counter += 1
        orgs = hut_src.organization.slug
        service = SERVICES.get(orgs)()
        hut = service.convert(src=hut_src)
        # source_class_name = hut_src.source_data.get("convert_class")
        # SrcClass = globals().get(source_class_name)
        # if SrcClass is None:
        #    click.secho(f"Converter class '{source_class_name}' not imported!", fg="red")
        #    sys.exit(1)
        # hut_src_schema = SrcClass(source=hut_src.source_data)
        ## TODO: move source class ou of dictionary and into model
        # hut = HutSchema(**hut_src_schema.model_dump())
        _name = f"  Hut {hut_counter!s: <3} '{hut.name.i18n}'"
        click.echo(f"{_name: <48}", nl=False)
        i18n_fields = {}
        for field in ["name", "description", "notes"]:
            model = getattr(hut, field)
            if not model:
                continue
            if field == "notes":
                model = model[0]
            for code, value in model.model_dump(by_alias=True).items():
                out_field = "note" if field == "notes" else field
                i18n_fields[f"{out_field}_{code}"] = value
        db_hut = Hut(
            point=dbPoint(hut.location.lon_lat),
            elevation=hut.location.ele,
            capacity=hut.capacity.opened,
            url=hut.url,
            is_active=hut.is_active,
            is_public=hut.is_public,
            country=hut.country,
            type=hut_types.get(str(hut.hut_type.value), default_type),
            review_status=Hut.ReviewStatusChoices.done if init else Hut.ReviewStatusChoices.review,
            **i18n_fields,
        )
        src_owner = hut.owner
        owner = None
        if src_owner:
            owner_slug = slugify(src_owner)[:50]
            try:
                owner = Owner.objects.get(slug=owner_slug)
            except Owner.DoesNotExist:
                note = ""
                if len(src_owner) > 60:
                    note = src_owner
                    src_owner = src_owner[:60]
                owner = Owner(slug=owner_slug, name=src_owner, note_de=note)
                try:
                    owner.save()
                except DataError as e:
                    err_msg = str(e).split("\n")[0]
                    click.secho(f" {'(owner: '+owner_slug+')':<20} E: {err_msg}", dim=True)
                    continue
                owner.refresh_from_db()
            db_hut.owner = owner

        try:
            with transaction.atomic():
                db_hut.save()
                new_org = HutOrganizationAssociation(
                    hut=db_hut,
                    organization=hut_src.organization,
                    props=hut_src.source_properties,
                    source_id=hut_src.source_id,
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
    added, failed = init_huts_db(
        src_huts, init=init
    )  # , update_existing=update_existing, overwrite_existing_fields=overwrite_existing_fields)
    if added:
        obj.stdout.write(obj.style.SUCCESS(f"Successfully added {added} new hut{'s' if failed > 1 else ''}"))
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
        parser.add_argument("--organization", help="Organization slug, only add this one, otherwise all", type=str)

    def handle(self, init, organization, *args, **options):
        super().handle(kwargs_add={"init": init, "selected_organization": organization}, **options)
