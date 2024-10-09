import csv
import os

from django.core.management.base import BaseCommand, CommandError

from server.apps.licenses.models import License


class Command(BaseCommand):
    help = "Imports licenses from a CSV file"

    def handle(self, *args, **options):
        script_dir = os.path.dirname(__file__)
        csv_file = os.path.join(script_dir, "licenses.csv")

        if not os.path.isfile(csv_file):
            raise CommandError(f"CSV file '{csv_file}' does not exist.")

        with open(csv_file, "r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                license, created = License.objects.update_or_create(
                    slug=row["slug"],
                    defaults={
                        "name_en": row["name_en"],
                        "fullname_en": row["fullname_en"],
                        "description_en": row["description_en"],
                        "link_en": row["link_en"],
                        "name_de": row["name_de"],
                        "fullname_de": row["fullname_de"],
                        "description_de": row["description_de"],
                        "link_de": row["link_de"],
                        "is_active": row["is_active"].lower() == "true",
                        "order": row["order"],
                        "attribution_required": row["attribution_required"].lower() == "true",
                        "no_commercial": row["no_commercial"].lower() == "true",
                        "no_modifying": row["no_modifying"].lower() == "true",
                        "share_alike": row["share_alike"].lower() == "true",
                        "no_publication": row["no_publication"].lower() == "true",
                    },
                )

                if created:
                    self.stdout.write(self.style.SUCCESS(f"Created License: {license}"))
                else:
                    self.stdout.write(self.style.WARNING(f"Updated License: {license}"))
