import os
import sys
from pathlib import Path
from typing import Callable
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
import click
from django.db import models
from server.core.managers import BaseManager
from django.core.management import call_command
import traceback
import shutil
from django.db.models.deletion import RestrictedError

from typing import Tuple


def add_fixture_function(parser: "CRUDCommand", force: bool, model: models.Model, **kwargs):
    ignore_media = kwargs.get("ignore_media", False)
    fixture_name = getattr(parser, "fixture_name", "")
    parser.stdout.write(f"Load data from '{fixture_name}.yaml' fixtures")
    if not force and model.objects.all().count() > 0:
        try:
            force = click.confirm(
                f"Careful this might overwrite exisitng data in the database, continue?", default=True
            )
        except click.Abort:
            print()
            sys.exit(0)
    if force or model.objects.all().count() == 0:
        try:
            call_command("loaddata", fixture_name, app_label=parser.app_label)
            parser.stdout.write(parser.style.SUCCESS(f"Successfully loaded data"))
        except Exception as e:
            parser.stdout.write(parser.style.ERROR(f"Loaddata failed, fix issues and run again, error message:"))
            parser.stdout.write(parser.style.NOTICE(e.args[0]))
            sys.exit(1)
        if parser.media_src and not ignore_media:
            media_src_rel = parser.media_src.relative_to(settings.BASE_DIR)
            media_dst_rel = parser.media_dst.relative_to(settings.BASE_DIR)
            parser.stdout.write(f"Copy media files from '{media_src_rel}' to '{media_dst_rel}'")
            try:
                shutil.copytree(parser.media_src, parser.media_dst, dirs_exist_ok=True)
                parser.stdout.write(parser.style.SUCCESS(f"Successfully copied data"))
            except FileNotFoundError as e:
                parser.stdout.write(parser.style.ERROR(f"Could not copy files, error message:"))
                parser.stdout.write(parser.style.NOTICE(e.args[1]))
                sys.exit(1)


def dump_fixture_function(parser: "CRUDCommand", force: bool, model: models.Model, **kwargs):
    fixture_name = getattr(parser, "fixture_name", "")
    fixture_path = parser.get_app_path() / "fixtures" / f"{fixture_name}.yaml"
    fixture_path_rel = fixture_path.relative_to(settings.BASE_DIR)
    meta = model._meta
    try:
        if os.path.exists(fixture_path) and not force:
            do_abort = False
            try:
                if not click.confirm(f"File '{fixture_path_rel}', overwrite?", default=True):
                    do_abort = True
                    parser.stdout.write(parser.style.NOTICE(f"Do not write file '{fixture_path_rel}"))
                    sys.exit(0)
            except click.Abort:
                print()
                do_abort = True
            if do_abort:
                parser.stdout.write(parser.style.NOTICE(f"Do not write file '{fixture_path_rel}"))
                sys.exit(0)

        call_command("dumpdata", f"{parser.app_label}.{meta.object_name}", format="yaml", output=fixture_path)
        with open(fixture_path, "r") as file:
            new_lines = []  # remove created and modified
            for line in file.readlines():
                if "    modified: " not in line and "    created: " not in line:
                    new_lines.append(line)
        with open(fixture_path, "w") as file:
            file.writelines(new_lines)
        if parser.media_src:
            parser.stdout.write(
                parser.style.WARNING(
                    f"Make sure to manually copy any new/changed logo from '{parser.media_dst.relative_to(settings.BASE_DIR)}' to '{parser.media_src.relative_to(settings.BASE_DIR)}'"
                )
            )
        parser.stdout.write(parser.style.SUCCESS(f"Successfully saved data to '{fixture_path_rel}'"))
    except Exception as e:
        parser.stdout.write(parser.style.ERROR(f"Save data failed, fix issue and run again, error message:"))
        parser.stdout.write(parser.style.NOTICE(e.args[0]))
        sys.exit(1)


