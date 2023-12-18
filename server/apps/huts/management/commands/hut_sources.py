import contextlib
import sys
from os import wait
from typing import Any, Sequence, Type, TypeAlias

import click
from hut_services import BaseService, HutSourceSchema

# from hut_services import BaseHutSourceSchema, BaseSourceProperties
# from hut_services.core.service import BaseService
from pydantic import BaseModel

from django.conf import settings
from django.contrib.gis.geos import Point as dbPoint
from django.core.management.base import CommandParser

from server.apps.organizations.models import Organization
from server.core.management.base import CRUDCommand

from ...models import HutSource
from ...schemas.status import CreateOrUpdateStatus
from ...services.sources import HutSourceService

SERVICES: dict[str, Type[BaseService[BaseModel]]] = settings.SERVICES


def add_hut_source_db(  # type: ignore[no-any-unimported]
    huts: Sequence[HutSourceSchema],
    reference: str,
    # update_existing: bool = False, overwrite_existing_fields: bool=False,
    init: bool,
    extern_slug: str | None = None,
) -> list[HutSource]:
    hut_source_service = HutSourceService()
    try:
        organization_id = Organization.get_by_slug(slug=reference).id
    except Organization.DoesNotExist:
        click.secho(f"Organiztion '{reference}' does not exist, add it first.", fg="red")
        sys.exit(1)
    source_huts = []
    number = 0
    for hut in huts:
        number += 1
        shut = HutSource(
            source_id=hut.source_id,
            location=dbPoint(hut.location.lon_lat),
            organization_id=organization_id,
            name=hut.name,
            source_data=hut.source_data.model_dump(by_alias=True) if hut.source_data is not None else {},
            source_properties=hut.source_properties.model_dump(by_alias=True) if hut.source_properties else {},
        )
        review_status = HutSource.ReviewStatusChoices.done if init else HutSource.ReviewStatusChoices.new
        shut, status = hut_source_service.create(shut, new_review_status=review_status)
        _hut_name = shut.name if len(shut.name) < 18 else shut.name[:15] + ".."
        _name = f"  Hut {number!s: <3} {'`'+shut.source_id+'`':<15} {_hut_name:<20} {'('+str(shut.organization)+')':<8}"
        click.echo(f"{_name: <48}", nl=False)
        status_color = {
            CreateOrUpdateStatus.updated: "yellow",
            CreateOrUpdateStatus.created: "green",
            CreateOrUpdateStatus.exists: "blue",
            CreateOrUpdateStatus.ignored: "magenta",
        }
        click.secho(f"  ... {status:<8}", fg=status_color.get(status, "red"), nl=False)
        click.secho(f" (#{shut.id})", dim=True)
        source_huts.append(shut)
    return source_huts


def add_hutsources_function(
    obj: "CRUDCommand[HutSource]",
    force: bool,
    model: HutSource,
    **kwargs: Any,
) -> None:
    selected_orgs = kwargs.get("selected_organizations", [])
    limit = kwargs.get("limit", None)
    offset = kwargs.get("offset", None)
    init = kwargs.get("init", None)
    lang = kwargs.get("lang", None)
    for org in selected_orgs:
        service_class = SERVICES.get(org, None)
        if service_class is not None:
            service = service_class()
            obj.stdout.write(f"Get data from '{service_class.__name__}'")
            src_huts = service.get_huts_from_source(limit=limit, offset=offset, lang=lang)
            obj.stdout.write(f"Got {len(src_huts)} results back, start filling database:")
            huts = add_hut_source_db(src_huts, reference=org, init=init)
            obj.stdout.write(obj.style.SUCCESS(f"Successfully added {len(huts)} new huts"))
        else:
            obj.stdout.write(obj.style.WARNING(f"Selected organization '{org}' not supported."))


class Command(CRUDCommand[HutSource]):
    # help = ""
    model = HutSource
    model_names = "hutsources"
    add_function = add_hutsources_function
    use_limit_arg = True
    use_offset_arg = True
    # use_update_arg = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def add_arguments(self, parser: CommandParser) -> None:
        super().add_arguments(parser)
        parser.add_argument("-i", "--init", action="store_true", help="Initial data fill")
        parser.add_argument(
            "-O",
            "--orgs",
            "--organizations",
            help=f"Organization slug, only add this one, use 'all' to add all (possible values: {', '.join(SERVICES.keys())}).",
            type=str,
            required=True,
        )
        parser.add_argument("--lang", help="Language to use (de, en, fr, it)", default="de", type=str)

    def handle(self, init: bool, orgs: str, lang: str, *args: Any, **options: Any) -> None:  # type: ignore[override]
        org_list = SERVICES.keys() if orgs.lower().strip() == "all" else [o.strip() for o in orgs.split(",")]
        super().handle(kwargs_add={"init": init, "selected_organizations": org_list, "lang": lang}, **options)
