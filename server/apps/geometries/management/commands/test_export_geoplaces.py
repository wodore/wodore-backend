import yaml
from django.core.management.base import BaseCommand

from server.apps.geometries.models import GeoPlace


class Command(BaseCommand):
    help = "Export geoplace records as YAML seed files for test data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of geoplaces to export",
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

    def handle(self, *args, **options):
        qs = GeoPlace.objects.filter(is_active=True, is_public=True).prefetch_related(
            "categories"
        )

        sort = options["sort"]
        if sort == "random":
            qs = qs.order_by("?")
        elif sort == "elevation":
            qs = qs.order_by("-elevation")
        else:
            qs = qs.order_by("name")

        if options["limit"]:
            qs = qs[: options["limit"]]

        geoplaces_data = []
        for place in qs:
            location = place.location
            place_dict = {
                "name": place.name,
                "location": f"SRID=4326;POINT ({location.x} {location.y})",
                "elevation": place.elevation,
                "country": place.country_code.code,
                "importance": place.importance,
                "detail_type": place.detail_type,
            }

            category_slugs = [cat.slug for cat in place.categories.all()]
            if category_slugs:
                place_dict["category_slugs"] = category_slugs

            geoplaces_data.append(place_dict)

        output = yaml.dump(
            {"geoplaces": geoplaces_data},
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        if options["out"]:
            with open(options["out"], "w") as f:
                f.write(output)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Exported {len(geoplaces_data)} geoplaces to {options['out']}"
                )
            )
        else:
            self.stdout.write(output)