def default_drop_function(parser: "CRUDCommand", force: bool, model: models.Model, **kwargs):
    limit = kwargs.get("limit")
    offset = kwargs.get("offset")
    ignore_media = kwargs.get("ignore_media", False)
    objects: BaseManager = model.objects  # type: ignore
    entries = model.objects.all().count()
    db_force = force
    # check support for limit
    err_msg = "'{}' parameter is not supported without custom manager 'drop()' function ('server.core.managers')"
    if not hasattr(objects, "drop") and parser.use_limit_arg:
        parser.stdout.write(parser.style.ERROR(err_msg.format("--limit")))
        sys.exit(1)
    if not hasattr(objects, "drop") and parser.use_offset_arg:
        parser.stdout.write(parser.style.ERROR(err_msg.format("--offset")))
        sys.exit(1)

    if not db_force and entries > 0:
        try:
            db_force = click.confirm(f"Delete {limit or 'all'} entries (total: {objects.all().count()})?", default=True)
        except click.Abort:
            db_force = False
            print()
    if entries == 0:
        parser.stdout.write(
            parser.style.NOTICE(f"Nothing to delete in table '{parser.app_label}.{model._meta.object_name}'")
        )
        db_force = False
    if db_force:
        try:
            if hasattr(objects, "drop"):
                total_entries, tables = objects.drop(limit=limit, offset=offset)
            else:
                total_entries, tables = objects.delete()
            for table, deleted in tables.items():
                parser.stdout.write(f"  > dropped {deleted} entries from table '{table}'")
            parser.stdout.write(
                parser.style.SUCCESS(
                    f"Successfully dropped {total_entries} entries from {len(tables)} table{'s' if len(tables) else ''}"
                )
            )
        except RestrictedError as e:
            parser.stdout.write(
                parser.style.ERROR(f"Cannot drop due to restictions. Solve it first! The restriction is:")
            )
            parser.stdout.write(parser.style.NOTICE(e.args[0]))
            sys.exit(1)
    # media_src, media_dst = get_media(parser)
    if parser.media_src and not ignore_media and parser.media_dst.exists:
        media_dst_rel = parser.media_dst.relative_to(settings.BASE_DIR)
        if os.path.exists(parser.media_dst):
            media_force = force
            if not media_force:
                try:
                    media_force = click.confirm(f"Remove media file folder '{media_dst_rel}'?", default=True)
                except click.Abort:
                    media_force = False
                    print()
            if media_force:
                shutil.rmtree(parser.media_dst)
                parser.stdout.write(parser.style.SUCCESS(f"Successfully removed '{media_dst_rel}'"))
        else:
            parser.stdout.write(parser.style.NOTICE(f"Path '{media_dst_rel}' already removed"))


