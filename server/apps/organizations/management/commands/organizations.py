import os
import traceback
from django.core.management.base import BaseCommand, CommandError
from ...models import Organization
from django.core.management import call_command
from django.conf import settings
import shutil
from djjmt.utils import override


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
        parser.add_argument("-a", "--all", action="store_true", help="Run drop and fill commands")
        parser.add_argument(
            "-s",
            "--save",
            action="store_true",
            help="Save entries from database as defaults (overwrite fixtures/organizations.yml)",
        )
        parser.add_argument(
            "-m", "--ignore-media", action="store_true", help="Ignore media files (do not copy or remove)"
        )
        self._parser = parser

    def handle(self, drop: bool, fill: bool, all: bool, save: bool, ignore_media: bool, *args, **options):
        # get media files paths
        logo_path = "/organizations"
        media_dst = os.path.relpath(f"{settings.MEDIA_ROOT}/{logo_path}")
        app_root = os.path.join(os.path.dirname(__file__), "..", "..")
        media_src = os.path.relpath(f"{app_root}/media/{logo_path}")
        if drop or all:
            db = Organization.objects
            self.stdout.write(f"Drop {db.count()} entries from table 'Organizations'")
            db.all().delete()
            if not ignore_media and os.path.exists(media_dst):
                self.stdout.write(f"Remove media file folder '{media_dst}'")
                shutil.rmtree(media_dst)
        if fill or all:
            self.stdout.write(f"Load data from 'organizations.yaml' fixtures")
            try:
                call_command("loaddata", "organizations", app_label="organizations")
                self.stdout.write(self.style.SUCCESS(f"Successfully loaded data"))
            except Exception as e:
                self.stderr.write(traceback.format_exc())
                self.stdout.write(self.style.ERROR(f"Loaddata failed, fix issues and run again"))
            if not ignore_media:
                self.stdout.write(f"Copy media files from '{media_src}' to '{media_dst}'")
                shutil.copytree(media_src, media_dst, dirs_exist_ok=True)
        if save:
            try:
                fixture_path = os.path.relpath(f"{app_root}/fixtures/organizations.yaml")
                call_command("dumpdata", "organizations.Organization", format="yaml", output=fixture_path)
                with open(fixture_path, "r") as file:
                    new_lines = []  # remove created and modified
                    for line in file.readlines():
                        if "    modified: " not in line and "    created: " not in line:
                            new_lines.append(line)
                with open(fixture_path, "w") as file:
                    file.writelines(new_lines)
                self.stdout.write(self.style.WARNING(f"Make sure to copy any new/changed logo to '{media_src}'"))
                self.stdout.write(self.style.SUCCESS(f"Successfully saved data to '{fixture_path}'"))
            except Exception as e:
                self.stderr.write(str(e))
                self.stdout.write(self.style.ERROR(f"Save data failed, fix issues and run again"))

        if not fill and not drop and not all and not save:
            if self._parser is not None:
                self._parser.print_help()
            else:
                self.stdout.write(self.style.NOTICE(f"Missing arguments"))
