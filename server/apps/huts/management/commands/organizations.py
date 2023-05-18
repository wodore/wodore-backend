from django.core.management.base import BaseCommand, CommandError
from ...models import Organization
from django.core.management import call_command
from django.conf import settings
import shutil

class Command(BaseCommand):
    help = "Initialize and drop data in Organizations table"
    suppressed_base_arguments = ("--version", "--settings", "--pythonpath", "--traceback", "--no-color", "--force-color")
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._parser = None

    def add_arguments(self, parser):
        parser.add_argument("-d", "--drop", action='store_true', help="Drop entries in table")
        parser.add_argument("-f", "--fill", action='store_true', help="Fill table with default entries")
        parser.add_argument("-a", "--all", action='store_true', help="Run drop and fill commands")
        self._parser = parser

    def handle(self, drop: bool, fill: bool, all: bool, *args, **options):
        if drop or all:
            db = Organization.objects
            self.stdout.write(f"Drop {db.count()} entries from table 'Organizations'")
            db.all().delete()
        if fill or all:
            self.stdout.write(f"Load data from 'organizations.yaml' fixtures")
            try:
                call_command('loaddata', "organizations", app_label='huts') 
                self.stdout.write( self.style.SUCCESS(f"Successfully loaded data"))
            except Exception as e:
                self.stderr.write(str(e))
                self.stdout.write(self.style.ERROR(f"Loaddata failed, fix issues and run again"))
            logo_path = "/huts/organizations"
            dst = f"{settings.MEDIA_ROOT}/{logo_path}"
            src = f"server/apps/huts/media/{logo_path}"
            shutil.copytree(src, dst, dirs_exist_ok=True)
        if not fill and not drop and not all:
            if self._parser is not None:
                self._parser.print_help()
            else:
                self.stdout.write(self.style.NOTICE(f"Missing arguments"))