class CRUDCommand(BaseCommand):
    help = "Drop, add, update and save entries from, respectively, to database table."

    model: models.Model | None = None  # REQUIRED
    model_names: str = ""  # REQUIRED
    app_label: str = ""  # if not main app model

    # general settings
    use_offset_arg = False
    use_limit_arg = False
    use_update_arg = False
    use_media_args = (
        None  # if None use it if media_src is set, if False never us it if True auto generate media_src if no given
    )

    # add settings
    add_function: None | Callable = add_fixture_function
    media_src: str | Path | None = None  # copy media file from this location to
    media_dst: str | Path | None = None  # this location (destination is not required an per default settins.MEDIA_ROOT)
    fixture_name: str = ""  # name for fixture under <app_label>/fixtures/<fixture_name>.yaml

    # drop settings
    drop_function: None | Callable = default_drop_function  # drop_function(parser, limit, offset, force, **kwargs_add)

    # dump settings
    dump_function: None | Callable = dump_fixture_function

    # BaseCommand settings
    requires_system_checks = []
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
        ##   check for model
        if self.model is None:
            raise AttributeError("'model' is needed, add it to the global variables in your class!")
        # set default attributes
        self.model_names = self.model_names or self.model._meta.object_name.lower() + "s"
        self.app_label = self.app_label or self.model._meta.app_label
        self.fixture_name = self.fixture_name or self.model_names
        if not self.fixture_name:
            raise AttributeError("'fixture_name' is needed, add it to the global variables in your class!")
        if self.use_media_args or self.use_media_args is None:
            self.set_media_paths()

    def add_arguments(self, parser):
        if self.drop_function:
            parser.add_argument("-d", "--drop", action="store_true", help="Drop entries in table")
        if self.add_function:
            parser.add_argument("-a", "--add", action="store_true", help="Add data to table")
        if self.use_update_arg:
            parser.add_argument("-u", "--update", action="store_true", help="Update existing entries")
        if self.use_limit_arg:
            parser.add_argument("-n", "--limit", help="Limit of entries", type=int)
        if self.use_offset_arg:
            parser.add_argument("-o", "--offset", help="Offset of entries", type=int)
        if self.dump_function:
            parser.add_argument(
                "--dump",
                action="store_true",
                help=f"Dump entries from database as fixture (overwrites  '<app_label>/fixtures/<fixture-name>.yaml'). "
                "The file can be loaded with '--add' again into the database. "
                "Use '--fixture-name' in order to change the default name.",
            )
        parser.add_argument(
            "-f", "--force", action="store_true", help="Force, e.g. overwrite exisinting data (be careful!)"
        )
        if self.add_function.__name__ == "add_fixture_function":
            parser.add_argument("--fixture-name", help=f"Name of the fixtues (default: {self.fixture_name})")
        if self.media_src:
            parser.add_argument(
                "--ignore-media", action="store_true", help="Ignore media files (do not copy or remove)"
            )
            parser.add_argument(
                "-m",
                "--media-src",
                help=f"Media source path (default: {self.media_src.relative_to(settings.BASE_DIR)})",
            )

    def default_limit(self, drop, add, update, **kwargs):
        if drop:  # drop and add the same amount
            return self.model.objects.all().count()
        elif add:
            return 100000  # all

    def handle(
        self,
        force: bool,
        # init: bool,
        kwargs_add: dict | None = None,
        kwargs_drop: dict | None = None,
        kwargs_dump: dict | None = None,
        *args,
        **options,
    ):
        ##   defaults
        dump = options.get("dump", None)
        drop = options.get("drop", None)
        add = options.get("add", None)
        update = options.get("update", None)
        ## set optional kwargs
        kwargs = {}
        entries = self.model.objects.all().count()
        ##   fixture name
        if options.get("fixture_name", None):
            self.fixture_name = options.get("fixture_name", False)
            kwargs["fixture_name"] = options.get("fixture_name", False)
        if options.get("media_src", None):
            self.fixture_name = options.get("media_src", "")
            kwargs["media_src"] = options.get("media_src", "")
        ##   limit
        if self.use_limit_arg:
            limit = options.get("limit", None)
            if not limit:
                if force:
                    limit = self.default_limit(drop=drop, add=add, update=update)
                else:
                    try:
                        limit = click.prompt("Limit of entries to add (--limit)", type=int, default=10)
                    except click.Abort:
                        print()
                        sys.exit(0)
            kwargs["limit"] = limit
        ##   offset
        if self.use_offset_arg:
            offset = options.get("offset", None)
            if offset is None:
                offset = entries
            kwargs["offset"] = offset
        ##   meda stuff
        if self.media_src:
            kwargs["ignore_media"] = options.get("ignore_media", False)
            kwargs["media_src"] = options.get("media_src", False)
        ##   default add
        if kwargs_add is None:
            kwargs_add = {}
        kwargs_add.update(kwargs)
        ##   default drop
        if kwargs_drop is None:
            kwargs_drop = {}
        kwargs_drop.update(kwargs)
        ## DROP
        if drop:
            if self.drop_function:
                self.drop_function(force=force, model=self.model, **kwargs_drop)
            else:
                self.stdout.write(self.style.WARNING("'drop_function' is not implemented"))
        ## ADD
        if add:
            if self.add_function:
                self.add_function(update=update, force=force, model=self.model, **kwargs_add)
            else:
                self.stdout.write(self.style.WARNING("'add_function' is not implemented"))
        ## ADD
        if dump:
            if self.dump_function:
                self.dump_function(force=force, model=self.model, **kwargs_add)
            else:
                self.stdout.write(self.style.WARNING("'dump_function' is not implemented"))

    def get_app_path(self) -> Path:
        return settings.BASE_DIR / "server" / "apps" / self.app_label

    def get_media_paths(self) -> Tuple[Path | None, Path | None]:
        if (getattr(self, "media_src") and not self.use_media_args == False) or self.use_media_args:
            media_dst = Path(getattr(self, "media_dst"))
            media_src = Path(getattr(self, "media_src"))
            if not media_src.exists:
                self.stdout.write(self.style.ERROR(f"'media_src' directory '{media_src}' does not exist."))
                sys.exit(1)
            return media_src, media_dst
        return None, None

    def set_media_paths(
        self, src: Path | str | None = None, dst: Path | str | None = None
    ) -> Tuple[Path | None, Path | None]:
        """Set media source and destination path, starint add app root, respecively, media root"""
        if src is None:
            default_src = Path("media") / self.app_label / self.model_names
            self.media_src = self.media_src or self.get_app_path() / default_src
        else:
            self.media_src = self.get_app_path() / src
        if dst is None:
            default_dst = Path(self.app_label) / self.model_names
            self.media_dst = self.media_dst or settings.MEDIA_ROOT / default_dst
        else:
            self.media_dst = settings.MEDIA_ROOT / dst
        # make sure it is a Path object
        if self.media_src:
            self.media_src = Path(self.media_src)
        if self.media_dst:
            self.media_dst = Path(self.media_dst)
        return self.media_src, self.media_dst
