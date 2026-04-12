import yaml
from django.core.management.base import BaseCommand

from server.apps.huts.models import Hut


class Command(BaseCommand):
    help = "Export hut records as YAML seed files for test data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of huts to export",
        )
        parser.add_argument(
            "--sort",
            type=str,
            default="alpha",
            choices=["random", "alpha", "elevation"],
            help="Sort order: random, alpha (by name), or elevation (descending)",
        )
        parser.add_argument(
            "--out",
            type=str,
            default=None,
            help="Output file path (defaults to stdout)",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            default=False,
            help="Include inactive huts in the export",
        )

    def handle(self, *args, **options):
        qs = Hut.objects.select_related(
            "hut_type_open", "hut_type_closed", "hut_owner"
        ).prefetch_related("contact_set__function", "org_set")

        if not options["include_inactive"]:
            qs = qs.filter(is_active=True, is_public=True)

        sort = options["sort"]
        if sort == "random":
            qs = qs.order_by("?")
        elif sort == "elevation":
            qs = qs.order_by("-elevation")
        else:
            qs = qs.order_by("name")

        if options["limit"]:
            qs = qs[: options["limit"]]

        huts_data = []
        for hut in qs:
            location = hut.location
            hut_dict = {
                "name": hut.name,
                "location": f"SRID=4326;POINT ({location.x} {location.y})",
                "elevation": float(hut.elevation) if hut.elevation else None,
                "country": hut.country_field.code,
                "hut_type_open": hut.hut_type_open.slug if hut.hut_type_open else None,
                "hut_type_closed": hut.hut_type_closed.slug
                if hut.hut_type_closed
                else None,
                "capacity_open": hut.capacity_open,
                "capacity_closed": hut.capacity_closed,
            }

            orgs = []
            for org_assoc in hut.orgs_source.all():
                orgs.append(
                    {
                        "slug": org_assoc.organization.slug,
                        "source_id": org_assoc.source_id or "",
                    }
                )
            if orgs:
                hut_dict["organizations"] = orgs

            contacts = []
            for contact in hut.contact_set.all():
                contact_dict = {}
                if contact.function:
                    contact_dict["function_slug"] = contact.function.slug
                contact_dict["name"] = contact.name
                if contact.email:
                    contact_dict["email"] = contact.email
                if contact.phone:
                    contact_dict["phone"] = contact.phone
                contacts.append(contact_dict)
            if contacts:
                hut_dict["contacts"] = contacts

            huts_data.append(hut_dict)

        output = yaml.dump(
            {"huts": huts_data},
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        if options["out"]:
            with open(options["out"], "w") as f:
                f.write(output)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Exported {len(huts_data)} huts to {options['out']}"
                )
            )
        else:
            self.stdout.write(output)
